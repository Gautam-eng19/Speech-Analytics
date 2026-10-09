"""Alignment Validation Service (TASK-023, ARCHITECTURE.md §12).

Validates that an AlignedTranscript is structurally and temporally valid before
downstream feature extraction and temporal grounding services consume it.

Validations:
1. Word integrity:
   - Every aligned word must contain non-empty text.
   - Word order is preserved; no modification of word text tokens.
2. Timestamp validity:
   - Timings must be finite numbers.
   - If start_s is present, it must be >= 0.0.
   - If end_s is present, it must be >= 0.0.
   - If both start_s and end_s are present, end_s must be >= start_s.
   - Unaligned words (missing start_s and/or end_s) are permitted.
3. Chronological consistency:
   - For words with complete timestamps, start and end intervals must not
     move backward in time.
   - Missing timestamps do not cause false validation failures.
4. Audio-bound validation:
   - When audio duration is provided, complete word intervals must not extend
     materially beyond the audio duration (subject to configurable tolerance).
5. Coverage validation:
   - total_coverage_pct must be a finite fraction in the canonical range [0.0, 1.0].
   - If coverage is below MIN_COVERAGE_PCT, a deterministic warning is recorded
     without failing validation (ARCHITECTURE.md §12).
6. Text/word sanity:
   - Empty transcript with empty word list is valid.
   - Non-empty transcript with zero aligned words produces a validation failure.
7. Determinism:
   - Pure, fully deterministic numerical checks with no external calls or LLMs.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from app.core.config import settings
from app.schemas.contracts import (
    AlignedTranscript,
    AlignedWord,
    AlignmentValidationResult,
    ValidationResult,
)

logger = logging.getLogger(__name__)


class AlignmentValidationError(ValueError):
    """Raised when an AlignedTranscript fails validation in strict mode."""


def validate_alignment(
    aligned: Any,
    audio_duration_s: Optional[float] = None,
    tolerance_s: float = 0.1,
    min_coverage_pct: Optional[float] = settings.MIN_COVERAGE_PCT,
) -> AlignmentValidationResult:
    """Validate an AlignedTranscript contract for structural and temporal sanity.

    Parameters
    ----------
    aligned:
        AlignedTranscript instance (or compatible dictionary/object) to validate.
    audio_duration_s:
        Optional duration of the audio recording in seconds.
    tolerance_s:
        Allowed tolerance in seconds for audio duration boundary checks (default 0.1s).
    min_coverage_pct:
        Optional threshold (fraction in [0.0, 1.0]) below which a low coverage
        warning is emitted. Defaults to settings.MIN_COVERAGE_PCT.

    Returns
    -------
    AlignmentValidationResult:
        Typed result containing is_valid, deterministic error reasons, and warnings.
    """
    errors: List[str] = []
    warnings: List[str] = []

    # -------------------------------------------------------------------------
    # 0. Container & Attribute Extraction
    # -------------------------------------------------------------------------
    if aligned is None:
        return AlignmentValidationResult(
            is_valid=False,
            errors=["Aligned transcript input must not be None."],
            warnings=[],
        )

    if isinstance(aligned, dict):
        text = aligned.get("text")
        words = aligned.get("words")
        coverage = aligned.get("total_coverage_pct")
    elif hasattr(aligned, "words") and hasattr(aligned, "text"):
        text = getattr(aligned, "text")
        words = getattr(aligned, "words")
        coverage = getattr(aligned, "total_coverage_pct", None)
    else:
        return AlignmentValidationResult(
            is_valid=False,
            errors=[
                "Input must be an AlignedTranscript instance or mapping with 'text', 'words', and 'total_coverage_pct'."
            ],
            warnings=[],
        )

    if not isinstance(text, str):
        errors.append(f"Transcript text must be a str, got {type(text).__name__}.")
        text_str = ""
    else:
        text_str = text

    if words is None or not isinstance(words, (list, tuple)):
        errors.append(f"Aligned words must be a sequence (list or tuple), got {type(words).__name__}.")
        words_list: Sequence[Any] = []
    else:
        words_list = words

    # -------------------------------------------------------------------------
    # 1. Text / Word Sanity (Requirement 6)
    # -------------------------------------------------------------------------
    has_text = bool(text_str.strip())
    has_words = len(words_list) > 0

    if not has_text and not has_words:
        # Both empty: valid empty transcript
        pass
    elif has_text and not has_words:
        errors.append(
            f"Transcript contains non-empty text ({len(text_str)} chars) but aligned words list is empty."
        )
    elif not has_text and has_words:
        errors.append(
            f"Transcript text is empty but aligned words list contains {len(words_list)} words."
        )

    # -------------------------------------------------------------------------
    # 2. Audio Duration Bound Pre-check (Requirement 4)
    # -------------------------------------------------------------------------
    valid_audio_duration: Optional[float] = None
    if audio_duration_s is not None:
        if (
            not isinstance(audio_duration_s, (int, float))
            or not math.isfinite(audio_duration_s)
            or audio_duration_s < 0.0
        ):
            errors.append(
                f"audio_duration_s must be a non-negative finite number, got {audio_duration_s}."
            )
        else:
            valid_audio_duration = float(audio_duration_s)

    # -------------------------------------------------------------------------
    # 3. Coverage Validation (Requirement 5)
    # -------------------------------------------------------------------------
    if coverage is None:
        errors.append("total_coverage_pct must not be None.")
    elif not isinstance(coverage, (int, float)) or not math.isfinite(coverage):
        errors.append(f"total_coverage_pct must be a finite number, got {coverage}.")
    elif coverage < 0.0 or coverage > 1.0:
        errors.append(
            f"total_coverage_pct ({coverage}) is outside canonical fraction range [0.0, 1.0]."
        )
    else:
        # Valid coverage fraction in [0.0, 1.0]
        cov_val = float(coverage)
        if has_words and min_coverage_pct is not None and cov_val < min_coverage_pct:
            warnings.append(
                f"total_coverage_pct ({cov_val:.4f}) is below MIN_COVERAGE_PCT ({min_coverage_pct})."
            )

    # -------------------------------------------------------------------------
    # 4. Word Integrity, Timestamps, Chronology, and Audio Bounds
    # -------------------------------------------------------------------------
    prev_complete_word: Optional[Tuple[int, str, float, float]] = None

    for i, word_item in enumerate(words_list):
        # Extract word token
        if isinstance(word_item, dict):
            word_raw = word_item.get("word")
            start_raw = word_item.get("start_s")
            end_raw = word_item.get("end_s")
            conf_raw = word_item.get("confidence")
        else:
            word_raw = getattr(word_item, "word", None)
            start_raw = getattr(word_item, "start_s", None)
            end_raw = getattr(word_item, "end_s", None)
            conf_raw = getattr(word_item, "confidence", None)

        # 4.1 Word text integrity (Requirement 1)
        if word_raw is None or not isinstance(word_raw, str) or not word_raw.strip():
            errors.append(f"Word at index {i} has empty or whitespace-only text.")
            word_display = repr(word_raw)
        else:
            word_display = word_raw

        # 4.2 Timestamp validity (Requirement 2)
        start_is_finite = False
        if start_raw is not None:
            if not isinstance(start_raw, (int, float)) or not math.isfinite(start_raw):
                errors.append(
                    f"Word '{word_display}' at index {i} has non-finite start_s ({start_raw})."
                )
            elif start_raw < 0.0:
                errors.append(
                    f"Word '{word_display}' at index {i} has negative start_s ({start_raw})."
                )
            else:
                start_is_finite = True

        end_is_finite = False
        if end_raw is not None:
            if not isinstance(end_raw, (int, float)) or not math.isfinite(end_raw):
                errors.append(
                    f"Word '{word_display}' at index {i} has non-finite end_s ({end_raw})."
                )
            elif end_raw < 0.0:
                errors.append(
                    f"Word '{word_display}' at index {i} has negative end_s ({end_raw})."
                )
            else:
                end_is_finite = True

        has_both_valid_timings = start_is_finite and end_is_finite
        if start_raw is not None and end_raw is not None and has_both_valid_timings:
            if end_raw < start_raw:
                errors.append(
                    f"Word '{word_display}' at index {i} has end_s ({end_raw}) < start_s ({start_raw})."
                )

        # 4.3 Confidence validity (if present)
        if conf_raw is not None:
            if not isinstance(conf_raw, (int, float)) or not math.isfinite(conf_raw):
                errors.append(
                    f"Word '{word_display}' at index {i} has non-finite confidence ({conf_raw})."
                )
            elif conf_raw < 0.0 or conf_raw > 1.0:
                errors.append(
                    f"Word '{word_display}' at index {i} has confidence ({conf_raw}) outside [0.0, 1.0]."
                )

        # 4.4 Chronological consistency (Requirement 3)
        # Only evaluate words that have complete, valid timestamps where end >= start
        if has_both_valid_timings and end_raw >= start_raw:
            start_f = float(start_raw)
            end_f = float(end_raw)
            if prev_complete_word is not None:
                p_idx, p_name, p_start, p_end = prev_complete_word
                if start_f < p_start:
                    errors.append(
                        f"Chronological ordering violation at index {i}: word '{word_display}' start_s ({start_f}s) "
                        f"is earlier than previous word '{p_name}' (index {p_idx}) start_s ({p_start}s)."
                    )
                if end_f < p_end:
                    errors.append(
                        f"Chronological ordering violation at index {i}: word '{word_display}' end_s ({end_f}s) "
                        f"is earlier than previous word '{p_name}' (index {p_idx}) end_s ({p_end}s)."
                    )
            prev_complete_word = (i, word_display, start_f, end_f)

        # 4.5 Audio-bound validation (Requirement 4)
        if valid_audio_duration is not None:
            max_bound = valid_audio_duration + max(0.0, float(tolerance_s))
            if start_is_finite and float(start_raw) > max_bound:
                errors.append(
                    f"Word '{word_display}' at index {i} start_s ({start_raw}s) extends beyond audio duration "
                    f"({valid_audio_duration}s, tolerance={tolerance_s}s)."
                )
            if end_is_finite and float(end_raw) > max_bound:
                errors.append(
                    f"Word '{word_display}' at index {i} end_s ({end_raw}s) extends beyond audio duration "
                    f"({valid_audio_duration}s, tolerance={tolerance_s}s)."
                )

    is_valid = len(errors) == 0
    return AlignmentValidationResult(
        is_valid=is_valid,
        errors=errors,
        warnings=warnings,
    )


def validate_alignment_or_raise(
    aligned: Any,
    audio_duration_s: Optional[float] = None,
    tolerance_s: float = 0.1,
    min_coverage_pct: Optional[float] = settings.MIN_COVERAGE_PCT,
) -> AlignmentValidationResult:
    """Validate an AlignedTranscript, raising AlignmentValidationError if invalid.

    Parameters
    ----------
    aligned:
        AlignedTranscript instance to validate.
    audio_duration_s:
        Optional duration of the audio recording in seconds.
    tolerance_s:
        Allowed tolerance in seconds for audio duration boundary checks.
    min_coverage_pct:
        Optional coverage threshold for warning generation.

    Returns
    -------
    AlignmentValidationResult:
        Validation result if valid.

    Raises
    ------
    AlignmentValidationError:
        If validation fails.
    """
    result = validate_alignment(
        aligned=aligned,
        audio_duration_s=audio_duration_s,
        tolerance_s=tolerance_s,
        min_coverage_pct=min_coverage_pct,
    )
    if not result.is_valid:
        error_msg = "; ".join(result.errors)
        raise AlignmentValidationError(
            f"Alignment validation failed with {len(result.errors)} error(s): {error_msg}"
        )
    return result
