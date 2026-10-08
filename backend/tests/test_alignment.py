"""Unit and contract tests for Forced Alignment service (TASK-022).

Covers:
1. Valid alignment using mocked/stubbed WhisperX behavior
2. Correct word-level output (word, start_s, end_s, confidence)
3. Preservation of original transcript text
4. Correct start/end timing propagation
5. Missing optional confidence handling (no fabrication)
6. Invalid audio inputs (wrong SR, non-mono, non-finite, empty audio with text)
7. Invalid transcript input (wrong type, non-transcript)
8. Unsupported language handling
9. Model loading failure and alignment runtime failure handling
10. Deterministic repeated behavior
11. Model caching and reuse across calls
12. Coverage percentage calculation
13. Empty transcript handling
14. Real-model smoke test (marked @pytest.mark.smoke)
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.schemas.common import AlignmentMethod, TranscriptSource
from app.schemas.contracts import (
    AlignedTranscript,
    AlignedWord,
    PreprocessedAudio,
    Transcript,
    TranscriptSegment,
    WordTiming,
)
from app.services.alignment.aligner import (
    AlignmentConfig,
    AlignmentConfigError,
    AlignmentError,
    AlignmentModelError,
    AlignmentRuntimeError,
    WhisperXAligner,
    align,
    clear_alignment_model_cache,
)


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------

TARGET_SR = 16_000


def _make_audio(
    duration_s: float = 2.0,
    sr: int = TARGET_SR,
    channels: int = 1,
) -> PreprocessedAudio:
    """Build a valid canonical PreprocessedAudio."""
    n_samples = int(duration_s * sr)
    arr = np.zeros(n_samples, dtype=np.float32)
    # Add a tiny tone so it's not pure zero if needed
    t = np.linspace(0.0, duration_s, n_samples, endpoint=False, dtype=np.float32)
    arr = (0.1 * np.sin(2.0 * np.pi * 220.0 * t)).astype(np.float32)
    sha = hashlib.sha256(arr.tobytes()).hexdigest()
    return PreprocessedAudio(
        sample_rate_hz=sr,
        channels=channels,
        duration_s=round(duration_s, 4),
        audio_array=arr,
        sha256=sha,
        peak_dbfs=-20.0,
    )


def _make_transcript(
    text: str = "hello world",
    words: Optional[List[Tuple[str, float, float]]] = None,
) -> Transcript:
    """Build a valid canonical Transcript with segments."""
    if words is None:
        words = [("hello", 0.0, 0.6), ("world", 0.7, 1.5)]

    word_timings = [
        WordTiming(word=w, approx_start_s=s, approx_end_s=e, probability=0.95)
        for w, s, e in words
    ]
    segment = TranscriptSegment(
        segment_id=0,
        text=text,
        start_s=words[0][1] if words else 0.0,
        end_s=words[-1][2] if words else 0.0,
        no_speech_prob=0.01,
        words=word_timings,
    )
    return Transcript(
        text=text,
        segments=[segment],
        words=word_timings,
        model_name="whisper_base",
        source=TranscriptSource.ASR,
        language="en",
    )


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    clear_alignment_model_cache()


def _mock_whisperx_output(
    aligned_words: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build a mock WhisperX alignment response dict."""
    if aligned_words is None:
        aligned_words = [
            {"word": "hello", "start": 0.12, "end": 0.58, "score": 0.94},
            {"word": "world", "start": 0.72, "end": 1.45, "score": 0.88},
        ]
    return {
        "segments": [
            {
                "start": 0.12,
                "end": 1.45,
                "text": "hello world",
                "words": aligned_words,
            }
        ],
        "word_segments": aligned_words,
    }


def _create_mock_aligner(
    mock_raw_output: Optional[Dict[str, Any]] = None,
) -> WhisperXAligner:
    """Create a WhisperXAligner with mocked loader and align runner."""
    raw_output = mock_raw_output or _mock_whisperx_output()
    mock_model = MagicMock()
    mock_metadata = {"dictionary": {"a": 1}, "language": "en"}

    mock_loader = MagicMock(return_value=(mock_model, mock_metadata))
    mock_align_fn = MagicMock(return_value=raw_output)

    aligner = WhisperXAligner(
        config=AlignmentConfig(device="cpu", language_code="en"),
        load_align_model_fn=mock_loader,
        align_fn=mock_align_fn,
    )
    return aligner


# ---------------------------------------------------------------------------
# Tests: Valid Alignment & Contract Conformance
# ---------------------------------------------------------------------------

