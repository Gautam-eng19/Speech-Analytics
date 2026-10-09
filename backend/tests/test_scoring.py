"""Unit tests for deterministic scoring (TASK-060/061/062, DEC-014 as amended by DEC-030).

Covers:
- Exact penalties / sub-scores / composite for hand-computed cases and the penalty formula
  (BASE_PENALTY x severity x reliability, no second duration weight)
- Missing-feature handling: unevaluated features are omitted, weights renormalised explicitly, reasons returned
- Floors, rounding, reproducibility of the composite from the displayed numbers
- Properties: order independence, monotonicity, determinism
- Every error path and configuration validation
"""
from __future__ import annotations

import itertools
import json
import math
import random

import pytest
from app.schemas.common import FeatureName, FlawType, PauseBoundaryType, PauseDetectionSource
from app.schemas.response import (
    ClarityEvidence,
    DetectionRule,
    EnergyEvidence,
    FlatPitchEvidence,
    PauseEvidence,
    PitchInstabilityEvidence,
    RateEvidence,
    ScoreSummary,
)
from app.services.grounding import GroundedFlaw
from app.services.scoring import (
    FEATURE_FOR_FLAW,
    ScoringConfig,
    ScoringError,
    evaluated_features,
    score_analysis,
)

VERSION = "1.0.0"
PITCH_SKIPPED = {"flat_pitch": "no baseline statistic of F0 variation", "pitch_instability": "P1", "reduced_clarity": "P1"}

_EVIDENCE = {
    FlawType.TOO_FAST: RateEvidence(
        rate_participant_wpm=180, rate_baseline_mean_wpm=120, rate_baseline_std_wpm=10, rate_delta_wpm=60,
        rate_delta_pct=50, rate_z_score=6, peak_z_score=6, window_duration_s=4, word_count_in_window=12),
    FlawType.PITCH_INSTABILITY: PitchInstabilityEvidence(
        f0_var_hz_in_window=10, f0_var_baseline_hz=5, f0_var_z=3, window_duration_s=2),
    FlawType.REDUCED_CLARITY: ClarityEvidence(
        hf_ratio_mean=0.1, hf_ratio_baseline_mean=0.3, hf_ratio_z=-3, window_duration_s=2),
    FlawType.FLAT_PITCH: FlatPitchEvidence(
        f0_std_hz_in_window=1, f0_std_baseline_hz=20, f0_std_z=-3, f0_voiced_fraction=0.8, window_duration_s=2),
    FlawType.LOW_ENERGY: EnergyEvidence(
        energy_mean_db=-45, energy_baseline_mean_db=-25, energy_baseline_std_db=5, energy_delta_db=-20,
        energy_z_score=-4, window_duration_s=2),
    FlawType.EXCESSIVE_PAUSE: PauseEvidence(
        pause_duration_s=1.5, pause_baseline_mean_s=0.4, pause_baseline_std_s=0.1, pause_delta_s=1.1,
        pause_z_score=11, boundary_type=PauseBoundaryType.WITHIN_PHRASE, detection_source=PauseDetectionSource.BOTH),
}
_EVIDENCE[FlawType.TOO_SLOW] = _EVIDENCE[FlawType.TOO_FAST]
_EVIDENCE[FlawType.HIGH_ENERGY] = _EVIDENCE[FlawType.LOW_ENERGY]
_RULE = DetectionRule(feature="x_z", direction="above", threshold_z=2.0, min_duration_s=0.5)


def _flaw(ftype: FlawType, severity: float, reliability: float = 1.0, number: int = 1,
          start: float = 0.0, end: float = 1.0) -> GroundedFlaw:
    return GroundedFlaw(
        flaw_id=f"flaw_{number:03d}", type=ftype, start_s=start, end_s=end, severity=severity,
        reliability=reliability, low_confidence=False, evidence=_EVIDENCE[ftype], rule=_RULE,
        affected_words=(), warnings=(),
    )


def _score(flaws, skipped=None, config=None):
    return score_analysis(flaws, PITCH_SKIPPED if skipped is None else skipped, VERSION, config)


def _by_feature(result):
    return result.scores.feature_scores


