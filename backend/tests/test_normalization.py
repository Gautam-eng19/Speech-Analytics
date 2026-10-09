"""Unit tests for baseline-relative feature normalization (TASK-041, DEC-010).

Covers:
- Exact z-scores for F0, energy, speech rate and pauses (direction and units)
- Missing stays missing: unvoiced F0, energy outside the baseline's frame rule, unknown pauses
- The energy frame rule is read from the baseline file, with explicit errors when absent
- Zero-variance / unusable baseline spread -> NaN + reason (no invented floor)
- Features not provided or skipped are reported, never treated as normal
- Provenance (passage id / sha256), baseline verification, invalid inputs
- Determinism and input immutability
"""
from __future__ import annotations

import math
from typing import List, Optional

import numpy as np
import pytest
from app.schemas.common import (
    AlignmentMethod,
    PauseBoundaryType,
    PauseDetectionSource,
)
from app.schemas.contracts import AlignedTranscript, AlignedWord, BaselineStatsRecord
from app.schemas.response import PauseEvent
from app.services.features.energy import EnergyConfig, EnergyExtractionResult
from app.services.features.f0 import F0Config, F0ExtractionResult
from app.services.features.rate import extract_rate
from app.services.grounding import (
    NormalizationError,
    NormalizedFeatureBundle,
    normalize_features,
    z_score,
)

W, C, U = PauseBoundaryType.WITHIN_PHRASE, PauseBoundaryType.CROSS_SENTENCE, PauseBoundaryType.UNKNOWN


def _baseline(**overrides) -> BaselineStatsRecord:
    data = dict(
        passage_id="p001",
        dataset_version="1.0.0",
        baseline_recording_ids=["rec_a"],
        f0_voiced_hz_mean=150.0,
        f0_voiced_hz_std=20.0,
        f0_voiced_hz_p05=120.0,
        f0_voiced_hz_p95=185.0,
        energy_db_mean=-25.0,
        energy_db_std=5.0,
        rate_wpm_mean=120.0,
        rate_wpm_std=20.0,
        pause_within_phrase_mean_s=0.4,
        pause_within_phrase_std_s=0.1,
        pause_cross_sentence_mean_s=0.9,
        pause_cross_sentence_std_s=0.2,
        n_f0_voiced_frames=100,
        n_energy_frames=100,
        n_rate_windows=5,
        n_pauses_within_phrase=3,
        n_pauses_cross_sentence=2,
        n_pauses_unknown_boundary=0,
        config_snapshot={"energy_frame_selection": "active", "energy_active_threshold_dbfs": -50.0},
        sha256="0" * 64,
    )
    data.update(overrides)
    return BaselineStatsRecord(**data).with_computed_sha256()


def _f0(values, voiced) -> F0ExtractionResult:
    n = len(values)
    return F0ExtractionResult(
        times_s=np.arange(n) * 0.01,
        values_hz=np.array(values, dtype=np.float64),
        voiced=np.array(voiced, dtype=bool),
        voiced_prob=np.ones(n),
        config=F0Config(),
    )


def _energy(values) -> EnergyExtractionResult:
    return EnergyExtractionResult(
        times_s=np.arange(len(values)) * 0.01, values_db=np.array(values, dtype=np.float64), config=EnergyConfig()
    )


def _rate(n_words: int = 40, period: float = 0.4):
    words = [
        AlignedWord(word=f"w{i}", start_s=i * period, end_s=i * period + 0.3, confidence=0.9) for i in range(n_words)
    ]
    transcript = AlignedTranscript(
        text=" ".join(w.word for w in words), words=words,
        alignment_method=AlignmentMethod.WHISPERX, total_coverage_pct=0.9,
    )
    return extract_rate(transcript)


def _pause(duration: float, kind: PauseBoundaryType) -> PauseEvent:
    return PauseEvent(
        start_s=1.0, end_s=1.0 + duration, duration_s=duration,
        detection_source=PauseDetectionSource.BOTH, boundary_type=kind,
    )


# -------------------------------------------------------------------- z_score
def test_z_score_basic_and_nan_passthrough():
    z = z_score(np.array([10.0, 12.0, np.nan, 8.0]), mean=10.0, std=2.0)
    assert z[0] == 0.0 and z[1] == 1.0 and z[3] == -1.0 and math.isnan(z[2])


@pytest.mark.parametrize("std", [0.0, -1.0, float("nan"), float("inf")])
def test_z_score_rejects_unusable_std(std):
    with pytest.raises(NormalizationError):
        z_score(np.array([1.0]), 0.0, std)


def test_z_score_rejects_non_finite_mean():
    with pytest.raises(NormalizationError):
        z_score(np.array([1.0]), float("nan"), 1.0)


