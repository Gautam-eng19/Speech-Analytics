"""Unit tests for the pipeline's own logic: error mapping, content check, config fingerprint (DEC-016, DEC-032).

The analytical stages are tested elsewhere; here only the orchestration contract is exercised: which failure becomes which public
error code, that failures never leave anything in the cache and never leak internals, and how the content check and the
configuration fingerprint behave. The full happy path on synthetic speech is in tests/test_pipeline_e2e.py.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np
import pytest
import scipy.io.wavfile as wavfile
from app.core.baseline import BaselineProvider
from app.core.cache import ResultCache
from app.core.config import settings
from app.core.passages import PassageCatalog
from app.schemas.common import AlignmentMethod, ErrorCode, TranscriptSource
from app.schemas.contracts import AlignedTranscript, AlignedWord, BaselineStatsRecord, Transcript
from app.schemas.request import AnalyzeRequest
from app.services.audio import AudioPreprocessor
from app.services.grounding import DetectionConfig
from app.services.pipeline import (
    AnalysisPipeline,
    PipelineConfig,
    PipelineError,
    _canon,
    analysis_config_fingerprint,
    content_match_ratio,
    library_versions,
)
from test_baseline_provider import _record, _write

REQUEST = AnalyzeRequest(baseline_id="p001", passage_id="p001")
SR = 16000
USABLE_SNAPSHOT = {"energy_frame_selection": "active", "energy_active_threshold_dbfs": -50.0, "std_ddof": 1}


def usable_record(**overrides):
    """A baseline record the normalizer accepts (the provider tests' default snapshot has no energy threshold).

    Its energy statistics match a peak-normalised (-3 dBFS) sine, whose RMS level is about -6 dBFS, so the test tones below are
    "normal" delivery against it unless a test overrides the statistics.
    """
    overrides.setdefault("config_snapshot", dict(USABLE_SNAPSHOT))
    overrides.setdefault("energy_db_mean", -6.0)
    overrides.setdefault("energy_db_std", 3.0)
    return _record(**overrides)


def tone_wav(seconds: float = 2.0, amp: float = 0.5, freq: float = 200.0) -> bytes:
    t = np.arange(int(seconds * SR)) / SR
    buf = io.BytesIO()
    wavfile.write(buf, SR, (amp * np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16))
    return buf.getvalue()


class ScriptedTranscriber:
    def __init__(self, text: str = "hello world", error: Optional[BaseException] = None) -> None:
        self.text, self.error, self.calls = text, error, 0

    def transcribe(self, audio):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return Transcript(text=self.text, segments=[], words=[], model_name="whisper_small.en",
                          source=TranscriptSource.ASR, language="en")


class ScriptedAligner:
    """Answers with the given (word, start, end) triples; start/end may be None (an unaligned word)."""

    def __init__(self, words: Sequence[Tuple[str, Optional[float], Optional[float]]] = (("hello", 0.1, 0.9), ("world", 1.0, 1.8)),
                 error: Optional[BaseException] = None, coverage: float = 0.9, text: Optional[str] = None) -> None:
        self.words, self.error, self.coverage, self.calls = list(words), error, coverage, 0
        self.text = text                                       # None: join the words; otherwise the transcript text to report

    def align(self, audio, transcript):
        self.calls += 1
        if self.error is not None:
            raise self.error
        aligned: List[AlignedWord] = [AlignedWord(word=w, start_s=s, end_s=e, confidence=0.9 if s is not None else None)
                                      for w, s, e in self.words]
        text = self.text if self.text is not None else " ".join(w for w, _, _ in self.words)
        return AlignedTranscript(text=text, words=aligned, alignment_method=AlignmentMethod.WHISPERX,
                                 total_coverage_pct=self.coverage)


def make_pipeline(tmp_path: Path, *, transcriber=None, aligner=None, preprocessor=None, record=None, write_baseline: bool = True):
    if write_baseline:
        _write(tmp_path / "baselines", record or usable_record())
    pipeline = AnalysisPipeline(
        preprocessor=preprocessor, transcriber=transcriber or ScriptedTranscriber(), aligner=aligner or ScriptedAligner(),
        baseline_provider=BaselineProvider(tmp_path / "baselines"), cache=ResultCache(tmp_path / "cache"),
        passages=PassageCatalog(tmp_path / "none.json"),
    )
    return pipeline


def assert_fails(pipeline: AnalysisPipeline, audio: bytes, code: ErrorCode, request: AnalyzeRequest = REQUEST) -> PipelineError:
    with pytest.raises(PipelineError) as info:
        pipeline.analyze(audio, request)
    assert info.value.code == code, info.value.detail
    assert info.value.detail.strip()
    assert not list(pipeline.cache.directory.glob("*.json")), "a failed analysis must not leave a stored result"
    return info.value


# ------------------------------------------------------------------ the happy path (sanity)
def test_the_scripted_pipeline_completes_on_simple_audio(tmp_path):
    result = make_pipeline(tmp_path).analyze(tone_wav(), REQUEST)
    assert result.baseline.passage_id == "p001" and result.audio.duration_s > 1.9 and result.flaws == []
    assert result.processing_meta.cached is False


def test_a_recording_that_is_flagged_from_its_very_first_frame_still_yields_a_valid_result(tmp_path):
    """Regression: a flaw touching either end of the recording used to start at -0.005 s and fail the public contract."""
    loud_baseline = usable_record(energy_db_mean=-25.0, energy_db_std=5.0)          # the tone (-6 dBFS) is 3.8 sd too loud
    result = make_pipeline(tmp_path, record=loud_baseline).analyze(tone_wav(2.0), REQUEST)
    (flaw,) = result.flaws
    assert flaw.type.value == "high_energy" and flaw.start_s == 0.0
    assert flaw.end_s == pytest.approx(result.audio.duration_s, abs=0.011) and flaw.end_s <= result.audio.duration_s + 0.01
    assert "0.0" in flaw.explanation                                                # the text starts at 0.0 s, not at "-0.0"
    assert type(result).model_validate_json(result.model_dump_json()) == result


# ------------------------------------------------------------------------------ error mapping
@pytest.mark.parametrize("blob", [
    b"this is not audio at all",
    b"RIFF\x00\x00\x00\x00WAVEfmt ",                 # a truncated WAV: the decoder fails with a Python-internal message
    bytes(range(256)) * 20,
])
def test_undecodable_audio_is_an_unsupported_format_with_a_fixed_message(tmp_path, blob):
    error = assert_fails(make_pipeline(tmp_path), blob, ErrorCode.UNSUPPORTED_AUDIO_FORMAT)
    assert error.detail == "The audio could not be decoded. Upload a valid WAV or MP3 recording."     # no decoder text


def test_audio_over_the_duration_limit_is_audio_too_long(tmp_path):
    pipeline = make_pipeline(tmp_path, preprocessor=AudioPreprocessor(max_duration_s=1.0))
    assert_fails(pipeline, tone_wav(2.0), ErrorCode.AUDIO_TOO_LONG)


def test_silent_audio_is_a_validation_error_not_a_crash(tmp_path):
    silent = tone_wav(2.0, amp=0.0)
    error = assert_fails(make_pipeline(tmp_path), silent, ErrorCode.VALIDATION_ERROR)
    assert "no speech" in error.detail.lower()


def test_unknown_baseline_is_baseline_not_found_without_revealing_server_paths(tmp_path):
    pipeline = make_pipeline(tmp_path, write_baseline=False)
    error = assert_fails(pipeline, tone_wav(), ErrorCode.BASELINE_NOT_FOUND)
    assert "'p001'" in error.detail and str(tmp_path) not in error.detail and "baselines" not in error.detail


def test_a_baseline_for_another_passage_is_a_validation_error(tmp_path):
    _write(tmp_path / "baselines", usable_record(passage_id="p002"), name="p001.json")           # file p001.json describes p002
    pipeline = make_pipeline(tmp_path, write_baseline=False)
    error = assert_fails(pipeline, tone_wav(), ErrorCode.VALIDATION_ERROR)
    assert "p001" in error.detail


def test_a_tampered_baseline_is_a_processing_error_that_does_not_leak_paths(tmp_path):
    path = _write(tmp_path / "baselines", usable_record())
    data = json.loads(path.read_text(encoding="utf-8"))
    data["energy_db_mean"] += 1.0                                          # changed content, stale sha256
    path.write_text(json.dumps(data), encoding="utf-8")
    assert not BaselineStatsRecord.model_validate(data).verify_sha256()    # the tampering really happened
    pipeline = make_pipeline(tmp_path, write_baseline=False)
    error = assert_fails(pipeline, tone_wav(), ErrorCode.PROCESSING_ERROR)
    assert str(tmp_path) not in error.detail and "sha256" not in error.detail


@pytest.mark.parametrize("snapshot", [
    {"energy_frame_selection": "nonsense", "std_ddof": 1},                                  # unknown frame rule
    {"energy_frame_selection": "active", "std_ddof": 1},                                    # rule without its threshold
])
def test_a_baseline_the_normalizer_cannot_use_is_a_processing_error(tmp_path, snapshot):
    pipeline = make_pipeline(tmp_path, record=usable_record(config_snapshot=snapshot))
    error = assert_fails(pipeline, tone_wav(), ErrorCode.PROCESSING_ERROR)
    assert error.detail.startswith("The analysis could not be completed") and "energy" in error.detail


def test_a_failing_transcriber_is_a_processing_error_without_the_model_message(tmp_path):
    pipeline = make_pipeline(tmp_path, transcriber=ScriptedTranscriber(error=RuntimeError("exploded at /srv/models/whisper.pt")))
    error = assert_fails(pipeline, tone_wav(), ErrorCode.PROCESSING_ERROR)
    assert error.detail == "Transcription failed."


def test_an_empty_transcript_is_a_validation_error(tmp_path):
    transcriber = ScriptedTranscriber(text="   ")
    aligner = ScriptedAligner()
    error = assert_fails(make_pipeline(tmp_path, transcriber=transcriber, aligner=aligner), tone_wav(), ErrorCode.VALIDATION_ERROR)
    assert "transcribed" in error.detail and aligner.calls == 0


def test_a_failing_aligner_is_a_processing_error_without_the_model_message(tmp_path):
    pipeline = make_pipeline(tmp_path, aligner=ScriptedAligner(error=RuntimeError("missing /srv/models/wav2vec2.pt")))
    error = assert_fails(pipeline, tone_wav(), ErrorCode.PROCESSING_ERROR)
    assert error.detail == "Forced alignment failed."


@pytest.mark.parametrize("words", [
    [],                                                                    # nothing aligned at all
    [("hello", None, None), ("world", None, None)],                        # words without any timing
])
def test_speech_that_cannot_be_aligned_is_a_validation_error(tmp_path, words):
    # As WhisperX does: the transcript text is there, but no word could be placed in the audio.
    aligner = ScriptedAligner(words=words, text="hello world")
    error = assert_fails(make_pipeline(tmp_path, aligner=aligner), tone_wav(), ErrorCode.VALIDATION_ERROR)
    assert "No words could be aligned" in error.detail


@pytest.mark.parametrize("words,fragment", [
    ([("hello", 0.1, 0.9), ("world", 1.0, 9.0)], "audio"),                 # extends far beyond the 2 s of audio
    ([("hello", 1.0, 1.5), ("world", 0.2, 0.6)], ""),                      # goes back in time
])
def test_an_inconsistent_alignment_is_a_processing_error(tmp_path, words, fragment):
    error = assert_fails(make_pipeline(tmp_path, aligner=ScriptedAligner(words=words)), tone_wav(), ErrorCode.PROCESSING_ERROR)
    assert error.detail.startswith("The word alignment failed validation") and fragment in error.detail


def test_a_transcriber_is_not_created_when_a_manual_transcript_is_given(tmp_path):
    class Exploding:
        def transcribe(self, audio):                                      # pragma: no cover - must not run
            raise AssertionError("ASR must not run when a manual transcript is supplied")

    request = AnalyzeRequest(baseline_id="p001", passage_id="p001", manual_transcript="hello world")
    result = make_pipeline(tmp_path, transcriber=Exploding()).analyze(tone_wav(), request)
    assert result.processing_meta.transcript_source == TranscriptSource.MANUAL


def test_alignment_warnings_are_reported_as_notes(tmp_path):
    result = make_pipeline(tmp_path, aligner=ScriptedAligner(coverage=0.1)).analyze(tone_wav(), REQUEST)
    assert any(n.code == "alignment_warning" for n in result.notes)


def _mostly_silent_wav() -> bytes:
    """Two short tone bursts around 6 s of digital silence: after peak normalisation the mean level is far below -70 dBFS."""
    burst = 0.5 * np.sin(2 * np.pi * 200.0 * np.arange(int(0.3 * SR)) / SR)
    signal = np.concatenate([burst, np.zeros(6 * SR), burst])
    buf = io.BytesIO()
    wavfile.write(buf, SR, (signal * 32767).astype(np.int16))
    return buf.getvalue()


def test_a_mostly_silent_recording_is_flagged_as_very_quiet_and_a_normal_one_is_not(tmp_path):
    aligner = ScriptedAligner(words=(("a", 0.0, 0.3), ("b", 6.3, 6.6)))
    quiet = make_pipeline(tmp_path / "quiet", aligner=aligner).analyze(_mostly_silent_wav(), REQUEST)
    note = next(n for n in quiet.notes if n.code == "audio_very_quiet")
    assert "-70.0 dBFS" in note.message and "unreliable" in note.message
    normal = make_pipeline(tmp_path / "normal").analyze(tone_wav(), REQUEST)
    assert "audio_very_quiet" not in [n.code for n in normal.notes]


def test_words_without_timing_are_listed_as_omitted_but_do_not_stop_the_analysis(tmp_path):
    words = [("hello", 0.1, 0.9), ("uh", None, None), ("world", 1.0, 1.8)]
    result = make_pipeline(tmp_path, aligner=ScriptedAligner(words=words)).analyze(tone_wav(), REQUEST)
    assert [w.word for w in result.alignment] == ["hello", "world"]
    note = next(n for n in result.notes if n.code == "words_without_timing")
    assert note.message.startswith("1 word(s)")


def test_a_result_that_cannot_be_saved_is_still_returned_with_a_note(tmp_path):
    blocker = tmp_path / "cache"
    blocker.write_text("a file where the cache directory should be", encoding="utf-8")        # mkdir/write will fail
    pipeline = make_pipeline(tmp_path)
    assert pipeline.cache.directory == blocker
    result = pipeline.analyze(tone_wav(), REQUEST)
    note = next(n for n in result.notes if n.code == "result_not_stored")
    assert "/result/" in note.message and result.processing_meta.cached is False
    assert result.audio.duration_s > 1.9 and str(tmp_path) not in note.message
    again = pipeline.analyze(tone_wav(), REQUEST)                  # nothing was stored, so the second request is computed again
    assert again.processing_meta.cached is False and again.analysis_id == result.analysis_id


# ------------------------------------------------------------------- content check
@pytest.mark.parametrize("a,b,expected", [
    ("Welcome everyone. Today we present Track C", "welcome everyone today we present track c", 1.0),
    ("  Welcome,   EVERYONE! ", "welcome everyone", 1.0),
    ("", "welcome everyone", 0.0),
    ("welcome everyone", "", 0.0),
    ("alpha beta gamma", "delta epsilon zeta", 0.0),
])
def test_content_match_ratio_exact_cases(a, b, expected):
    assert content_match_ratio(a, b) == expected


def test_content_match_ratio_is_graded_and_order_sensitive():
    full = "one two three four five six seven eight nine ten"
    half = "one two three four five"
    ratio = content_match_ratio(half, full)
    assert ratio == pytest.approx(2 * 5 / 15)                                  # SequenceMatcher: 2*matches / total tokens
    assert 0.0 < ratio < 1.0
    assert content_match_ratio("ten nine eight seven six five four three two one", full) < 0.5
    assert content_match_ratio(full, half) == ratio                            # symmetric for this measure


def test_content_match_ratio_is_deterministic():
    a, b = "the quick brown fox jumps", "the quick red fox leaps"
    assert len({content_match_ratio(a, b) for _ in range(5)}) == 1


# ------------------------------------------------------------- fingerprint / versions
def test_fingerprint_is_stable_and_a_sha256():
    one = analysis_config_fingerprint(PipelineConfig())
    assert one == analysis_config_fingerprint(PipelineConfig())
    assert len(one) == 64 and set(one) <= set("0123456789abcdef")


@pytest.mark.parametrize("config", [
    PipelineConfig(detection=DetectionConfig(z_energy=2.5)),
    PipelineConfig(detection=DetectionConfig(z_rate_fast=3.0)),
    PipelineConfig(detection=DetectionConfig(merge_gap_s=0.7)),
])
def test_fingerprint_changes_with_any_analytical_constant(config):
    assert analysis_config_fingerprint(config) != analysis_config_fingerprint(PipelineConfig())


@pytest.mark.parametrize("name,value", [
    ("THRESHOLDS_CALIBRATED", True), ("MIN_COVERAGE_PCT", 0.5), ("WHISPER_MODEL", "tiny"), ("TARGET_PEAK_DBFS", -6.0),
])
def test_fingerprint_changes_with_the_settings_that_influence_results(monkeypatch, name, value):
    before = analysis_config_fingerprint(PipelineConfig())
    monkeypatch.setattr(settings, name, value)
    assert analysis_config_fingerprint(PipelineConfig()) != before


def test_fingerprint_ignores_machine_specific_settings(monkeypatch):
    before = analysis_config_fingerprint(PipelineConfig())
    monkeypatch.setattr(settings, "DATA_DIR", "/somewhere/else")
    monkeypatch.setattr(settings, "MAX_UPLOAD_BYTES", 12345)
    assert analysis_config_fingerprint(PipelineConfig()) == before


def test_canon_handles_nested_values_and_rejects_unknown_types():
    assert _canon({"b": (1, 2.5), "a": [True, None, "x"]}) == {"b": [1, 2.5], "a": [True, None, "x"]}
    assert _canon(float("nan")) == "nan" and _canon(float("inf")) == "inf"
    with pytest.raises(TypeError):
        _canon(object())


def test_library_versions_reports_every_numeric_library_or_none():
    versions = library_versions()
    assert set(versions) == {"numpy", "scipy", "librosa", "av", "openai-whisper", "whisperx", "torch"}
    assert all(v is None or (isinstance(v, str) and v) for v in versions.values())
    assert versions["numpy"] == np.__version__