# ------------------------------------------------------------------- mapping
def test_every_flaw_type_maps_to_a_feature_dimension():
    assert set(FEATURE_FOR_FLAW) == set(FlawType)
    assert FEATURE_FOR_FLAW[FlawType.TOO_FAST] == FEATURE_FOR_FLAW[FlawType.TOO_SLOW] == FeatureName.SPEECH_RATE
    assert FEATURE_FOR_FLAW[FlawType.LOW_ENERGY] == FEATURE_FOR_FLAW[FlawType.HIGH_ENERGY] == FeatureName.ENERGY
    assert FEATURE_FOR_FLAW[FlawType.EXCESSIVE_PAUSE] == FeatureName.PAUSES
    assert FEATURE_FOR_FLAW[FlawType.FLAT_PITCH] == FEATURE_FOR_FLAW[FlawType.PITCH_INSTABILITY] == FeatureName.PITCH


# ------------------------------------------------------ exact numbers, formula
def test_no_flaws_with_all_p0_features_evaluated_gives_100_and_the_configured_weights():
    result = _score([], skipped={})
    fs = _by_feature(result)
    assert list(fs) == [FeatureName.SPEECH_RATE, FeatureName.PITCH, FeatureName.PAUSES, FeatureName.ENERGY]
    assert [fs[f].weight for f in fs] == [0.3, 0.25, 0.25, 0.2]
    assert all(s.score == 100.0 and s.flaw_count == 0 and s.penalty_total == 0.0 for s in fs.values())
    assert result.scores.composite_score == 100.0 and result.scores.scoring_version == VERSION
    assert set(result.excluded) == {FeatureName.MFCC, FeatureName.CLARITY}


def test_unevaluated_pitch_is_omitted_and_remaining_weights_are_renormalised():
    result = _score([])
    fs = _by_feature(result)
    assert FeatureName.PITCH not in fs
    assert [f.value for f in fs] == ["speech_rate", "pauses", "energy"]
    assert [fs[f].weight for f in fs] == [0.4, 0.333333, 0.266667]
    assert sum(s.weight for s in fs.values()) == pytest.approx(1.0, abs=1e-5)
    assert result.excluded[FeatureName.PITCH].startswith("flat_pitch: no baseline statistic")
    assert "weight is 0" in result.excluded[FeatureName.MFCC] and FeatureName.CLARITY in result.excluded


def test_single_flaw_exact_penalty_subscore_and_composite():
    result = _score([_flaw(FlawType.TOO_FAST, 0.5)])
    fs = _by_feature(result)
    assert fs[FeatureName.SPEECH_RATE].penalty_total == 15.0                    # 30 x 0.5
    assert fs[FeatureName.SPEECH_RATE].score == 85.0 and fs[FeatureName.SPEECH_RATE].flaw_count == 1
    assert fs[FeatureName.PAUSES].score == fs[FeatureName.ENERGY].score == 100.0
    assert result.scores.composite_score == 94.0                                # .4x85 + .333333x100 + .266667x100


def test_penalties_add_within_a_feature_across_flaw_types():
    flaws = [_flaw(FlawType.LOW_ENERGY, 0.4, number=1), _flaw(FlawType.HIGH_ENERGY, 0.3, number=2)]
    fs = _by_feature(_score(flaws))
    assert fs[FeatureName.ENERGY].penalty_total == 21.0 and fs[FeatureName.ENERGY].score == 79.0
    assert fs[FeatureName.ENERGY].flaw_count == 2


def test_sub_score_floors_at_zero_but_the_unclamped_penalty_is_reported():
    flaws = [_flaw(FlawType.TOO_FAST, 1.0, number=i) for i in range(1, 6)]    # 5 x 30 = 150
    fs = _by_feature(_score(flaws))
    assert fs[FeatureName.SPEECH_RATE].penalty_total == 150.0 and fs[FeatureName.SPEECH_RATE].score == 0.0


def test_reliability_scales_the_penalty():
    fs = _by_feature(_score([_flaw(FlawType.EXCESSIVE_PAUSE, 1.0, reliability=0.5)]))
    assert fs[FeatureName.PAUSES].penalty_total == 15.0 and fs[FeatureName.PAUSES].score == 85.0


