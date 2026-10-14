"""Tests for the word-by-word comparison with the baseline (DEC-040): the scan for runs of words, what it reports, what it refuses to report, and how
its findings enter the candidate stage, the severity and the evidence.

The readings are hand-made (profile_helpers): a passage whose words differ in expected duration and level, read with a known amount of chance
variation, with stretches made faster, slower, louder or quieter where the test says. So "found where it was put" and "not found where nothing was put"
are checked against known truth. Covers: ordinary readings not flagged, each of the four kinds located on its own words, two stretches kept apart, a
reading that is off as a whole judged as a whole, speakers of a different overall pace, the practical-size guards, the minimum run length and duration,
a transcript with dropped and added words, a transcript that does not match, too few words, the tie-breaking and masking of the scan itself, the
fallbacks, determinism, severity from the size of the change, and the evidence a finding carries.
"""
from __future__ import annotations

import math

import numpy as np
import pytest
from app.schemas.common import FlawType
from app.services.grounding import (
    DetectionConfig,
    EvidenceError,
    FlawCandidate,
    SeverityConfig,
    compute_severity,
    detect_candidates,
    ground_flaws,
)
from app.services.grounding.flaws import WARNING_ENERGY_RUN, WARNING_RATE_OVERALL, WARNING_RATE_RUN
from app.services.grounding.normalizer import NormalizedFeatureBundle
from app.services.grounding.profile_detection import StretchReading, _find_runs, detect_runs, measure_stretch
from app.services.grounding.profile import window_mean
from profile_helpers import base_levels, baseline_record, make_profile, make_tokens, observations, reading

PROFILE = make_profile()
RULES = DetectionConfig()
FAST = (30, 47, 0.6)          # words 30 to 47 made 1.67 times as fast
SLOW = (30, 47, 1.7)


def near(found, first, last, tolerance=2):
    return abs(found.first_word - first) <= tolerance and abs(found.last_word - last) <= tolerance


# ------------------------------------------------------------------------------------------------------------------------------
# Finding what was put there
# ------------------------------------------------------------------------------------------------------------------------------
def test_ordinary_readings_of_the_passage_are_not_flagged():
    for seed in range(500, 530):
        found = detect_runs(reading(seed, tempo=0.9 + 0.005 * (seed - 500)), PROFILE, RULES)
        assert found.rate == [] and found.energy == [] and found.reason is None, seed


def test_a_faster_stretch_is_located_on_its_own_words_with_the_times_of_those_words():
    obs = reading(600, stretches=[FAST])
    found = detect_runs(obs, PROFILE, RULES)
    assert found.energy == [] and len(found.rate) == 1
    run = found.rate[0]
    assert run.kind == "rate_run" and near(run, 30, 47) and run.z > RULES.z_run_rate
    assert run.start_s == obs.start_s[run.first_word] and run.end_s == obs.end_s[run.last_word]
    assert run.n_words == run.last_word - run.first_word + 1 == len(run.word_indices)
    assert run.observed / run.expected == pytest.approx(1 / 0.6, rel=0.2)          # words per minute: about 1.67 times the expected
    assert run.effect == pytest.approx(math.log(1 / 0.6), rel=0.25)


def test_a_slower_stretch_has_a_negative_z_and_the_same_machinery():
    run = detect_runs(reading(601, stretches=[SLOW]), PROFILE, RULES).rate[0]
    assert near(run, 30, 47) and run.z < -RULES.z_run_rate and run.observed / run.expected == pytest.approx(1 / 1.7, rel=0.2)


def test_a_louder_and_a_quieter_stretch_are_located_with_their_size_in_decibels():
    loud = detect_runs(reading(602, loud=[(30, 47, 8.0)]), PROFILE, RULES)
    quiet = detect_runs(reading(603, loud=[(30, 47, -8.0)]), PROFILE, RULES)
    assert loud.rate == [] and quiet.rate == [] and len(loud.energy) == len(quiet.energy) == 1
    up, down = loud.energy[0], quiet.energy[0]
    assert near(up, 30, 47) and up.z > RULES.z_run_energy and up.observed - up.expected == pytest.approx(8.0, abs=1.5)
    assert near(down, 30, 47) and down.z < -RULES.z_run_energy and down.observed - down.expected == pytest.approx(-8.0, abs=1.5)
    assert up.effect == pytest.approx(abs(up.observed - up.expected), abs=0.01)


def test_two_stretches_are_two_findings_that_share_no_word():
    found = detect_runs(reading(604, stretches=[(10, 25, 0.6), (55, 72, 1.7)]), PROFILE, RULES)
    assert len(found.rate) == 2
    fast = next(r for r in found.rate if r.z > 0)
    slow = next(r for r in found.rate if r.z < 0)
    assert near(fast, 10, 25) and near(slow, 55, 72)
    assert not set(fast.word_indices) & set(slow.word_indices)


def test_pace_and_loudness_are_judged_independently_of_each_other():
    found = detect_runs(reading(612, stretches=[(10, 25, 0.6)], loud=[(55, 72, -9.0)]), PROFILE, RULES)
    assert [near(r, 10, 25) for r in found.rate] == [True] and [near(r, 55, 72) for r in found.energy] == [True]


def test_a_reading_that_is_off_as_a_whole_is_one_finding_over_all_its_words_and_has_no_local_findings():
    slow = detect_runs(reading(605, tempo=1.7), PROFILE, RULES)
    assert [r.kind for r in slow.rate] == ["rate_overall"] and slow.rate[0].z < -RULES.z_run_rate
    assert (slow.rate[0].first_word, slow.rate[0].last_word, slow.rate[0].n_words) == (0, 89, 90)
    assert slow.rate[0].observed / slow.rate[0].expected == pytest.approx(1 / 1.7, rel=0.1) and slow.tempo == pytest.approx(math.log(1.7), abs=0.08)
    fast = detect_runs(reading(608, tempo=0.6), PROFILE, RULES)
    assert [r.kind for r in fast.rate] == ["rate_overall"] and fast.rate[0].z > RULES.z_run_rate


