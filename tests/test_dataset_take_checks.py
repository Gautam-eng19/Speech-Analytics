"""Tests for scripts/dataset/take_checks.py: alignment plausibility and "was the planned flaw performed".

Hand-built alignments and tone signals with known levels. Covers a clean alignment, every warning and failure of the plausibility check
(word count, word text, untimed words, edges, scores, coverage) on both sides of its limit, the word and gap geometry, the loudness
offset of a stretch, and the speed / loudness / pause verdicts on both sides of the half-way rule.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "dataset"))

import take_checks as tc  # noqa: E402
from app.schemas.common import AlignmentMethod  # noqa: E402
from app.schemas.contracts import AlignedTranscript, AlignedWord  # noqa: E402

PASSAGE = ["Good", "morning,", "my", "dear", "friends."]


def aligned(words: Sequence[Tuple[str, Optional[float], Optional[float], Optional[float]]], coverage: float = 0.9) -> AlignedTranscript:
    return AlignedTranscript(
        text=" ".join(w[0] for w in words),
        words=[AlignedWord(word=w, start_s=a, end_s=b, confidence=c) for w, a, b, c in words],
        alignment_method=AlignmentMethod.WHISPERX,
        total_coverage_pct=coverage,
    )


def clean(n: int = 5, conf: Optional[float] = 0.9, step: float = 0.5) -> AlignedTranscript:
    return aligned([(PASSAGE[i % 5], 0.2 + i * step, 0.2 + i * step + 0.4, conf) for i in range(n)])


def levels(findings: Sequence[tc.Finding]) -> List[str]:
    return [f.level for f in findings]


# ---------------------------------------------------------------------------------------------------------------------------------
# normalise_word
# ---------------------------------------------------------------------------------------------------------------------------------

def test_normalise_word_ignores_case_and_punctuation_but_keeps_apostrophes():
    assert tc.normalise_word("Analytics.") == "analytics"
    assert tc.normalise_word("It's,") == "it's"
    assert tc.normalise_word("“Hello”") == "hello"
    assert tc.normalise_word("...") == ""


# ---------------------------------------------------------------------------------------------------------------------------------
# assess_alignment
# ---------------------------------------------------------------------------------------------------------------------------------

def test_clean_alignment_has_no_findings():
    assert tc.assess_alignment(clean(), PASSAGE, audio_duration_s=2.8, is_baseline=True) == []


def test_word_count_mismatch_fails_and_names_both_counts():
    result = tc.assess_alignment(clean(4), PASSAGE, 2.8, is_baseline=False)
    assert levels(result) == [tc.FAIL]
    assert "4 words" in result[0].message and "5 words" in result[0].message


def test_different_word_text_warns_with_the_first_position():
    words = [("Good", 0.2, 0.6, 0.9), ("evening", 0.7, 1.1, 0.9), ("my", 1.2, 1.6, 0.9), ("dear", 1.7, 2.1, 0.9), ("people.", 2.2, 2.6, 0.9)]
    result = tc.assess_alignment(aligned(words), PASSAGE, 2.8, is_baseline=False)
    assert levels(result) == [tc.WARN]
    assert "2 aligned word(s)" in result[0].message and "word 2" in result[0].message and "'evening'" in result[0].message


def test_punctuation_and_case_differences_are_not_differences():
    words = [("good", 0.2, 0.6, 0.9), ("morning", 0.7, 1.1, 0.9), ("my", 1.2, 1.6, 0.9), ("dear", 1.7, 2.1, 0.9), ("friends", 2.2, 2.6, 0.9)]
    assert tc.assess_alignment(aligned(words), PASSAGE, 2.8, is_baseline=True) == []


def test_one_untimed_word_fails_a_baseline_take():
    words = [("Good", 0.2, 0.6, 0.9), ("morning,", None, None, None), ("my", 1.2, 1.6, 0.9), ("dear", 1.7, 2.1, 0.9), ("friends.", 2.2, 2.6, 0.9)]
    result = tc.assess_alignment(aligned(words), PASSAGE, 2.8, is_baseline=True)
    assert levels(result) == [tc.FAIL]
    assert "1 of 5" in result[0].message and "word 2" in result[0].message and "baseline needs every word" in result[0].message


def test_a_few_untimed_words_only_warn_for_other_takes_and_many_fail():
    passage = [f"w{i}" for i in range(40)]
    def with_untimed(n: int) -> AlignedTranscript:
        return aligned([(w, None, None, None) if 10 <= i < 10 + n else (w, 0.2 + i * 0.5, 0.6 + i * 0.5, 0.9) for i, w in enumerate(passage)])

    assert levels(tc.assess_alignment(with_untimed(2), passage, 20.5, is_baseline=False)) == [tc.WARN]      # 2 of 40 = 5 %: at the limit
    assert levels(tc.assess_alignment(with_untimed(3), passage, 20.5, is_baseline=False)) == [tc.FAIL]      # 3 of 40 = 7.5 %


def test_edges_warn_only_beyond_the_limit():
    gates = tc.ALIGNMENT_GATES
    start = lambda lead: aligned([(w, lead + i * 0.5, lead + i * 0.5 + 0.4, 0.9) for i, w in enumerate(PASSAGE)])
    assert tc.assess_alignment(start(gates.max_edge_gap_s), PASSAGE, gates.max_edge_gap_s + 2.5, False) == []
    late = tc.assess_alignment(start(gates.max_edge_gap_s + 0.1), PASSAGE, gates.max_edge_gap_s + 2.6, False)
    assert levels(late) == [tc.WARN] and "first word starts" in late[0].message
    early = tc.assess_alignment(clean(), PASSAGE, audio_duration_s=2.6 + gates.max_edge_gap_s + 0.1, is_baseline=False)
    assert levels(early) == [tc.WARN] and "last word ends" in early[0].message
    assert tc.assess_alignment(clean(), PASSAGE, audio_duration_s=2.6 + gates.max_edge_gap_s, is_baseline=False) == []


def test_edge_limit_is_one_and_a_half_seconds():
    start = lambda lead: aligned([(w, lead + i * 0.5, lead + i * 0.5 + 0.4, 0.9) for i, w in enumerate(PASSAGE)])
    assert tc.assess_alignment(start(1.4), PASSAGE, 4.0, False) == []
    assert levels(tc.assess_alignment(start(1.6), PASSAGE, 4.2, False)) == [tc.WARN]


def test_a_single_untimed_word_fails_a_baseline_take_however_long_the_passage():
    passage = [f"w{i}" for i in range(40)]
    one = aligned([(w, None, None, None) if i == 10 else (w, 0.2 + i * 0.5, 0.6 + i * 0.5, 0.9) for i, w in enumerate(passage)])    # 2.5 %
    assert levels(tc.assess_alignment(one, passage, 20.5, is_baseline=True)) == [tc.FAIL]
    assert levels(tc.assess_alignment(one, passage, 20.5, is_baseline=False)) == [tc.WARN]


def test_alignment_scores_warn_on_low_average_and_on_many_doubtful_words():
    low = tc.assess_alignment(clean(conf=0.49), PASSAGE, 2.8, False)
    assert levels(low) == [tc.WARN] and "unsure" in low[0].message
    assert tc.assess_alignment(clean(conf=0.5), PASSAGE, 2.8, False) == []          # exactly the limit: fine
    passage = [f"w{i}" for i in range(10)]

    def with_doubtful(n: int) -> AlignedTranscript:
        return aligned([(w, 0.2 + i * 0.5, 0.6 + i * 0.5, 0.05 if i < n else 1.0) for i, w in enumerate(passage)])

    assert tc.assess_alignment(with_doubtful(2), passage, 5.5, False) == []         # 20 % doubtful: at the limit
    many = tc.assess_alignment(with_doubtful(3), passage, 5.5, False)               # 30 %
    assert levels(many) == [tc.WARN] and "3 of 10 words have a low alignment score" in many[0].message


def test_missing_scores_are_not_a_finding():
    assert tc.assess_alignment(clean(conf=None), PASSAGE, 2.8, True) == []


def test_low_coverage_warns_below_the_limit_only():
    assert levels(tc.assess_alignment(aligned([(w, 0.2 + i * 0.5, 0.6 + i * 0.5, 0.9) for i, w in enumerate(PASSAGE)], coverage=0.49),
                                      PASSAGE, 2.8, False)) == [tc.WARN]
    assert tc.assess_alignment(aligned([(w, 0.2 + i * 0.5, 0.6 + i * 0.5, 0.9) for i, w in enumerate(PASSAGE)], coverage=0.5),
                               PASSAGE, 2.8, False) == []


def test_assessment_is_deterministic():
    a = tc.assess_alignment(clean(conf=0.2), PASSAGE, 9.0, False)
    assert a == tc.assess_alignment(clean(conf=0.2), PASSAGE, 9.0, False)


# ---------------------------------------------------------------------------------------------------------------------------------
# pace_wpm
# ---------------------------------------------------------------------------------------------------------------------------------

def test_pace_is_words_over_first_to_last_word_in_minutes():
    words = [(f"w{i}", i * 0.5, i * 0.5 + 0.4, 0.9) for i in range(60)]          # first start 0, last end 29.9 s
    assert tc.pace_wpm(aligned(words)) == pytest.approx(60 * 60 / 29.9)


def test_pace_counts_only_the_timed_words():
    words = [(f"w{i}", i * 0.5, i * 0.5 + 0.4, 0.9) for i in range(60)]
    words[10] = ("w10", None, None, None)
    assert tc.pace_wpm(aligned(words)) == pytest.approx(59 * 60 / 29.9)


def test_pace_needs_two_timed_words_and_a_positive_span():
    assert tc.pace_wpm(aligned([("a", 0.0, 0.4, 0.9)])) is None
    assert tc.pace_wpm(aligned([("a", None, None, None), ("b", 1.0, 1.4, 0.9)])) is None
    assert tc.pace_wpm(aligned([("a", 1.0, 1.0, 0.9), ("b", 1.0, 1.0, 0.9)])) is None


# ---------------------------------------------------------------------------------------------------------------------------------
# word_span / gap_after_word
# ---------------------------------------------------------------------------------------------------------------------------------

def test_word_span_runs_from_first_start_to_last_end():
    assert tc.word_span(clean(), 2, 4) == (0.7, 2.1)
    assert tc.word_span(clean(), 1, 5) == (0.2, 2.6)
    assert tc.word_span(clean(), 3, 3) == (1.2, 1.6)


def test_word_span_is_none_when_the_last_word_ends_before_the_first_begins():
    a = aligned([("a", 2.0, 2.4, 0.9), ("b", 0.5, 1.0, 0.9)])
    assert tc.word_span(a, 1, 2) is None
    assert tc.word_span(a, 2, 2) == (0.5, 1.0)


def test_word_span_is_none_when_a_boundary_word_has_no_time():
    words = [("a", None, None, None), ("b", 1.0, 1.4, 0.9), ("c", 1.5, 1.9, 0.9), ("d", 2.0, None, None)]
    a = aligned(words)
    assert tc.word_span(a, 1, 3) is None
    assert tc.word_span(a, 2, 4) is None
    assert tc.word_span(a, 2, 3) == (1.0, 1.9)          # an untimed word INSIDE is not needed


@pytest.mark.parametrize("first,last", [(0, 3), (3, 2), (1, 6), (6, 6)])
def test_word_span_rejects_ranges_outside_the_words(first, last):
    with pytest.raises(ValueError):
        tc.word_span(clean(), first, last)


def test_gap_is_between_the_end_of_a_word_and_the_start_of_the_next():
    assert tc.gap_after_word(clean(), 1) == pytest.approx((0.6, 0.7))
    words = [("a", 0.0, 0.4, 0.9), ("b", 4.0, 4.4, 0.9)]
    assert tc.gap_after_word(aligned(words), 1) == (0.4, 4.0)


def test_words_that_touch_have_a_gap_of_zero_length():
    assert tc.gap_after_word(aligned([("a", 0.0, 0.5, 0.9), ("b", 0.5, 0.9, 0.9)]), 1) == (0.5, 0.5)


def test_gap_is_none_for_untimed_or_overlapping_words_and_rejects_the_last_word():
    assert tc.gap_after_word(aligned([("a", 0.0, 0.5, 0.9), ("b", 0.4, 0.9, 0.9)]), 1) is None
    assert tc.gap_after_word(aligned([("a", 0.0, None, None), ("b", 0.4, 0.9, 0.9)]), 1) is None
    for bad in (0, 5):
        with pytest.raises(ValueError):
            tc.gap_after_word(clean(), bad)


# ---------------------------------------------------------------------------------------------------------------------------------
# level_offset_db
# ---------------------------------------------------------------------------------------------------------------------------------

SR = 16_000


def tone(seconds: float, amplitude: float) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return amplitude * np.sin(2 * np.pi * 150.0 * t)


def test_level_offset_is_the_difference_between_the_stretch_and_the_rest():
    audio = np.concatenate([tone(3, 0.05), tone(4, 0.05 * 10 ** (8 / 20)), tone(3, 0.05)])
    assert tc.level_offset_db(audio, SR, (3.0, 7.0), 30.0) == pytest.approx(8.0, abs=0.3)
    quiet = np.concatenate([tone(3, 0.1), tone(4, 0.1 * 10 ** (-14 / 20)), tone(3, 0.1)])
    assert tc.level_offset_db(quiet, SR, (3.0, 7.0), 30.0) == pytest.approx(-14.0, abs=0.3)


def test_level_offset_ignores_one_global_gain():
    audio = np.concatenate([tone(3, 0.05), tone(4, 0.125), tone(3, 0.05)])
    a = tc.level_offset_db(audio, SR, (3.0, 7.0), 30.0)
    b = tc.level_offset_db(audio * 0.3, SR, (3.0, 7.0), 30.0)
    assert a == pytest.approx(b, abs=0.05)


def test_level_offset_is_none_for_a_short_stretch_or_silence():
    audio = tone(10, 0.05)
    assert tc.level_offset_db(audio, SR, (3.0, 3.4), 30.0) is None                 # under min_stretch_s
    assert tc.level_offset_db(audio, SR, (3.0, 3.5), 30.0) is not None            # exactly min_stretch_s
    assert tc.level_offset_db(np.zeros(10 * SR), SR, (3.0, 7.0), 30.0) is None
    assert tc.level_offset_db(audio, SR, (0.0, 10.0), 30.0) is None                # nothing left outside the stretch


# ---------------------------------------------------------------------------------------------------------------------------------
# check_speed / check_level / check_pause
# ---------------------------------------------------------------------------------------------------------------------------------

def test_too_fast_is_clear_from_half_way_to_the_planned_factor():
    # take 1 plans 0.75, so the half-way point is 0.875 of the baseline time
    assert tc.check_speed("too_fast", 1, 8.75, 10.0).level == tc.OK
    assert tc.check_speed("too_fast", 1, 7.5, 10.0).level == tc.OK
    weak = tc.check_speed("too_fast", 1, 8.8, 10.0)
    assert weak.level == tc.WARN and "weak example" in weak.message and "0.88" in weak.message and "0.75" in weak.message


def test_too_slow_is_clear_from_half_way_to_the_planned_factor_and_wrong_direction_is_weak():
    # take 2 plans 1.8, so the half-way point is 1.4
    assert tc.check_speed("too_slow", 2, 14.1, 10.0).level == tc.OK
    assert tc.check_speed("too_slow", 2, 13.9, 10.0).level == tc.WARN
    assert tc.check_speed("too_slow", 2, 8.0, 10.0).level == tc.WARN
    assert tc.check_speed("too_fast", 2, 12.0, 10.0).level == tc.WARN


def test_the_half_way_point_itself_counts_as_clear_for_both_speed_flaws():
    import make_plan as mp

    for flaw in ("too_fast", "too_slow"):
        for take in (1, 2):
            halfway = 1.0 + 0.5 * (mp.SPEED_FACTOR[(flaw, take)] - 1.0)
            assert tc.check_speed(flaw, take, halfway * 16.0, 16.0).level == tc.OK, (flaw, take)


def test_loud_and_quiet_are_clear_from_half_the_planned_change_compared_with_the_baseline_takes():
    # take 1 plans 8 dB, so 4 dB is enough; take 2 plans 14 dB, so 7 dB
    assert tc.check_level("high_energy", 1, 4.0, 0.0).level == tc.OK
    assert tc.check_level("high_energy", 1, 3.9, 0.0).level == tc.WARN
    assert tc.check_level("low_energy", 2, -7.0, 0.0).level == tc.OK
    assert tc.check_level("low_energy", 2, -6.9, 0.0).level == tc.WARN
    # the baseline takes' own natural difference is taken off
    assert tc.check_level("high_energy", 1, 6.0, 2.0).level == tc.OK
    assert tc.check_level("high_energy", 1, 5.0, 2.0).level == tc.WARN
    # the wrong direction is never clear
    assert tc.check_level("high_energy", 1, -8.0, 0.0).level == tc.WARN
    assert tc.check_level("low_energy", 1, 8.0, 0.0).level == tc.WARN


def test_pause_is_clear_from_seventy_percent_of_the_planned_minimum():
    # take 1 plans 1.5 to 2 s: 1.05 s is enough; take 2 plans 3 to 4 s: 2.1 s
    assert tc.check_pause(1, 1.05).level == tc.OK
    assert tc.check_pause(1, 1.04).level == tc.WARN
    assert tc.check_pause(2, 2.1).level == tc.OK
    weak = tc.check_pause(2, 2.0)
    assert weak.level == tc.WARN and "weak example" in weak.message and "3 to 4 s" in weak.message


def test_verdicts_are_deterministic():
    assert tc.check_speed("too_fast", 1, 8.0, 10.0) == tc.check_speed("too_fast", 1, 8.0, 10.0)
    assert tc.check_level("low_energy", 2, -9.0, 1.0) == tc.check_level("low_energy", 2, -9.0, 1.0)
