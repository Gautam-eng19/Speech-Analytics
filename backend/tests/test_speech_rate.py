"""Unit and contract tests for rolling-window speech-rate extraction (TASK-033, DEC-020).

Covers:
- Exact WPM values against hand-computed windows (rolling-window formula)
- Window grid, membership boundaries and effective-duration semantics
- Fast vs. slow sections produce higher / lower rates
- min_words / min_windows skipping with explicit reasons (no invented values)
- Missing / non-finite word timings are ignored and reported, never guessed
- Deterministic repeated extraction
- Compatibility with the SpeechRateTimeline response schema
- Invalid inputs and invalid configurations
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

import numpy as np
import pytest
from app.schemas.common import AlignmentMethod
from app.schemas.contracts import AlignedTranscript, AlignedWord
from app.schemas.response import SpeechRateTimeline
from app.services.features.rate import RateConfig, RateExtractor, extract_rate

WordSpec = Tuple[str, Optional[float], Optional[float]]


def _aligned(specs: Sequence[WordSpec]) -> AlignedTranscript:
    words: List[AlignedWord] = [
        AlignedWord(word=w, start_s=s, end_s=e, confidence=0.9) for w, s, e in specs
    ]
    return AlignedTranscript(
        text=" ".join(w for w, _, _ in specs),
        words=words,
        alignment_method=AlignmentMethod.WHISPERX,
        total_coverage_pct=1.0,
    )


def _uniform(n_words: int, period_s: float, word_len_s: float = 0.3, t0: float = 0.0) -> List[WordSpec]:
    return [(f"w{i}", t0 + i * period_s, t0 + i * period_s + word_len_s) for i in range(n_words)]


# ------------------------------------------------------------------ exact math
def test_first_window_matches_hand_computed_wpm():
    # 20 words, one every 0.4 s, 0.3 s long. Window [0, 8): starts 0 .. 7.6 -> 20 words,
    # effective span = 19*0.4 + 0.3 - 0 = 7.9 s  ->  20 / 7.9 * 60 wpm.
    res = extract_rate(_aligned(_uniform(20, 0.4)))
    assert not res.skipped
    assert res.word_count[0] == 20
    assert res.window_start_s[0] == 0.0 and res.window_end_s[0] == 8.0
    assert res.effective_duration_s[0] == pytest.approx(7.9)
    assert res.words_per_min[0] == pytest.approx(20 / 7.9 * 60.0)
    assert res.times_s[0] == pytest.approx((0.0 + 7.9) / 2.0)


def test_second_window_uses_step_grid_and_effective_span():
    res = extract_rate(_aligned(_uniform(20, 0.4)))
    # Window 1 = [4, 12): word starts 4.0 .. 7.6 (10 words, i=10..19).
    assert res.window_start_s[1] == 4.0 and res.window_end_s[1] == 12.0
    assert res.word_count[1] == 10
    span = (19 * 0.4 + 0.3) - (10 * 0.4)
    assert res.effective_duration_s[1] == pytest.approx(span)
    assert res.words_per_min[1] == pytest.approx(10 / span * 60.0)


def test_rate_is_not_inverse_of_individual_word_duration():
    # Same word timing pattern except one very long word: DEC-020 uses the span of the
    # window, so doubling a single word's duration changes the span only through `end`.
    base = _uniform(20, 0.4)
    longer = list(base)
    longer[5] = (base[5][0], base[5][1], base[5][1] + 0.35)  # still inside the 0.4 s period
    a = extract_rate(_aligned(base))
    b = extract_rate(_aligned(longer))
    assert np.array_equal(a.words_per_min, b.words_per_min)


def test_fast_section_has_higher_rate_than_slow_section():
    slow = _uniform(16, 1.0, word_len_s=0.5)  # 16 words in ~16 s  (60 wpm)
    fast = _uniform(16, 0.25, word_len_s=0.2, t0=17.0)  # 16 words in ~4 s (240 wpm)
    res = extract_rate(_aligned(slow + fast), RateConfig(window_s=8.0, step_s=4.0, min_words=5, min_windows=2))
    assert not res.skipped
    assert res.words_per_min[0] < 100.0
    assert res.words_per_min.max() > 200.0
    assert np.argmax(res.words_per_min) > 0


def test_uniform_speech_gives_stable_rate():
    res = extract_rate(_aligned(_uniform(60, 0.4)))
    interior = res.words_per_min[:-2]  # tail windows hold fewer words
    assert interior.max() - interior.min() < 5.0


# --------------------------------------------------------- grid & membership
def test_window_membership_start_inclusive_end_exclusive():
    cfg = RateConfig(window_s=4.0, step_s=4.0, min_words=2, min_windows=1)
    specs = [("a", 0.0, 0.5), ("b", 1.0, 1.5), ("c", 2.0, 2.5), ("d", 3.0, 3.5),
             ("e", 4.0, 4.5), ("f", 5.0, 5.5)]
    res = extract_rate(_aligned(specs), cfg)
    assert list(res.word_count) == [4, 2]  # word starting exactly at 4.0 is in window [4, 8) only
    assert list(res.window_start_s) == [0.0, 4.0]


def test_grid_windows_stop_at_last_word_start():
    cfg = RateConfig(window_s=4.0, step_s=4.0, min_words=2, min_windows=1)
    specs = [(f"w{i}", i * 1.0, i * 1.0 + 0.5) for i in range(14)]  # last start 13.0
    res = extract_rate(_aligned(specs), cfg)
    assert list(res.window_start_s) == [0.0, 4.0, 8.0, 12.0]
    assert list(res.word_count) == [4, 4, 4, 2]


def test_overlapping_windows_count_a_word_in_each_window():
    cfg = RateConfig(window_s=8.0, step_s=4.0, min_words=2, min_windows=1)
    specs = [("a", 5.0, 5.4), ("b", 6.0, 6.4)]  # both inside [0,8) and [4,12)
    res = extract_rate(_aligned(specs), cfg)
    assert list(res.word_count) == [2, 2]


# ---------------------------------------------------------------- skipping
def test_windows_below_min_words_are_skipped_not_invented():
    cfg = RateConfig(window_s=4.0, step_s=4.0, min_words=3, min_windows=1)
    specs = [("a", 0.0, 0.4), ("b", 0.5, 0.9), ("c", 1.0, 1.4),   # 3 words: valid
             ("d", 4.0, 4.4), ("e", 5.0, 5.4)]                    # 2 words: skipped
    res = extract_rate(_aligned(specs), cfg)
    assert res.total_windows == 1
    assert res.n_valid_windows == 1
    assert list(res.window_start_s) == [0.0]


def test_insufficient_windows_marks_analysis_skipped_with_reason():
    res = extract_rate(_aligned(_uniform(8, 0.5)))  # one valid window only (< min_windows=2)
    assert res.skipped is True
    assert res.skip_reason is not None and res.skip_reason.startswith("insufficient_windows")
    assert res.n_valid_windows == 1
    assert res.total_windows == 0
    assert len(res.words_per_min) == 0 and len(res.times_s) == 0


def test_no_words_is_skipped():
    res = extract_rate(_aligned([]))
    assert res.skipped and res.skip_reason == "no_aligned_words"
    assert res.n_words_total == 0


def test_zero_effective_duration_window_is_skipped():
    cfg = RateConfig(window_s=4.0, step_s=4.0, min_words=2, min_windows=1)
    specs = [(f"w{i}", 1.0, 1.0) for i in range(5)]  # all words instantaneous at t=1
    res = extract_rate(_aligned(specs), cfg)
    assert res.skipped and res.n_valid_windows == 0


# --------------------------------------------------------- missing timings
def test_unaligned_words_are_ignored_and_counted():
    specs = _uniform(20, 0.4)
    specs[3] = ("w3", None, None)
    specs[7] = ("w7", 3.0, None)
    full = extract_rate(_aligned(_uniform(20, 0.4)))
    res = extract_rate(_aligned(specs))
    assert res.n_words_total == 20
    assert res.n_words_unaligned == 2
    assert res.word_count[0] == full.word_count[0] - 2  # missing words are not guessed back in


def test_all_words_unaligned_is_skipped():
    res = extract_rate(_aligned([("a", None, None), ("b", None, None)]))
    assert res.skipped and res.skip_reason == "no_aligned_words"
    assert res.n_words_unaligned == 2


def test_non_finite_timings_are_treated_as_unaligned():
    specs = _uniform(20, 0.4)
    specs[2] = ("w2", math.inf, math.inf)
    res = extract_rate(_aligned(specs))
    assert res.n_words_unaligned == 1
    assert np.all(np.isfinite(res.words_per_min))


# ------------------------------------------------------------- determinism
def test_deterministic_repeated_extraction():
    transcript = _aligned(_uniform(40, 0.37, word_len_s=0.21))
    a = extract_rate(transcript)
    b = extract_rate(transcript)
    for name in ("times_s", "words_per_min", "window_start_s", "window_end_s", "word_count", "effective_duration_s"):
        assert np.array_equal(getattr(a, name), getattr(b, name))


def test_input_transcript_not_modified():
    transcript = _aligned(_uniform(20, 0.4))
    before = transcript.model_dump_json()
    extract_rate(transcript)
    assert transcript.model_dump_json() == before


# ------------------------------------------------------------------ schema
def test_timeline_dict_matches_response_schema():
    res = extract_rate(_aligned(_uniform(30, 0.4)))
    timeline = SpeechRateTimeline(**res.to_timeline_dict())
    assert len(timeline.times_s) == res.total_windows > 0
    assert set(res.to_feature_bundle_dict()) == {"rate_times_s", "rate_wpm"}


def test_skipped_result_serializes_to_empty_timeline():
    res = extract_rate(_aligned([]))
    timeline = SpeechRateTimeline(**res.to_timeline_dict())
    assert timeline.times_s == [] and timeline.words_per_min == []


# ------------------------------------------------------------------ invalid
def test_non_transcript_input_rejected():
    with pytest.raises(TypeError):
        RateExtractor().extract("not a transcript")
    with pytest.raises(TypeError):
        RateExtractor().extract(None)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"window_s": 0.0},
        {"window_s": float("inf")},
        {"step_s": -1.0},
        {"step_s": float("nan")},
        {"min_words": 1},
        {"min_windows": 0},
    ],
)
def test_invalid_config_rejected(kwargs):
    with pytest.raises(ValueError):
        RateConfig(**kwargs)