def test_a_speaker_whose_pace_differs_a_little_is_compared_with_their_own_pace_not_flagged_and_still_gets_local_findings():
    assert detect_runs(reading(606, tempo=1.2), PROFILE, RULES).rate == []             # 20 % slower overall: inside the allowed band
    assert detect_runs(reading(613, tempo=0.85), PROFILE, RULES).rate == []
    run = detect_runs(reading(607, tempo=1.2, stretches=[FAST]), PROFILE, RULES).rate
    assert len(run) == 1 and run[0].kind == "rate_run" and near(run[0], 30, 47)
    assert run[0].expected == pytest.approx(60 * run[0].n_words / sum(PROFILE.slot_s[i] * math.exp(0.18) for i in run[0].word_indices), rel=0.1)


def test_the_louder_part_of_a_reading_does_not_make_the_rest_look_quiet():
    found = detect_runs(reading(614, level_offset=4.0, loud=[(30, 47, 8.0)]), PROFILE, RULES)           # the whole reading 4 dB up, one stretch 8 dB more
    assert len(found.energy) == 1 and found.energy[0].z > 0 and found.energy[0].observed - found.energy[0].expected == pytest.approx(8.0, abs=1.5)


# ------------------------------------------------------------------------------------------------------------------------------
# What is refused
# ------------------------------------------------------------------------------------------------------------------------------
def test_a_change_too_small_to_matter_is_not_reported_however_even_the_baseline_is():
    even = make_profile(jitter=0.01, level_jitter=0.1)
    small_fast = reading(609, jitter=0.01, level_jitter=0.1, stretches=[(20, 49, 0.88)])          # 13 % faster over 30 words
    assert detect_runs(small_fast, even, RULES).rate == []                                          # under the 15 % guard
    assert len(detect_runs(small_fast, even, DetectionConfig(min_rate_change_pct=10)).rate) == 1
    small_loud = reading(610, jitter=0.01, level_jitter=0.1, loud=[(20, 49, 2.5)])                 # 2.5 dB louder
    assert detect_runs(small_loud, even, RULES).energy == []                                        # under the 3 dB guard
    assert len(detect_runs(small_loud, even, DetectionConfig(min_energy_change_db=2.0)).energy) == 1


def test_the_spread_is_never_taken_below_its_floor():
    even = make_profile(jitter=0.001, level_jitter=0.01)
    assert even.rate_noise.word < 0.01
    barely = reading(615, jitter=0.001, level_jitter=0.01, loud=[(20, 49, 3.2)])
    loose = DetectionConfig(sigma_floor_level_drift=0.0, sigma_floor_level_word=0.0)
    assert len(detect_runs(barely, even, loose).energy) == 1                                        # without floors a 3.2 dB step is hugely significant
    strict = DetectionConfig(sigma_floor_level_drift=2.0, sigma_floor_level_word=2.0)
    assert detect_runs(barely, even, strict).energy == []                                           # with a 2 dB floor it is within the spread


def test_a_reading_is_judged_as_a_whole_only_if_it_differs_by_more_than_readers_differ_among_themselves():
    wide = PROFILE.model_copy(update={"tempo_sd": 0.3})                      # baseline readings that differ a lot in overall pace
    assert "rate_overall" not in [r.kind for r in detect_runs(reading(620, tempo=1.4), wide, RULES).rate]      # 40 % off, but well within that spread
    assert "rate_overall" in [r.kind for r in detect_runs(reading(620, tempo=1.4), PROFILE, RULES).rate]


def test_a_reading_is_judged_as_a_whole_only_if_the_difference_is_large_in_size_too():
    exact = PROFILE.model_copy(update={"tempo_sd": 0.0})                      # spread at its floor (0.04): 20 % is 4.6 spreads
    assert "rate_overall" not in [r.kind for r in detect_runs(reading(621, tempo=1.2), exact, RULES).rate]       # under the 30 % guard
    assert "rate_overall" in [r.kind for r in detect_runs(reading(621, tempo=1.2), exact, DetectionConfig(global_tempo_change_pct=10)).rate]


def test_each_kind_of_finding_has_its_own_minimum_duration():
    loud = reading(622, loud=[(30, 47, 9.0)])
    quiet = reading(623, loud=[(30, 47, -9.0)])
    only_loud_is_too_short = DetectionConfig(min_duration_s={FlawType.HIGH_ENERGY: 1000.0})
    only_quiet_is_too_short = DetectionConfig(min_duration_s={FlawType.LOW_ENERGY: 1000.0})
    assert detect_runs(loud, PROFILE, only_loud_is_too_short).energy == [] and len(detect_runs(loud, PROFILE, only_quiet_is_too_short).energy) == 1
    assert len(detect_runs(quiet, PROFILE, only_loud_is_too_short).energy) == 1 and detect_runs(quiet, PROFILE, only_quiet_is_too_short).energy == []
    fast, slow = reading(624, stretches=[FAST]), reading(625, stretches=[SLOW])
    assert detect_runs(slow, PROFILE, DetectionConfig(min_duration_s={FlawType.TOO_FAST: 1000.0})).rate != []
    assert detect_runs(fast, PROFILE, DetectionConfig(min_duration_s={FlawType.TOO_SLOW: 1000.0})).rate != []
    assert detect_runs(slow, PROFILE, DetectionConfig(min_duration_s={FlawType.TOO_SLOW: 1000.0})).rate == []


