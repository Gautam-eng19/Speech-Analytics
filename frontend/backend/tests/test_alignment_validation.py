"""Unit tests for Alignment Validation (TASK-023, ARCHITECTURE.md §12).

Tests cover all required validation dimensions:
1. Valid aligned transcript
2. Empty transcript + empty word list (valid)
3. Empty word text / whitespace-only text (invalid)
4. Negative timestamps (invalid)
5. End before start (invalid)
6. Non-finite timestamps (NaN, Inf) (invalid)
7. Backwards chronological ordering (invalid)
8. Missing timestamps accepted (WhisperX unaligned words allowed, no false failure)
9. Timestamps exceeding audio duration (with tolerance) (invalid)
10. Valid coverage boundary values (0.0, 1.0, and interior fractions)
11. Invalid coverage values (<0.0, >1.0, NaN)
12. Non-empty transcript with no aligned words (invalid)
13. Deterministic repeated validation produces identical results
14. Low coverage generates warning without failing validation
15. validate_alignment_or_raise behavior
"""
from __future__ import annotations

import math
from typing import List, Optional

import pytest
from pydantic import ValidationError

from app.schemas.common import AlignmentMethod
from app.schemas.contracts import (
    AlignedTranscript,
    AlignedWord,
    AlignmentValidationResult,
    ValidationResult,
)
from app.services.alignment import (
    AlignmentValidationError,
    validate_alignment,
    validate_alignment_or_raise,
)


# ---------------------------------------------------------------------------
# Fixture / Construction Helpers
# ---------------------------------------------------------------------------

def _make_aligned_transcript(
    text: str = "hello world",
    words: Optional[List[AlignedWord]] = None,
    total_coverage_pct: float = 0.85,
    method: AlignmentMethod = AlignmentMethod.WHISPERX,
) -> AlignedTranscript:
    """Build a standard canonical AlignedTranscript."""
    if words is None:
        words = [
            AlignedWord(word="hello", start_s=0.1, end_s=0.6, confidence=0.95),
            AlignedWord(word="world", start_s=0.7, end_s=1.2, confidence=0.90),
        ]
    return AlignedTranscript(
        text=text,
        words=words,
        alignment_method=method,
        total_coverage_pct=total_coverage_pct,
    )


# ---------------------------------------------------------------------------
# 1. Valid Aligned Transcript
# ---------------------------------------------------------------------------

def test_valid_aligned_transcript() -> None:
    """A standard valid AlignedTranscript passes validation with no errors."""
    transcript = _make_aligned_transcript()
    result = validate_alignment(transcript, audio_duration_s=2.0)

    assert result.is_valid is True
    assert result.valid is True
    assert bool(result) is True
    assert len(result.errors) == 0
    assert isinstance(result, AlignmentValidationResult)
    assert isinstance(result, ValidationResult)


# ---------------------------------------------------------------------------
# 2. Empty Transcript + Empty Word List
# ---------------------------------------------------------------------------

def test_empty_transcript_and_empty_words_is_valid() -> None:
    """An empty transcript with an empty aligned-word list is valid."""
    transcript = AlignedTranscript(
        text="",
        words=[],
        alignment_method=AlignmentMethod.WHISPERX,
        total_coverage_pct=0.0,
    )
    result = validate_alignment(transcript, audio_duration_s=0.0)

    assert result.is_valid is True
    assert len(result.errors) == 0


def test_whitespace_transcript_and_empty_words_is_valid() -> None:
    """A whitespace-only transcript with an empty aligned-word list is valid."""
    transcript = AlignedTranscript(
        text="   \n\t  ",
        words=[],
        alignment_method=AlignmentMethod.WHISPERX,
        total_coverage_pct=0.0,
    )
    result = validate_alignment(transcript)

    assert result.is_valid is True
    assert len(result.errors) == 0


# ---------------------------------------------------------------------------
# 3. Empty Word Text
# ---------------------------------------------------------------------------

def test_empty_word_text_fails_validation() -> None:
    """A word with empty or whitespace-only text fails validation."""
    # Construct with model_construct to bypass initial pydantic schema check
    bad_word_empty = AlignedWord.model_construct(
        word="", start_s=0.1, end_s=0.5, confidence=0.9
    )
    transcript_empty = AlignedTranscript.model_construct(
        text="test",
        words=[bad_word_empty],
        alignment_method=AlignmentMethod.WHISPERX,
        total_coverage_pct=0.8,
    )
    result_empty = validate_alignment(transcript_empty)
    assert result_empty.is_valid is False
    assert any("empty or whitespace-only text" in err for err in result_empty.errors)

    # Whitespace-only word text
    bad_word_ws = AlignedWord(
        word="   ", start_s=0.1, end_s=0.5, confidence=0.9
    )
    transcript_ws = AlignedTranscript(
        text="test",
        words=[bad_word_ws],
        alignment_method=AlignmentMethod.WHISPERX,
        total_coverage_pct=0.8,
    )
    result_ws = validate_alignment(transcript_ws)
    assert result_ws.is_valid is False
    assert any("empty or whitespace-only text" in err for err in result_ws.errors)


