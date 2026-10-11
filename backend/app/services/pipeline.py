"""Analysis pipeline orchestration (ARCHITECTURE.md §4, §6, §23, §26; DEC-016, DEC-019, DEC-023, DEC-029, DEC-032).

`AnalysisPipeline.analyze(audio_bytes, request)` runs the canonical pipeline once, synchronously, and returns the public
`AnalysisResult`:

    preprocess -> baseline lookup -> (cache check) -> transcribe -> align + validate -> features
    -> normalize -> detect -> severity/evidence -> score -> convert to source time -> explain -> assemble -> cache

Every number comes from the stages above; this module only wires them together, converts times, and states what was NOT
evaluated. It contains no analytics of its own.

Key properties
    * Time: stages work in processed-audio time. All times in the result are converted to SOURCE time (the uploaded recording's
      timeline) exactly once, by adding `PreprocessedAudio.trim_start_s` while assembling the result (DEC-023, DEC-029).
    * Honesty: everything not evaluated or limited is listed in `AnalysisResult.notes` (unavailable features, features left out
      of the score, thin baselines, a transcript that does not match the passage, alignment warnings, uncalibrated thresholds).
    * Reproducibility: the cache key covers the audio, its trim offset, the baseline, the transcript override, all versions, a
      fingerprint of every analytical constant in effect and the library versions; the `analysis_id` is derived from it.
    * One analysis at a time (a lock): the Whisper/WhisperX models are shared and the work is CPU-bound (DEC-016).
    * Models are injected (`transcriber`, `aligner`), created lazily on first use otherwise, so the logic is testable without them.

Errors are reported as `PipelineError(code, detail)`, mapped onto the public `ErrorCode`s; unexpected exceptions are not
swallowed here (the API layer turns them into PROCESSING_ERROR without leaking internals).
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import logging
import math
import re
import threading
import time
from dataclasses import dataclass, field, fields, is_dataclass
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from app.core.baseline import (
    BaselineIntegrityError,
    BaselineNotFoundError,
    BaselinePassageMismatchError,
    BaselineProvider,
)
from app.core.cache import ResultCache, analysis_id_for_key, make_cache_key
from app.core.config import settings
from app.core.passages import PassageCatalog
from app.schemas.common import API_CONTRACT_VERSION, ErrorCode, TranscriptSource
from app.schemas.contracts import AlignedTranscript, BaselineStatsRecord, PreprocessedAudio, Transcript
from app.schemas.request import AnalyzeRequest
from app.schemas.response import AlignedWord as ResponseAlignedWord
from app.schemas.response import (
    AnalysisNote,
    AnalysisResult,
    AudioInfo,
    BaselineInfo,
    EnergyTimeline,
    F0Timeline,
    FeatureSet,
    MfccSummary,
    PauseEvent,
    ProcessingMeta,
    SpeechRateTimeline,
)
from app.services.audio import AudioPreprocessingError, AudioPreprocessor, AudioTooLongError
from app.services.explanation import build_overall_summary, explain_flaw
from app.services.features.energy import EnergyConfig, EnergyExtractor
from app.services.features.f0 import F0Config, F0Extractor
from app.services.features.mfcc import MFCCConfig, MFCCExtractor
from app.services.features.pause import PauseConfig, PauseDetector
from app.services.features.rate import RateConfig, RateExtractor
from app.services.grounding import (
    DetectionConfig,
    EvidenceError,
    NormalizationError,
    SeverityConfig,
    detect_candidates,
    ground_flaws,
    normalize_features,
    to_api_flaw,
)
from app.services.scoring import ScoringConfig, ScoringError, score_analysis

logger = logging.getLogger(__name__)

TIME_DECIMALS = 4  # response times are rounded to 0.1 ms


class PipelineError(Exception):
    """A pipeline failure that maps onto a public error code.

    `detail` is shown to the client, so it is built only from this project's own validation messages and the client's own
    identifiers. Text raised by third-party code (decoders, models, the file system) is logged, never put in `detail`.
    """

    def __init__(self, code: ErrorCode, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


# --------------------------------------------------------------------------- configuration
@dataclass(frozen=True)
class PipelineConfig:
    """Every analytical configuration object the pipeline uses (and fingerprints)."""

    f0: F0Config = field(default_factory=F0Config)
    energy: EnergyConfig = field(default_factory=EnergyConfig)
    mfcc: MFCCConfig = field(default_factory=MFCCConfig)
    rate: RateConfig = field(default_factory=RateConfig)
    pause: PauseConfig = field(default_factory=PauseConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    severity: SeverityConfig = field(default_factory=SeverityConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)


_SETTINGS_IN_FINGERPRINT = (
    "TARGET_SAMPLE_RATE", "TARGET_PEAK_DBFS", "VAD_ENERGY_THRESHOLD_DBFS", "MAX_DURATION_S", "WHISPER_MODEL",
    "WHISPER_LANGUAGE", "ALIGNMENT_LANGUAGE", "ALIGNMENT_DEVICE", "MIN_COVERAGE_PCT", "PASSAGE_MATCH_MIN_RATIO",
    "BASELINE_THIN_RATE_WINDOWS", "BASELINE_THIN_PAUSES", "THRESHOLDS_CALIBRATED", "EXPLANATION_PROVIDER",
)


def _canon(obj: Any) -> Any:
    """JSON-safe, order-independent form of a configuration value."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _canon(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Mapping):
        return {str(_canon(k)): _canon(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_canon(x) for x in obj]
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else str(obj)
    if isinstance(obj, Path):
        return str(obj)
    if obj is None or isinstance(obj, (str, int, bool)):
        return obj
    raise TypeError(f"cannot fingerprint {type(obj).__name__}")


def analysis_config_fingerprint(config: PipelineConfig) -> str:
    """SHA-256 of every analytical constant in effect (not the environment, so it is comparable across machines)."""
    payload = {
        "pipeline": _canon(config),
        "settings": {name: _canon(getattr(settings, name)) for name in _SETTINGS_IN_FINGERPRINT},
    }
    return make_cache_key(payload)


def library_versions() -> Dict[str, Optional[str]]:
    """Installed versions of the libraries whose numerics can change results (ARCHITECTURE.md §26.5)."""
    versions: Dict[str, Optional[str]] = {}
    for name in ("numpy", "scipy", "librosa", "av", "openai-whisper", "whisperx", "torch"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


# ------------------------------------------------------------------------ content check
_TOKEN_RE = re.compile(r"[a-z0-9']+")


def content_match_ratio(transcript_text: str, passage_text: str) -> float:
    """Similarity in [0, 1] of the word sequences (case and punctuation ignored); 1.0 means the same words in order."""
    a = _TOKEN_RE.findall(transcript_text.lower())
    b = _TOKEN_RE.findall(passage_text.lower())
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


# ----------------------------------------------------------------------------- helpers
def _short(exc: BaseException, limit: int = 200) -> str:
    text = str(exc).strip().replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _t(value: float, offset: float) -> float:
    """Convert a processed-audio time to source time (the only place the trim offset is applied to raw times)."""
    return round(float(value) + offset, TIME_DECIMALS)


def _finite_or_none(value: float, decimals: int) -> Optional[float]:
    return round(float(value), decimals) if math.isfinite(value) else None


# ------------------------------------------------------------------------------ pipeline
class AnalysisPipeline:
    """Runs one analysis end to end (see module docstring)."""

    def __init__(
        self,
        *,
        preprocessor: Optional[AudioPreprocessor] = None,
        transcriber: Any = None,
        aligner: Any = None,
        baseline_provider: Optional[BaselineProvider] = None,
        cache: Optional[ResultCache] = None,
        passages: Optional[PassageCatalog] = None,
        config: Optional[PipelineConfig] = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.preprocessor = preprocessor or AudioPreprocessor()
        self._transcriber = transcriber
        self._aligner = aligner
        self.baseline_provider = baseline_provider or BaselineProvider()
        self.cache = cache or ResultCache()
        self.passages = passages or PassageCatalog()
        self.config = config or PipelineConfig()
        self._clock = clock
        self._lock = threading.Lock()

    # -- lazily created heavy services -------------------------------------------------
    def _get_transcriber(self) -> Any:
        if self._transcriber is None:
            from app.services.transcription import get_transcriber

            self._transcriber = get_transcriber()
        return self._transcriber

    def _get_aligner(self) -> Any:
        if self._aligner is None:
            from app.services.alignment import get_aligner

            self._aligner = get_aligner()
        return self._aligner

    # -- stages ------------------------------------------------------------------------
    def _preprocess(self, audio_bytes: bytes) -> PreprocessedAudio:
        try:
            audio = self.preprocessor.process(audio_bytes)
        except AudioTooLongError as exc:
            raise PipelineError(ErrorCode.AUDIO_TOO_LONG, _short(exc)) from exc
        except AudioPreprocessingError as exc:
            # Decoder text is library-internal (error numbers, Python messages): logged, not returned.
            logger.warning("audio could not be decoded: %s", _short(exc))
            raise PipelineError(
                ErrorCode.UNSUPPORTED_AUDIO_FORMAT, "The audio could not be decoded. Upload a valid WAV or MP3 recording."
            ) from exc
        if len(audio.audio_array) == 0 or audio.duration_s <= 0.0:
            raise PipelineError(ErrorCode.VALIDATION_ERROR, "The audio contains no speech (it is silent after preprocessing).")
        return audio

    def _load_baseline(self, request: AnalyzeRequest) -> BaselineStatsRecord:
        try:
            return self.baseline_provider.get(request.baseline_id, passage_id=request.passage_id)
        except BaselineNotFoundError as exc:
            # The provider's message names the server's directory; the client only needs its own (validated) identifier.
            raise PipelineError(
                ErrorCode.BASELINE_NOT_FOUND, f"No baseline statistics exist for baseline_id '{request.baseline_id}'."
            ) from exc
        except BaselinePassageMismatchError as exc:
            raise PipelineError(ErrorCode.VALIDATION_ERROR, f"baseline_id '{request.baseline_id}' is not a baseline for passage '{request.passage_id}'.") from exc
        except BaselineIntegrityError as exc:
            logger.error("baseline '%s' failed verification: %s", request.baseline_id, exc)
            raise PipelineError(ErrorCode.PROCESSING_ERROR, "The baseline statistics could not be loaded or verified.") from exc

    def _cache_identity(self, audio: PreprocessedAudio, record: BaselineStatsRecord, request: AnalyzeRequest, fingerprint: str) -> str:
        """The analysis id: a pure function of every input that can change the stored result, notes included.

        `speaker_gender` and the passage reference text do not influence any number, but they appear in `notes`, so they are part
        of the key: a cache hit must return exactly what a fresh run for the same request would.
        """
        manual = request.manual_transcript.strip() if request.manual_transcript else None
        passage_text = self.passages.get_text(request.passage_id)
        key = make_cache_key(
            {
                "audio_sha256": audio.sha256,
                "trim_start_s": audio.trim_start_s,
                "source_duration_s": audio.source_duration_s,
                "baseline_id": request.baseline_id,
                "baseline_sha256": record.sha256,
                "passage_id": request.passage_id,
                "passage_text_sha256": hashlib.sha256(passage_text.encode("utf-8")).hexdigest() if passage_text else None,
                "speaker_gender": request.speaker_gender.value if request.speaker_gender is not None else None,
                "manual_transcript_sha256": hashlib.sha256(manual.encode("utf-8")).hexdigest() if manual else None,
                "config_version": settings.CONFIG_VERSION,
                "pipeline_version": settings.PIPELINE_VERSION,
                "api_contract_version": API_CONTRACT_VERSION,
                "config_fingerprint": fingerprint,
                "libraries": library_versions(),
            }
        )
        return analysis_id_for_key(key)

    def _transcribe(self, audio: PreprocessedAudio, manual: Optional[str]) -> Transcript:
        if manual is not None:
            return Transcript(
                text=manual, segments=[], words=[], model_name="manual",
                source=TranscriptSource.MANUAL, language=settings.WHISPER_LANGUAGE or None,
            )
        try:
            return self._get_transcriber().transcribe(audio)
        except Exception as exc:  # noqa: BLE001 - any model failure is a processing error
            logger.exception("transcription failed")
            raise PipelineError(ErrorCode.PROCESSING_ERROR, "Transcription failed.") from exc

    def _align(self, audio: PreprocessedAudio, transcript: Transcript) -> "tuple[AlignedTranscript, List[str]]":
        from app.services.alignment import validate_alignment

        if not transcript.text.strip():
            raise PipelineError(ErrorCode.VALIDATION_ERROR, "No speech could be transcribed from the audio.")
        try:
            aligned = self._get_aligner().align(audio, transcript)
        except Exception as exc:  # noqa: BLE001
            logger.exception("alignment failed")
            raise PipelineError(ErrorCode.PROCESSING_ERROR, "Forced alignment failed.") from exc
        # Nothing alignable is a property of the recording (no or unintelligible speech), not a server fault, so it is checked
        # before the structural validation, which would report the same situation as an internal error.
        if not any(w.start_s is not None and w.end_s is not None for w in aligned.words):
            raise PipelineError(ErrorCode.VALIDATION_ERROR, "No words could be aligned to the audio.")
        validation = validate_alignment(aligned, audio_duration_s=audio.duration_s)
        if not validation.is_valid:
            raise PipelineError(ErrorCode.PROCESSING_ERROR, "The word alignment failed validation: " + "; ".join(validation.errors))
        return aligned, list(validation.warnings)

    # -- main entry point ----------------------------------------------------------------
    def analyze(self, audio_bytes: bytes, request: AnalyzeRequest) -> AnalysisResult:
        """Analyse `audio_bytes` against the baseline named in `request` (see module docstring)."""
        with self._lock:
            started = self._clock()
            cfg = self.config
            fingerprint = analysis_config_fingerprint(cfg)

            audio = self._preprocess(audio_bytes)
            record = self._load_baseline(request)
            analysis_id = self._cache_identity(audio, record, request, fingerprint)

            cached = self.cache.get(analysis_id)
            if cached is not None:
                meta = cached.processing_meta.model_copy(
                    update={"cached": True, "processing_time_s": round(self._clock() - started, 3)}
                )
                return cached.model_copy(update={"processing_meta": meta})

            manual = request.manual_transcript.strip() if request.manual_transcript else None
            transcript = self._transcribe(audio, manual)
            aligned, alignment_warnings = self._align(audio, transcript)

            f0 = F0Extractor(cfg.f0).extract(audio)
            energy = EnergyExtractor(cfg.energy).extract(audio)
            rate = RateExtractor(cfg.rate).extract(aligned)
            pauses = PauseDetector(cfg.pause).detect(aligned=aligned, energy=energy)
            try:
                mfcc_summary: Optional[Dict[str, List[float]]] = MFCCExtractor(cfg.mfcc).extract(audio).to_summary_dict()
            except ValueError as exc:
                logger.warning("MFCC summary unavailable: %s", exc)
                mfcc_summary = None

            try:
                normalized = normalize_features(record, f0=f0, energy=energy, rate=rate, pauses=pauses.events)
                detection = detect_candidates(normalized, cfg.detection)
                grounded = ground_flaws(detection, normalized, record, rate=rate, energy=energy, aligned=aligned, severity=cfg.severity)
                scoring = score_analysis(grounded, detection.skipped, settings.CONFIG_VERSION, cfg.scoring)
            except (NormalizationError, EvidenceError, ScoringError) as exc:
                logger.exception("analytical stage failed")
                raise PipelineError(ErrorCode.PROCESSING_ERROR, f"The analysis could not be completed: {_short(exc)}") from exc

            # ---- single conversion to source time, then explanations are written in that timeline ----
            offset = audio.trim_start_s
            source_flaws = [f.shifted(offset) for f in grounded]
            api_flaws = []
            fallback_used = False
            for flaw in source_flaws:
                explained = explain_flaw(flaw)
                fallback_used = fallback_used or explained.used_fallback
                api_flaws.append(to_api_flaw(flaw, explained.explanation, explained.recommendation, explained.method))

            notes = self._notes(
                request=request, record=record, aligned=aligned, transcript=transcript, alignment_warnings=alignment_warnings,
                normalized=normalized, scoring=scoring, mfcc_available=mfcc_summary is not None, fallback_used=fallback_used,
                energy=energy,
            )
            summary = build_overall_summary(
                source_flaws, scoring.scores, scoring.unevaluated, audio.duration_s,
                thresholds_calibrated=settings.THRESHOLDS_CALIBRATED,
            )

            words, omitted = self._response_words(aligned, offset)
            if omitted:
                notes.append(AnalysisNote(
                    code="words_without_timing",
                    message=f"{omitted} word(s) have incomplete timing or confidence information and are left out of the word list.",
                ))

            result = AnalysisResult(
                analysis_id=analysis_id,
                config_version=settings.CONFIG_VERSION,
                pipeline_version=settings.PIPELINE_VERSION,
                audio=AudioInfo(
                    sha256=audio.sha256, duration_s=audio.duration_s, sample_rate_hz=audio.sample_rate_hz,
                    channels=audio.channels, peak_dbfs=audio.peak_dbfs,
                    trim_start_s=round(audio.trim_start_s, TIME_DECIMALS),
                    source_duration_s=None if audio.source_duration_s is None else round(audio.source_duration_s, TIME_DECIMALS),
                ),
                baseline=BaselineInfo(
                    baseline_id=request.baseline_id, passage_id=request.passage_id,
                    sha256=record.sha256, dataset_version=record.dataset_version,
                ),
                alignment_method=aligned.alignment_method,
                transcript=aligned.text,
                alignment=words,
                features=self._feature_set(f0, energy, rate, pauses.events, mfcc_summary, offset),
                baseline_stats=record.to_response_stats(),
                flaws=api_flaws,
                scores=scoring.scores,
                overall_summary=summary,
                processing_meta=ProcessingMeta(
                    whisper_model=None if transcript.source == TranscriptSource.MANUAL
                    else transcript.model_name.replace("whisper_", "", 1),
                    transcript_source=transcript.source,
                    processing_time_s=round(self._clock() - started, 3),
                    cached=False,
                ),
                notes=notes,
                config_fingerprint=fingerprint,
            )
            try:
                self.cache.put(result)
            except OSError as exc:
                # The analysis itself succeeded; losing the stored copy must not discard it. Say so instead.
                logger.error("result %s could not be stored: %s", analysis_id, _short(exc))
                result = result.model_copy(update={"notes": [*result.notes, AnalysisNote(
                    code="result_not_stored",
                    message="The result could not be saved on the server, so GET /result/{analysis_id} will not find it.",
                )]})
            return result

    # -- assembly helpers (all time conversion happens here) ---------------------------------
    @staticmethod
    def _response_words(aligned: AlignedTranscript, offset: float) -> "tuple[List[ResponseAlignedWord], int]":
        words: List[ResponseAlignedWord] = []
        omitted = 0
        for w in aligned.words:
            if w.start_s is None or w.end_s is None or w.confidence is None:
                omitted += 1
                continue
            words.append(ResponseAlignedWord(word=w.word, start_s=_t(w.start_s, offset), end_s=_t(w.end_s, offset), confidence=w.confidence))
        return words, omitted

    @staticmethod
    def _feature_set(f0: Any, energy: Any, rate: Any, pause_events: Sequence[PauseEvent], mfcc_summary: Optional[Dict[str, List[float]]], offset: float) -> FeatureSet:
        values_hz = [
            _finite_or_none(v, 3) if bool(voiced) else None for v, voiced in zip(f0.values_hz, f0.voiced)
        ]
        return FeatureSet(
            f0_timeline=F0Timeline(
                times_s=[_t(x, offset) for x in f0.times_s],
                values_hz=values_hz,
                voiced=[v is not None for v in values_hz],
            ),
            energy_timeline=EnergyTimeline(
                times_s=[_t(x, offset) for x in energy.times_s],
                values_db=[round(float(v), 3) for v in energy.values_db],
            ),
            speech_rate_timeline=SpeechRateTimeline(
                times_s=[_t(x, offset) for x in rate.times_s],
                words_per_min=[round(float(v), 3) for v in rate.words_per_min],
            ),
            pause_events=[
                PauseEvent(
                    start_s=_t(e.start_s, offset), end_s=_t(e.end_s, offset), duration_s=round(e.duration_s, TIME_DECIMALS),
                    detection_source=e.detection_source, boundary_type=e.boundary_type,
                )
                for e in pause_events
            ],
            mfcc_summary=None if mfcc_summary is None else MfccSummary(
                mean_13=[round(v, 4) for v in mfcc_summary["mean_13"]], std_13=[round(v, 4) for v in mfcc_summary["std_13"]]
            ),
        )

    def _notes(
        self, *, request: AnalyzeRequest, record: BaselineStatsRecord, aligned: AlignedTranscript, transcript: Transcript,
        alignment_warnings: Sequence[str], normalized: Any, scoring: Any, mfcc_available: bool, fallback_used: bool,
        energy: Any,
    ) -> List[AnalysisNote]:
        notes: List[AnalysisNote] = []

        def add(code: str, message: str) -> None:
            notes.append(AnalysisNote(code=code, message=message))

        if not settings.THRESHOLDS_CALIBRATED:
            add("thresholds_uncalibrated",
                "Detection thresholds and score weights are initial values that have not been calibrated on recorded data; "
                "treat findings and scores as indicative.")
        if record.n_rate_windows < settings.BASELINE_THIN_RATE_WINDOWS:
            add("baseline_thin_rate",
                f"The baseline speech-rate statistics rest on only {record.n_rate_windows} rolling window(s); speech-rate "
                "z-scores can be over-sensitive.")
        if record.n_pauses_within_phrase < settings.BASELINE_THIN_PAUSES:
            add("baseline_thin_pauses",
                f"The baseline pause statistics rest on only {record.n_pauses_within_phrase} within-phrase pause(s); "
                "pause z-scores can be over-sensitive.")

        quiet_limit = self.config.energy.quiet_warning_dbfs
        if float(energy.mean_db) < quiet_limit:
            add("audio_very_quiet",
                f"The recording's mean level ({float(energy.mean_db):.1f} dBFS) is below {quiet_limit:.1f} dBFS, so it is mostly "
                "silence relative to its peak; energy-based findings can be unreliable.")

        passage_text = self.passages.get_text(request.passage_id)
        if passage_text is None:
            add("passage_text_unavailable", "The reference text of this passage is not available, so the transcript could not be compared with it.")
        else:
            ratio = content_match_ratio(transcript.text, passage_text)
            if ratio < settings.PASSAGE_MATCH_MIN_RATIO:
                add("content_mismatch",
                    f"The transcript matches the passage text only partly (word-sequence similarity {ratio:.2f}); the baseline "
                    "comparison assumes the same content was read.")

        for warning in alignment_warnings:
            add("alignment_warning", warning)

        for name in sorted(normalized.unavailable):
            add(f"{name}_unavailable", f"The {name} analysis was not available: {normalized.unavailable[name]}.")

        uncomparable = sum(1 for p in normalized.pauses if not math.isfinite(p.z_score))
        if uncomparable:
            add("pauses_not_comparable",
                f"{uncomparable} pause(s) could not be compared with the baseline (unknown pause type or no baseline spread for that type).")

        for feature in scoring.unevaluated:
            add(f"{feature.value}_not_scored", f"{feature.value.replace('_', ' ').capitalize()} was not evaluated and is not part of the score: {scoring.excluded[feature]}.")

        if request.speaker_gender is not None:
            add("speaker_gender_ignored", "The speaker_gender hint was ignored: baselines are not gender-specific.")
        if not mfcc_available:
            add("mfcc_unavailable", "The MFCC summary could not be computed for this audio.")
        if settings.EXPLANATION_PROVIDER != "template":
            add("explanation_provider_unavailable",
                f"Explanation provider '{settings.EXPLANATION_PROVIDER}' is not implemented; template explanations were used.")
        if fallback_used:
            add("explanation_fallback_used", "At least one explanation used the minimal fallback text.")
        return notes