def test_a_stretch_shorter_than_the_minimum_is_reported_with_the_words_around_it_or_not_at_all():
    obs = reading(611, stretches=[(30, 35, 0.4)])
    assert min(r.n_words for r in detect_runs(obs, PROFILE, RULES).rate) >= 10 and RULES.run_min_words == 10
    exact = detect_runs(obs, PROFILE, DetectionConfig(run_min_words=5)).rate
    assert [(r.first_word, r.last_word) for r in exact] == [(30, 35)]


def test_a_finding_shorter_than_the_minimum_duration_is_dropped():
    obs = reading(600, stretches=[FAST])
    assert len(detect_runs(obs, PROFILE, RULES).rate) == 1
    long_only = DetectionConfig(min_duration_s={FlawType.TOO_FAST: 1000.0})
    assert detect_runs(obs, PROFILE, long_only).rate == []


def test_words_a_speaker_dropped_or_added_do_not_hide_a_stretch():
    base = reading(616, stretches=[FAST])
    keep = [i for i in range(90) if i not in (5, 40, 41, 70)]
    slots = list(np.array(base.slot_s)[keep])
    levels = list(np.array(base.level_db)[keep])
    tokens = [make_tokens()[i] for i in keep]
    for position, word in ((20, "zzz"), (60, "yyy"), (61, "xxx")):
        slots.insert(position, 0.25)
        levels.insert(position, -26.0)
        tokens.insert(position, word)
    obs = observations(slots, levels, tokens)
    found = detect_runs(obs, PROFILE, RULES)
    assert found.reason is None and found.coverage > 0.9
    assert len(found.rate) == 1 and found.rate[0].z > 0
    inside = [tokens[i] for i in found.rate[0].word_indices]
    assert sum(1 for t in inside if t in make_tokens()[30:48]) >= 14           # the run is made of the stretch's words


def test_a_transcript_that_does_not_match_the_passage_is_not_compared_word_by_word():
    other = reading(617, tokens=[f"{t}q" for t in make_tokens()])
    found = detect_runs(other, PROFILE, RULES)
    assert found.rate is None and found.energy is None and found.reason == "transcript_mismatch" and found.coverage == 0.0


def test_too_few_comparable_words_are_not_enough():
    short = reading(618, n=12)
    found = detect_runs(short, PROFILE, RULES)
    assert found.rate is None and found.energy is None and found.reason == "too_few_words" and found.n_usable_rate == 12
    assert detect_runs(short, PROFILE, DetectionConfig(profile_min_usable_words=12, run_min_words=10)).rate is not None


def test_words_without_a_time_are_left_out_and_the_rest_is_still_judged():
    obs = reading(619, stretches=[FAST])
    slots = np.array(obs.slot_s)
    slots[[3, 4, 60]] = np.nan
    start = np.array(obs.start_s)
    start[[3, 4, 60]] = np.nan
    cut = type(obs)(obs.tokens, start, obs.end_s, slots, obs.level_db, obs.max_gap_s, obs.active_threshold_dbfs)
    found = detect_runs(cut, PROFILE, RULES)
    assert found.n_usable_rate == 87 and len(found.rate) == 1 and near(found.rate[0], 30, 47)


def test_the_result_is_the_same_every_time():
    obs = reading(604, stretches=[(10, 25, 0.6), (55, 72, 1.7)], loud=[(30, 40, 9.0)])
    assert detect_runs(obs, PROFILE, RULES) == detect_runs(obs, PROFILE, RULES)


# ------------------------------------------------------------------------------------------------------------------------------
# Measuring a given stretch (what a planned flaw really amounted to, whether or not the scan reported it)
# ------------------------------------------------------------------------------------------------------------------------------
def span(obs, first, last):
    """The times of words `first` to `last` (0-based, inclusive): from the start of the first to the end of the last."""
    return float(obs.start_s[first]), float(obs.end_s[last])


def test_a_stretch_made_faster_is_measured_as_that_much_faster_and_an_ordinary_one_as_about_nothing():
    obs = reading(600, stretches=[FAST])
    made = measure_stretch(obs, PROFILE, RULES, *span(obs, 30, 47))
    assert made.reason is None and made.rate.n_words == 18 and made.rate.change == pytest.approx(100 * (1 / 0.6 - 1), abs=15.0)
    assert made.rate.z > RULES.z_run_rate and abs(made.level.change) < 3.0
    ordinary = measure_stretch(obs, PROFILE, RULES, *span(obs, 60, 77))
    assert abs(ordinary.rate.change) < 15.0 and abs(ordinary.rate.z) < RULES.z_run_rate and abs(ordinary.level.z) < RULES.z_run_energy
    slower = measure_stretch(reading(601, stretches=[SLOW]), PROFILE, RULES, *span(reading(601, stretches=[SLOW]), 30, 47))
    assert slower.rate.change == pytest.approx(100 * (1 / 1.7 - 1), abs=10.0) and slower.rate.z < -RULES.z_run_rate


def test_a_louder_and_a_quieter_stretch_are_measured_in_decibels_without_the_pace_changing():
    loud, quiet = reading(602, loud=[(30, 47, 8.0)]), reading(603, loud=[(30, 47, -8.0)])
    up, down = measure_stretch(loud, PROFILE, RULES, *span(loud, 30, 47)), measure_stretch(quiet, PROFILE, RULES, *span(quiet, 30, 47))
    assert up.level.change == pytest.approx(8.0, abs=1.5) and up.level.z > RULES.z_run_energy and abs(up.rate.z) < RULES.z_run_rate
    assert down.level.change == pytest.approx(-8.0, abs=1.5) and down.level.z < -RULES.z_run_energy and abs(down.rate.z) < RULES.z_run_rate


