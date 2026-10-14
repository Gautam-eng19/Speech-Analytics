"""Unit tests for flaw severity.

Covers:
- Exact magnitude / duration / product values and every clipping boundary
- Direction independence (|z|), flagged time (not span), pause exemption from the duration component
- Properties over a grid: bounded in [0, 1], monotone non-decreasing in |z| and in flagged duration
- Rounding, determinism, invalid candidates and invalid configuration
- Behaviour on real detector output
"""
from __future__ import annotations

import itertools
import math

import numpy as np
import pytest
from app.schemas.common import FlawType
from app.services.grounding import (
    DetectionConfig,
    FlawCandidate,
    NormalizedFeatureBundle,
    SeverityConfig,
    compute_severity,
    detect_candidates,
    severity_components,
)


def _cand(ftype: FlawType = FlawType.TOO_FAST, mean_z: float = 3.0, flagged_s: float = 5.0, span_s: float = None):
    span = flagged_s if span_s is None else span_s
    return FlawCandidate(
        type=ftype, start_s=1.0, end_s=1.0 + span, peak_z=abs(mean_z), mean_z=mean_z,
        detection_feature="rate_z", member_indices=(0,), flagged_intervals=((1.0, 1.0 + flagged_s),),
    )


# ------------------------------------------------------------------ magnitude
@pytest.mark.parametrize(
    "z,expected",
    [(0.0, 0.0), (0.5, 0.0), (1.0, 0.0), (1.75, 0.25), (2.5, 0.5), (3.25, 0.75), (4.0, 1.0), (4.5, 1.0), (35.8, 1.0)],
)
def test_magnitude_is_linear_between_z_min_and_z_severe_and_clipped(z, expected):
    magnitude, duration = severity_components(_cand(mean_z=z, flagged_s=5.0))
    assert magnitude == pytest.approx(expected)
    assert duration == 1.0


@pytest.mark.parametrize("z", [1.5, 2.2, 3.9, 7.0])
def test_direction_does_not_change_severity(z):
    assert compute_severity(_cand(mean_z=z)) == compute_severity(_cand(mean_z=-z))


# ------------------------------------------------------------------- duration
@pytest.mark.parametrize(
    "flagged,expected", [(0.0, 0.0), (1.0, 0.2), (2.5, 0.5), (5.0, 1.0), (12.0, 1.0)]
)
def test_duration_component_is_linear_to_the_reference_and_clipped(flagged, expected):
    magnitude, duration = severity_components(_cand(mean_z=10.0, flagged_s=flagged))
    assert magnitude == 1.0
    assert duration == pytest.approx(expected)


def test_severity_is_the_product_of_both_components():
    assert compute_severity(_cand(mean_z=2.5, flagged_s=2.5)) == pytest.approx(0.25)
    assert compute_severity(_cand(mean_z=4.0, flagged_s=5.0)) == 1.0
    assert compute_severity(_cand(mean_z=0.9, flagged_s=5.0)) == 0.0          # below z_min: nothing
    assert compute_severity(_cand(mean_z=10.0, flagged_s=0.0)) == 0.0         # no flagged time: nothing


def test_flagged_time_counts_not_the_span():
    sparse = FlawCandidate(
        FlawType.LOW_ENERGY, 0.0, 4.0, 9.0, -9.0, "energy_z", (0, 1), ((0.0, 0.5), (3.5, 4.0)),
    )
    assert sparse.duration_s == 4.0 and sparse.flagged_duration_s == pytest.approx(1.0)
    assert severity_components(sparse)[1] == pytest.approx(0.2)               # 1.0 / 5.0, not 4.0 / 5.0


def test_excessive_pause_has_no_duration_component():
    short = _cand(FlawType.EXCESSIVE_PAUSE, mean_z=2.5, flagged_s=0.6)
    long = _cand(FlawType.EXCESSIVE_PAUSE, mean_z=2.5, flagged_s=3.0)
    assert severity_components(short) == (pytest.approx(0.5), 1.0)
    assert compute_severity(short) == compute_severity(long) == pytest.approx(0.5)
    # A 16-sigma pause is fully severe even though it is only 1.5 s long.
    assert compute_severity(_cand(FlawType.EXCESSIVE_PAUSE, mean_z=16.3, flagged_s=1.5)) == 1.0


@pytest.mark.parametrize("ftype", [t for t in FlawType if t != FlawType.EXCESSIVE_PAUSE])
def test_every_other_type_uses_the_duration_component(ftype):
    assert severity_components(_cand(ftype, mean_z=10.0, flagged_s=2.5))[1] == pytest.approx(0.5)