def test_valid_alignment_mocked() -> None:
    """Test 1: Valid alignment using mocked WhisperX produces AlignedTranscript."""
    clear_alignment_model_cache()
    aligner = _create_mock_aligner()
    audio = _make_audio(duration_s=2.0)
    transcript = _make_transcript("hello world")

    aligned = aligner.align(audio, transcript)

    assert isinstance(aligned, AlignedTranscript)
    assert aligned.alignment_method == AlignmentMethod.WHISPERX
    assert aligned.text == "hello world"
    assert len(aligned.words) == 2


def test_word_level_output_and_timing_propagation() -> None:
    """Test 2 & 4: Word-level output and accurate start/end timing propagation."""
    clear_alignment_model_cache()
    aligner = _create_mock_aligner()
    audio = _make_audio(duration_s=2.0)
    transcript = _make_transcript()

    aligned = aligner.align(audio, transcript)

    w1 = aligned.words[0]
    assert isinstance(w1, AlignedWord)
    assert w1.word == "hello"
    assert w1.start_s == pytest.approx(0.12)
    assert w1.end_s == pytest.approx(0.58)
    assert w1.confidence == pytest.approx(0.94)

    w2 = aligned.words[1]
    assert w2.word == "world"
    assert w2.start_s == pytest.approx(0.72)
    assert w2.end_s == pytest.approx(1.45)
    assert w2.confidence == pytest.approx(0.88)


def test_preservation_of_transcript_text() -> None:
    """Test 3: Full transcript text is preserved exactly from input Transcript."""
    clear_alignment_model_cache()
    aligner = _create_mock_aligner()
    audio = _make_audio(duration_s=3.0)
    special_text = "Good morning, everyone! Welcome to IIT Mandi."
    transcript = _make_transcript(text=special_text)

    aligned = aligner.align(audio, transcript)

    assert aligned.text == special_text


def test_missing_optional_confidence_handling() -> None:
    """Test 5: Words without WhisperX score have confidence=None (no fabrication)."""
    clear_alignment_model_cache()
    raw = {
        "segments": [
            {
                "start": 0.0,
                "end": 1.0,
                "text": "test missing confidence",
                "words": [
                    {"word": "test", "start": 0.1, "end": 0.4},  # No score field
                    {"word": "confidence", "start": 0.5, "end": 0.9, "score": None},
                ],
            }
        ]
    }
    aligner = _create_mock_aligner(raw)
    audio = _make_audio(duration_s=2.0)
    transcript = _make_transcript("test missing confidence")

    aligned = aligner.align(audio, transcript)

    assert len(aligned.words) == 2
    assert aligned.words[0].confidence is None
    assert aligned.words[1].confidence is None


def test_unaligned_word_missing_timing_handling() -> None:
    """Test 5 (variant): Word without timing has start_s=None, end_s=None."""
    clear_alignment_model_cache()
    raw = {
        "segments": [
            {
                "start": 0.0,
                "end": 1.0,
                "text": "unaligned word",
                "words": [
                    {"word": "unaligned"},  # no start/end
                    {"word": "word", "start": 0.4, "end": 0.8, "score": 0.9},
                ],
            }
        ]
    }
    aligner = _create_mock_aligner(raw)
    audio = _make_audio(duration_s=2.0)
    transcript = _make_transcript("unaligned word")

    aligned = aligner.align(audio, transcript)

    assert len(aligned.words) == 2
    assert aligned.words[0].word == "unaligned"
    assert aligned.words[0].start_s is None
    assert aligned.words[0].end_s is None
    assert aligned.words[1].word == "word"
    assert aligned.words[1].start_s == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# Tests: Input Validation & Edge Cases
# ---------------------------------------------------------------------------

def test_invalid_audio_wrong_sample_rate() -> None:
    """Test 6a: Audio sample rate != 16000 Hz raises AlignmentConfigError."""
    aligner = _create_mock_aligner()
    bad_audio = _make_audio(sr=8000)
    transcript = _make_transcript()

    with pytest.raises(AlignmentConfigError, match="16000 Hz"):
        aligner.align(bad_audio, transcript)


def test_invalid_audio_non_mono() -> None:
    """Test 6b: Non-mono channels raises AlignmentConfigError."""
    aligner = _create_mock_aligner()
    bad_audio = _make_audio()
    # Modify channels attribute
    object.__setattr__(bad_audio, "channels", 2)
    transcript = _make_transcript()

    with pytest.raises(AlignmentConfigError, match="mono"):
        aligner.align(bad_audio, transcript)