def test_the_measure_of_a_stretch_agrees_with_the_finding_the_scan_reports_for_exactly_those_words():
    obs = reading(600, stretches=[FAST], loud=[(55, 72, -9.0)])
    pace = detect_runs(obs, PROFILE, RULES).rate[0]
    level = detect_runs(obs, PROFILE, RULES).energy[0]
    on_pace = measure_stretch(obs, PROFILE, RULES, pace.start_s, pace.end_s)
    on_level = measure_stretch(obs, PROFILE, RULES, level.start_s, level.end_s)
    assert on_pace.rate.n_words == pace.n_words and on_pace.rate.z == pytest.approx(pace.z)
    assert 1.0 + on_pace.rate.change / 100.0 == pytest.approx(pace.observed / pace.expected)       # the pace ratio is the same number
    assert on_level.level.n_words == level.n_words and on_level.level.z == pytest.approx(level.z)
    assert on_level.level.change == pytest.approx(level.observed - level.expected)


def test_the_overall_pace_and_level_of_the_reading_are_removed_before_a_stretch_is_measured():
    slow_reader = reading(607, tempo=1.2, stretches=[FAST])                       # 20 % slower overall, and one stretch much faster than that
    measured = measure_stretch(slow_reader, PROFILE, RULES, *span(slow_reader, 30, 47))
    assert measured.rate.change == pytest.approx(100 * (1 / 0.6 - 1), abs=15.0)    # against the reader's own pace, not the baseline's (that would be +39 %)
    loud_reader = reading(614, level_offset=4.0, loud=[(30, 47, 8.0)])
    assert measure_stretch(loud_reader, PROFILE, RULES, *span(loud_reader, 30, 47)).level.change == pytest.approx(8.0, abs=1.5)      # not 12


def test_a_word_belongs_to_a_stretch_by_its_middle():
    obs = reading(600)
    middle = lambda i: float((obs.start_s[i] + obs.end_s[i]) / 2.0)             # noqa: E731
    both = measure_stretch(obs, PROFILE, RULES, middle(30) - 0.001, middle(39) + 0.001)
    assert both.rate.n_words == both.level.n_words == 10
    without_first = measure_stretch(obs, PROFILE, RULES, middle(30) + 0.001, middle(39) + 0.001)
    assert without_first.rate.n_words == without_first.level.n_words == 9
    without_last = measure_stretch(obs, PROFILE, RULES, middle(30) - 0.001, middle(39) - 0.001)
    assert without_last.rate.n_words == without_last.level.n_words == 9


def test_a_stretch_with_no_comparable_word_has_no_change_and_a_short_one_is_still_measured():
    obs = reading(600)
    nothing = measure_stretch(obs, PROFILE, RULES, 1000.0, 1001.0)
    assert nothing.reason is None and (nothing.rate.n_words, nothing.rate.change, nothing.rate.z) == (0, None, None)
    assert (nothing.level.n_words, nothing.level.change, nothing.level.z) == (0, None, None)
    short = measure_stretch(reading(600, stretches=[(30, 34, 0.5)]), PROFILE, RULES, *span(reading(600, stretches=[(30, 34, 0.5)]), 30, 34))
    assert short.rate.n_words == 5 and short.rate.change > 50.0                   # fewer words than a finding needs: the number is still given


def test_words_without_a_time_do_not_count_in_a_stretch():
    obs = reading(600, stretches=[FAST])
    start, slots = np.array(obs.start_s), np.array(obs.slot_s)
    start[[32, 33]] = np.nan
    slots[[32, 33]] = np.nan
    cut = type(obs)(obs.tokens, start, obs.end_s, slots, obs.level_db, obs.max_gap_s, obs.active_threshold_dbfs)
    assert measure_stretch(cut, PROFILE, RULES, *span(obs, 30, 47)).rate.n_words == 16


def test_a_reading_the_profile_cannot_judge_gives_the_reason_instead_of_numbers():
    other = reading(617, tokens=[f"{t}q" for t in make_tokens()])
    assert measure_stretch(other, PROFILE, RULES, 0.0, 1000.0) == StretchReading(None, None, "transcript_mismatch")
    short = reading(618, n=12)
    cut = measure_stretch(short, PROFILE, RULES, 0.0, 1000.0)
    assert (cut.rate, cut.level, cut.reason) == (None, None, "too_few_words")
    assert measure_stretch(short, PROFILE, DetectionConfig(profile_min_usable_words=12, run_min_words=10), 0.0, 1000.0).rate.n_words == 12


def test_each_spread_floor_alone_lowers_z_in_a_measured_stretch_and_none_changes_the_size():
    obs = reading(600, stretches=[FAST], loud=[(30, 47, 8.0)])
    normal = measure_stretch(obs, PROFILE, RULES, *span(obs, 30, 47))
    for floor, signal, other in (("sigma_floor_rate_word", "rate", "level"), ("sigma_floor_rate_drift", "rate", "level"),
                                 ("sigma_floor_level_word", "level", "rate"), ("sigma_floor_level_drift", "level", "rate")):
        raised = measure_stretch(obs, PROFILE, DetectionConfig(**{floor: 5.0}), *span(obs, 30, 47))
        assert (raised.rate.change, raised.level.change) == (normal.rate.change, normal.level.change), floor           # the size does not depend on the spread
        assert 0 < getattr(raised, signal).z < getattr(normal, signal).z, floor                                          # this floor lowers z of its own signal ...
        assert getattr(raised, other).z == getattr(normal, other).z, floor                                               # ... and of no other