# ----------------------------------------------------------------- properties
def test_bounded_and_monotone_over_a_grid():
    zs = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 10.0, 50.0]
    durations = [0.0, 0.25, 0.5, 1.0, 2.0, 3.5, 5.0, 8.0, 30.0]
    for ftype in FlawType:
        grid = {(z, d): compute_severity(_cand(ftype, mean_z=z, flagged_s=d)) for z, d in itertools.product(zs, durations)}
        assert all(0.0 <= v <= 1.0 for v in grid.values())
        for d in durations:
            column = [grid[(z, d)] for z in zs]
            assert column == sorted(column), f"{ftype.value}: not monotone in |z| at duration {d}"
        for z in zs:
            row = [grid[(z, d)] for d in durations]
            assert row == sorted(row), f"{ftype.value}: not monotone in duration at z {z}"


# ------------------------------------------------------------------- rounding
def test_result_is_rounded_to_the_configured_decimals():
    z = 2.0                                                                  # magnitude 1/3
    assert compute_severity(_cand(mean_z=z)) == 0.3333
    assert compute_severity(_cand(mean_z=z), SeverityConfig(decimals=2)) == 0.33
    assert compute_severity(_cand(mean_z=z), SeverityConfig(decimals=6)) == 0.333333


def test_deterministic():
    cand = _cand(mean_z=2.718, flagged_s=3.14159)
    assert len({compute_severity(cand) for _ in range(5)}) == 1


# --------------------------------------------------------------- configuration
def test_custom_constants_change_the_result():
    cfg = SeverityConfig(z_min=0.0, z_severe=2.0, duration_severe_s={FlawType.TOO_FAST: 10.0})
    assert severity_components(_cand(mean_z=1.0, flagged_s=5.0), cfg) == (pytest.approx(0.5), pytest.approx(0.5))
    # Other types keep their defaults when only one reference is overridden.
    assert cfg.duration_severe_s[FlawType.LOW_ENERGY] == SeverityConfig().duration_severe_s[FlawType.LOW_ENERGY]
    assert cfg.duration_severe_s[FlawType.EXCESSIVE_PAUSE] is None


def test_duration_reference_can_be_enabled_for_pauses_or_disabled_for_others():
    cfg = SeverityConfig(duration_severe_s={FlawType.EXCESSIVE_PAUSE: 2.0, FlawType.TOO_FAST: None})
    assert severity_components(_cand(FlawType.EXCESSIVE_PAUSE, mean_z=10.0, flagged_s=1.0), cfg)[1] == pytest.approx(0.5)
    assert severity_components(_cand(FlawType.TOO_FAST, mean_z=10.0, flagged_s=0.1), cfg)[1] == 1.0


def test_value_strings_are_accepted_as_flaw_type_keys():
    cfg = SeverityConfig(duration_severe_s={"low_energy": 10.0})
    assert cfg.duration_severe_s[FlawType.LOW_ENERGY] == 10.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"z_min": -0.1}, {"z_min": float("nan")}, {"z_severe": 1.0}, {"z_severe": 0.5}, {"z_severe": float("inf")},
        {"duration_severe_s": {FlawType.TOO_FAST: 0.0}}, {"duration_severe_s": {FlawType.TOO_FAST: -1.0}},
        {"duration_severe_s": {FlawType.TOO_FAST: float("nan")}}, {"duration_severe_s": {"bogus": 5.0}},
        {"decimals": -1}, {"decimals": 9},
    ],
)
def test_invalid_config_rejected(kwargs):
    with pytest.raises(ValueError):
        SeverityConfig(**kwargs)


@pytest.mark.parametrize("bad_z", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_mean_z_rejected(bad_z):
    with pytest.raises(ValueError, match="mean_z"):
        compute_severity(_cand(mean_z=bad_z))


def test_negative_or_non_finite_flagged_duration_rejected():
    for bad in ((2.0, 1.0), (0.0, float("nan"))):                            # negative length; nan
        cand = FlawCandidate(FlawType.TOO_FAST, 0.0, 1.0, 3.0, 3.0, "rate_z", (0,), (bad,))
        with pytest.raises(ValueError, match="flagged duration"):
            compute_severity(cand)


# ------------------------------------------------------------------ real input
def test_detector_output_gets_sensible_severities():
    nb = NormalizedFeatureBundle(baseline_passage_id="p001", baseline_sha256="a" * 64)
    nb.energy_z = np.array([0.0] * 10 + [-6.0] * 120 + [0.0] * 10)           # 1.2 s of strong low energy
    nb.energy_times_s = np.arange(len(nb.energy_z)) * 0.01
    nb.energy_in_baseline_rule = ~np.isnan(nb.energy_z)
    nb.energy_hop_s = 0.01
    (cand,) = detect_candidates(nb, DetectionConfig()).candidates
    magnitude, duration = severity_components(cand)
    assert magnitude == 1.0 and duration == pytest.approx(1.2 / 5.0)
    assert compute_severity(cand) == pytest.approx(0.24, abs=1e-4)