def test_invalid_audio_non_finite_samples() -> None:
    """Test 6c: Audio containing NaN/Inf raises AlignmentConfigError."""
    aligner = _create_mock_aligner()
    bad_audio = _make_audio()
    bad_audio.audio_array[10] = np.nan
    transcript = _make_transcript()

    with pytest.raises(AlignmentConfigError, match="non-finite"):
        aligner.align(bad_audio, transcript)


def test_empty_audio_with_non_empty_transcript() -> None:
    """Test 6d: Empty audio array (0 samples) with non-empty text raises AlignmentConfigError."""
    aligner = _create_mock_aligner()
    empty_audio = PreprocessedAudio(
        sample_rate_hz=16000,
        channels=1,
        duration_s=0.0,
        audio_array=np.empty(0, dtype=np.float32),
        sha256=hashlib.sha256(b"").hexdigest(),
        peak_dbfs=-100.0,
    )
    transcript = _make_transcript("some text")

    with pytest.raises(AlignmentConfigError, match="empty audio"):
        aligner.align(empty_audio, transcript)


def test_invalid_transcript_type() -> None:
    """Test 7: Passing non-transcript raises AlignmentConfigError."""
    aligner = _create_mock_aligner()
    audio = _make_audio()

    with pytest.raises(AlignmentConfigError, match="Transcript contract"):
        aligner.align(audio, "not a transcript")  # type: ignore[arg-type]


def test_empty_transcript_handling() -> None:
    """Test 13: Empty transcript text returns empty AlignedTranscript with 0 coverage."""
    aligner = _create_mock_aligner()
    audio = _make_audio(duration_s=2.0)
    empty_transcript = Transcript(
        text="",
        segments=[],
        words=[],
        model_name="whisper_base",
        source=TranscriptSource.ASR,
    )

    aligned = aligner.align(audio, empty_transcript)

    assert aligned.text == ""
    assert aligned.words == []
    assert aligned.total_coverage_pct == 0.0


# ---------------------------------------------------------------------------
# Tests: Error Handling & Unsupported Language
# ---------------------------------------------------------------------------

def test_unsupported_language_raises_config_error() -> None:
    """Test 8: Unsupported language raises AlignmentConfigError."""
    mock_loader = MagicMock(side_effect=ValueError("No default align-model for language: invalid_lang"))
    aligner = WhisperXAligner(
        config=AlignmentConfig(language_code="invalid_lang"),
        load_align_model_fn=mock_loader,
    )
    audio = _make_audio()
    transcript = _make_transcript()

    with pytest.raises(AlignmentConfigError, match="Unsupported language code"):
        aligner.align(audio, transcript)


def test_model_loading_failure_raises_model_error() -> None:
    """Test 9a: Model loading failure raises AlignmentModelError."""
    mock_loader = MagicMock(side_effect=RuntimeError("CUDA out of memory"))
    aligner = WhisperXAligner(
        config=AlignmentConfig(language_code="en"),
        load_align_model_fn=mock_loader,
    )
    audio = _make_audio()
    transcript = _make_transcript()

    with pytest.raises(AlignmentModelError, match="Failed to load WhisperX"):
        aligner.align(audio, transcript)


def test_alignment_runtime_failure_raises_runtime_error() -> None:
    """Test 9b: Runtime execution failure raises AlignmentRuntimeError."""
    mock_model = MagicMock()
    mock_metadata = {}
    mock_loader = MagicMock(return_value=(mock_model, mock_metadata))
    mock_align_fn = MagicMock(side_effect=RuntimeError("Alignment matrix error"))

    aligner = WhisperXAligner(
        config=AlignmentConfig(language_code="en"),
        load_align_model_fn=mock_loader,
        align_fn=mock_align_fn,
    )
    audio = _make_audio()
    transcript = _make_transcript()

    with pytest.raises(AlignmentRuntimeError, match="WhisperX alignment execution failed"):
        aligner.align(audio, transcript)


# ---------------------------------------------------------------------------
# Tests: Determinism & Caching
# ---------------------------------------------------------------------------

def test_deterministic_repeated_behavior() -> None:
    """Test 10: Repeated execution with identical inputs produces identical output."""
    clear_alignment_model_cache()
    aligner = _create_mock_aligner()
    audio = _make_audio(duration_s=2.0)
    transcript = _make_transcript()

    res1 = aligner.align(audio, transcript)
    res2 = aligner.align(audio, transcript)

    assert res1.text == res2.text
    assert len(res1.words) == len(res2.words)
    for w1, w2 in zip(res1.words, res2.words):
        assert w1.word == w2.word
        assert w1.start_s == w2.start_s
        assert w1.end_s == w2.end_s
        assert w1.confidence == w2.confidence
    assert res1.total_coverage_pct == res2.total_coverage_pct