def test_the_spread_in_a_measured_stretch_depends_on_the_number_of_words():
    obs = reading(600, stretches=[FAST], loud=[(30, 47, 8.0)])
    many, few = measure_stretch(obs, PROFILE, RULES, *span(obs, 30, 47)), measure_stretch(obs, PROFILE, RULES, *span(obs, 30, 39))
    assert (many.rate.n_words, few.rate.n_words) == (18, 10) and few.level.change > 0
    assert few.level.z / few.level.change < many.level.z / many.level.change       # z per decibel: a shorter run has a wider spread, so a given change counts for less


def test_a_measured_stretch_is_the_same_every_time():
    obs = reading(604, stretches=[(10, 25, 0.6)], loud=[(30, 40, 9.0)])
    assert measure_stretch(obs, PROFILE, RULES, *span(obs, 10, 25)) == measure_stretch(obs, PROFILE, RULES, *span(obs, 10, 25))


# ------------------------------------------------------------------------------------------------------------------------------
# The scan itself
# ------------------------------------------------------------------------------------------------------------------------------
def scan(values, *, sigma=lambda n: 1.0, min_words=5, min_abs=0.0, min_duration_s=0.0, z=2.0, max_runs=8, ends_after=0.9):
    values = np.asarray(values, dtype=float)
    size = len(values)
    starts = np.arange(size, dtype=float)
    return _find_runs(size=size, min_words=min_words, stat=lambda n: window_mean(values, n), sigma=sigma, min_abs=min_abs,
                      min_duration_s=min_duration_s, starts_s=starts, ends_s=starts + ends_after, z_threshold=z, max_runs=max_runs)


def block(at, length, height, size=60):
    v = np.zeros(size)
    v[at:at + length] = height
    return v


def test_the_scan_takes_the_run_with_the_largest_z_and_a_spread_that_shrinks_with_length_prefers_the_full_stretch():
    best = scan(block(20, 12, 3.0), sigma=lambda n: 1.0 / math.sqrt(n))[0]
    assert (best[0], best[1]) == (20, 12) and best[3] == pytest.approx(3.0 * math.sqrt(12))


def test_a_tie_goes_to_the_shorter_and_then_the_earlier_run():
    first = scan(block(20, 12, 3.0), sigma=lambda n: 1.0)[0]                    # every run of 5 or more words inside the block has the same z
    assert (first[0], first[1]) == (20, 5)


def test_a_z_exactly_on_the_threshold_is_not_a_finding_and_just_above_it_is():
    values = block(20, 12, 3.0)
    assert scan(values, z=3.0) == []
    assert len(scan(values, z=2.999)) >= 1


def test_runs_that_are_too_small_in_size_or_too_short_in_time_are_skipped():
    values = block(20, 12, 3.0)
    assert scan(values, min_abs=3.5) == []
    assert len(scan(values, min_abs=3.0)) >= 1
    shrinking = lambda n: 1.0 / math.sqrt(n)
    # With this spread only the block itself (12 entries, z = 3 * sqrt(12) = 10.39) is above z = 10; it lasts 11 + 0.9 = 11.9 s.
    assert [(f, n) for f, n, _s, _z in scan(values, sigma=shrinking, z=10.0, min_duration_s=11.9)] == [(20, 12)]
    assert scan(values, sigma=shrinking, z=10.0, min_duration_s=12.0) == []


def test_a_result_takes_its_entries_out_and_the_scan_goes_on_until_nothing_qualifies_or_the_limit_is_reached():
    values = block(5, 10, 3.0) + block(40, 10, -3.0)
    both = scan(values, sigma=lambda n: 1.0 / math.sqrt(n))
    assert [(first, n) for first, n, _s, _z in both] == [(5, 10), (40, 10)] or [(first, n) for first, n, _s, _z in both] == [(40, 10), (5, 10)]
    assert len(scan(values, sigma=lambda n: 1.0 / math.sqrt(n), max_runs=1)) == 1
    taken = set()
    for first, n, _s, _z in both:
        assert not taken & set(range(first, first + n))
        taken |= set(range(first, first + n))


def test_too_few_entries_give_no_result():
    assert scan(np.full(4, 9.0), min_words=5) == []
    assert scan(np.array([])) == []


# ------------------------------------------------------------------------------------------------------------------------------
# In the candidate stage
# ------------------------------------------------------------------------------------------------------------------------------
def bundle(record, **kw):
    return NormalizedFeatureBundle(baseline_passage_id=record.passage_id, baseline_sha256=record.sha256, **kw)


def window_bundle(record):
    """Overall statistics that say 'very fast' at 4 s to 12 s: what the fallback rule would flag."""
    return bundle(
        record, rate_times_s=np.array([8.0]), rate_z=np.array([5.0]), rate_window_start_s=np.array([4.0]), rate_window_end_s=np.array([12.0]),
        rate_effective_duration_s=np.array([7.0]), rate_word_count=np.array([20]),
    )


def test_findings_of_the_profile_become_candidates_that_carry_their_run_and_size():
    record = baseline_record(word_profile=PROFILE)
    obs = reading(612, stretches=[(10, 25, 0.6)], loud=[(55, 72, -9.0)])
    result = detect_candidates(bundle(record), RULES, baseline=record, observations=obs)
    assert result.modes == {"rate": "profile", "energy": "profile", "pitch": "not judged"} and result.profile_note is None
    fast, quiet = result.candidates
    assert (fast.type, fast.detection_feature) == (FlawType.TOO_FAST, "rate_run_z") and (quiet.type, quiet.detection_feature) == (FlawType.LOW_ENERGY, "energy_run_z")
    for c in (fast, quiet):
        assert c.run is not None and c.effect == c.run.effect and c.mean_z == c.run.z and c.peak_z == abs(c.run.z)
        assert c.member_indices == c.run.word_indices and c.flagged_intervals == ((c.start_s, c.end_s),) and c.stretch_rate_wpm is None
    assert fast.start_s < fast.end_s < quiet.start_s