# ---------------------------------------------------------------------------
# 4. Negative Timestamps
# ---------------------------------------------------------------------------

def test_negative_start_timestamp_fails() -> None:
    """Negative start_s timestamp fails validation."""
    bad_word = AlignedWord.model_construct(
        word="negative", start_s=-0.5, end_s=0.5, confidence=0.9
    )
    transcript = AlignedTranscript.model_construct(
        text="negative",
        words=[bad_word],
        alignment_method=AlignmentMethod.WHISPERX,
        total_coverage_pct=0.5,
    )
    result = validate_alignment(transcript)
    assert result.is_valid is False
    assert any("negative start_s" in err for err in result.errors)


def test_negative_end_timestamp_fails() -> None:
    """Negative end_s timestamp fails validation."""
    bad_word = AlignedWord.model_construct(
        word="negative", start_s=0.0, end_s=-0.2, confidence=0.9
    )
    transcript = AlignedTranscript.model_construct(
        text="negative",
        words=[bad_word],
        alignment_method=AlignmentMethod.WHISPERX,
        total_coverage_pct=0.5,
    )
    result = validate_alignment(transcript)
    assert result.is_valid is False
    assert any("negative end_s" in err for err in result.errors)


# ---------------------------------------------------------------------------
# 5. End Before Start
# ---------------------------------------------------------------------------

def test_end_before_start_fails() -> None:
    """A word where end_s < start_s fails validation."""
    bad_word = AlignedWord.model_construct(
        word="inverted", start_s=1.5, end_s=1.0, confidence=0.9
    )
    transcript = AlignedTranscript.model_construct(
        text="inverted",
        words=[bad_word],
        alignment_method=AlignmentMethod.WHISPERX,
        total_coverage_pct=0.5,
    )
    result = validate_alignment(transcript)
    assert result.is_valid is False
    assert any("end_s (1.0) < start_s (1.5)" in err for err in result.errors)


# ---------------------------------------------------------------------------
# 6. Non-Finite Timestamps
# ---------------------------------------------------------------------------

def test_nan_timestamps_fail() -> None:
    """NaN timestamps fail validation."""
    bad_word_nan_start = AlignedWord.model_construct(
        word="nan_start", start_s=float("nan"), end_s=1.0, confidence=0.9
    )
    transcript_nan_start = AlignedTranscript.model_construct(
        text="nan_start",
        words=[bad_word_nan_start],
        alignment_method=AlignmentMethod.WHISPERX,
        total_coverage_pct=0.5,
    )
    result_nan_start = validate_alignment(transcript_nan_start)
    assert result_nan_start.is_valid is False
    assert any("non-finite start_s" in err for err in result_nan_start.errors)

    bad_word_nan_end = AlignedWord.model_construct(
        word="nan_end", start_s=0.0, end_s=float("nan"), confidence=0.9
    )
    transcript_nan_end = AlignedTranscript.model_construct(
        text="nan_end",
        words=[bad_word_nan_end],
        alignment_method=AlignmentMethod.WHISPERX,
        total_coverage_pct=0.5,
    )
    result_nan_end = validate_alignment(transcript_nan_end)
    assert result_nan_end.is_valid is False
    assert any("non-finite end_s" in err for err in result_nan_end.errors)


def test_inf_timestamps_fail() -> None:
    """Infinite timestamps (float('inf')) fail validation."""
    bad_word_inf = AlignedWord(
        word="infinite", start_s=0.0, end_s=float("inf"), confidence=0.9
    )
    transcript = AlignedTranscript(
        text="infinite",
        words=[bad_word_inf],
        alignment_method=AlignmentMethod.WHISPERX,
        total_coverage_pct=0.5,
    )
    result = validate_alignment(transcript)
    assert result.is_valid is False
    assert any("non-finite end_s" in err for err in result.errors)


# ---------------------------------------------------------------------------
# 7. Backwards Chronological Ordering
# ---------------------------------------------------------------------------