def test_duration_is_not_applied_a_second_time():
    # Same severity, very different durations: identical penalty (duration lives in severity; DEC-028/030).
    short = _score([_flaw(FlawType.LOW_ENERGY, 0.6, start=0.0, end=0.5)])
    long = _score([_flaw(FlawType.LOW_ENERGY, 0.6, start=0.0, end=9.0)])
    assert short.scores == long.scores
    assert _by_feature(short)[FeatureName.ENERGY].penalty_total == 18.0


def test_rounding_to_two_decimals_and_six_decimal_weights():
    fs = _by_feature(_score([_flaw(FlawType.TOO_SLOW, 0.3333)]))             # 30 x 0.3333 = 9.999
    assert fs[FeatureName.SPEECH_RATE].penalty_total == 10.0 and fs[FeatureName.SPEECH_RATE].score == 90.0
    fs = _by_feature(_score([_flaw(FlawType.TOO_SLOW, 0.1234)]))             # 3.702
    assert fs[FeatureName.SPEECH_RATE].penalty_total == 3.7 and fs[FeatureName.SPEECH_RATE].score == 96.3
    assert all(round(s.weight, 6) == s.weight for s in fs.values())


def test_composite_can_be_rederived_from_the_displayed_numbers():
    rng = random.Random(7)
    types = [FlawType.TOO_FAST, FlawType.TOO_SLOW, FlawType.EXCESSIVE_PAUSE, FlawType.LOW_ENERGY, FlawType.HIGH_ENERGY]
    for trial in range(40):
        flaws = [
            _flaw(rng.choice(types), round(rng.random(), 4), round(rng.uniform(0.5, 1.0), 2), number=i + 1)
            for i in range(rng.randint(0, 8))
        ]
        fs = _by_feature(_score(flaws))
        assert sum(s.weight for s in fs.values()) == pytest.approx(1.0, abs=2e-6)
        shown = sum(s.weight * s.score for s in fs.values())
        assert _score(flaws).scores.composite_score == pytest.approx(shown, abs=0.0051)
        for s in fs.values():
            assert s.score == pytest.approx(max(0.0, 100.0 - s.penalty_total), abs=1e-9)


# -------------------------------------------------------------- properties
def test_result_does_not_depend_on_the_order_of_the_flaws():
    flaws = [_flaw(t, sev, number=i) for i, (t, sev) in enumerate(
        [(FlawType.TOO_FAST, 0.37), (FlawType.EXCESSIVE_PAUSE, 0.81), (FlawType.LOW_ENERGY, 0.12),
         (FlawType.TOO_SLOW, 0.55), (FlawType.HIGH_ENERGY, 0.9), (FlawType.EXCESSIVE_PAUSE, 0.44)], start=1)]
    baseline = _score(flaws)
    for perm in itertools.islice(itertools.permutations(flaws), 60):
        assert _score(list(perm)) == baseline


def test_adding_a_flaw_or_raising_severity_never_raises_the_score():
    types = [FlawType.TOO_FAST, FlawType.EXCESSIVE_PAUSE, FlawType.LOW_ENERGY]
    previous = _score([]).scores.composite_score
    flaws = []
    for i, t in enumerate(types * 3, start=1):
        flaws.append(_flaw(t, 0.3, number=i))
        current = _score(flaws).scores.composite_score
        assert current <= previous
        previous = current
    last = None
    for sev in [0.0, 0.1, 0.25, 0.5, 0.75, 1.0]:
        value = _score([_flaw(FlawType.TOO_FAST, sev)]).scores.composite_score
        assert last is None or value <= last
        last = value


def test_deterministic_and_inputs_not_mutated():
    flaws = [_flaw(FlawType.TOO_FAST, 0.37), _flaw(FlawType.EXCESSIVE_PAUSE, 0.81, number=2)]
    snapshot = list(flaws)
    results = {_score(flaws).scores.model_dump_json() for _ in range(5)}
    assert len(results) == 1 and flaws == snapshot


def test_summary_is_a_valid_public_model_with_canonical_key_order():
    result = _score([_flaw(FlawType.LOW_ENERGY, 0.5)])
    assert isinstance(result.scores, ScoreSummary)
    assert ScoreSummary.model_validate_json(result.scores.model_dump_json()) == result.scores
    assert list(json.loads(result.scores.model_dump_json())["feature_scores"]) == ["speech_rate", "pauses", "energy"]


