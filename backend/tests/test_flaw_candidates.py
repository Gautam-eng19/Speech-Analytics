"""Unit tests for flaw candidate generation, duration filtering and merging (TASK-050/051).

Covers:
- Detection rules and directions for every supported P0 type (strict thresholds)
- Intervals (rate spans, energy run edges, pause events) in seconds
- NaN z-scores (pauses, unvoiced, uncovered frames) never flagged and break runs
- Minimum-duration filter (inclusive, per type) and merge gap (strict '<'), pauses never merged
- Skipped/unavailable reporting, determinism, immutability, invalid configuration
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence

import numpy as np
import pytest
from app.schemas.common import FlawType, PauseBoundaryType, PauseDetectionSource
from app.schemas.response import PauseEvent
from app.services.grounding import (
    DetectionConfig,
    FlawCandidate,
    NormalizedFeatureBundle,
    detect_candidates,
    merge_candidates,
)
from app.services.grounding.normalizer import NormalizedPause

HOP = 0.01
W, C, U = PauseBoundaryType.WITHIN_PHRASE, PauseBoundaryType.CROSS_SENTENCE, PauseBoundaryType.UNKNOWN


def _bundle(**kwargs) -> NormalizedFeatureBundle:
    return NormalizedFeatureBundle(baseline_passage_id="p001", baseline_sha256="a" * 64, **kwargs)


def _rate_bundle(z: Sequence[float], starts: Sequence[float], ends: Sequence[float]) -> NormalizedFeatureBundle:
    starts_a, ends_a = np.array(starts, dtype=float), np.array(ends, dtype=float)
    return _bundle(
        rate_z=np.array(z, dtype=float),
        rate_times_s=(starts_a + ends_a) / 2.0,
        rate_effective_duration_s=ends_a - starts_a,
        rate_window_start_s=starts_a,
        rate_window_end_s=ends_a,
        rate_word_count=np.full(len(z), 8, dtype=np.int64),
    )


def _energy_bundle(z: Sequence[float]) -> NormalizedFeatureBundle:
    z_a = np.array(z, dtype=float)
    return _bundle(
        energy_z=z_a, energy_times_s=np.arange(len(z_a)) * HOP,
        energy_in_baseline_rule=~np.isnan(z_a), energy_hop_s=HOP,
    )


def _inside_recording(z: Sequence[float], frames: int = 5) -> List[float]:
    """`z` surrounded by normal-range covered frames, so no run touches the (clipped) edges of the recording."""
    return [0.0] * frames + list(z) + [0.0] * frames


def _pause(start: float, end: float, kind: PauseBoundaryType, z: float) -> NormalizedPause:
    ev = PauseEvent(
        start_s=start, end_s=end, duration_s=end - start,
        detection_source=PauseDetectionSource.BOTH, boundary_type=kind,
    )
    return NormalizedPause(ev, z, 0.4, 0.1)


def _types(result) -> List[str]:
    return [c.type.value for c in result.candidates]


# ----------------------------------------------------------------------- rate
def test_rate_fast_and_slow_use_symmetric_strict_thresholds():
    nb = _rate_bundle([0.0, 2.5, 2.0, -2.0, -2.5], [0, 4, 8, 12, 16], [8, 12, 16, 20, 24])
    result = detect_candidates(nb)
    by_type = {c.type: c for c in result.candidates}
    assert set(by_type) == {FlawType.TOO_FAST, FlawType.TOO_SLOW}     # z == +/-2.0 not flagged
    fast, slow = by_type[FlawType.TOO_FAST], by_type[FlawType.TOO_SLOW]
    assert (fast.start_s, fast.end_s) == (4.0, 12.0) and fast.member_indices == (1,)
    assert (slow.start_s, slow.end_s) == (16.0, 24.0) and slow.member_indices == (4,)
    assert fast.peak_z == 2.5 and fast.mean_z == 2.5 and fast.detection_feature == "rate_z"
    assert slow.peak_z == 2.5 and slow.mean_z == -2.5


def test_overlapping_flagged_rate_windows_merge_into_one_interval():
    nb = _rate_bundle([3.0, 2.2, 0.0], [0, 4, 8], [8, 12, 16])   # windows overlap by 4 s
    (cand,) = detect_candidates(nb).candidates
    assert cand.type == FlawType.TOO_FAST
    assert (cand.start_s, cand.end_s) == (0.0, 12.0)
    assert cand.member_indices == (0, 1)
    assert cand.peak_z == 3.0 and cand.mean_z == pytest.approx(2.6)


def test_rate_window_shorter_than_minimum_is_dropped():
    nb = _rate_bundle([5.0], [1.0], [1.4])                        # 0.4 s span < 0.5 s
    assert detect_candidates(nb).candidates == []
    nb = _rate_bundle([5.0], [1.0], [1.5])                        # exactly 0.5 s is kept (inclusive)
    assert len(detect_candidates(nb).candidates) == 1


def test_nan_rate_z_never_flagged():
    nb = _rate_bundle([np.nan, np.nan], [0, 4], [8, 12])
    assert detect_candidates(nb).candidates == []


# --------------------------------------------------------------------- energy
def test_energy_low_and_high_runs_with_interval_edges():
    z = [0.0] * 10 + [-3.0] * 60 + [0.0] * 10 + [3.0] * 60 + [0.0] * 10
    result = detect_candidates(_energy_bundle(z))
    low = next(c for c in result.candidates if c.type == FlawType.LOW_ENERGY)
    high = next(c for c in result.candidates if c.type == FlawType.HIGH_ENERGY)
    assert low.start_s == pytest.approx(10 * HOP - HOP / 2) and low.end_s == pytest.approx(69 * HOP + HOP / 2)
    assert low.member_indices == tuple(range(10, 70)) and low.mean_z == -3.0 and low.peak_z == 3.0
    assert high.start_s == pytest.approx(80 * HOP - HOP / 2) and high.end_s == pytest.approx(139 * HOP + HOP / 2)


def test_energy_threshold_is_strict():
    assert detect_candidates(_energy_bundle([-2.0] * 100)).candidates == []
    assert detect_candidates(_energy_bundle([2.0] * 100)).candidates == []
    assert len(detect_candidates(_energy_bundle([-2.01] * 100)).candidates) == 1


def test_energy_min_duration_is_inclusive_and_short_runs_dropped():
    assert detect_candidates(_energy_bundle([0.0] * 5 + [-3.0] * 49 + [0.0] * 5)).candidates == []   # 0.49 s
    kept = detect_candidates(_energy_bundle([0.0] * 5 + [-3.0] * 50 + [0.0] * 5)).candidates          # 0.50 s
    assert len(kept) == 1 and kept[0].duration_s == pytest.approx(0.5)


def test_uncovered_stretch_boundary_is_robust_to_float_rounding():
    # Frames 6-65 flagged, 50 uncovered frames (66-115), frames 116-175 flagged. The raw float
    # difference times[116] - times[65] - hop is 0.4999999999999999, yet this is exactly 0.50 s of
    # uncovered time and must split the run like any other 0.50 s gap.
    z = [np.nan] * 6 + [-9.0] * 60 + [np.nan] * 50 + [-9.0] * 60
    assert len(z) == 176
    assert len(detect_candidates(_energy_bundle(z)).candidates) == 2


def test_sustained_quiet_speech_with_word_gaps_is_detected_as_one_flaw():
    # 8 quiet 'words' (0.4 s of z = -9) separated by 0.1 s of uncovered frames (NaN): each word alone is
    # shorter than the 0.5 s minimum, but uncovered frames bridge them into one run of 3.2 s flagged time.
    word, gap = [-9.0] * 40, [np.nan] * 10
    z = []
    for i in range(8):
        z += word + (gap if i < 7 else [])
    z = _inside_recording(z)                                          # keep the run away from the clipped recording edges
    (cand,) = detect_candidates(_energy_bundle(z)).candidates
    assert cand.type == FlawType.LOW_ENERGY
    assert cand.flagged_duration_s == pytest.approx(3.2)
    assert cand.duration_s == pytest.approx(3.9)                     # span includes the 7 gaps
    assert len(cand.flagged_intervals) == 8 and cand.member_indices == tuple(i for i in range(len(z)) if z[i] == -9.0)


def test_low_energy_blips_cannot_chain_through_normal_range_frames():
    # Brief dips (0.2 s) separated by NORMAL covered frames never accumulate into a flaw, however many.
    blip, normal = [-3.0] * 20, [0.0] * 30
    z = (blip + normal) * 10 + blip                                   # 2.2 s of dips in 8.2 s
    assert detect_candidates(_energy_bundle(z)).candidates == []


def test_minimum_duration_counts_flagged_time_not_span():
    # Two 0.2 s dips bridged by 0.4 s of uncovered frames: span 0.8 s but only 0.4 s flagged -> rejected.
    blip, gap = [-3.0] * 20, [np.nan] * 40
    assert detect_candidates(_energy_bundle(_inside_recording(blip + gap + blip))).candidates == []
    # Three such dips reach 0.6 s of flagged time -> kept, with the span (1.4 s) larger than flagged time.
    three = _inside_recording(blip + gap + blip + gap + blip)
    (cand,) = detect_candidates(_energy_bundle(three)).candidates
    assert cand.flagged_duration_s == pytest.approx(0.6) and cand.duration_s == pytest.approx(1.4)
    # A stricter configured minimum rejects it.
    cfg = DetectionConfig(min_duration_s={FlawType.LOW_ENERGY: 0.7})
    assert detect_candidates(_energy_bundle(three), cfg).candidates == []


def test_uncovered_stretch_of_merge_gap_or_more_splits_the_run():
    word = [-9.0] * 60
    short = word + [np.nan] * 49 + word                               # 0.49 s uncovered: one run
    long = word + [np.nan] * 50 + word                                # 0.50 s uncovered: two runs
    assert len(detect_candidates(_energy_bundle(short)).candidates) == 1
    assert len(detect_candidates(_energy_bundle(long)).candidates) == 2


def test_flagged_intervals_are_disjoint_and_sorted_for_overlapping_rate_windows():
    nb = _rate_bundle([3.0, 2.2, 5.0], [0, 4, 20], [8, 12, 28])
    cands = detect_candidates(nb).candidates
    first = cands[0]
    assert first.flagged_intervals == ((0.0, 12.0),) and first.flagged_duration_s == 12.0   # union, not 16
    assert cands[1].flagged_intervals == ((20.0, 28.0),)


def test_nan_frames_break_runs_and_are_never_low_energy():
    # A pause (NaN z) between two low-energy runs: the pause itself is not "low energy".
    z = [-3.0] * 60 + [np.nan] * 100 + [-3.0] * 60
    result = detect_candidates(_energy_bundle(z))
    lows = [c for c in result.candidates if c.type == FlawType.LOW_ENERGY]
    assert len(lows) == 2
    assert lows[0].end_s < 60 * HOP + HOP and lows[1].start_s > 159 * HOP
    assert all(not any(np.isnan(np.array(z)[list(c.member_indices)])) for c in lows)


def test_energy_runs_with_small_gaps_merge_and_large_gaps_do_not():
    z_close = [-3.0] * 60 + [0.0] * 30 + [-3.0] * 60      # 0.30 s gap < 0.5 -> one flaw
    (merged,) = detect_candidates(_energy_bundle(z_close)).candidates
    assert merged.member_indices == tuple(range(0, 60)) + tuple(range(90, 150))
    # The run touches both ends of the recording, so it is clipped to the span of the frame centres (never negative).
    assert merged.start_s == 0.0 and merged.end_s == pytest.approx(149 * HOP)

    z_far = [-3.0] * 60 + [0.0] * 60 + [-3.0] * 60        # 0.60 s gap -> two flaws
    assert len(detect_candidates(_energy_bundle(z_far)).candidates) == 2


def test_energy_runs_at_the_recording_edges_are_clipped_to_the_audio():
    """Frames are centred (first centre 0, last centre = end of audio); a run must never reach outside the recording."""
    (high,) = detect_candidates(_energy_bundle([3.0] * 100 + [0.0] * 100)).candidates      # starts on the first frame
    assert high.type == FlawType.HIGH_ENERGY
    assert high.start_s == 0.0 and high.end_s == pytest.approx(99 * HOP + HOP / 2)

    (low,) = detect_candidates(_energy_bundle([0.0] * 100 + [-3.0] * 100)).candidates      # ends on the last frame
    assert low.start_s == pytest.approx(100 * HOP - HOP / 2) and low.end_s == pytest.approx(199 * HOP)

    (whole,) = detect_candidates(_energy_bundle([3.0] * 200)).candidates                   # the entire recording
    assert whole.start_s == 0.0 and whole.end_s == pytest.approx(199 * HOP)
    assert whole.flagged_intervals == ((0.0, pytest.approx(199 * HOP)),)
    assert whole.flagged_duration_s == pytest.approx(199 * HOP)


def test_a_one_frame_timeline_has_no_extent_to_flag():
    nb = _energy_bundle([3.0])
    cfg = DetectionConfig(min_duration_s={FlawType.HIGH_ENERGY: 0.0})                       # no minimum: only the clipping decides
    assert detect_candidates(nb, cfg).candidates == []


def test_merge_gap_is_strictly_less_than():
    z = [-3.0] * 60 + [0.0] * 50 + [-3.0] * 60            # gap = 0.50 s exactly -> NOT merged
    assert len(detect_candidates(_energy_bundle(z)).candidates) == 2
    z = [-3.0] * 60 + [0.0] * 49 + [-3.0] * 60            # gap = 0.49 s -> merged
    assert len(detect_candidates(_energy_bundle(z)).candidates) == 1


def test_energy_without_hop_is_reported_as_skipped():
    nb = _energy_bundle([-3.0] * 100)
    nb.energy_hop_s = None
    result = detect_candidates(nb)
    assert result.candidates == [] and result.skipped["low_energy"] == "energy frame hop unknown"


# ---------------------------------------------------------------------- pauses
def test_pause_thresholds_are_type_specific_and_strict():
    nb = _bundle(pauses=[
        _pause(1.0, 1.6, W, 2.5),      # within: > 2.0 -> flagged
        _pause(3.0, 3.6, W, 2.0),      # exactly the threshold -> not flagged
        _pause(5.0, 5.9, C, 2.4),      # cross: needs > 2.5 -> not flagged
        _pause(7.0, 8.2, C, 2.6),      # flagged
        _pause(9.0, 9.9, U, 99.0),     # unknown boundary -> never flagged
        _pause(11.0, 12.0, W, float("nan")),   # undefined z -> never flagged
    ])
    cands = detect_candidates(nb, DetectionConfig(min_duration_s={FlawType.EXCESSIVE_PAUSE: 0.0})).candidates      # only the z rule is under test here
    assert [(c.start_s, c.end_s) for c in cands] == [(1.0, 1.6), (7.0, 8.2)]
    assert all(c.type == FlawType.EXCESSIVE_PAUSE and c.detection_feature == "pause_z" for c in cands)
    assert cands[0].member_indices == (0,) and cands[1].member_indices == (3,) and cands[1].peak_z == 2.6


def test_nearby_excessive_pauses_stay_separate_evidence():
    nb = _bundle(pauses=[_pause(1.0, 2.3, W, 4.0), _pause(2.4, 3.7, W, 5.0)])   # 0.1 s apart
    assert len(detect_candidates(nb).candidates) == 2


def test_pause_minimum_duration_is_configurable_and_a_breath_is_not_an_excessive_pause_by_default():
    nb = _bundle(pauses=[_pause(1.0, 1.3, W, 40.0), _pause(3.0, 4.19, W, 40.0), _pause(5.0, 6.2, W, 40.0)])       # z of 40: very regular baseline
    assert [(c.start_s, c.end_s) for c in detect_candidates(nb).candidates] == [(5.0, 6.2)]                # default floor 1.2 s: only the 1.2 s pause counts
    assert DetectionConfig().min_duration_s[FlawType.EXCESSIVE_PAUSE] == 1.2
    none = DetectionConfig(min_duration_s={FlawType.EXCESSIVE_PAUSE: 0.0})
    assert len(detect_candidates(nb, none).candidates) == 3
    strict = DetectionConfig(min_duration_s={FlawType.EXCESSIVE_PAUSE: 1.5})
    assert detect_candidates(nb, strict).candidates == []


# ---------------------------------------------------------- skipped reporting
def test_unsupported_and_unavailable_types_are_reported_not_silent():
    result = detect_candidates(_bundle(unavailable={"rate": "not_provided", "pauses": "not_provided"}))
    assert result.candidates == []
    assert result.skipped["too_fast"] == "rate unavailable: not_provided"
    assert result.skipped["too_slow"] == "rate unavailable: not_provided"
    assert result.skipped["excessive_pause"] == "pauses unavailable: not_provided"
    assert "word by word" in result.skipped["flat_pitch"]                      # judged only against the baseline's reading of the same words (DEC-042)
    assert "not implemented" in result.skipped["pitch_instability"] and "P1" in result.skipped["reduced_clarity"]
    assert "low_energy" not in result.skipped                                  # energy not flagged unavailable here


def test_empty_bundle_gives_no_candidates():
    assert detect_candidates(_bundle()).candidates == []


# -------------------------------------------------------- ordering/determinism
def test_candidates_sorted_deterministically_and_inputs_untouched():
    z = [-3.0] * 60 + [0.0] * 100 + [3.0] * 60
    nb = _energy_bundle(z)
    nb.rate_z = np.array([3.0]); nb.rate_times_s = np.array([0.5])
    nb.rate_effective_duration_s = np.array([1.0]); nb.rate_word_count = np.array([8])
    nb.pauses = [_pause(0.2, 1.5, W, 9.0)]
    before = (nb.energy_z.copy(), nb.rate_z.copy())
    a = detect_candidates(nb)
    b = detect_candidates(nb)
    assert a.candidates == b.candidates
    keys = [(c.start_s, c.end_s, c.type.value) for c in a.candidates]
    assert keys == sorted(keys)
    assert np.array_equal(nb.energy_z, before[0]) and np.array_equal(nb.rate_z, before[1])


# ------------------------------------------------------------ merge helper/api
def test_merge_candidates_unions_samples_and_recomputes_statistics():
    z = np.array([3.0, 1.0, 5.0])
    a = FlawCandidate(FlawType.TOO_FAST, 0.0, 2.0, 3.0, 3.0, "rate_z", (0,), ((0.0, 2.0),))
    b = FlawCandidate(FlawType.TOO_FAST, 2.3, 4.0, 5.0, 5.0, "rate_z", (2,), ((2.3, 4.0),))
    other = FlawCandidate(FlawType.TOO_SLOW, 0.0, 2.0, 3.0, -3.0, "rate_z", (0,), ((0.0, 2.0),))
    merged = merge_candidates([b, a, other], {"rate_z": z}, merge_gap_s=0.5)
    fast = next(c for c in merged if c.type == FlawType.TOO_FAST)
    assert (fast.start_s, fast.end_s, fast.member_indices) == (0.0, 4.0, (0, 2))
    assert fast.peak_z == 5.0 and fast.mean_z == 4.0
    assert fast.flagged_intervals == ((0.0, 2.0), (2.3, 4.0))
    assert fast.flagged_duration_s == pytest.approx(3.7) and fast.duration_s == pytest.approx(4.0)
    assert len(merged) == 2                                                    # different types never merge


def test_merge_candidates_gap_boundary_is_strict():
    z = np.zeros(4)
    a = FlawCandidate(FlawType.TOO_SLOW, 0.0, 2.0, 1.0, -1.0, "rate_z", (0,), ((0.0, 2.0),))
    exactly = FlawCandidate(FlawType.TOO_SLOW, 2.5, 4.0, 1.0, -1.0, "rate_z", (1,), ((2.5, 4.0),))   # gap == 0.5
    just_under = FlawCandidate(FlawType.TOO_SLOW, 2.49, 4.0, 1.0, -1.0, "rate_z", (2,), ((2.49, 4.0),))
    overlapping = FlawCandidate(FlawType.TOO_SLOW, 1.5, 3.0, 1.0, -1.0, "rate_z", (3,), ((1.5, 3.0),))
    zmap = {"rate_z": z}
    assert len(merge_candidates([a, exactly], zmap, 0.5)) == 2
    assert len(merge_candidates([a, just_under], zmap, 0.5)) == 1
    assert len(merge_candidates([a, overlapping], zmap, 0.5)) == 1
    assert len(merge_candidates([a, overlapping], zmap, 0.0)) == 1           # overlap merges even with no gap tolerance
    assert len(merge_candidates([], zmap, 0.5)) == 0


def test_wrong_input_type_rejected():
    with pytest.raises(TypeError):
        detect_candidates({"rate_z": []})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"z_rate_fast": 0.0}, {"z_rate_slow": -1.0}, {"z_energy": float("nan")},
        {"z_pause_within": float("inf")}, {"z_pause_cross": 0.0},
        {"merge_gap_s": -0.1}, {"merge_gap_s": float("nan")},
        {"min_duration_s": {FlawType.TOO_FAST: -1.0}},
        {"min_duration_s": {"bogus_type": 0.5}},
    ],
)
def test_invalid_detection_config_rejected(kwargs):
    with pytest.raises(ValueError):
        DetectionConfig(**kwargs)


def test_min_duration_accepts_flaw_type_value_strings():
    cfg = DetectionConfig(min_duration_s={"too_fast": 9.0})     # FlawType is a str enum: same key
    assert cfg.min_duration_s[FlawType.TOO_FAST] == 9.0
    assert cfg.min_duration_s[FlawType.TOO_SLOW] == DetectionConfig().min_duration_s[FlawType.TOO_SLOW]
    assert detect_candidates(_rate_bundle([5.0], [0], [8]), cfg).candidates == []


def test_custom_thresholds_change_detection():
    nb = _rate_bundle([2.5], [0], [8])
    assert len(detect_candidates(nb).candidates) == 1
    assert detect_candidates(nb, DetectionConfig(z_rate_fast=3.0)).candidates == []