def test_backwards_start_chronological_ordering_fails() -> None:
    """Words whose start_s moves backward in time fail validation."""
    words = [
        AlignedWord(word="first", start_s=2.0, end_s=2.5, confidence=0.9),
        AlignedWord(word="second", start_s=1.0, end_s=2.6, confidence=0.9),
    ]
    transcript = _make_aligned_transcript(text="first second", words=words)
    result = validate_alignment(transcript)

    assert result.is_valid is False
    assert any("Chronological ordering violation" in err and "start_s" in err for err in result.errors)


def test_backwards_end_chronological_ordering_fails() -> None:
    """Words whose end_s moves backward in time fail validation."""
    words = [
        AlignedWord(word="first", start_s=1.0, end_s=2.5, confidence=0.9),
        AlignedWord(word="second", start_s=1.5, end_s=2.0, confidence=0.9),
    ]
    transcript = _make_aligned_transcript(text="first second", words=words)
    result = validate_alignment(transcript)

    assert result.is_valid is False
    assert any("Chronological ordering violation" in err and "end_s" in err for err in result.errors)


def test_forward_overlapping_intervals_allowed() -> None:
    """Slight coarticulation overlap moving forward in time is valid."""
    words = [
        AlignedWord(word="going", start_s=1.0, end_s=1.45, confidence=0.9),
        AlignedWord(word="to", start_s=1.40, end_s=1.65, confidence=0.9),
    ]
    transcript = _make_aligned_transcript(text="going to", words=words)
    result = validate_alignment(transcript, audio_duration_s=2.0)

    assert result.is_valid is True
    assert len(result.errors) == 0


# ---------------------------------------------------------------------------
# 8. Missing Timestamps Accepted
# ---------------------------------------------------------------------------

def test_missing_timestamps_accepted_without_false_failures() -> None:
    """Words with missing start/end are allowed (e.g. unaligned by WhisperX).

    Interleaved unaligned words must not break chronological validation between
    subsequent aligned words.
    """
    words = [
        AlignedWord(word="hello", start_s=0.1, end_s=0.5, confidence=0.95),
        AlignedWord(word="unaligned_1", start_s=None, end_s=None, confidence=None),
        AlignedWord(word="middle", start_s=0.6, end_s=1.0, confidence=0.90),
        AlignedWord(word="unaligned_2", start_s=None, end_s=None, confidence=None),
        AlignedWord(word="world", start_s=1.1, end_s=1.5, confidence=0.92),
    ]
    transcript = _make_aligned_transcript(
        text="hello unaligned_1 middle unaligned_2 world", words=words
    )
    result = validate_alignment(transcript, audio_duration_s=2.0)

    assert result.is_valid is True
    assert len(result.errors) == 0


def test_missing_timestamps_with_subsequent_chronological_violation_fails() -> None:
    """Un-aligned words do not hide a subsequent backwards chronological jump."""
    words = [
        AlignedWord(word="hello", start_s=1.0, end_s=1.5, confidence=0.95),
        AlignedWord(word="unaligned", start_s=None, end_s=None, confidence=None),
        # 'world' jumps backwards before 'hello'
        AlignedWord(word="world", start_s=0.5, end_s=0.9, confidence=0.92),
    ]
    transcript = _make_aligned_transcript(text="hello unaligned world", words=words)
    result = validate_alignment(transcript, audio_duration_s=2.0)

    assert result.is_valid is False
    assert any("Chronological ordering violation" in err for err in result.errors)


# ---------------------------------------------------------------------------
# 9. Timestamps Exceeding Audio Duration
# ---------------------------------------------------------------------------

def test_timestamps_exceeding_audio_duration_fails() -> None:
    """Words ending beyond audio duration + tolerance fail validation."""
    words = [
        AlignedWord(word="hello", start_s=0.1, end_s=0.5, confidence=0.9),
        AlignedWord(word="world", start_s=0.6, end_s=2.5, confidence=0.9),
    ]
    transcript = _make_aligned_transcript(words=words)
    # Audio is only 2.0s long; default tolerance is 0.1s -> 2.5s exceeds 2.1s
    result = validate_alignment(transcript, audio_duration_s=2.0, tolerance_s=0.1)

    assert result.is_valid is False
    assert any("extends beyond audio duration" in err for err in result.errors)