def test_model_reuse_and_caching() -> None:
    """Test 11: Alignment model is loaded once and cached across calls/instances."""
    clear_alignment_model_cache()
    mock_model = MagicMock()
    mock_metadata = {"dict": 1}
    mock_loader = MagicMock(return_value=(mock_model, mock_metadata))
    mock_align_fn = MagicMock(return_value=_mock_whisperx_output())

    aligner1 = WhisperXAligner(
        config=AlignmentConfig(device="cpu", language_code="en"),
        load_align_model_fn=mock_loader,
        align_fn=mock_align_fn,
    )
    aligner2 = WhisperXAligner(
        config=AlignmentConfig(device="cpu", language_code="en"),
        load_align_model_fn=mock_loader,
        align_fn=mock_align_fn,
    )

    audio = _make_audio()
    transcript = _make_transcript()

    aligner1.align(audio, transcript)
    aligner2.align(audio, transcript)

    # Loader must be called exactly ONCE due to cache
    assert mock_loader.call_count == 1


# ---------------------------------------------------------------------------
# Tests: Coverage Calculation
# ---------------------------------------------------------------------------

def test_coverage_pct_calculation() -> None:
    """Test 12: Coverage percentage correctly computed from non-overlapping word durations."""
    clear_alignment_model_cache()
    # Word 1: 0.0 -> 0.5 (0.5s)
    # Word 2: 1.0 -> 1.5 (0.5s)
    # Total covered = 1.0s. Total duration = 2.0s -> coverage = 0.50
    raw = {
        "segments": [
            {
                "start": 0.0,
                "end": 1.5,
                "text": "test coverage",
                "words": [
                    {"word": "test", "start": 0.0, "end": 0.5, "score": 0.9},
                    {"word": "coverage", "start": 1.0, "end": 1.5, "score": 0.9},
                ],
            }
        ]
    }
    aligner = _create_mock_aligner(raw)
    audio = _make_audio(duration_s=2.0)
    transcript = _make_transcript("test coverage")

    aligned = aligner.align(audio, transcript)

    assert aligned.total_coverage_pct == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# Real-Model Smoke Test (Marked 'smoke' - excluded from standard test runs)
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_real_whisperx_alignment_smoke() -> None:
    """Smoke test: Runs real WhisperX alignment on CPU using synthetic audio.

    Requires downloading/loading the English wav2vec2 model (~360 MB).
    Run explicitly via: pytest -m smoke backend/tests/test_alignment.py
    """
    import whisperx

    # 1.0s synthetic audio with a simple tone
    sr = 16000
    duration_s = 1.0
    t = np.linspace(0.0, duration_s, int(sr * duration_s), endpoint=False, dtype=np.float32)
    audio_arr = (0.5 * np.sin(2.0 * np.pi * 300.0 * t)).astype(np.float32)
    sha = hashlib.sha256(audio_arr.tobytes()).hexdigest()
    audio = PreprocessedAudio(
        sample_rate_hz=sr,
        channels=1,
        duration_s=duration_s,
        audio_array=audio_arr,
        sha256=sha,
        peak_dbfs=-6.0,
    )

    transcript = Transcript(
        text="hello",
        segments=[
            TranscriptSegment(
                segment_id=0,
                text="hello",
                start_s=0.0,
                end_s=1.0,
                no_speech_prob=0.0,
                words=[WordTiming(word="hello", approx_start_s=0.0, approx_end_s=1.0)],
            )
        ],
        words=[WordTiming(word="hello", approx_start_s=0.0, approx_end_s=1.0)],
        model_name="whisper_base",
        source=TranscriptSource.ASR,
        language="en",
    )

    aligner = WhisperXAligner(config=AlignmentConfig(device="cpu", language_code="en"))
    aligned = aligner.align(audio, transcript)

    assert isinstance(aligned, AlignedTranscript)
    assert aligned.alignment_method == AlignmentMethod.WHISPERX
    assert aligned.text == "hello"
    assert len(aligned.words) >= 1
    w = aligned.words[0]
    assert w.word.lower() == "hello"
    assert w.start_s is not None
    assert w.end_s is not None
    assert w.end_s >= w.start_s