# ------------------------------------------------------------------------ F0
def test_f0_z_scores_exact_with_unvoiced_as_nan():
    res = normalize_features(_baseline(), f0=_f0([150.0, 170.0, 130.0, 999.0, 190.0], [1, 1, 1, 0, 1]))
    assert res.f0_z[:3].tolist() == [0.0, 1.0, -1.0]
    assert math.isnan(res.f0_z[3])                      # unvoiced stays missing, never 0 or 999-derived
    assert res.f0_z[4] == 2.0
    assert np.array_equal(res.f0_times_s, np.arange(5) * 0.01)
    assert "f0" not in res.unavailable


def test_f0_voiced_flag_and_finite_value_are_both_required():
    res = normalize_features(_baseline(), f0=_f0([150.0, np.nan, 170.0], [1, 1, 0]))
    assert res.f0_z[0] == 0.0 and math.isnan(res.f0_z[1]) and math.isnan(res.f0_z[2])


def test_higher_pitch_gives_positive_z_and_lower_gives_negative():
    res = normalize_features(_baseline(), f0=_f0([200.0, 100.0], [1, 1]))
    assert res.f0_z[0] > 0 > res.f0_z[1]


# -------------------------------------------------------------------- energy
def test_energy_active_rule_masks_frames_below_threshold():
    res = normalize_features(_baseline(), energy=_energy([-25.0, -20.0, -30.0, -60.0, -50.0]))
    assert res.energy_in_baseline_rule.tolist() == [True, True, True, False, True]  # -50 is inclusive
    assert res.energy_z[:3].tolist() == [0.0, 1.0, -1.0]
    assert math.isnan(res.energy_z[3])                  # pause frame is not scored as "low energy"
    assert res.energy_z[4] == -5.0


def test_energy_all_selection_scores_every_frame():
    base = _baseline(config_snapshot={"energy_frame_selection": "all"})
    res = normalize_features(base, energy=_energy([-25.0, -60.0]))
    assert res.energy_in_baseline_rule.tolist() == [True, True]
    assert res.energy_z.tolist() == [0.0, -7.0]


def test_energy_threshold_comes_from_the_baseline_file():
    base = _baseline(config_snapshot={"energy_frame_selection": "active", "energy_active_threshold_dbfs": -30.0})
    res = normalize_features(base, energy=_energy([-25.0, -35.0]))
    assert res.energy_in_baseline_rule.tolist() == [True, False]


@pytest.mark.parametrize(
    "snapshot",
    [
        {},
        {"energy_frame_selection": "loud"},
        {"energy_frame_selection": "active"},
        {"energy_frame_selection": "active", "energy_active_threshold_dbfs": True},
        {"energy_frame_selection": "active", "energy_active_threshold_dbfs": "-50"},
    ],
)
def test_missing_or_invalid_energy_rule_is_an_explicit_error(snapshot):
    base = _baseline(config_snapshot=snapshot)
    with pytest.raises(NormalizationError):
        normalize_features(base, energy=_energy([-25.0]))
    # The rule is only needed when energy is normalized.
    assert normalize_features(base, f0=_f0([150.0], [1])).f0_z[0] == 0.0


# ---------------------------------------------------------------------- rate
def test_rate_z_scores_use_baseline_stats_and_keep_window_bounds():
    rate = _rate()
    res = normalize_features(_baseline(), rate=rate)
    expected = (rate.words_per_min - 120.0) / 20.0
    assert np.array_equal(res.rate_z, expected)
    assert np.array_equal(res.rate_times_s, rate.times_s)
    assert np.array_equal(res.rate_window_start_s, rate.window_start_s)
    assert np.array_equal(res.rate_window_end_s, rate.window_end_s)
    assert res.rate_z.max() > 0  # ~150 wpm vs 120 baseline: faster => positive z


def test_skipped_rate_is_reported_not_normalized():
    res = normalize_features(_baseline(), rate=_rate(n_words=6))
    assert len(res.rate_z) == 0
    assert res.unavailable["rate"].startswith("rate_analysis_skipped")


# --------------------------------------------------------------------- pauses
def test_pause_z_scores_by_boundary_type():
    events = [_pause(0.6, W), _pause(1.3, C), _pause(0.3, W)]
    res = normalize_features(_baseline(), pauses=events)
    assert [p.event for p in res.pauses] == events                       # order preserved
    assert res.pauses[0].z_score == pytest.approx(2.0)                   # (0.6-0.4)/0.1
    assert res.pauses[1].z_score == pytest.approx(2.0)                   # (1.3-0.9)/0.2
    assert res.pauses[2].z_score == pytest.approx(-1.0)
    assert (res.pauses[1].baseline_mean_s, res.pauses[1].baseline_std_s) == (0.9, 0.2)
    assert all(p.note is None for p in res.pauses)


def test_unknown_boundary_pause_has_no_z_score():
    res = normalize_features(_baseline(), pauses=[_pause(0.5, U)])
    p = res.pauses[0]
    assert math.isnan(p.z_score) and math.isnan(p.baseline_mean_s) and math.isnan(p.baseline_std_s)
    assert p.note.startswith("unknown_boundary_type")