def test_timestamps_within_tolerance_accepted() -> None:
    """Words slightly beyond audio duration but within tolerance are accepted."""
    words = [
        AlignedWord(word="hello", start_s=0.1, end_s=2.05, confidence=0.9),
    ]
    transcript = _make_aligned_transcript(words=words)
    # Audio is 2.0s, word ends at 2.05s, tolerance is 0.1s -> 2.05 <= 2.10
    result = validate_alignment(transcript, audio_duration_s=2.0, tolerance_s=0.1)

    assert result.is_valid is True
    assert len(result.errors) == 0


def test_negative_or_nan_audio_duration_fails() -> None:
    """Invalid audio_duration_s inputs produce validation errors."""
    transcript = _make_aligned_transcript()
    result_neg = validate_alignment(transcript, audio_duration_s=-1.0)
    assert result_neg.is_valid is False
    assert any("non-negative finite number" in err for err in result_neg.errors)

    result_nan = validate_alignment(transcript, audio_duration_s=float("nan"))
    assert result_nan.is_valid is False
    assert any("non-negative finite number" in err for err in result_nan.errors)


# ---------------------------------------------------------------------------
# 10. Valid Coverage Boundary Values
# ---------------------------------------------------------------------------

def test_valid_coverage_boundary_values() -> None:
    """0.0 and 1.0 boundary values are accepted fractions."""
    t_zero = _make_aligned_transcript(total_coverage_pct=0.0)
    res_zero = validate_alignment(t_zero)
    # 0.0 coverage emits a low-coverage warning, but is valid structurally
    assert res_zero.is_valid is True
    assert not any("outside canonical fraction range" in err for err in res_zero.errors)

    t_one = _make_aligned_transcript(total_coverage_pct=1.0)
    res_one = validate_alignment(t_one)
    assert res_one.is_valid is True
    assert len(res_one.errors) == 0

    t_mid = _make_aligned_transcript(total_coverage_pct=0.5)
    res_mid = validate_alignment(t_mid)
    assert res_mid.is_valid is True


# ---------------------------------------------------------------------------
# 11. Invalid Coverage Values
# ---------------------------------------------------------------------------

def test_invalid_coverage_values() -> None:
    """Coverage values < 0.0, > 1.0, or non-finite fail validation."""
    # Negative coverage
    t_neg = AlignedTranscript.model_construct(
        text="test",
        words=[AlignedWord(word="test", start_s=0.0, end_s=0.5)],
        alignment_method=AlignmentMethod.WHISPERX,
        total_coverage_pct=-0.1,
    )
    res_neg = validate_alignment(t_neg)
    assert res_neg.is_valid is False
    assert any("outside canonical fraction range" in err for err in res_neg.errors)

    # Coverage > 1.0
    t_gt1 = AlignedTranscript.model_construct(
        text="test",
        words=[AlignedWord(word="test", start_s=0.0, end_s=0.5)],
        alignment_method=AlignmentMethod.WHISPERX,
        total_coverage_pct=1.5,
    )
    res_gt1 = validate_alignment(t_gt1)
    assert res_gt1.is_valid is False
    assert any("outside canonical fraction range" in err for err in res_gt1.errors)

    # Coverage NaN
    t_nan = AlignedTranscript.model_construct(
        text="test",
        words=[AlignedWord(word="test", start_s=0.0, end_s=0.5)],
        alignment_method=AlignmentMethod.WHISPERX,
        total_coverage_pct=float("nan"),
    )
    res_nan = validate_alignment(t_nan)
    assert res_nan.is_valid is False
    assert any("finite number" in err for err in res_nan.errors)


def test_aligned_transcript_schema_coverage_bounds() -> None:
    """Schema rejects total_coverage_pct < 0.0 or > 1.0 and accepts 0.0 and 1.0."""
    # 0.0 is accepted
    t_zero = AlignedTranscript(
        text="test",
        words=[],
        alignment_method=AlignmentMethod.WHISPERX,
        total_coverage_pct=0.0,
    )
    assert t_zero.total_coverage_pct == 0.0

    # 1.0 is accepted
    t_one = AlignedTranscript(
        text="test",
        words=[],
        alignment_method=AlignmentMethod.WHISPERX,
        total_coverage_pct=1.0,
    )
    assert t_one.total_coverage_pct == 1.0

    # Values below 0.0 are rejected by the schema
    with pytest.raises(ValidationError):
        AlignedTranscript(
            text="test",
            words=[],
            alignment_method=AlignmentMethod.WHISPERX,
            total_coverage_pct=-0.01,
        )

    # Values above 1.0 are rejected by the schema
    with pytest.raises(ValidationError):
        AlignedTranscript(
            text="test",
            words=[],
            alignment_method=AlignmentMethod.WHISPERX,
            total_coverage_pct=1.01,
        )

    with pytest.raises(ValidationError):
        AlignedTranscript(
            text="test",
            words=[],
            alignment_method=AlignmentMethod.WHISPERX,
            total_coverage_pct=100.0,
        )



