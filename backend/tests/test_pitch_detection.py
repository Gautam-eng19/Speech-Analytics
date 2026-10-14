"""Tests for flat pitch, judged word by word against the baseline's reading of the same words.

The pitch of each word is measured as its movement around the reading's own median pitch (semitones, root mean square, deviations clipped); the
baseline profile keeps how much the same words moved in the baseline readings; a run of words that moves clearly less is flat pitch. The tests
use hand-made pitch tracks (known frames, known values, so the expected numbers are worked out here) and hand-made readings (profile_helpers:
a passage whose words move by a known amount, readings that differ by chance, stretches made flat where the test says), and cover: the
measurement (reference pitch, clipping, floor, minimum voiced frames, unvoiced and invalid frames), the profile (expected movement, the spread, the
spread of the overall movement, a missing part, a baseline file written before the pitch part existed), the detection (not flagged on ordinary
readings, found on its own words, one-sided, speakers who are more or less expressive, a reading that is flat as a whole, the size and spread
guards, every reason pitch can be left unjudged), the stretch measure, the candidates and their notes, severity, evidence, the explanation and
the settings.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from app.schemas.common import FlawType
from app.schemas.contracts import BaselineStatsRecord, PitchProfile
from app.schemas.response import FlatPitchEvidence
from app.services.explanation import explain_flaw
from app.services.explanation.facts import build_fact_sheet
from app.services.grounding import (
    DetectionConfig,
    EvidenceError,
    FlawCandidate,
    SeverityConfig,
    compute_severity,
    detect_candidates,
    ground_flaws,
)
from app.services.grounding.flaws import WARNING_PITCH_OVERALL, WARNING_PITCH_RUN
from app.services.grounding.normalizer import NormalizedFeatureBundle
from app.services.grounding.profile import MIN_MOVEMENT_ST2, build_word_profile, measure_words, noise_sigma, overall_movement
from app.services.grounding.profile_detection import RunFinding, detect_runs, measure_stretch
from profile_helpers import (
    ACTIVE_DBFS,
    GAP_CAP_S,
    N_WORDS,
    PITCH_REFERENCE_HZ,
    baseline_readings,
    baseline_record,
    make_profile,
    make_tokens,
    reading,
)
from pydantic import ValidationError

PROFILE = make_profile(pitch=True)
RULES = DetectionConfig()
FLAT = (30, 47, 0.3)          # words 30 to 47 move 0.3 times as far


def near(found, first, last, tolerance=2):
    return abs(found.first_word - first) <= tolerance and abs(found.last_word - last) <= tolerance


def span(obs, first, last):
    return float(obs.start_s[first]), float(obs.end_s[last])


# ------------------------------------------------------------------------------------------------------------------------------
# Measuring the pitch movement of the words
# ------------------------------------------------------------------------------------------------------------------------------
HOP = 0.01


def pitch_track(*pieces):
    """A pitch track from pieces ``(first_time, last_time, [Hz values cycled over the frames])``; frames outside every piece are unvoiced."""
    times = np.round(np.arange(0.0, 3.0, HOP), 6)
    values = np.full(len(times), np.nan)
    voiced = np.zeros(len(times), dtype=bool)
    for first, last, hz in pieces:
        idx = np.flatnonzero((times >= first - 1e-9) & (times <= last + 1e-9))
        values[idx] = [hz[k % len(hz)] for k in range(len(idx))]
        voiced[idx] = True
    return SimpleNamespace(times_s=times, values_hz=values, voiced=voiced)


def words(*spans):
    return SimpleNamespace(words=[SimpleNamespace(word=f"w{i}", start_s=s, end_s=e) for i, (s, e) in enumerate(spans)])


def energy():
    times = np.round(np.arange(0.0, 3.0, HOP), 6)
    return SimpleNamespace(times_s=times, values_db=np.full(len(times), -30.0))


def measure(track, aligned, **kw):
    return measure_words(aligned, energy(), max_gap_s=GAP_CAP_S, active_threshold_dbfs=ACTIVE_DBFS, f0=track, **kw)


UP, DOWN = 100.0 * 2 ** (3 / 12), 100.0 * 2 ** (-3 / 12)


def test_a_word_that_moves_three_semitones_either_side_of_the_median_pitch_has_a_movement_of_nine():
    track = pitch_track((0.0, 0.5, [100.0]), (0.6, 1.1, [UP, DOWN]), (1.2, 1.7, [100.0]))
    obs = measure(track, words((0.0, 0.5), (0.6, 1.1), (1.2, 1.7)))
    assert obs.pitch_reference_hz == pytest.approx(100.0)                                   # the median of the voiced frames
    assert obs.pitch_movement_st2[1] == pytest.approx(9.0, abs=0.01)                        # (+3)^2 and (-3)^2
    assert obs.pitch_movement_st2[0] == obs.pitch_movement_st2[2] == MIN_MOVEMENT_ST2        # a word that does not move has the smallest movement, not zero
    assert list(obs.pitch_frames) == [51, 51, 51] and list(obs.pitch_voiced_frames) == [51, 51, 51]
    assert obs.pitch_min_voiced_frames == 5 and obs.pitch_clip_st == 6.0


def test_a_deviation_beyond_the_clip_counts_as_the_clip_so_a_tracking_error_cannot_dominate():
    octave_error = [100.0] * 3 + [200.0]                                                    # every fourth frame an octave up: +12 semitones
    track = pitch_track((0.0, 0.5, [100.0]), (0.6, 1.1, octave_error), (1.2, 1.7, [100.0]), (1.8, 2.3, [100.0]))
    aligned = words((0.0, 0.5), (0.6, 1.1), (1.2, 1.7), (1.8, 2.3))
    clipped = measure(track, aligned)
    assert clipped.pitch_movement_st2[1] == pytest.approx(12 / 51 * 36.0, abs=0.01)         # 12 of the 51 frames are octave errors; 12 semitones is clipped to 6, squared 36
    wide = measure(track, aligned, pitch_deviation_clip_st=12.0)
    assert wide.pitch_movement_st2[1] == pytest.approx(12 / 51 * 144.0, abs=0.05) and wide.pitch_clip_st == 12.0


def test_a_word_needs_enough_voiced_frames_and_unvoiced_or_invalid_frames_do_not_count():
    track = pitch_track((0.0, 1.0, [100.0]), (1.2, 1.23, [UP, DOWN]), (1.5, 1.9, [UP, DOWN]))        # word 2 has 4 voiced frames, word 3 has 41
    aligned = words((0.0, 1.0), (1.2, 1.3), (1.5, 1.9))
    obs = measure(track, aligned)
    assert np.isnan(obs.pitch_movement_st2[1]) and list(obs.pitch_voiced_frames) == [101, 4, 41] and list(obs.pitch_frames) == [101, 11, 41]
    assert np.isfinite(measure(track, aligned, pitch_min_voiced_frames=4).pitch_movement_st2[1])
    unvoiced = SimpleNamespace(times_s=track.times_s, values_hz=track.values_hz, voiced=np.zeros(len(track.times_s), dtype=bool))
    assert measure(unvoiced, aligned).pitch_movement_st2 is None                            # no voiced speech: no reference
    broken = np.array(track.values_hz)
    broken[(track.times_s >= 1.5) & (track.times_s <= 1.9)] = -5.0                          # impossible pitches are not frames
    assert np.isnan(measure(SimpleNamespace(times_s=track.times_s, values_hz=broken, voiced=track.voiced), aligned).pitch_movement_st2[2])


def test_the_reference_pitch_is_the_median_of_the_voiced_frames_only():
    track = pitch_track((0.0, 0.5, [150.0]), (0.6, 1.1, [150.0]), (1.2, 1.7, [150.0]))
    track.values_hz[track.times_s > 2.0] = 1000.0                                           # finite values on frames that are not voiced
    obs = measure(track, words((0.0, 0.5), (0.6, 1.1), (1.2, 1.7)))
    assert obs.pitch_reference_hz == pytest.approx(150.0)


def test_a_word_without_a_time_has_no_pitch_movement_and_a_reading_without_a_track_has_no_pitch_part():
    track = pitch_track((0.0, 0.5, [100.0]), (0.6, 1.1, [UP, DOWN]), (1.2, 1.7, [100.0]))
    aligned = SimpleNamespace(words=[SimpleNamespace(word="a", start_s=0.0, end_s=0.5), SimpleNamespace(word="b", start_s=None, end_s=None),
                                     SimpleNamespace(word="c", start_s=1.2, end_s=1.7)])
    obs = measure(track, aligned)
    assert np.isnan(obs.pitch_movement_st2[1]) and obs.pitch_frames[1] == 0
    plain = measure_words(aligned, energy(), max_gap_s=GAP_CAP_S, active_threshold_dbfs=ACTIVE_DBFS)
    assert plain.pitch_movement_st2 is None and plain.pitch_voiced_frames is None and math.isnan(plain.pitch_reference_hz)


def test_pitch_settings_and_tracks_that_cannot_be_used_are_refused():
    track = pitch_track((0.0, 0.5, [100.0]))
    aligned = words((0.0, 0.5))
    for kw in ({"pitch_min_voiced_frames": 0}, {"pitch_deviation_clip_st": 0.0}, {"pitch_deviation_clip_st": float("nan")}):
        with pytest.raises(ValueError):
            measure(track, aligned, **kw)
    with pytest.raises(ValueError, match="equal length"):
        measure(SimpleNamespace(times_s=track.times_s, values_hz=track.values_hz[:-1], voiced=track.voiced), aligned)


def test_the_measurement_is_the_same_every_time():
    track = pitch_track((0.0, 0.5, [100.0]), (0.6, 1.1, [UP, DOWN]), (1.2, 1.7, [100.0]))
    aligned = words((0.0, 0.5), (0.6, 1.1), (1.2, 1.7))
    one, two = measure(track, aligned), measure(track, aligned)
    assert np.array_equal(one.pitch_movement_st2, two.pitch_movement_st2) and one.pitch_reference_hz == two.pitch_reference_hz


# ------------------------------------------------------------------------------------------------------------------------------
# The profile
# ------------------------------------------------------------------------------------------------------------------------------
def test_the_expected_movement_of_a_word_is_the_mean_over_the_baseline_readings():
    readings = baseline_readings(6, pitch=True)
    profile = build_word_profile(readings, make_tokens(), max_gap_s=GAP_CAP_S, active_threshold_dbfs=ACTIVE_DBFS)
    expected = np.mean([r.pitch_movement_st2 for r in readings], axis=0)
    assert profile.pitch is not None and len(profile.pitch.movement_st2) == N_WORDS
    assert np.allclose(profile.pitch.movement_st2, expected, atol=1e-5)
    assert (profile.pitch.min_voiced_frames, profile.pitch.deviation_clip_st) == (5, 6.0)


def test_a_word_measured_in_fewer_than_two_baseline_readings_has_no_expectation():
    readings = baseline_readings(6, pitch=True)
    for i in range(1, 6):
        movement = np.array(readings[i].pitch_movement_st2)
        movement[5] = np.nan
        readings[i] = replace(readings[i], pitch_movement_st2=movement)
    profile = build_word_profile(readings, make_tokens(), max_gap_s=GAP_CAP_S, active_threshold_dbfs=ACTIVE_DBFS)
    assert profile.pitch.movement_st2[5] is None and profile.pitch.movement_st2[4] is not None


def test_the_spread_of_a_run_is_what_chance_does_to_the_movement_of_single_words():
    noise = PROFILE.pitch.noise
    assert noise.word == pytest.approx(0.45 / 2 * math.sqrt(1.2), rel=0.25)                # a log-normal factor of 0.45 on the squared movement, leave-one-out
    assert noise.drift < 0.08 and PROFILE.pitch.scale_sd > 0.0                             # no drift was put in; the two kinds of speaker differ in how expressive they are
    assert noise_sigma(noise, 10, drift_floor=0.05, word_floor=0.3) > noise_sigma(noise, 40, drift_floor=0.05, word_floor=0.3)


def test_the_pitch_part_is_built_only_from_readings_that_have_pitch_and_only_if_three_do():
    with_pitch = baseline_readings(2, pitch=True)
    without = baseline_readings(4)
    mixed = build_word_profile(with_pitch + without, make_tokens(), max_gap_s=GAP_CAP_S, active_threshold_dbfs=ACTIVE_DBFS)
    assert mixed is not None and mixed.pitch is None                                      # pace and loudness are still profiled
    three = build_word_profile(baseline_readings(3, pitch=True) + without, make_tokens(), max_gap_s=GAP_CAP_S, active_threshold_dbfs=ACTIVE_DBFS)
    assert three.pitch is not None


def test_a_profile_is_the_same_whatever_the_order_of_the_readings():
    readings = baseline_readings(6, pitch=True)
    forward = build_word_profile(readings, make_tokens(), max_gap_s=GAP_CAP_S, active_threshold_dbfs=ACTIVE_DBFS)
    backward = build_word_profile(readings[::-1], make_tokens(), max_gap_s=GAP_CAP_S, active_threshold_dbfs=ACTIVE_DBFS)
    assert forward.pitch == backward.pitch


def test_a_baseline_written_before_the_pitch_part_existed_still_verifies_and_the_pitch_part_is_part_of_the_hash_when_there():
    plain = baseline_record(word_profile=make_profile())
    assert '"pitch"' not in plain.canonical_json() and plain.verify_sha256()
    old_form = plain.model_dump(mode="json", exclude={"sha256"})
    old_form["word_profile"].pop("pitch")                                                  # the file as it was written before
    old_hash = hashlib.sha256(json.dumps(old_form, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    assert plain.sha256 == old_hash
    restored = BaselineStatsRecord.model_validate_json(plain.model_dump_json())
    assert restored.verify_sha256() and restored.word_profile.pitch is None
    with_pitch = baseline_record(word_profile=PROFILE)
    assert '"pitch":{' in with_pitch.canonical_json() and with_pitch.verify_sha256() and with_pitch.sha256 != plain.sha256
    changed = with_pitch.model_copy(update={"word_profile": PROFILE.model_copy(update={"pitch": PROFILE.pitch.model_copy(update={"scale_sd": 0.5})})})
    assert not changed.verify_sha256()


def test_a_pitch_profile_must_be_consistent():
    good = PROFILE.pitch
    with pytest.raises(ValidationError):
        PitchProfile(**{**good.model_dump(), "movement_st2": [-1.0] + good.movement_st2[1:]})
    with pytest.raises(ValidationError):
        PitchProfile(**{**good.model_dump(), "deviation_clip_st": 0.0})
    with pytest.raises(ValidationError):
        PitchProfile(**{**good.model_dump(), "min_voiced_frames": 0})
    with pytest.raises(ValidationError, match="one entry per word"):
        PROFILE.model_copy(update={}).__class__(**{**PROFILE.model_dump(), "pitch": {**good.model_dump(), "movement_st2": good.movement_st2[:-1]}})


# ------------------------------------------------------------------------------------------------------------------------------
# Finding what was made flat
# ------------------------------------------------------------------------------------------------------------------------------
def test_ordinary_readings_are_not_flagged_for_flat_pitch_even_when_the_speaker_is_a_little_more_or_less_expressive():
    for seed in range(500, 540):
        found = detect_runs(reading(seed, pitch=True, expressive=0.8 + 0.01 * (seed - 500)), PROFILE, RULES)
        assert found.pitch == [] and found.pitch_reason is None, seed


def test_a_flat_stretch_is_found_on_its_own_words_with_the_movement_in_hz_and_the_voiced_share():
    obs = reading(600, pitch=True, flat=[FLAT])
    found = detect_runs(obs, PROFILE, RULES)
    (run,) = found.pitch
    assert run.kind == "pitch_run" and near(run, 30, 47) and run.z < -RULES.z_run_pitch
    assert (run.start_s, run.end_s) == (obs.start_s[run.first_word], obs.end_s[run.last_word])
    assert run.n_words == run.last_word - run.first_word + 1 == len(run.word_indices)
    assert run.observed < 0.5 * run.expected and run.expected > 0                          # Hz: the voice moved a good deal less than it should
    assert run.effect == pytest.approx(math.log(1 / 0.3), abs=0.35)
    assert run.voiced_fraction == pytest.approx(12 / 20)                                   # the share of the run's frames that were voiced
    sigma = noise_sigma(PROFILE.pitch.noise, run.n_words, drift_floor=RULES.sigma_floor_pitch_drift, word_floor=RULES.sigma_floor_pitch_word)
    assert run.z == pytest.approx(-run.effect / sigma) and run.sigma_equiv == pytest.approx(abs(run.observed - run.expected) / abs(run.z))
    assert found.n_usable_pitch == N_WORDS and found.rate == [] and found.energy == []


def test_hz_are_the_root_mean_square_movement_above_the_median_pitch_of_the_reading():
    flat = reading(601, pitch=True, flat=[(0, N_WORDS - 1, 0.3)])
    (run,) = detect_runs(flat, PROFILE, RULES).pitch                                        # the whole reading, so the overall movement is the run
    assert run.kind == "pitch_overall"
    mean_movement = float(np.mean(flat.pitch_movement_st2))
    assert run.observed == pytest.approx(PITCH_REFERENCE_HZ * (2 ** (math.sqrt(mean_movement) / 12) - 1))
    expected_mean = float(np.mean([m for m in PROFILE.pitch.movement_st2]))
    assert run.expected == pytest.approx(PITCH_REFERENCE_HZ * (2 ** (math.sqrt(expected_mean) / 12) - 1))


def test_only_less_movement_is_a_flaw_a_more_expressive_stretch_is_not_reported():
    assert detect_runs(reading(602, pitch=True, flat=[(30, 47, 2.5)]), PROFILE, RULES).pitch == []


def test_a_reserved_speaker_is_judged_against_their_own_range_and_a_flat_stretch_is_still_found():
    reserved = detect_runs(reading(603, pitch=True, expressive=0.7), PROFILE, RULES)
    assert reserved.pitch == []
    (run,) = detect_runs(reading(604, pitch=True, expressive=0.7, flat=[FLAT]), PROFILE, RULES).pitch
    assert run.kind == "pitch_run" and near(run, 30, 47)


def test_a_reading_that_is_flat_as_a_whole_is_one_finding_over_all_its_words_and_has_no_local_findings():
    (run,) = detect_runs(reading(605, pitch=True, expressive=0.3), PROFILE, RULES).pitch
    assert run.kind == "pitch_overall" and (run.first_word, run.last_word, run.n_words) == (0, N_WORDS - 1, N_WORDS) and run.z < -RULES.z_run_pitch


def test_a_reading_is_flat_as_a_whole_only_if_it_is_far_enough_below_and_below_what_readers_differ_by():
    moderate = reading(606, pitch=True, expressive=0.6)                                    # 40 % less movement: under the 45 % guard
    assert detect_runs(moderate, PROFILE, RULES).pitch == []
    assert [r.kind for r in detect_runs(moderate, PROFILE, DetectionConfig(global_pitch_change_pct=30)).pitch] == ["pitch_overall"]
    wide = PROFILE.model_copy(update={"pitch": PROFILE.pitch.model_copy(update={"scale_sd": 0.4})})           # readers differ a lot in how expressive they are
    very_flat = reading(607, pitch=True, expressive=0.3)
    assert detect_runs(very_flat, wide, RULES).pitch == []
    assert [r.kind for r in detect_runs(very_flat, PROFILE, RULES).pitch] == ["pitch_overall"]


def test_a_change_too_small_to_matter_is_not_reported_however_even_the_baseline_is_and_the_spread_has_a_floor():
    even = make_profile(pitch=True, movement_jitter=0.01)
    mild = reading(608, pitch=True, movement_jitter=0.01, flat=[(20, 49, 0.7)])            # the pitch moves 30 % less over 30 words
    assert detect_runs(mild, even, RULES).pitch == []                                      # under the 35 % guard, however sure the statistics are
    assert len(detect_runs(mild, even, DetectionConfig(min_flat_pitch_change_pct=20)).pitch) == 1
    barely = reading(609, pitch=True, movement_jitter=0.01, flat=[(20, 49, 0.6)])          # 40 % less: over the guard
    assert len(detect_runs(barely, even, DetectionConfig(sigma_floor_pitch_drift=0.0, sigma_floor_pitch_word=0.0)).pitch) == 1
    assert detect_runs(barely, even, DetectionConfig(sigma_floor_pitch_drift=0.5, sigma_floor_pitch_word=3.0)).pitch == []


def test_a_stretch_shorter_than_the_minimum_is_reported_with_the_words_around_it_or_not_at_all():
    obs = reading(610, pitch=True, flat=[(30, 37, 0.05)])
    assert min(r.n_words for r in detect_runs(obs, PROFILE, RULES).pitch) >= 10 and RULES.run_min_words == 10
    (exact,) = detect_runs(obs, PROFILE, DetectionConfig(run_min_words=5)).pitch
    assert near(exact, 30, 37, tolerance=1) and exact.n_words < 10


def test_a_finding_shorter_than_the_minimum_duration_is_dropped():
    obs = reading(600, pitch=True, flat=[FLAT])
    assert len(detect_runs(obs, PROFILE, RULES).pitch) == 1
    assert detect_runs(obs, PROFILE, DetectionConfig(min_duration_s={FlawType.FLAT_PITCH: 1000.0})).pitch == []
    assert detect_runs(reading(605, pitch=True, expressive=0.3), PROFILE, DetectionConfig(min_duration_s={FlawType.FLAT_PITCH: 1000.0})).pitch == []


def test_a_word_without_a_pitch_movement_is_left_out_and_the_rest_is_still_judged():
    obs = reading(611, pitch=True, flat=[FLAT])
    movement = np.array(obs.pitch_movement_st2)
    movement[[3, 4, 60]] = np.nan
    found = detect_runs(replace(obs, pitch_movement_st2=movement), PROFILE, RULES)
    assert found.n_usable_pitch == N_WORDS - 3 and len(found.pitch) == 1 and near(found.pitch[0], 30, 47)


def test_every_reason_pitch_is_not_judged_is_named_and_pace_and_loudness_are_still_judged():
    ordinary = reading(612, pitch=True)
    assert detect_runs(reading(612), PROFILE, RULES).pitch_reason == "pitch_not_measured"                  # the reading has no pitch part
    assert detect_runs(ordinary, make_profile(), RULES).pitch_reason == "baseline_without_pitch_profile"   # the baseline has none
    few = detect_runs(reading(613, pitch=True, n=12), PROFILE, RULES)
    assert few.pitch is None and few.pitch_reason == "too_few_pitch_words" and few.n_usable_pitch == 12
    other = detect_runs(reading(614, pitch=True, tokens=[f"{t}q" for t in make_tokens()]), PROFILE, RULES)
    assert other.pitch is None and other.pitch_reason == "transcript_mismatch" and other.reason == "transcript_mismatch"
    for case in (detect_runs(reading(612), PROFILE, RULES), detect_runs(ordinary, make_profile(), RULES)):
        assert case.pitch is None and case.rate == [] and case.energy == []


def test_the_result_for_pitch_is_the_same_every_time():
    obs = reading(604, pitch=True, flat=[(10, 25, 0.3), (55, 72, 0.2)])
    assert detect_runs(obs, PROFILE, RULES) == detect_runs(obs, PROFILE, RULES)
    assert len(detect_runs(obs, PROFILE, RULES).pitch) == 2


# ------------------------------------------------------------------------------------------------------------------------------
# Measuring a given stretch
# ------------------------------------------------------------------------------------------------------------------------------
def test_a_stretch_made_flat_is_measured_as_that_much_less_movement_and_an_ordinary_one_as_about_nothing():
    obs = reading(600, pitch=True, flat=[FLAT])
    made = measure_stretch(obs, PROFILE, RULES, *span(obs, 30, 47))
    assert made.pitch.n_words == 18 and made.pitch.change == pytest.approx(-70.0, abs=15.0) and made.pitch.z < -RULES.z_run_pitch
    ordinary = measure_stretch(obs, PROFILE, RULES, *span(obs, 60, 77))
    assert abs(ordinary.pitch.change) < 35.0 and abs(ordinary.pitch.z) < RULES.z_run_pitch


def test_the_measure_of_a_stretch_agrees_with_the_finding_the_scan_reports_for_exactly_those_words():
    obs = reading(600, pitch=True, flat=[FLAT])
    (run,) = detect_runs(obs, PROFILE, RULES).pitch
    measured = measure_stretch(obs, PROFILE, RULES, run.start_s, run.end_s)
    assert measured.pitch.n_words == run.n_words and measured.pitch.z == pytest.approx(run.z)
    assert 1.0 + measured.pitch.change / 100.0 == pytest.approx(math.exp(-run.effect))


def test_the_overall_movement_of_the_reading_is_removed_before_a_stretch_is_measured_and_a_missing_part_is_not_measured():
    reserved = reading(604, pitch=True, expressive=0.7, flat=[FLAT])
    assert measure_stretch(reserved, PROFILE, RULES, *span(reserved, 30, 47)).pitch.change == pytest.approx(-70.0, abs=15.0)       # against its own range
    assert measure_stretch(reading(600, flat=[(30, 47, 0.3)]), PROFILE, RULES, 0.0, 1000.0).pitch is None
    assert measure_stretch(reading(600, pitch=True), make_profile(), RULES, 0.0, 1000.0).pitch is None
    empty = measure_stretch(reading(600, pitch=True), PROFILE, RULES, 1000.0, 1001.0)
    assert (empty.pitch.n_words, empty.pitch.change, empty.pitch.z) == (0, None, None)


# ------------------------------------------------------------------------------------------------------------------------------
# Candidates, severity, evidence, explanation
# ------------------------------------------------------------------------------------------------------------------------------
def bundle(record, **kw):
    return NormalizedFeatureBundle(baseline_passage_id=record.passage_id, baseline_sha256=record.sha256, **kw)


def detection_for(obs, record=None, cfg=RULES):
    record = record or baseline_record(word_profile=PROFILE)
    return detect_candidates(bundle(record), cfg, baseline=record, observations=obs), record


def test_a_flat_run_becomes_a_flat_pitch_candidate_that_carries_its_run_and_size_and_flat_pitch_is_no_longer_skipped():
    result, _ = detection_for(reading(600, pitch=True, flat=[FLAT]))
    (candidate,) = result.candidates
    assert candidate.type == FlawType.FLAT_PITCH and candidate.detection_feature == "pitch_run_z" and candidate.run.kind == "pitch_run"
    assert candidate.effect == pytest.approx(candidate.run.effect) and candidate.mean_z == candidate.run.z < 0
    assert candidate.member_indices == candidate.run.word_indices and candidate.flagged_intervals == ((candidate.start_s, candidate.end_s),)
    assert result.modes["pitch"] == "profile" and result.pitch_note is None and "flat_pitch" not in result.skipped
    assert "pitch_instability" in result.skipped and "not implemented" in result.skipped["pitch_instability"]


def test_a_whole_reading_that_is_flat_has_its_own_rule_feature():
    result, _ = detection_for(reading(605, pitch=True, expressive=0.3))
    assert [c.detection_feature for c in result.candidates] == ["pitch_overall_z"]


def test_pitch_that_could_not_be_judged_is_skipped_with_its_reason_and_the_other_signals_are_judged_as_before():
    record = baseline_record(word_profile=PROFILE)
    cases = {
        "pitch_not_measured": (reading(612), record),
        "baseline_without_pitch_profile": (reading(612, pitch=True), baseline_record(word_profile=make_profile())),
        "too_few_pitch_words": (reading(613, pitch=True, n=12), record),
        "transcript_mismatch": (reading(614, pitch=True, tokens=[f"{t}q" for t in make_tokens()]), record),
    }
    for note, (obs, rec) in cases.items():
        result, _ = detection_for(obs, rec)
        assert result.pitch_note == note and result.modes["pitch"] == "not judged", note
        assert "flat_pitch" in result.skipped and result.skipped["flat_pitch"], note
    mismatch, _ = detection_for(*cases["transcript_mismatch"])
    assert "do not match the passage" in mismatch.skipped["flat_pitch"] and mismatch.profile_note == "transcript_mismatch"
    old_baseline, _ = detection_for(reading(612, pitch=True), baseline_record())
    assert old_baseline.pitch_note == "baseline_without_pitch_profile" and "no pitch profile" in old_baseline.skipped["flat_pitch"]
    off, _ = detection_for(reading(600, pitch=True, flat=[FLAT]), cfg=DetectionConfig(use_profile=False))
    assert off.candidates == [] and off.modes["pitch"] == "not judged" and "word by word" in off.skipped["flat_pitch"]


def test_pitch_is_judged_while_pace_and_loudness_findings_stay_what_they_were():
    obs = reading(612, pitch=True, flat=[(10, 25, 0.3)], stretches=[(50, 65, 0.6)], loud=[(70, 85, -9.0)])
    result, _ = detection_for(obs)
    assert sorted(c.type.value for c in result.candidates) == ["flat_pitch", "low_energy", "too_fast"]


def candidate(effect, mean_z=-8.0, duration=10.0, ftype=FlawType.FLAT_PITCH):
    return FlawCandidate(ftype, 0.0, duration, abs(mean_z), mean_z, "pitch_run_z", (0,), ((0.0, duration),), effect=effect)


def test_severity_follows_how_much_less_the_pitch_moved_a_third_as_much_is_the_most_serious():
    cfg = SeverityConfig()
    assert cfg.effect_scale[FlawType.FLAT_PITCH] == pytest.approx(math.log(3.0))
    assert compute_severity(candidate(math.log(3.0)), cfg) == 1.0
    assert compute_severity(candidate(math.log(1.5)), cfg) == pytest.approx(math.log(1.5) / math.log(3.0), abs=1e-3)
    assert compute_severity(candidate(math.log(5.0)), cfg) == 1.0                          # beyond the scale: capped
    assert compute_severity(candidate(math.log(3.0), duration=2.5), cfg) == pytest.approx(0.5)      # half of the 5 s that count as long
    assert compute_severity(candidate(math.log(3.0)), SeverityConfig(effect_scale={FlawType.FLAT_PITCH: 2 * math.log(3.0)})) == pytest.approx(0.5)


def grounded(obs, aligned=None, cfg=RULES):
    detection, record = detection_for(obs, cfg=cfg)
    return detection, ground_flaws(detection, bundle(record), record, aligned=aligned)


def test_flat_pitch_evidence_is_the_runs_own_numbers_and_z_is_negative():
    detection, (flaw,) = grounded(reading(600, pitch=True, flat=[FLAT]))
    run = detection.candidates[0].run
    ev = flaw.evidence
    assert flaw.type == FlawType.FLAT_PITCH and isinstance(ev, FlatPitchEvidence)
    assert ev.f0_std_hz_in_window == pytest.approx(run.observed, abs=1e-4) and ev.f0_std_baseline_hz == pytest.approx(run.expected, abs=1e-4)
    assert ev.f0_std_hz_in_window < ev.f0_std_baseline_hz and ev.f0_std_z == pytest.approx(run.z, abs=1e-4) and ev.f0_std_z < 0
    assert ev.f0_voiced_fraction == pytest.approx(0.6) and ev.window_duration_s == pytest.approx(flaw.duration_s)
    assert 0.0 < flaw.severity <= 1.0 and flaw.warnings == (WARNING_PITCH_RUN,)


def test_the_rule_of_a_flat_pitch_finding_states_the_pitch_threshold_and_a_whole_reading_says_so():
    _, (run_flaw,) = grounded(reading(600, pitch=True, flat=[FLAT]))
    assert (run_flaw.rule.feature, run_flaw.rule.direction, run_flaw.rule.threshold_z) == ("pitch_run_z", "below", -RULES.z_run_pitch)
    _, (whole,) = grounded(reading(605, pitch=True, expressive=0.3))
    assert (whole.rule.feature, whole.rule.direction, whole.rule.threshold_z) == ("pitch_overall_z", "below", -RULES.z_run_pitch)
    assert whole.warnings == (WARNING_PITCH_OVERALL,) and whole.rule.min_duration_s == RULES.min_duration_s[FlawType.FLAT_PITCH]
    _, (stricter,) = grounded(reading(600, pitch=True, flat=[FLAT]), cfg=DetectionConfig(z_run_pitch=3.0))
    assert stricter.rule.threshold_z == -3.0                                               # the threshold that was applied, not the default


def test_evidence_for_flat_pitch_needs_the_run_and_the_voiced_share():
    record = baseline_record(word_profile=PROFILE)
    nb = bundle(record)
    bare = FlawCandidate(FlawType.FLAT_PITCH, 0.0, 1.0, 5.0, -5.0, "pitch_run_z", (0,), ((0.0, 1.0),), effect=1.0)
    with pytest.raises(EvidenceError, match="run of words"):
        ground_flaws(replace_detection(bare), nb, record)
    result, _ = detection_for(reading(600, pitch=True, flat=[FLAT]))
    run = result.candidates[0].run
    for broken in (replace(run, voiced_fraction=None), replace(run, observed=float("nan"))):
        with pytest.raises(EvidenceError, match="voiced fraction"):
            ground_flaws(replace_detection(replace(result.candidates[0], run=broken)), nb, record)


def replace_detection(candidate):
    from app.services.grounding import CandidateDetectionResult

    return CandidateDetectionResult(candidates=[candidate], skipped={}, config=RULES)


def test_the_explanation_of_flat_pitch_states_its_numbers_from_the_evidence_and_passes_the_guard():
    _, (flaw,) = grounded(reading(600, pitch=True, flat=[FLAT]))
    facts = build_fact_sheet(flaw)
    ev = flaw.evidence
    assert facts["pitch_hz"] == f"{ev.f0_std_hz_in_window:.1f}" and facts["baseline_pitch_hz"] == f"{ev.f0_std_baseline_hz:.1f}"
    assert facts["less_pct"] == f"{100 * (1 - ev.f0_std_hz_in_window / ev.f0_std_baseline_hz):.0f}" and facts["voiced_pct"] == "60"
    assert facts["z"] == f"{abs(ev.f0_std_z):.2f}"
    out = explain_flaw(flaw)
    assert out.used_fallback is False
    for text in (facts["pitch_hz"], facts["baseline_pitch_hz"], facts["less_pct"] + "%", facts["z"]):
        assert text in out.explanation, text
    assert "flatter, more monotone delivery than the baseline" in out.explanation and "these same words" in out.explanation
    assert facts["baseline_pitch_hz"] in out.recommendation and "melody" in out.recommendation
    assert "twice" not in out.explanation + out.recommendation


def test_a_whole_reading_that_is_flat_is_explained_as_the_whole_recording():
    _, (flaw,) = grounded(reading(605, pitch=True, expressive=0.3))
    out = explain_flaw(flaw)
    assert out.used_fallback is False and "over the whole recording" in out.explanation and "differ in pitch movement" in out.explanation


# ------------------------------------------------------------------------------------------------------------------------------
# Settings
# ------------------------------------------------------------------------------------------------------------------------------
def test_the_flat_pitch_settings_are_checked_and_flat_pitch_has_a_minimum_duration():
    assert DetectionConfig().min_duration_s[FlawType.FLAT_PITCH] > 0
    for kw in ({"z_run_pitch": 0.0}, {"z_run_pitch": float("nan")}, {"min_flat_pitch_change_pct": 0.0}, {"min_flat_pitch_change_pct": 100.0},
               {"global_pitch_change_pct": 0.0}, {"global_pitch_change_pct": 100.0}, {"sigma_floor_pitch_drift": -0.1},
               {"sigma_floor_pitch_word": float("inf")}, {"sigma_floor_pitch_scale": -1.0}):
        with pytest.raises(ValueError):
            DetectionConfig(**kw)
    assert DetectionConfig(min_flat_pitch_change_pct=99.0, global_pitch_change_pct=1.0, sigma_floor_pitch_scale=0.0).min_flat_pitch_change_pct == 99.0


def test_the_defaults_of_the_pitch_part_are_the_settings():
    from app.core.config import settings

    cfg = DetectionConfig()
    assert (cfg.z_run_pitch, cfg.min_flat_pitch_change_pct, cfg.global_pitch_change_pct) == (settings.Z_RUN_PITCH, settings.MIN_FLAT_PITCH_CHANGE_PCT, settings.GLOBAL_PITCH_CHANGE_PCT)
    assert (cfg.sigma_floor_pitch_drift, cfg.sigma_floor_pitch_word, cfg.sigma_floor_pitch_scale) == (
        settings.SIGMA_FLOOR_PITCH_DRIFT, settings.SIGMA_FLOOR_PITCH_WORD, settings.SIGMA_FLOOR_PITCH_SCALE)
    assert (settings.PITCH_MIN_VOICED_FRAMES, settings.PITCH_DEVIATION_CLIP_ST, settings.SEVERITY_PITCH_FLAT_SEVERE_RATIO) == (5, 6.0, 3.0)


# ------------------------------------------------------------------------------------------------------------------------------
# Details the mutation check showed were not pinned down
# ------------------------------------------------------------------------------------------------------------------------------
def test_the_spread_of_the_readers_overall_expressiveness_is_the_sample_spread_of_their_leave_one_out_movements():
    readings = baseline_readings(6, pitch=True)
    movement = np.vstack([r.pitch_movement_st2 for r in readings])
    scales = [overall_movement(movement[b], np.mean(np.delete(movement, b, axis=0), axis=0)) for b in range(6)]
    profile = build_word_profile(readings, make_tokens(), max_gap_s=GAP_CAP_S, active_threshold_dbfs=ACTIVE_DBFS)
    assert profile.pitch.scale_sd == pytest.approx(float(np.std(scales, ddof=1)), rel=1e-4, abs=1e-5) and profile.pitch.scale_sd > 0.0


def test_a_reading_too_short_to_judge_its_overall_expressiveness_does_not_count_towards_the_spread():
    readings = baseline_readings(6, pitch=True)
    reference = build_word_profile(readings, make_tokens(), max_gap_s=GAP_CAP_S, active_threshold_dbfs=ACTIVE_DBFS).pitch.scale_sd
    short = np.full(N_WORDS, np.nan)
    short[:6] = np.array(readings[0].pitch_movement_st2)[:6] * 0.04                         # measured on 6 words only, and nearly monotone there
    odd = build_word_profile(readings + [replace(readings[0], pitch_movement_st2=short)], make_tokens(), max_gap_s=GAP_CAP_S, active_threshold_dbfs=ACTIVE_DBFS)
    assert odd.pitch is not None and odd.pitch.scale_sd < max(0.3, 3 * reference)


def test_the_voiced_share_of_a_finding_is_that_of_its_own_words_not_of_the_whole_reading():
    obs = reading(600, pitch=True, flat=[FLAT])
    frames = np.full(N_WORDS, 20, dtype=np.int64)
    voiced = np.full(N_WORDS, 20, dtype=np.int64)
    voiced[29:48] = 5                                                                      # the flat stretch is mostly unvoiced, the rest of the reading fully voiced
    (run,) = detect_runs(replace(obs, pitch_frames=frames, pitch_voiced_frames=voiced), PROFILE, RULES).pitch
    inside = list(run.word_indices)
    assert run.voiced_fraction == pytest.approx(float(voiced[inside].sum()) / float(frames[inside].sum()))
    assert run.voiced_fraction < 0.5


def test_the_baseline_movement_in_hz_is_the_one_expected_of_this_speaker_at_their_own_range():
    expressive = 0.7                                                                      # a reserved speaker: everything moves 0.49 times as far as in the baseline
    obs = reading(604, pitch=True, expressive=expressive, flat=[FLAT])
    (run,) = detect_runs(obs, PROFILE, RULES).pitch
    inside = list(run.word_indices)
    tau = overall_movement(np.array(obs.pitch_movement_st2), np.array(PROFILE.pitch.movement_st2))
    adjusted = float(np.mean(np.array(PROFILE.pitch.movement_st2)[inside])) * math.exp(2.0 * tau)
    assert run.expected == pytest.approx(PITCH_REFERENCE_HZ * (2 ** (math.sqrt(adjusted) / 12) - 1))
    assert run.expected < PITCH_REFERENCE_HZ * (2 ** (math.sqrt(float(np.mean(np.array(PROFILE.pitch.movement_st2)[inside]))) / 12) - 1)


def test_a_word_the_baseline_has_no_expectation_for_is_not_used():
    cut = PROFILE.pitch.movement_st2[:]
    for i in (3, 4, 60):
        cut[i] = None
    profile = PROFILE.model_copy(update={"pitch": PROFILE.pitch.model_copy(update={"movement_st2": cut})})
    found = detect_runs(reading(611, pitch=True), profile, RULES)
    assert found.n_usable_pitch == N_WORDS - 3 and found.pitch == []


def test_pitch_needs_as_many_words_as_a_run_does_and_not_only_the_minimum_for_the_profile():
    short = reading(613, pitch=True, n=18)
    assert detect_runs(short, PROFILE, RULES).pitch == []                                  # 18 words: enough for a profile (16) and for a run (10)
    strict = DetectionConfig(run_min_words=20)
    found = detect_runs(short, PROFILE, strict)
    assert found.pitch is None and found.pitch_reason == "too_few_pitch_words" and found.n_usable_pitch == 18


def test_the_difference_in_hz_is_written_as_a_positive_number():
    _, (flaw,) = grounded(reading(600, pitch=True, flat=[FLAT]))
    ev = flaw.evidence
    assert build_fact_sheet(flaw)["delta_pitch_hz"] == f"{ev.f0_std_baseline_hz - ev.f0_std_hz_in_window:.1f}"


# ------------------------------------------------------------------------------------------------------------------------------
# Found with the first real recordings: the strict voicing decision left about 5 % of the frames, too few per word
# ------------------------------------------------------------------------------------------------------------------------------
def test_the_pitch_movement_uses_the_permissive_pitch_track_when_the_extractor_gave_one():
    strict = pitch_track()                                                                  # nothing passes the strict decision (as on real speech)
    permissive = pitch_track((0.0, 0.5, [UP, DOWN]))
    track = SimpleNamespace(times_s=strict.times_s, values_hz=strict.values_hz, voiced=strict.voiced,
                            track_values_hz=permissive.values_hz, track_voiced=permissive.voiced)
    aligned = words((0.0, 0.5))
    assert measure(strict, aligned).pitch_movement_st2 is None                              # too little voiced speech for a reference pitch
    long = pitch_track((0.0, 2.5, [UP, DOWN]))
    track = SimpleNamespace(times_s=strict.times_s, values_hz=strict.values_hz, voiced=strict.voiced,
                            track_values_hz=long.values_hz, track_voiced=long.voiced)
    measured = measure(track, words((0.0, 2.5))).pitch_movement_st2
    assert measured is not None and np.isfinite(measured[0]) and measured[0] > 0.0                  # measured from the permissive track although `voiced` is empty


def test_the_f0_extractor_gives_a_permissive_track_that_contains_the_strict_one():
    from app.services.features.f0 import F0Config, extract_f0

    sr = 16000
    t = np.arange(int(1.5 * sr)) / sr
    audio = (0.3 * np.sin(2 * np.pi * 180.0 * t) * (1 + 0.3 * np.sin(2 * np.pi * 3.0 * t))).astype(np.float32)
    result = extract_f0(audio)
    assert result.track_voiced is not None and result.track_values_hz is not None
    assert np.all(result.track_voiced[result.voiced]) and result.track_voiced.sum() >= result.voiced.sum()
    assert np.all(np.isfinite(result.track_values_hz[result.track_voiced])) and np.all(np.isnan(result.track_values_hz[~result.track_voiced]))
    assert extract_f0(audio, F0Config(track_prob_threshold=1.0)).track_voiced.sum() <= result.track_voiced.sum()
    with pytest.raises(ValueError, match="track_prob_threshold"):
        F0Config(track_prob_threshold=1.5)


def test_a_reading_that_is_flat_as_a_whole_is_not_also_reported_in_pieces():
    found = detect_runs(reading(605, pitch=True, expressive=0.3, flat=[(10, 25, 0.3)]), PROFILE, RULES)
    assert [r.kind for r in found.pitch] == ["pitch_overall"]