def test_when_the_profile_judges_pace_and_loudness_the_overall_rules_do_not_run():
    record = baseline_record(word_profile=PROFILE)
    clean = reading(500)
    result = detect_candidates(window_bundle(record), RULES, baseline=record, observations=clean)
    assert result.candidates == [] and result.modes["rate"] == "profile"
    fallback = detect_candidates(window_bundle(record), DetectionConfig(use_profile=False), baseline=record, observations=clean)
    assert [c.type for c in fallback.candidates] == [FlawType.TOO_FAST] and fallback.modes == {"rate": "windows", "energy": "frames", "pitch": "not judged"}
    assert fallback.candidates[0].run is None and fallback.candidates[0].effect is None


def test_a_baseline_without_a_profile_falls_back_and_says_so():
    record = baseline_record()
    result = detect_candidates(window_bundle(record), RULES, baseline=record, observations=reading(500))
    assert result.modes == {"rate": "windows", "energy": "frames", "pitch": "not judged"} and result.profile_note == "baseline_without_profile"
    assert [c.type for c in result.candidates] == [FlawType.TOO_FAST]


def test_a_transcript_that_does_not_match_falls_back_and_says_so():
    record = baseline_record(word_profile=PROFILE)
    other = reading(617, tokens=[f"{t}q" for t in make_tokens()])
    result = detect_candidates(window_bundle(record), RULES, baseline=record, observations=other)
    assert result.modes == {"rate": "windows", "energy": "frames", "pitch": "not judged"} and result.profile_note == "transcript_mismatch"
    assert [c.type for c in result.candidates] == [FlawType.TOO_FAST]


def test_a_louder_stretch_becomes_a_high_energy_candidate_and_a_slower_one_a_too_slow_candidate():
    record = baseline_record(word_profile=PROFILE)
    result = detect_candidates(bundle(record), RULES, baseline=record, observations=reading(630, stretches=[(10, 25, 1.7)], loud=[(55, 72, 9.0)]))
    assert [(c.type, c.detection_feature) for c in result.candidates] == [(FlawType.TOO_SLOW, "rate_run_z"), (FlawType.HIGH_ENERGY, "energy_run_z")]
    whole = detect_candidates(bundle(record), RULES, baseline=record, observations=reading(605, tempo=1.7))
    assert [(c.type, c.detection_feature) for c in whole.candidates] == [(FlawType.TOO_SLOW, "rate_overall_z")]


def test_the_frame_rule_does_not_run_beside_the_loudness_comparison():
    record = baseline_record(word_profile=PROFILE)
    frames = bundle(
        record, energy_times_s=np.arange(300) * 0.01, energy_z=np.full(300, -6.0), energy_in_baseline_rule=np.ones(300, dtype=bool), energy_hop_s=0.01,
    )
    clean = reading(500)
    assert detect_candidates(frames, RULES, baseline=record, observations=clean).candidates == []
    old_way = detect_candidates(frames, DetectionConfig(use_profile=False), baseline=record, observations=clean)
    assert [c.type for c in old_way.candidates] == [FlawType.LOW_ENERGY] and old_way.candidates[0].run is None


def test_the_rule_of_a_loudness_finding_states_the_loudness_threshold_not_the_pace_one():
    record = baseline_record(word_profile=PROFILE)
    cfg = DetectionConfig(z_run_rate=4.0, z_run_energy=5.0)
    nb = bundle(record)
    detection = detect_candidates(nb, cfg, baseline=record, observations=reading(612, stretches=[(10, 25, 0.6)], loud=[(55, 72, -9.0)]))
    flaws = ground_flaws(detection, nb, record)
    thresholds = {f.type: f.rule.threshold_z for f in flaws}
    assert thresholds == {FlawType.TOO_FAST: 4.0, FlawType.LOW_ENERGY: -5.0}


def test_without_observations_nothing_changes():
    record = baseline_record(word_profile=PROFILE)
    result = detect_candidates(window_bundle(record), RULES, baseline=record)
    assert result.modes == {"rate": "windows", "energy": "frames", "pitch": "not judged"} and result.profile_note is None and len(result.candidates) == 1


def test_the_profile_must_belong_to_the_baseline_the_features_were_normalized_with():
    record = baseline_record(word_profile=PROFILE)
    other = baseline_record(word_profile=PROFILE, dataset_version="2.0.0")
    with pytest.raises(ValueError, match="word profile"):
        detect_candidates(bundle(other), RULES, baseline=record, observations=reading(500))


def test_pace_the_profile_judged_is_not_reported_unavailable_when_the_windows_could_not_be_measured():
    record = baseline_record(word_profile=PROFILE)
    reasons = {"rate": "rate_analysis_skipped: insufficient_windows", "energy": "baseline_std_not_positive"}
    judged = detect_candidates(bundle(record, unavailable=reasons), RULES, baseline=record, observations=reading(500))
    assert "too_fast" not in judged.skipped and "low_energy" not in judged.skipped
    plain = baseline_record(word_profile=None)
    not_judged = detect_candidates(bundle(plain, unavailable=reasons), RULES, baseline=plain, observations=reading(500))
    assert "too_fast" in not_judged.skipped and "low_energy" in not_judged.skipped