# ---------------------------------------------------------------------------
# 12. Non-Empty Transcript with No Aligned Words
# ---------------------------------------------------------------------------

def test_non_empty_transcript_with_no_aligned_words_fails() -> None:
    """A transcript with non-empty text but an empty word list fails validation."""
    transcript = AlignedTranscript(
        text="This speech has text but alignment returned no words",
        words=[],
        alignment_method=AlignmentMethod.WHISPERX,
        total_coverage_pct=0.0,
    )
    result = validate_alignment(transcript)

    assert result.is_valid is False
    assert any("aligned words list is empty" in err for err in result.errors)


def test_empty_transcript_with_aligned_words_fails() -> None:
    """An empty transcript text with non-empty aligned words fails validation."""
    transcript = AlignedTranscript(
        text="",
        words=[AlignedWord(word="ghost", start_s=0.0, end_s=0.5)],
        alignment_method=AlignmentMethod.WHISPERX,
        total_coverage_pct=0.5,
    )
    result = validate_alignment(transcript)

    assert result.is_valid is False
    assert any("Transcript text is empty but aligned words list contains" in err for err in result.errors)


# ---------------------------------------------------------------------------
# 13. Deterministic Repeated Runs
# ---------------------------------------------------------------------------

def test_deterministic_repeated_validation() -> None:
    """Repeated validation of identical input produces identical results."""
    transcript = _make_aligned_transcript()
    result1 = validate_alignment(transcript, audio_duration_s=2.0)
    result2 = validate_alignment(transcript, audio_duration_s=2.0)

    assert result1.is_valid == result2.is_valid
    assert result1.errors == result2.errors
    assert result1.warnings == result2.warnings
    assert result1.messages == result2.messages


# ---------------------------------------------------------------------------
# 14. Low Coverage Warning (ARCHITECTURE.md §12)
# ---------------------------------------------------------------------------

def test_low_coverage_warning_does_not_fail() -> None:
    """Coverage below MIN_COVERAGE_PCT logs a warning but does not fail validation."""
    transcript = _make_aligned_transcript(total_coverage_pct=0.60)
    result = validate_alignment(
        transcript, audio_duration_s=2.0, min_coverage_pct=0.80
    )

    assert result.is_valid is True
    assert len(result.errors) == 0
    assert any("below MIN_COVERAGE_PCT" in warn for warn in result.warnings)


# ---------------------------------------------------------------------------
# 15. validate_alignment_or_raise
# ---------------------------------------------------------------------------

def test_validate_alignment_or_raise_success() -> None:
    """Valid alignment returns result without raising."""
    transcript = _make_aligned_transcript()
    res = validate_alignment_or_raise(transcript, audio_duration_s=2.0)
    assert res.is_valid is True


def test_validate_alignment_or_raise_failure() -> None:
    """Invalid alignment raises AlignmentValidationError."""
    transcript = AlignedTranscript(
        text="some text",
        words=[],
        alignment_method=AlignmentMethod.WHISPERX,
        total_coverage_pct=0.0,
    )
    with pytest.raises(AlignmentValidationError) as exc_info:
        validate_alignment_or_raise(transcript)

    assert "aligned words list is empty" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 16. Invalid Container / Non-Aligned Object
# ---------------------------------------------------------------------------

def test_none_input_fails() -> None:
    """Passing None returns an invalid result."""
    result = validate_alignment(None)
    assert result.is_valid is False
    assert any("must not be None" in err for err in result.errors)


def test_invalid_type_input_fails() -> None:
    """Passing an incompatible object returns an invalid result."""
    result = validate_alignment("not an aligned transcript")
    assert result.is_valid is False
    assert any("Input must be an AlignedTranscript instance" in err for err in result.errors)


def test_dictionary_input_supported() -> None:
    """A dictionary with valid alignment fields validates correctly."""
    valid_dict = {
        "text": "hello world",
        "words": [
            {"word": "hello", "start_s": 0.0, "end_s": 0.5, "confidence": 0.9},
            {"word": "world", "start_s": 0.6, "end_s": 1.1, "confidence": 0.9},
        ],
        "total_coverage_pct": 0.9,
    }
    result = validate_alignment(valid_dict, audio_duration_s=1.5)
    assert result.is_valid is True
    assert len(result.errors) == 0
