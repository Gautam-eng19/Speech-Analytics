"""Deterministic delivery scoring (TASK-060, TASK-061, TASK-062; ARCHITECTURE.md §20; DEC-014 as amended by DEC-030).

The score summarises how many and how severe the detected deviations from the BASELINE are. It is not a
speech-quality or intelligibility score, it says nothing about content, and it is not calibrated (all
constants are proposed starting values): 100 means "no deviation from the baseline was detected in the
dimensions that were evaluated".

Per feature (speech_rate, pitch, pauses, energy, mfcc, clarity):

    penalty(flaw)   = BASE_PENALTY * severity * reliability          (duration is already inside severity; DEC-028)
    penalty_total   = sum of its flaws' penalties (rounded to 2 dp)
    sub_score       = max(0, 100 - penalty_total)

Composite, over the EVALUATED features only:

    effective_weight(f) = weight(f) / sum(weight(g) for evaluated g)       (rounded to 6 dp)
    composite           = sum(effective_weight(f) * sub_score(f))          (rounded to 2 dp, within [0, 100])

Missing features are never silently scored:
    * A feature is EVALUATED only if every P0 flaw type that maps to it was actually checked. Flaw types the
      detector reported as skipped (not implemented such as flat_pitch, or whose feature was unavailable
      such as speech rate with too few windows) make their feature NOT evaluated.
    * A feature that is not evaluated is OMITTED from `feature_scores`: it gets neither 100 ("perfect") nor 0.
      The reason is returned in `ScoringResult.excluded` so the caller can state it (AnalysisResult.notes).
    * The weights of the remaining features are renormalised, explicitly, and the EFFECTIVE weights are what
      the result reports; so composite == sum(reported weight * reported score) up to rounding. Features with
      weight 0 (mfcc and clarity at P0) are excluded for that reason.
    * If no feature can be evaluated, scoring fails with `ScoringError` instead of returning a number.

All displayed numbers are rounded before they are combined, so the composite can be re-derived by hand from the
response. Same flaws + same config produce the same result regardless of the order of the flaws.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from app.core.config import settings
from app.schemas.common import FeatureName, FlawType
from app.schemas.response import FeatureScore, ScoreSummary
from app.services.grounding.flaws import GroundedFlaw

FEATURE_FOR_FLAW: Mapping[FlawType, FeatureName] = {
    FlawType.TOO_FAST: FeatureName.SPEECH_RATE,
    FlawType.TOO_SLOW: FeatureName.SPEECH_RATE,
    FlawType.EXCESSIVE_PAUSE: FeatureName.PAUSES,
    FlawType.FLAT_PITCH: FeatureName.PITCH,
    FlawType.PITCH_INSTABILITY: FeatureName.PITCH,
    FlawType.LOW_ENERGY: FeatureName.ENERGY,
    FlawType.HIGH_ENERGY: FeatureName.ENERGY,
    FlawType.REDUCED_CLARITY: FeatureName.CLARITY,
}

# Flaw types of the P0 scope (DEC-013). A feature is evaluated only if all of ITS P0 types were checked.
_P0_FLAW_TYPES = frozenset(
    {
        FlawType.TOO_FAST,
        FlawType.TOO_SLOW,
        FlawType.EXCESSIVE_PAUSE,
        FlawType.FLAT_PITCH,
        FlawType.LOW_ENERGY,
        FlawType.HIGH_ENERGY,
    }
)


class ScoringError(ValueError):
    """Raised when a score cannot be computed faithfully."""


def _default_weights() -> Dict[FeatureName, float]:
    return {
        FeatureName.SPEECH_RATE: settings.SCORE_WEIGHT_SPEECH_RATE,
        FeatureName.PITCH: settings.SCORE_WEIGHT_PITCH,
        FeatureName.PAUSES: settings.SCORE_WEIGHT_PAUSES,
        FeatureName.ENERGY: settings.SCORE_WEIGHT_ENERGY,
        FeatureName.MFCC: settings.SCORE_WEIGHT_MFCC,
        FeatureName.CLARITY: settings.SCORE_WEIGHT_CLARITY,
    }


@dataclass(frozen=True)
class ScoringConfig:
    """Scoring constants (defaults: PROPOSED, uncalibrated values from config.py).

    `weights` entries given here override the defaults; they need not sum to 1 (they are renormalised over
    the evaluated features).
    """

    base_penalty: float = settings.BASE_PENALTY
    weights: Mapping[FeatureName, float] = None  # type: ignore[assignment]
    decimals: int = 2
    weight_decimals: int = 6

    def __post_init__(self) -> None:
        merged = _default_weights()
        if self.weights is not None:
            merged.update(self.weights)
        object.__setattr__(self, "weights", merged)
        if not (math.isfinite(self.base_penalty) and self.base_penalty > 0.0):
            raise ValueError(f"base_penalty must be a positive finite number, got {self.base_penalty}")
        for feature, weight in merged.items():
            if not isinstance(feature, FeatureName):
                raise ValueError(f"weights keys must be FeatureName, got {feature!r}")
            if not (math.isfinite(weight) and weight >= 0.0):
                raise ValueError(f"weight for {feature.value} must be a finite number >= 0, got {weight}")
        if not any(w > 0.0 for w in merged.values()):
            raise ValueError("at least one feature weight must be > 0")
        if not (0 <= self.decimals <= 6 and 0 <= self.weight_decimals <= 9):
            raise ValueError("decimals must be in [0, 6] and weight_decimals in [0, 9]")


@dataclass(frozen=True)
class ScoringResult:
    """The public `ScoreSummary` plus why some features were left out of it."""

    scores: ScoreSummary
    excluded: Dict[FeatureName, str]


def evaluated_features(
    skipped: Mapping[str, str], config: Optional[ScoringConfig] = None
) -> Tuple[List[FeatureName], Dict[FeatureName, str]]:
    """Split the features into evaluated ones and excluded ones (with reasons).

    `skipped` maps a flaw-type value (e.g. "flat_pitch") to the reason it was not checked, exactly as
    `CandidateDetectionResult.skipped` reports it.
    """
    cfg = config or ScoringConfig()
    evaluated: List[FeatureName] = []
    excluded: Dict[FeatureName, str] = {}
    for feature in FeatureName:
        if cfg.weights[feature] <= 0.0:
            excluded[feature] = "weight is 0 (not part of the P0 composite)"
            continue
        p0_types = [t for t in FlawType if FEATURE_FOR_FLAW[t] == feature and t in _P0_FLAW_TYPES]
        if not p0_types:
            excluded[feature] = "no P0 flaw type is defined for this feature"
            continue
        not_checked = [t for t in p0_types if t.value in skipped]
        if not_checked:
            excluded[feature] = "; ".join(f"{t.value}: {skipped[t.value]}" for t in not_checked)
            continue
        evaluated.append(feature)
    return evaluated, excluded


def _check_flaw(f: GroundedFlaw) -> None:
    for name, value in (("severity", f.severity), ("reliability", f.reliability)):
        if not (isinstance(value, (int, float)) and math.isfinite(value) and 0.0 <= value <= 1.0):
            raise ScoringError(f"{f.flaw_id}: {name} must be a number in [0, 1], got {value!r}")


def score_analysis(
    flaws: Sequence[GroundedFlaw],
    skipped: Mapping[str, str],
    scoring_version: str,
    config: Optional[ScoringConfig] = None,
) -> ScoringResult:
    """Score the flaws of one analysis.

    Args:
        flaws: the grounded flaws (any order).
        skipped: flaw types that were NOT checked, with reasons (`CandidateDetectionResult.skipped`).
        scoring_version: the `config_version` the score is computed under (AnalysisResult requires equality).
        config: scoring constants.

    Raises:
        ScoringError: no feature could be evaluated, a flaw belongs to a feature that was not evaluated
            (inconsistent inputs), or a flaw has an invalid severity / reliability.
    """
    cfg = config or ScoringConfig()
    evaluated, excluded = evaluated_features(skipped, cfg)
    if not evaluated:
        raise ScoringError("no feature could be evaluated, so no score can be computed: " + "; ".join(
            f"{f.value} ({why})" for f, why in excluded.items()))

    penalties: Dict[FeatureName, float] = {f: 0.0 for f in evaluated}
    counts: Dict[FeatureName, int] = {f: 0 for f in evaluated}
    for flaw in sorted(flaws, key=lambda x: x.flaw_id):          # fixed order: float sums are reproducible
        _check_flaw(flaw)
        feature = FEATURE_FOR_FLAW[flaw.type]
        if feature not in penalties:
            raise ScoringError(
                f"{flaw.flaw_id} ({flaw.type.value}) belongs to feature '{feature.value}', which was not "
                f"evaluated: {excluded.get(feature, 'unknown reason')}"
            )
        penalties[feature] += cfg.base_penalty * flaw.severity * flaw.reliability
        counts[feature] += 1

    total_weight = sum(cfg.weights[f] for f in evaluated)
    feature_scores: Dict[FeatureName, FeatureScore] = {}
    composite = 0.0
    for feature in evaluated:                                    # FeatureName order
        penalty_total = round(penalties[feature], cfg.decimals)
        sub_score = round(max(0.0, 100.0 - penalty_total), cfg.decimals)
        weight = round(cfg.weights[feature] / total_weight, cfg.weight_decimals)
        feature_scores[feature] = FeatureScore(
            score=sub_score, weight=weight, flaw_count=counts[feature], penalty_total=penalty_total
        )
        composite += weight * sub_score

    summary = ScoreSummary(
        feature_scores=feature_scores,
        composite_score=min(100.0, max(0.0, round(composite, cfg.decimals))),
        scoring_version=scoring_version,
    )
    return ScoringResult(scores=summary, excluded=excluded)