def test_the_new_settings_are_checked():
    for bad in (dict(run_min_words=1), dict(profile_min_usable_words=1), dict(z_run_rate=0.0), dict(z_run_energy=float("nan")), dict(min_rate_change_pct=-1.0),
                dict(min_energy_change_db=0.0), dict(global_tempo_change_pct=float("inf")), dict(profile_min_coverage=0.0), dict(profile_min_coverage=1.5),
                dict(sigma_floor_rate_word=-0.1), dict(sigma_floor_tempo=float("nan"))):
        with pytest.raises(ValueError):
            DetectionConfig(**bad)
    DetectionConfig(sigma_floor_rate_word=0.0, sigma_floor_level_drift=0.0)             # zero floors are allowed


# ------------------------------------------------------------------------------------------------------------------------------
# Severity from the size of the change
# ------------------------------------------------------------------------------------------------------------------------------
def candidate(ftype, effect, mean_z, duration=10.0):
    return FlawCandidate(type=ftype, start_s=0.0, end_s=duration, peak_z=abs(mean_z), mean_z=mean_z, detection_feature="x", member_indices=(0,),
                         flagged_intervals=((0.0, duration),), effect=effect)


def test_severity_follows_the_size_of_the_change_not_how_many_spreads_it_is():
    cfg = SeverityConfig()
    assert compute_severity(candidate(FlawType.TOO_FAST, math.log(2.0), 40.0), cfg) == 1.0                  # twice as fast: the maximum
    assert compute_severity(candidate(FlawType.TOO_FAST, math.log(2.0) / 2, 40.0), cfg) == pytest.approx(0.5)
    assert compute_severity(candidate(FlawType.TOO_SLOW, math.log(1.15), -9.0), cfg) == pytest.approx(math.log(1.15) / math.log(2.0), abs=1e-4)
    assert compute_severity(candidate(FlawType.HIGH_ENERGY, 7.5, 18.0), cfg) == pytest.approx(0.5)             # 7.5 dB of the 15 dB scale
    assert compute_severity(candidate(FlawType.LOW_ENERGY, 30.0, -50.0), cfg) == 1.0
    assert compute_severity(candidate(FlawType.EXCESSIVE_PAUSE, 1.75, 8.0), cfg) == pytest.approx(0.5)         # 1.75 s of the 3.5 s scale, no duration part


def test_a_short_stretch_is_less_serious_by_the_same_rule_as_before():
    cfg = SeverityConfig()
    assert compute_severity(candidate(FlawType.HIGH_ENERGY, 15.0, 20.0, duration=2.5), cfg) == pytest.approx(0.5)     # full size, half of the 5 s


def test_a_finding_without_a_size_keeps_the_z_score_rule():
    cfg = SeverityConfig()
    assert compute_severity(candidate(FlawType.TOO_FAST, None, 2.5, duration=10.0), cfg) == pytest.approx(0.5)         # (2.5 - 1) / (4 - 1), full duration
    assert compute_severity(candidate(FlawType.PITCH_INSTABILITY, 99.0, 2.5, duration=10.0), cfg) == pytest.approx(0.5)  # no size scale for this type: z rule


def test_the_scales_can_be_changed_and_are_checked():
    assert compute_severity(candidate(FlawType.HIGH_ENERGY, 7.5, 18.0), SeverityConfig(effect_scale={FlawType.HIGH_ENERGY: 7.5})) == 1.0
    for bad in (0.0, -1.0, float("inf")):
        with pytest.raises(ValueError):
            SeverityConfig(effect_scale={FlawType.TOO_FAST: bad})
    with pytest.raises(ValueError):
        compute_severity(candidate(FlawType.TOO_FAST, -0.1, 5.0))
    with pytest.raises(ValueError):
        compute_severity(candidate(FlawType.TOO_FAST, float("nan"), 5.0))


# ------------------------------------------------------------------------------------------------------------------------------
# The evidence a finding carries
# ------------------------------------------------------------------------------------------------------------------------------
def grounded(obs, aligned=None):
    record = baseline_record(word_profile=PROFILE)
    nb = bundle(record)
    detection = detect_candidates(nb, RULES, baseline=record, observations=obs)
    return detection, ground_flaws(detection, nb, record, aligned=aligned)


def test_pace_evidence_is_the_runs_own_numbers_and_z_can_be_re_derived_from_them():
    detection, (flaw,) = grounded(reading(600, stretches=[FAST]))
    ev, run = flaw.evidence, detection.candidates[0].run
    assert flaw.type == FlawType.TOO_FAST and ev.rate_participant_wpm == pytest.approx(run.observed, abs=1e-3) and ev.rate_baseline_mean_wpm == pytest.approx(run.expected, abs=1e-3)
    assert ev.rate_delta_wpm == pytest.approx(run.observed - run.expected, abs=2e-3)
    assert ev.rate_delta_pct == pytest.approx(100 * (run.observed - run.expected) / run.expected, abs=2e-3)
    assert (ev.rate_participant_wpm - ev.rate_baseline_mean_wpm) / ev.rate_baseline_std_wpm == pytest.approx(ev.rate_z_score, abs=2e-3)
    assert ev.rate_z_score == pytest.approx(run.z, abs=1e-3) and ev.peak_z_score == ev.rate_z_score
    assert ev.window_duration_s == pytest.approx(flaw.end_s - flaw.start_s, abs=1e-3) and ev.word_count_in_window == run.n_words     # no aligned transcript: the run's own count
    assert flaw.rule.feature == "rate_run_z" and flaw.rule.direction == "above" and flaw.rule.threshold_z == RULES.z_run_rate
    assert flaw.warnings == (WARNING_RATE_RUN,)
    assert flaw.severity == pytest.approx(min(1.0, run.effect / math.log(2.0)) * min(1.0, (flaw.end_s - flaw.start_s) / 5.0), abs=2e-4)


