"""Flaw candidate generation, minimum-duration filtering and merging (TASK-050, TASK-051;
ARCHITECTURE.md §17 steps 1-3, §9.8; DEC-P005 thresholds).

Input is a `NormalizedFeatureBundle` (z-scores against the baseline). Output is a deterministic,
time-sorted list of `FlawCandidate`s, each with a start and end time in processed-audio time.
No severity, scoring, explanation or evidence payload is produced here (later stages).

Detection rules (strict inequalities, as written in §17; a z-score exactly on a threshold is
NOT flagged):

    too_fast         rate_z   >  +Z_RATE_FAST
    too_slow         rate_z   <  -Z_RATE_SLOW
    low_energy       energy_z <  -Z_ENERGY
    high_energy      energy_z >  +Z_ENERGY
    excessive_pause  pause_z  >  Z_PAUSE_WITHIN (within_phrase) / Z_PAUSE_CROSS (cross_sentence)

Intervals:
    * rate: the measured span of the flagged window (first word start .. last word end). The
      rolling window makes rate findings window-resolution (several seconds); finer location is
      a P1 refinement. Overlapping flagged windows merge into one interval.
    * energy: a run of consecutive flagged frames, from half a hop before the first frame to
      half a hop after the last. Frames the baseline statistic does not cover (NaN z, e.g. pauses)
      are never flagged and break a run, so silence is not reported as "low energy".
    * pause: the pause event itself.

Pipeline (P0 minimum, §17 order): [1] threshold -> [2] minimum-duration filter -> [3] merge
same-type windows whose gap is < MERGE_GAP_S. Smoothing, hysteresis and boundary refinement are P1
and absent.

Energy runs are formed over COVERED frames (those with a z-score). Uncovered frames (NaN: pauses and
inter-word silence under the baseline's "active frames" rule) neither flag nor break a run, so a
genuinely quiet stretch of speech stays ONE run even though every word is followed by a gap
(otherwise every run would be cut to word length and fall under the minimum duration). A covered
frame within normal range DOES break the run, so isolated low-energy blips (word onsets/offsets)
cannot chain across a recording. A run also breaks where the uncovered stretch reaches MERGE_GAP_S.
The minimum duration applies to the run's FLAGGED time (flagged frames only), not its span.

Choices where §17 / DEC-P005 are silent (documented, to be confirmed):
    * Excessive pauses are NOT merged: two nearby long pauses are two pieces of evidence.
    * The minimum duration is configurable per flaw type; it defaults to MIN_FLAW_DURATION_S for
      rate and energy findings and to 0.0 for pauses, because a pause is already a measured event
      that exceeds the baseline by a z threshold.
    * peak_z is the largest |z| among the flagged samples, mean_z their signed mean.
    * A rolling-window rate finding is window-resolution, and overlapping flagged windows merge
      into one interval, so a flaw can look longer than the actual behavior.
    * With a single reference recording the baseline rate spread rests on only a few windows
      and can be very small, which makes the rate z-score hypersensitive (see BaselineStatsRecord
      n_rate_windows).

Not covered, reported in `skipped`:
    * flat_pitch: needs baseline statistics of F0 variation WITHIN a window; `BaselineStats`
      only holds the pooled global F0 std, which is not a valid reference for a local std.
    * pitch_instability, reduced_clarity: P1 flaw types.
    * any type whose feature is unavailable in the bundle (with the reason).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from app.core.config import settings
from app.schemas.common import FlawType, PauseBoundaryType
from app.services.grounding.normalizer import NormalizedFeatureBundle

_EPS_S = 1e-9


def _default_min_durations() -> Dict[FlawType, float]:
    return {
        FlawType.TOO_FAST: settings.MIN_FLAW_DURATION_S,
        FlawType.TOO_SLOW: settings.MIN_FLAW_DURATION_S,
        FlawType.LOW_ENERGY: settings.MIN_FLAW_DURATION_S,
        FlawType.HIGH_ENERGY: settings.MIN_FLAW_DURATION_S,
        FlawType.EXCESSIVE_PAUSE: 0.0,
    }


@dataclass(frozen=True)
class DetectionConfig:
    """Thresholds for candidate generation (defaults: PROPOSED values, uncalibrated, DEC-P005).

    min_duration_s maps each detectable flaw type to its minimum duration in seconds.
    """

    z_rate_fast: float = settings.Z_RATE_FAST
    z_rate_slow: float = settings.Z_RATE_SLOW
    z_energy: float = settings.Z_ENERGY
    z_pause_within: float = settings.Z_PAUSE_WITHIN
    z_pause_cross: float = settings.Z_PAUSE_CROSS
    merge_gap_s: float = settings.MERGE_GAP_S
    min_duration_s: Mapping[FlawType, float] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        durations = dict(_default_min_durations())
        if self.min_duration_s is not None:
            durations.update(self.min_duration_s)
        object.__setattr__(self, "min_duration_s", durations)
        for name in ("z_rate_fast", "z_rate_slow", "z_energy", "z_pause_within", "z_pause_cross"):
            value = getattr(self, name)
            if not (math.isfinite(value) and value > 0.0):
                raise ValueError(f"{name} must be a positive finite z-score threshold, got {value}")
        if not (math.isfinite(self.merge_gap_s) and self.merge_gap_s >= 0.0):
            raise ValueError(f"merge_gap_s must be finite and >= 0, got {self.merge_gap_s}")
        for ftype, minimum in durations.items():
            if not isinstance(ftype, FlawType):
                raise ValueError(f"min_duration_s keys must be FlawType, got {ftype!r}")
            if not (math.isfinite(minimum) and minimum >= 0.0):
                raise ValueError(f"min_duration_s[{ftype.value}] must be finite and >= 0, got {minimum}")


@dataclass(frozen=True)
class FlawCandidate:
    """A time interval where a feature deviates beyond its threshold (ARCHITECTURE.md §9.8).

    Attributes:
        type: flaw type.
        start_s / end_s: interval in processed-audio time, seconds.
        peak_z: largest |z-score| among the flagged samples (>= 0).
        mean_z: signed mean z-score of the flagged samples.
        detection_feature: normalized signal that triggered it ("rate_z", "energy_z", "pause_z").
        member_indices: sorted indices of the flagged samples in that signal (rate windows, energy
            frames, or pause events) so later stages can extract evidence without re-detecting.
        flagged_intervals: disjoint, sorted (start, end) intervals that were actually flagged;
            their total length is `flagged_duration_s` (<= the span `duration_s` after merging).
    """

    type: FlawType
    start_s: float
    end_s: float
    peak_z: float
    mean_z: float
    detection_feature: str
    member_indices: Tuple[int, ...]
    flagged_intervals: Tuple[Tuple[float, float], ...]

    @property
    def duration_s(self) -> float:
        """Span of the candidate (end - start), including any gaps between merged parts."""
        return self.end_s - self.start_s

    @property
    def flagged_duration_s(self) -> float:
        """Time actually flagged: total length of the disjoint flagged intervals."""
        return float(sum(e - s for s, e in self.flagged_intervals))


@dataclass
class CandidateDetectionResult:
    """Candidates (sorted by start, end, type) and the flaw types that could not be evaluated."""

    candidates: List[FlawCandidate]
    skipped: Dict[str, str]


_P1_OR_UNSUPPORTED = {
    FlawType.FLAT_PITCH: (
        "baseline has no statistic of F0 variation within a window (BaselineStats holds only the "
        "pooled global F0 std); detection not implemented"
    ),
    FlawType.PITCH_INSTABILITY: "P1 flaw type; not implemented",
    FlawType.REDUCED_CLARITY: "P1 flaw type; not implemented",
}


def _runs(mask: np.ndarray) -> List[Tuple[int, int]]:
    """Inclusive (first, last) index pairs of consecutive True values."""
    if len(mask) == 0:
        return []
    padded = np.concatenate(([0], mask.astype(np.int8), [0]))
    edges = np.diff(padded)
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1) - 1
    return [(int(a), int(b)) for a, b in zip(starts, ends)]


def _coalesce(intervals: Sequence[Tuple[float, float]]) -> Tuple[Tuple[float, float], ...]:
    """Sort and union overlapping/touching intervals."""
    out: List[List[float]] = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return tuple((float(s), float(e)) for s, e in out)


def _candidate(
    ftype: FlawType,
    start_s: float,
    end_s: float,
    z: np.ndarray,
    indices: Sequence[int],
    feature: str,
    flagged: Optional[Sequence[Tuple[float, float]]] = None,
) -> FlawCandidate:
    values = z[list(indices)]
    return FlawCandidate(
        type=ftype,
        start_s=float(start_s),
        end_s=float(end_s),
        peak_z=float(np.max(np.abs(values))),
        mean_z=float(np.mean(values)),
        detection_feature=feature,
        member_indices=tuple(int(i) for i in indices),
        flagged_intervals=_coalesce(flagged if flagged is not None else [(float(start_s), float(end_s))]),
    )


def _long_enough(duration_s: float, minimum: float) -> bool:
    return duration_s + _EPS_S >= minimum


def _rate_candidates(nb: NormalizedFeatureBundle, cfg: DetectionConfig) -> List[FlawCandidate]:
    z = nb.rate_z
    if len(z) == 0:
        return []
    half = nb.rate_effective_duration_s / 2.0
    starts, ends = nb.rate_times_s - half, nb.rate_times_s + half
    out: List[FlawCandidate] = []
    for ftype, mask in (
        (FlawType.TOO_FAST, z > cfg.z_rate_fast),
        (FlawType.TOO_SLOW, z < -cfg.z_rate_slow),
    ):
        minimum = cfg.min_duration_s[ftype]
        for i in np.flatnonzero(mask):
            if _long_enough(ends[i] - starts[i], minimum):
                out.append(_candidate(ftype, starts[i], ends[i], z, [int(i)], "rate_z"))
    return out


def _energy_candidates(nb: NormalizedFeatureBundle, cfg: DetectionConfig) -> List[FlawCandidate]:
    z = nb.energy_z
    if len(z) == 0 or nb.energy_hop_s is None:
        return []
    hop = nb.energy_hop_s
    times = nb.energy_times_s
    covered = np.flatnonzero(~np.isnan(z))
    out: List[FlawCandidate] = []
    for ftype, mask in (
        (FlawType.LOW_ENERGY, z < -cfg.z_energy),
        (FlawType.HIGH_ENERGY, z > cfg.z_energy),
    ):
        groups: List[List[int]] = []
        current: List[int] = []
        for pos in covered:
            if not mask[pos]:
                if current:
                    groups.append(current)
                    current = []
                continue
            if current and (times[pos] - times[current[-1]] - hop) + _EPS_S >= cfg.merge_gap_s:
                groups.append(current)
                current = []
            current.append(int(pos))
        if current:
            groups.append(current)

        minimum = cfg.min_duration_s[ftype]
        for members in groups:
            pieces = _contiguous_pieces(members)
            intervals = [(times[a] - hop / 2.0, times[b] + hop / 2.0) for a, b in pieces]
            if _long_enough(sum(e - s for s, e in intervals), minimum):
                out.append(
                    _candidate(ftype, intervals[0][0], intervals[-1][1], z, members, "energy_z", flagged=intervals)
                )
    return out


def _contiguous_pieces(indices: Sequence[int]) -> List[Tuple[int, int]]:
    """Split sorted indices into inclusive (first, last) pieces of consecutive integers."""
    pieces: List[Tuple[int, int]] = []
    first = prev = indices[0]
    for i in indices[1:]:
        if i != prev + 1:
            pieces.append((first, prev))
            first = i
        prev = i
    pieces.append((first, prev))
    return pieces


def _pause_candidates(nb: NormalizedFeatureBundle, cfg: DetectionConfig) -> List[FlawCandidate]:
    if not nb.pauses:
        return []
    z = np.array([p.z_score for p in nb.pauses], dtype=np.float64)
    minimum = cfg.min_duration_s[FlawType.EXCESSIVE_PAUSE]
    out: List[FlawCandidate] = []
    for i, p in enumerate(nb.pauses):
        if p.event.boundary_type == PauseBoundaryType.WITHIN_PHRASE:
            threshold = cfg.z_pause_within
        elif p.event.boundary_type == PauseBoundaryType.CROSS_SENTENCE:
            threshold = cfg.z_pause_cross
        else:
            continue
        if z[i] > threshold and _long_enough(p.event.end_s - p.event.start_s, minimum):
            out.append(_candidate(FlawType.EXCESSIVE_PAUSE, p.event.start_s, p.event.end_s, z, [i], "pause_z"))
    return out


def merge_candidates(
    candidates: Sequence[FlawCandidate], z_by_feature: Mapping[str, np.ndarray], merge_gap_s: float
) -> List[FlawCandidate]:
    """Merge same-type candidates that overlap or whose gap is < `merge_gap_s`.

    A merged candidate spans the union of its parts, keeps the union of their flagged intervals,
    and recomputes peak_z / mean_z from the union of their flagged samples. `z_by_feature` maps
    `detection_feature` to its z array.
    """
    by_type: Dict[FlawType, List[FlawCandidate]] = {}
    for c in candidates:
        by_type.setdefault(c.type, []).append(c)

    merged: List[FlawCandidate] = []
    for ftype in sorted(by_type, key=lambda t: t.value):
        group = sorted(by_type[ftype], key=lambda c: (c.start_s, c.end_s))
        current = [group[0]]
        for cand in group[1:]:
            current_end = max(c.end_s for c in current)
            if cand.start_s - current_end < merge_gap_s:
                current.append(cand)
            else:
                merged.append(_combine(current, z_by_feature))
                current = [cand]
        merged.append(_combine(current, z_by_feature))
    return merged


def _combine(parts: Sequence[FlawCandidate], z_by_feature: Mapping[str, np.ndarray]) -> FlawCandidate:
    if len(parts) == 1:
        return parts[0]
    feature = parts[0].detection_feature
    indices = sorted({i for c in parts for i in c.member_indices})
    return _candidate(
        parts[0].type,
        min(c.start_s for c in parts),
        max(c.end_s for c in parts),
        z_by_feature[feature],
        indices,
        feature,
        flagged=[iv for c in parts for iv in c.flagged_intervals],
    )


def detect_candidates(
    normalized: NormalizedFeatureBundle, config: Optional[DetectionConfig] = None
) -> CandidateDetectionResult:
    """Generate, duration-filter and merge flaw candidates from normalized features.

    Raises:
        TypeError: `normalized` is not a `NormalizedFeatureBundle`.
    """
    if not isinstance(normalized, NormalizedFeatureBundle):
        raise TypeError(f"normalized must be a NormalizedFeatureBundle, got {type(normalized).__name__}")
    cfg = config or DetectionConfig()

    skipped: Dict[str, str] = {k.value: v for k, v in _P1_OR_UNSUPPORTED.items()}
    unavailable = normalized.unavailable
    for feature, types in (
        ("rate", (FlawType.TOO_FAST, FlawType.TOO_SLOW)),
        ("energy", (FlawType.LOW_ENERGY, FlawType.HIGH_ENERGY)),
        ("pauses", (FlawType.EXCESSIVE_PAUSE,)),
    ):
        if feature in unavailable:
            for ftype in types:
                skipped[ftype.value] = f"{feature} unavailable: {unavailable[feature]}"
    if normalized.energy_hop_s is None and len(normalized.energy_z) and "energy" not in unavailable:
        for ftype in (FlawType.LOW_ENERGY, FlawType.HIGH_ENERGY):
            skipped[ftype.value] = "energy frame hop unknown"

    raw: List[FlawCandidate] = []
    raw += _rate_candidates(normalized, cfg)
    raw += _energy_candidates(normalized, cfg)
    pause_candidates = _pause_candidates(normalized, cfg)

    z_by_feature = {"rate_z": normalized.rate_z, "energy_z": normalized.energy_z}
    final = merge_candidates(raw, z_by_feature, cfg.merge_gap_s)
    final += pause_candidates  # pauses are never merged; their floor was applied when they were created
    final.sort(key=lambda c: (c.start_s, c.end_s, c.type.value))
    return CandidateDetectionResult(candidates=final, skipped=skipped)
