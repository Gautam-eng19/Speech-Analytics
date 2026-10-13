"""Flaw severity (TASK-052; ARCHITECTURE.md §18; DEC-P006 Option A as amended by DEC-028).

Severity is a deterministic number in [0, 1] answering "how serious is this deviation?":

    magnitude          = clip((|mean_z| - Z_MIN) / (Z_SEVERE - Z_MIN), 0, 1)
    duration_component = clip(flagged_duration_s / DURATION_SEVERE_S[type], 0, 1)
    severity           = magnitude * duration_component

Constants (config.py, PROPOSED and uncalibrated): Z_MIN = 1.0, Z_SEVERE = 4.0, DURATION_SEVERE_S = 5.0 s.

Amendment (DEC-040): a finding that carries a measured SIZE of the change (`FlawCandidate.effect`) takes its magnitude from that size,

    magnitude = clip(|effect| / effect_scale[type], 0, 1)

with the size in natural-log ratio of durations for pace (scale ln 2: twice or half as fast is the most serious), dB for loudness (scale
15 dB) and seconds beyond the baseline's mean for a pause (scale 3.5 s). The z-score says how sure we are that the change is more than the
natural variation; it saturates quickly when a baseline is very even (a 1.2 s breath is already 4 standard deviations from a reader whose
pauses are all 0.4 s) and then no longer separates a small change from a large one. The size does. Findings without a size (the fallback
rules for a baseline without a word profile) keep the z-score formula above.

Decisions behind the formula (DEC-028):
    * Option A (linear product) rather than the sigmoid: with the proposed constants the sigmoid only
      spans roughly 0.58-0.73, so it cannot separate a mild from a severe deviation.
    * Duration is counted ONCE. It lives here, and the scoring penalty does not multiply by a second
      duration weight (this amends DEC-014's formula).
    * The duration used is the FLAGGED time (what actually deviated), not the span that merging may
      stretch across gaps.
    * excessive_pause has no duration component (reference = None): a pause's z-score is
      (duration - baseline_mean) / baseline_std, a function of its duration alone, so a separate
      duration factor would count the same quantity twice and cap even a 16-sigma pause far below 1.
    * |mean_z| is used, so direction (too fast vs too slow) does not change severity.

Limitation: the proposed Z_SEVERE = 4 is easily exceeded by baselines with a small spread (single
reference recording), so magnitude then saturates at 1 and severity reduces to the duration component.
Constants must be calibrated on a dev split before they can be called validated.

Reliability is separate (ARCHITECTURE.md §19) and is a constant 1.0 at P0.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

from app.core.config import settings
from app.schemas.common import FlawType
from app.services.grounding.candidates import FlawCandidate


def _default_duration_refs() -> "dict[FlawType, Optional[float]]":
    refs: "dict[FlawType, Optional[float]]" = {t: settings.SEVERITY_DURATION_SEVERE_S for t in FlawType}
    refs[FlawType.EXCESSIVE_PAUSE] = None  # z already encodes the pause duration (DEC-028)
    return refs


def _default_effect_scales() -> "dict[FlawType, float]":
    """Size of the change that counts as maximum severity (DEC-040), per flaw type that carries a measured size."""
    pace = math.log(settings.SEVERITY_RATE_SEVERE_RATIO)
    return {
        FlawType.TOO_FAST: pace,
        FlawType.TOO_SLOW: pace,
        FlawType.HIGH_ENERGY: settings.SEVERITY_ENERGY_SEVERE_DB,
        FlawType.LOW_ENERGY: settings.SEVERITY_ENERGY_SEVERE_DB,
        FlawType.EXCESSIVE_PAUSE: settings.SEVERITY_PAUSE_EXCESS_SEVERE_S,
    }


@dataclass(frozen=True)
class SeverityConfig:
    """Severity constants (defaults: PROPOSED, uncalibrated values from config.py).

    duration_severe_s maps a flaw type to the flagged duration (seconds) at which the duration component
    reaches 1.0, or None for "no duration component". Entries given here override the defaults.
    """

    z_min: float = settings.SEVERITY_Z_MIN
    z_severe: float = settings.SEVERITY_Z_SEVERE
    duration_severe_s: Mapping[FlawType, Optional[float]] = None  # type: ignore[assignment]
    decimals: int = 4
    # Size of the change at which the magnitude of a finding that carries a measured size reaches 1.0 (see the module docstring).
    effect_scale: Mapping[FlawType, float] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        refs = _default_duration_refs()
        if self.duration_severe_s is not None:
            refs.update(self.duration_severe_s)
        object.__setattr__(self, "duration_severe_s", refs)
        scales = _default_effect_scales()
        if self.effect_scale is not None:
            scales.update(self.effect_scale)
        object.__setattr__(self, "effect_scale", scales)
        for ftype, scale in scales.items():
            if not isinstance(ftype, FlawType):
                raise ValueError(f"effect_scale keys must be FlawType, got {ftype!r}")
            if not (math.isfinite(scale) and scale > 0.0):
                raise ValueError(f"effect_scale[{ftype.value}] must be a positive finite number, got {scale}")
        if not (math.isfinite(self.z_min) and self.z_min >= 0.0):
            raise ValueError(f"z_min must be finite and >= 0, got {self.z_min}")
        if not (math.isfinite(self.z_severe) and self.z_severe > self.z_min):
            raise ValueError(f"z_severe must be finite and > z_min ({self.z_min}), got {self.z_severe}")
        for ftype, ref in refs.items():
            if not isinstance(ftype, FlawType):
                raise ValueError(f"duration_severe_s keys must be FlawType, got {ftype!r}")
            if ref is not None and not (math.isfinite(ref) and ref > 0.0):
                raise ValueError(f"duration_severe_s[{ftype.value}] must be None or a positive finite number, got {ref}")
        if not (0 <= self.decimals <= 8):
            raise ValueError(f"decimals must be in [0, 8], got {self.decimals}")


def _clip01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def severity_components(candidate: FlawCandidate, config: Optional[SeverityConfig] = None) -> Tuple[float, float]:
    """Return the unrounded ``(magnitude, duration_component)`` of a candidate, each in [0, 1].

    Raises:
        ValueError: non-finite ``mean_z`` or a negative / non-finite flagged duration.
    """
    cfg = config or SeverityConfig()
    z = candidate.mean_z
    if not math.isfinite(z):
        raise ValueError(f"candidate mean_z must be finite, got {z}")
    scale = cfg.effect_scale.get(candidate.type)
    if candidate.effect is not None and scale is not None:
        if not (math.isfinite(candidate.effect) and candidate.effect >= 0.0):
            raise ValueError(f"candidate effect must be finite and >= 0, got {candidate.effect}")
        magnitude = _clip01(candidate.effect / scale)
    else:
        magnitude = _clip01((abs(z) - cfg.z_min) / (cfg.z_severe - cfg.z_min))

    reference = cfg.duration_severe_s[candidate.type]
    if reference is None:
        return magnitude, 1.0
    flagged = candidate.flagged_duration_s
    if not (math.isfinite(flagged) and flagged >= 0.0):
        raise ValueError(f"candidate flagged duration must be finite and >= 0, got {flagged}")
    return magnitude, _clip01(flagged / reference)


def compute_severity(candidate: FlawCandidate, config: Optional[SeverityConfig] = None) -> float:
    """Severity in [0, 1] of a flaw candidate, rounded to ``config.decimals`` places."""
    cfg = config or SeverityConfig()
    magnitude, duration_component = severity_components(candidate, cfg)
    return round(magnitude * duration_component, cfg.decimals)