def test_a_slower_and_a_whole_reading_finding_state_their_own_direction_and_warning():
    _, (slow,) = grounded(reading(601, stretches=[SLOW]))
    assert slow.type == FlawType.TOO_SLOW and slow.rule.direction == "below" and slow.rule.threshold_z == -RULES.z_run_rate and slow.evidence.rate_delta_pct < 0
    _, (whole,) = grounded(reading(605, tempo=1.7))
    assert whole.rule.feature == "rate_overall_z" and whole.warnings == (WARNING_RATE_OVERALL,) and whole.type == FlawType.TOO_SLOW


def test_loudness_evidence_states_the_level_the_words_should_have_had():
    detection, (flaw,) = grounded(reading(603, loud=[(30, 47, -8.0)]))
    ev, run = flaw.evidence, detection.candidates[0].run
    assert flaw.type == FlawType.LOW_ENERGY and ev.energy_mean_db == pytest.approx(run.observed, abs=1e-3) and ev.energy_baseline_mean_db == pytest.approx(run.expected, abs=1e-3)
    assert ev.energy_delta_db == pytest.approx(run.observed - run.expected, abs=2e-3) and ev.energy_delta_db < -5.0
    assert (ev.energy_mean_db - ev.energy_baseline_mean_db) / ev.energy_baseline_std_db == pytest.approx(ev.energy_z_score, abs=2e-3)
    assert flaw.rule.feature == "energy_run_z" and flaw.rule.direction == "below" and flaw.rule.threshold_z == -RULES.z_run_energy
    assert flaw.warnings == (WARNING_ENERGY_RUN,)
    assert flaw.severity == pytest.approx(min(1.0, abs(ev.energy_delta_db) / 15.0) * min(1.0, (flaw.end_s - flaw.start_s) / 5.0), abs=2e-3)


def test_evidence_of_a_run_needs_a_finite_expectation():
    detection, _ = grounded(reading(600, stretches=[FAST]))
    c = detection.candidates[0]
    broken = FlawCandidate(**{**c.__dict__, "run": type(c.run)(**{**c.run.__dict__, "expected": float("nan")})})
    record = baseline_record(word_profile=PROFILE)
    with pytest.raises(EvidenceError, match="finite"):
        ground_flaws(type(detection)(candidates=[broken], skipped={}, config=detection.config), bundle(record), record)


# ------------------------------------------------------------------------------------------------------------------------------
# What the analysis tells the user about the comparison
# ------------------------------------------------------------------------------------------------------------------------------
def notes_for(unavailable, modes, profile_note):
    from pathlib import Path
    from types import SimpleNamespace

    from app.core.passages import PassageCatalog
    from app.schemas.request import AnalyzeRequest
    from app.services.pipeline import AnalysisPipeline

    pipeline = AnalysisPipeline(passages=PassageCatalog(Path("/nonexistent/passages.json")))
    return pipeline._notes(
        request=AnalyzeRequest(baseline_id="p001", passage_id="p001"), record=baseline_record(), aligned=None, transcript=SimpleNamespace(text="x"),
        alignment_warnings=[], normalized=SimpleNamespace(unavailable=unavailable, pauses=[]), scoring=SimpleNamespace(unevaluated=(), excluded={}),
        mfcc_available=True, fallback_used=False, energy=SimpleNamespace(mean_db=-30.0), detection=SimpleNamespace(modes=modes, profile_note=profile_note, skipped={}),
    )


def test_a_feature_the_word_comparison_judged_is_not_reported_unavailable_but_the_others_still_are():
    reasons = {"rate": "rate_analysis_skipped: insufficient_windows", "energy": "baseline_std_not_positive", "f0": "not_provided"}
    codes = {n.code for n in notes_for(reasons, {"rate": "profile", "energy": "profile"}, None)}
    assert "rate_unavailable" not in codes and "energy_unavailable" not in codes and "f0_unavailable" in codes
    codes = {n.code for n in notes_for(reasons, {"rate": "windows", "energy": "frames"}, None)}
    assert {"rate_unavailable", "energy_unavailable", "f0_unavailable"} <= codes
    codes = {n.code for n in notes_for(reasons, {"rate": "profile", "energy": "frames"}, None)}
    assert "rate_unavailable" not in codes and "energy_unavailable" in codes


def test_flat_pitch_judged_by_the_profile_needs_no_overall_pitch_statistics_and_one_that_was_not_judged_says_so():
    reasons = {"f0": "baseline_std_not_positive"}
    judged = {n.code for n in notes_for(reasons, {"rate": "profile", "energy": "profile", "pitch": "profile"}, None)}
    assert "f0_unavailable" not in judged and "pitch_not_judged" not in judged
    not_judged = {n.code: n.message for n in notes_for(reasons, {"rate": "profile", "energy": "profile", "pitch": "not judged"}, None)}
    assert "f0_unavailable" in not_judged and "Flat pitch was not checked" in not_judged["pitch_not_judged"]


def test_each_reason_the_comparison_fell_back_has_its_own_note():
    fallback = {"rate": "windows", "energy": "frames"}
    by_code = lambda note: {n.code: n.message for n in notes_for({}, fallback, note)}
    assert "overall averages" in by_code("baseline_without_profile")["baseline_without_profile"] and "Rebuild the baseline" in by_code("baseline_without_profile")["baseline_without_profile"]
    assert "match the passage text" in by_code("transcript_mismatch")["profile_not_applicable"]
    assert "Too few words could be compared" in by_code("too_few_words")["profile_not_applicable"]
    assert not {"baseline_without_profile", "profile_not_applicable"} & set(by_code(None))
