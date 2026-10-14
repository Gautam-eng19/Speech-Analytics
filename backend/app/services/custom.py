"""Custom passages: a baseline made from the user's own passage text and 2 to 6 of their own baseline recordings.

The analysis compares a recording with the effective delivery of the SAME content. The project ships baselines for its own passages; this
service lets a user bring their own passage: they give the text and a few recordings of a good reading, and the service makes a baseline in
exactly the way the offline dataset tool does (`app.services.baseline_builder`, the same preprocessing, alignment, features and word profile).
The ordinary analysis (`POST /analyze`) then works on it unchanged, because the baseline and passage providers also look in `data/custom/`.

Per baseline recording: preprocess, force-align it to the passage text (the text IS the transcript, as in the dataset tool), refuse it if too
few of the passage words could be timed, and, when the speech recogniser is available, refuse it if what was said does not match the passage.
Nothing of the audio is kept: only the statistics (and the passage text) are stored, under ids ``custom-<12 hex>`` that are derived from the
text and the recordings, so the same input gives the same baseline.

Errors are `CustomError(code, detail)` with the public `ErrorCode`s; `detail` is built from this project's own messages and the user's file names.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from app.core.baseline import (
    CUSTOM_BASELINE_SUBDIR,
    CUSTOM_ID_PREFIX,
    CUSTOM_PASSAGES_FILE,
    BaselineIntegrityError,
    BaselineNotFoundError,
    BaselineProvider,
    is_custom_id,
)
from app.core.config import settings
from app.schemas.common import ErrorCode, TranscriptSource
from app.schemas.contracts import AlignedTranscript, BaselineStatsRecord, Transcript
from app.schemas.request import ALLOWED_AUDIO_EXTENSIONS
from app.schemas.response import CustomBaselineDeleted, CustomBaselineResult, CustomTakeSummary
from app.services.alignment import validate_alignment
from app.services.audio import AudioPreprocessingError, AudioPreprocessor, AudioTooLongError
from app.services.baseline_builder import (
    BaselineBuildError,
    aggregate_baseline_stats,
    default_config_snapshot,
    extract_recording_features,
)
from app.services.grounding.profile import passage_tokens

logger = logging.getLogger(__name__)

DATASET_VERSION = "custom-1"
MAX_PASSAGE_CHARS = 8000
MAX_TITLE_CHARS = 80
_SENTENCE_END = re.compile(r"[.!?]+(?:[\"')\]]*)(?=\s|$)")
_ID_RE = re.compile(r"^custom-[0-9a-f]{12}$")


class CustomError(Exception):
    """A failure that maps onto a public error code; `detail` is safe to show."""

    def __init__(self, code: ErrorCode, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def normalise_passage(text: str) -> str:
    """The passage with every run of whitespace turned into one space (the aligner splits the text into words on spaces)."""
    return " ".join(str(text).split())


def content_match(transcript_text: str, passage_text: str) -> float:
    """Similarity in [0, 1] of the word sequences of what was recognised and of the passage (the pipeline's own measure)."""
    from app.services.pipeline import content_match_ratio

    return content_match_ratio(transcript_text, passage_text)


def custom_id_for(passage_text: str, recordings: Sequence[bytes]) -> str:
    """``custom-<12 hex>``: a function of the passage text and the recordings (in any order), so the same input is the same baseline."""
    digest = hashlib.sha256()
    digest.update(normalise_passage(passage_text).encode("utf-8"))
    for sha in sorted(hashlib.sha256(r).hexdigest() for r in recordings):
        digest.update(b"\0")
        digest.update(sha.encode("ascii"))
    return CUSTOM_ID_PREFIX + digest.hexdigest()[:12]


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class CustomStore:
    """Where custom baselines and passages live: ``<data>/custom/baseline_stats/<id>.json`` and ``<data>/custom/passages.json``."""

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        base = Path(data_dir) if data_dir is not None else Path(settings.DATA_DIR)
        self.baseline_dir = base / CUSTOM_BASELINE_SUBDIR
        self.passages_file = base / CUSTOM_PASSAGES_FILE
        self._lock = threading.Lock()

    def baseline_path(self, custom_id: str) -> Path:
        if not _ID_RE.match(custom_id):
            raise BaselineNotFoundError(f"invalid custom id {custom_id!r}")
        return self.baseline_dir / f"{custom_id}.json"

    def provider(self) -> BaselineProvider:
        """A provider that reads only custom baselines (the project directory is a placeholder that is never listed for custom ids)."""
        return BaselineProvider(self.baseline_dir.parent / "_none", custom_directory=self.baseline_dir)

    def _entries(self) -> List[Dict[str, Any]]:
        try:
            data = json.loads(self.passages_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []

    def count(self) -> int:
        if not self.baseline_dir.is_dir():
            return 0
        return sum(1 for p in self.baseline_dir.glob("custom-*.json") if _ID_RE.match(p.stem))

    def exists(self, custom_id: str) -> bool:
        try:
            return self.baseline_path(custom_id).is_file()
        except BaselineNotFoundError:
            return False

    def title_of(self, custom_id: str) -> Optional[str]:
        for entry in self._entries():
            if entry.get("passage_id") == custom_id and isinstance(entry.get("title"), str):
                return entry["title"]
        return None

    def save(self, record: BaselineStatsRecord, title: str, text: str) -> None:
        with self._lock:
            _atomic_write(self.baseline_path(record.passage_id), record.model_dump_json(indent=2) + "\n")
            entries = [e for e in self._entries() if e.get("passage_id") != record.passage_id]
            entries.append({
                "passage_id": record.passage_id, "title": title, "text": text, "target_word_count": len(passage_tokens(text)),
                "domain": "custom", "dataset_version": DATASET_VERSION, "created_at": date.today().isoformat(),
            })
            entries.sort(key=lambda e: str(e.get("passage_id")))
            _atomic_write(self.passages_file, json.dumps(entries, indent=2, ensure_ascii=False) + "\n")

    def delete(self, custom_id: str) -> bool:
        """Remove the baseline and its passage; False when there was nothing to remove."""
        path = self.baseline_path(custom_id)
        with self._lock:
            existed = path.is_file()
            if existed:
                path.unlink()
            entries = self._entries()
            kept = [e for e in entries if e.get("passage_id") != custom_id]
            if len(kept) != len(entries):
                _atomic_write(self.passages_file, json.dumps(kept, indent=2, ensure_ascii=False) + "\n")
            return existed


@dataclass
class _Take:
    filename: str
    raw: bytes
    duration_s: float = 0.0
    words_per_min: float = 0.0
    timed_share: float = 0.0
    content_match: Optional[float] = None


class CustomBaselineService:
    """Makes a custom baseline (see module docstring). The models and the lock are the analysis pipeline's own."""

    def __init__(
        self,
        store: Optional[CustomStore] = None,
        *,
        preprocessor: Optional[AudioPreprocessor] = None,
        get_aligner: Callable[[], Any],
        get_transcriber: Optional[Callable[[], Any]] = None,
        lock: Optional[threading.Lock] = None,
    ) -> None:
        self.store = store or CustomStore()
        self.preprocessor = preprocessor or AudioPreprocessor()
        self._get_aligner = get_aligner
        self._get_transcriber = get_transcriber
        self._lock = lock or threading.Lock()

    # -- validation -----------------------------------------------------------------------------------------------------------
    @staticmethod
    def check_passage(text: str) -> str:
        passage = normalise_passage(text)
        if not passage:
            raise CustomError(ErrorCode.VALIDATION_ERROR, "Enter the passage text that the recordings will read.")
        if len(passage) > MAX_PASSAGE_CHARS:
            raise CustomError(ErrorCode.VALIDATION_ERROR, f"The passage is too long ({len(passage)} characters; at most {MAX_PASSAGE_CHARS}).")
        n_words = len(passage_tokens(passage))
        if n_words < settings.CUSTOM_MIN_PASSAGE_WORDS:
            raise CustomError(
                ErrorCode.VALIDATION_ERROR,
                f"The passage has {n_words} words; at least {settings.CUSTOM_MIN_PASSAGE_WORDS} are needed to measure pace, loudness and pauses reliably.",
            )
        if n_words > settings.CUSTOM_MAX_PASSAGE_WORDS:
            raise CustomError(ErrorCode.VALIDATION_ERROR, f"The passage has {n_words} words; at most {settings.CUSTOM_MAX_PASSAGE_WORDS} are supported.")
        if len(_SENTENCE_END.findall(passage)) < 2:
            raise CustomError(
                ErrorCode.VALIDATION_ERROR,
                "The passage needs at least two sentences (ending in . ! or ?): the pause between sentences is part of the baseline.",
            )
        return passage

    @staticmethod
    def check_files(files: Sequence[Tuple[str, bytes]]) -> List[_Take]:
        low, high = settings.CUSTOM_MIN_BASELINE_TAKES, settings.CUSTOM_MAX_BASELINE_TAKES
        if not (low <= len(files) <= high):
            raise CustomError(
                ErrorCode.VALIDATION_ERROR,
                f"Provide between {low} and {high} baseline recordings of the passage (got {len(files)}); three give the most precise comparison.",
            )
        takes: List[_Take] = []
        seen: set = set()
        for raw_name, raw in files:
            name = os.path.basename((raw_name or "").replace("\\", "/")) or "recording"
            if os.path.splitext(name)[1].lower() not in ALLOWED_AUDIO_EXTENSIONS:
                raise CustomError(ErrorCode.UNSUPPORTED_AUDIO_FORMAT, f"“{name}” is not a WAV or MP3 file.")
            if not raw:
                raise CustomError(ErrorCode.VALIDATION_ERROR, f"“{name}” is empty.")
            if len(raw) > settings.MAX_UPLOAD_BYTES:
                raise CustomError(ErrorCode.FILE_TOO_LARGE, f"“{name}” is larger than the limit of {settings.MAX_UPLOAD_BYTES} bytes.")
            sha = hashlib.sha256(raw).hexdigest()
            if sha in seen:
                raise CustomError(ErrorCode.VALIDATION_ERROR, f"“{name}” is the same recording as another one; give separate readings of the passage.")
            seen.add(sha)
            takes.append(_Take(name, raw))
        return takes

    # -- one baseline recording -----------------------------------------------------------------------------------------------
    def _prepare_take(self, take: _Take, passage: str) -> Tuple[AlignedTranscript, List[str]]:
        try:
            audio = self.preprocessor.process(take.raw)
        except AudioTooLongError as exc:
            raise CustomError(ErrorCode.AUDIO_TOO_LONG, f"“{take.filename}”: {exc}") from exc
        except AudioPreprocessingError as exc:
            logger.warning("custom baseline: %s could not be decoded: %s", take.filename, exc)
            raise CustomError(ErrorCode.UNSUPPORTED_AUDIO_FORMAT, f"“{take.filename}” could not be decoded. Use a valid WAV or MP3 recording.") from exc
        if len(audio.audio_array) == 0 or audio.duration_s <= 0.0:
            raise CustomError(ErrorCode.VALIDATION_ERROR, f"“{take.filename}” contains no speech (it is silent).")
        take.duration_s = round(float(audio.duration_s), 2)

        warnings: List[str] = []
        if self._get_transcriber is not None and settings.CUSTOM_CHECK_CONTENT:
            try:
                heard = self._get_transcriber().transcribe(audio).text
                take.content_match = round(float(content_match(heard, passage)), 3)
            except Exception:  # noqa: BLE001 - the check is a safeguard; without the recogniser it is skipped, not fatal
                logger.exception("custom baseline: content check skipped for %s", take.filename)
            if take.content_match is not None:
                if take.content_match < settings.CUSTOM_MIN_CONTENT_MATCH:
                    raise CustomError(
                        ErrorCode.VALIDATION_ERROR,
                        f"“{take.filename}” does not seem to be a reading of this passage (the recognised words match it only {take.content_match:.0%}). "
                        "Read the passage text as written, or change the text to what was said.",
                    )
                if take.content_match < settings.CUSTOM_WARN_CONTENT_MATCH:
                    warnings.append(f"“{take.filename}”: the recognised words match the passage only {take.content_match:.0%}; check that it reads the passage.")

        transcript = Transcript(text=passage, segments=[], words=[], model_name="manual", source=TranscriptSource.MANUAL,
                                language=settings.ALIGNMENT_LANGUAGE or None)
        try:
            aligned = self._get_aligner().align(audio, transcript)
        except Exception as exc:  # noqa: BLE001
            logger.exception("custom baseline: alignment failed for %s", take.filename)
            raise CustomError(ErrorCode.PROCESSING_ERROR, f"The words of “{take.filename}” could not be aligned to the audio.") from exc
        n_words = len(aligned.words)
        timed = sum(1 for w in aligned.words if w.start_s is not None and w.end_s is not None)
        take.timed_share = round(timed / n_words, 3) if n_words else 0.0
        if take.timed_share < settings.CUSTOM_MIN_TIMED_WORD_SHARE:
            raise CustomError(
                ErrorCode.VALIDATION_ERROR,
                f"Only {take.timed_share:.0%} of the passage words could be found in “{take.filename}”. "
                "Is it a complete reading of the passage, recorded clearly?",
            )
        validation = validate_alignment(aligned, audio_duration_s=audio.duration_s, min_coverage_pct=None)
        if not validation.is_valid:
            raise CustomError(ErrorCode.VALIDATION_ERROR, f"The word timing of “{take.filename}” is not usable: " + "; ".join(validation.errors))
        speaking_s = max(1e-9, float(max(w.end_s for w in aligned.words if w.end_s is not None) - min(w.start_s for w in aligned.words if w.start_s is not None)))
        take.words_per_min = round(timed / speaking_s * 60.0, 1)
        return aligned, warnings

    # -- the whole baseline ---------------------------------------------------------------------------------------------------
    def create(self, passage_text: str, title: Optional[str], files: Sequence[Tuple[str, bytes]]) -> CustomBaselineResult:
        passage = self.check_passage(passage_text)
        takes = self.check_files(files)
        custom_id = custom_id_for(passage, [t.raw for t in takes])
        heading = " ".join((title or "").split())[:MAX_TITLE_CHARS] or (" ".join(passage.split()[:6]) + "…")

        if self.store.exists(custom_id):
            return self._existing(custom_id, passage, len(takes), heading)
        if self.store.count() >= settings.CUSTOM_MAX_BASELINES:
            raise CustomError(
                ErrorCode.VALIDATION_ERROR,
                f"There are already {settings.CUSTOM_MAX_BASELINES} custom baselines. Delete one you no longer need first.",
            )

        warnings: List[str] = []
        features = []
        with self._lock:
            for number, take in enumerate(takes, start=1):
                aligned, take_warnings = self._prepare_take(take, passage)
                warnings += take_warnings
                try:
                    features.append(extract_recording_features(f"{custom_id}_take_{number:02d}", take.raw, aligned))
                except BaselineBuildError as exc:
                    raise CustomError(ErrorCode.VALIDATION_ERROR, f"“{take.filename}” could not be measured: {exc}") from exc

        rates = [t.words_per_min for t in takes if t.words_per_min > 0]
        if len(rates) >= 2 and (max(rates) - min(rates)) / float(np.mean(rates)) > settings.CUSTOM_TAKE_RATE_SPREAD_WARN:
            warnings.append("The baseline recordings differ a lot in speaking pace; the comparison is fairest when they are readings of the same quality.")

        try:
            record = aggregate_baseline_stats(
                custom_id, DATASET_VERSION, features, extra_snapshot=default_config_snapshot({"source": "custom passage"}), passage_text=passage,
            )
        except BaselineBuildError as exc:
            raise CustomError(
                ErrorCode.VALIDATION_ERROR,
                f"A baseline could not be made from these recordings: {exc}. Record the whole passage, with a pause between its sentences.",
            ) from exc
        self.store.save(record, heading, passage)

        profile = record.word_profile
        if profile is None:
            warnings.append("Fewer than three recordings matched the passage, so pace and loudness will be compared with the recordings' overall averages, which is less precise. Add a third recording for the word-by-word comparison.")
        elif profile.pitch is None:
            warnings.append("The pitch of the words could not be measured well enough to judge flat pitch; pace, loudness and pauses are still judged word by word.")
        if record.n_rate_windows < settings.BASELINE_THIN_RATE_WINDOWS or record.n_pauses_within_phrase < settings.BASELINE_THIN_PAUSES:
            warnings.append("The baseline rests on few observations (a short passage or few recordings); expect noisier results.")
        return CustomBaselineResult(
            baseline_id=custom_id, passage_id=custom_id, title=heading, passage_text=passage, passage_word_count=len(passage_tokens(passage)),
            n_recordings=len(takes), already_existed=False, word_profile_built=profile is not None,
            pitch_profile_built=profile is not None and profile.pitch is not None,
            takes=[CustomTakeSummary(filename=t.filename, duration_s=t.duration_s, words_per_min=t.words_per_min, timed_word_share=t.timed_share,
                                     content_match=t.content_match) for t in takes],
            warnings=warnings,
        )

    def _existing(self, custom_id: str, passage: str, n_recordings: int, heading: str) -> CustomBaselineResult:
        try:
            record = self.store.provider().get(custom_id, passage_id=custom_id)
        except BaselineIntegrityError as exc:
            logger.error("custom baseline %s failed verification: %s", custom_id, exc)
            raise CustomError(ErrorCode.PROCESSING_ERROR, "The stored baseline could not be loaded; delete it and create it again.") from exc
        profile = record.word_profile
        return CustomBaselineResult(
            baseline_id=custom_id, passage_id=custom_id, title=self.store.title_of(custom_id) or heading, passage_text=passage,
            passage_word_count=len(passage_tokens(passage)), n_recordings=len(record.baseline_recording_ids), already_existed=True,
            word_profile_built=profile is not None, pitch_profile_built=profile is not None and profile.pitch is not None, takes=[], warnings=[],
        )

    def delete(self, baseline_id: str) -> CustomBaselineDeleted:
        if not is_custom_id(baseline_id) or not _ID_RE.match(baseline_id):
            raise CustomError(ErrorCode.VALIDATION_ERROR, "Only custom baselines can be deleted.")
        if not self.store.delete(baseline_id):
            raise CustomError(ErrorCode.BASELINE_NOT_FOUND, f"No custom baseline '{baseline_id}' exists.")
        return CustomBaselineDeleted(baseline_id=baseline_id, deleted=True)