# --------------------------------------------------- missing-feature handling
def test_skipped_rate_removes_speech_rate_and_renormalises():
    skipped = {**PITCH_SKIPPED, "too_fast": "rate unavailable: rate_analysis_skipped", "too_slow": "rate unavailable"}
    result = _score([], skipped)
    fs = _by_feature(result)
    assert list(fs) == [FeatureName.PAUSES, FeatureName.ENERGY]
    assert [fs[f].weight for f in fs] == [0.555556, 0.444444]
    assert "too_fast: rate unavailable" in result.excluded[FeatureName.SPEECH_RATE]


def test_a_flaw_in_a_feature_that_was_not_evaluated_is_an_inconsistency_error():
    with pytest.raises(ScoringError, match="not evaluated"):
        _score([_flaw(FlawType.FLAT_PITCH, 0.5)])                              # flat_pitch is in `skipped`
    with pytest.raises(ScoringError, match="not evaluated"):
        _score([_flaw(FlawType.REDUCED_CLARITY, 0.5)], skipped={})             # P1 feature, weight 0


def test_pitch_is_scored_once_it_is_evaluated():
    result = _score([_flaw(FlawType.FLAT_PITCH, 0.5)], skipped={})
    fs = _by_feature(result)
    assert fs[FeatureName.PITCH].penalty_total == 15.0 and fs[FeatureName.PITCH].weight == 0.25


def test_no_evaluable_feature_is_an_error_not_a_number():
    all_skipped = {t.value: "unavailable" for t in FlawType}
    with pytest.raises(ScoringError, match="no feature could be evaluated"):
        _score([], all_skipped)


def test_evaluated_features_helper_reports_reasons():
    evaluated, excluded = evaluated_features(PITCH_SKIPPED)
    assert evaluated == [FeatureName.SPEECH_RATE, FeatureName.PAUSES, FeatureName.ENERGY]
    assert set(excluded) == {FeatureName.PITCH, FeatureName.MFCC, FeatureName.CLARITY}


def test_p1_clarity_stays_excluded_even_with_a_positive_weight():
    cfg = ScoringConfig(weights={FeatureName.CLARITY: 0.1})
    evaluated, excluded = evaluated_features(PITCH_SKIPPED, cfg)
    assert FeatureName.CLARITY not in evaluated and "no P0 flaw type" in excluded[FeatureName.CLARITY]


# ------------------------------------------------------------- configuration
def test_custom_weights_and_base_penalty():
    cfg = ScoringConfig(base_penalty=50.0, weights={FeatureName.SPEECH_RATE: 1.0, FeatureName.PAUSES: 0.0,
                                                    FeatureName.ENERGY: 0.0, FeatureName.PITCH: 0.0})
    result = _score([_flaw(FlawType.TOO_FAST, 0.5)], config=cfg)
    fs = _by_feature(result)
    assert list(fs) == [FeatureName.SPEECH_RATE] and fs[FeatureName.SPEECH_RATE].weight == 1.0
    assert fs[FeatureName.SPEECH_RATE].penalty_total == 25.0 and result.scores.composite_score == 75.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"base_penalty": 0.0}, {"base_penalty": -1.0}, {"base_penalty": float("nan")},
        {"weights": {FeatureName.PITCH: -0.1}}, {"weights": {FeatureName.PITCH: float("inf")}},
        {"weights": {"bogus": 0.5}},
        {"weights": {f: 0.0 for f in FeatureName}},
        {"decimals": -1}, {"decimals": 7}, {"weight_decimals": 10},
    ],
)
def test_invalid_config_rejected(kwargs):
    with pytest.raises(ValueError):
        ScoringConfig(**kwargs)


@pytest.mark.parametrize("severity,reliability", [
    (1.2, 1.0), (-0.1, 1.0), (float("nan"), 1.0), (0.5, 1.5), (0.5, -0.2), (0.5, float("nan")), ("0.5", 1.0),
])
def test_invalid_flaw_values_rejected(severity, reliability):
    with pytest.raises(ScoringError, match="must be a number in"):
        _score([_flaw(FlawType.TOO_FAST, severity, reliability)])