def test_cross_sentence_without_baseline_std_is_nan_not_zero():
    base = _baseline(pause_cross_sentence_std_s=None)
    res = normalize_features(base, pauses=[_pause(1.3, C), _pause(0.6, W)])
    cross, within = res.pauses
    assert math.isnan(cross.z_score) and cross.note == "baseline_cross_sentence_std_unavailable"
    assert cross.baseline_mean_s == 0.9 and math.isnan(cross.baseline_std_s)
    assert within.z_score == pytest.approx(2.0)                          # other types unaffected


def test_empty_pause_list_is_valid():
    res = normalize_features(_baseline(), pauses=[])
    assert res.pauses == [] and "pauses" not in res.unavailable


# --------------------------------------------------------------- zero variance
def test_zero_baseline_std_makes_feature_undefined_with_reason():
    base = _baseline(
        f0_voiced_hz_std=0.0, energy_db_std=0.0, rate_wpm_std=0.0,
        pause_within_phrase_std_s=0.0, pause_cross_sentence_std_s=0.0,
    )
    res = normalize_features(
        base, f0=_f0([150.0, 160.0], [1, 1]), energy=_energy([-25.0, -20.0]),
        rate=_rate(), pauses=[_pause(0.5, W), _pause(1.0, C)],
    )
    assert np.all(np.isnan(res.f0_z)) and len(res.f0_z) == 2
    assert np.all(np.isnan(res.energy_z)) and len(res.energy_z) == 2
    assert res.energy_in_baseline_rule.tolist() == [True, True]
    assert np.all(np.isnan(res.rate_z)) and len(res.rate_z) > 0
    assert all(math.isnan(p.z_score) and p.note for p in res.pauses)
    for name in ("f0", "energy", "rate"):
        assert res.unavailable[name] == "baseline_std_not_positive"


# --------------------------------------------------------- not provided / empty
def test_unprovided_features_are_reported():
    res = normalize_features(_baseline())
    assert res.unavailable == {
        "f0": "not_provided", "energy": "not_provided", "rate": "not_provided", "pauses": "not_provided",
    }
    assert len(res.f0_z) == len(res.energy_z) == len(res.rate_z) == 0 and res.pauses == []


def test_provenance_is_carried_through():
    base = _baseline()
    res = normalize_features(base, f0=_f0([150.0], [1]))
    assert isinstance(res, NormalizedFeatureBundle)
    assert res.baseline_passage_id == "p001" and res.baseline_sha256 == base.sha256


# ---------------------------------------------------------------- invalid input
def test_unverified_baseline_is_rejected():
    stale = _baseline().model_copy(update={"energy_db_mean": -10.0})
    with pytest.raises(NormalizationError, match="sha256"):
        normalize_features(stale, f0=_f0([150.0], [1]))


@pytest.mark.parametrize("bad", [None, {}, "p001", object()])
def test_non_record_baseline_rejected(bad):
    with pytest.raises(TypeError):
        normalize_features(bad)


def test_malformed_arrays_rejected():
    bad_f0 = F0ExtractionResult(
        times_s=np.zeros(3), values_hz=np.zeros(2), voiced=np.zeros(3, dtype=bool),
        voiced_prob=np.zeros(3), config=F0Config(),
    )
    with pytest.raises(NormalizationError):
        normalize_features(_baseline(), f0=bad_f0)
    bad_energy = EnergyExtractionResult(times_s=np.zeros(3), values_db=np.zeros(2), config=EnergyConfig())
    with pytest.raises(NormalizationError):
        normalize_features(_baseline(), energy=bad_energy)


# ----------------------------------------------------------------- determinism
def test_deterministic_and_inputs_not_mutated():
    base = _baseline()
    f0 = _f0([150.0, 160.0, np.nan], [1, 1, 0])
    energy = _energy([-25.0, -60.0, -20.0])
    rate = _rate()
    before = (f0.values_hz.copy(), energy.values_db.copy(), rate.words_per_min.copy())

    a = normalize_features(base, f0=f0, energy=energy, rate=rate, pauses=[_pause(0.5, W)])
    b = normalize_features(base, f0=f0, energy=energy, rate=rate, pauses=[_pause(0.5, W)])

    for name in ("f0_z", "energy_z", "rate_z"):
        assert np.array_equal(getattr(a, name), getattr(b, name), equal_nan=True)
    assert [p.z_score for p in a.pauses] == [p.z_score for p in b.pauses]
    assert np.array_equal(f0.values_hz, before[0], equal_nan=True)
    assert np.array_equal(energy.values_db, before[1])
    assert np.array_equal(rate.words_per_min, before[2])
    # Output arrays are copies, not views of the inputs.
    a.f0_times_s[:] = -1.0
    assert f0.times_s[0] == 0.0
