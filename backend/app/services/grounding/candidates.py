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

With a baseline that has a word profile (DEC-040) rate and loudness are not detected by the rules above but by comparing every word with the
baseline's reading of the same word (`profile_detection`): a finding is a run of words, so its boundaries are word boundaries, and the
rolling-window rate rule and the frame energy rule below are only the fallback for a baseline without a profile, or for a transcript that does
not match the passage. The result states which was used (`CandidateDetectionResult.modes`).

Intervals:
    * rate: the measured span of the flagged window (first word start .. last word end). The
      rolling window makes rate detection window-resolution (several seconds), so a short fast or slow
      stretch is first found as a much wider interval. When the aligned words and the baseline are
      given, each such interval is then NARROWED to the words that were really faster (slower)
      (`refine_rate_candidates`, DEC-039); without them, or when no run of words qualifies, the window
      interval is kept. Overlapping flagged windows merge into one interval before the narrowing.
    * energy: a run of consecutive flagged frames, from half a hop before the first frame to
      half a hop after the last, clipped to the span the frame centres cover (frames are centred, so
      the first centre is at 0 and the last at the end of the audio; without the clip a run touching
      either end would reach half a hop outside the recording and produce a negative start).
      Frames the baseline statistic does not cover (NaN z, e.g. pauses)
      are never flagged and break a run, so silence is not reported as "low energy".
    * pause: the pause event itself.

Pipeline (§17 order): [1] threshold -> [2] minimum-duration filter -> [3] merge
same-type windows whose gap is < MERGE_GAP_S -> [4] narrow rate intervals to the words that deviate
(DEC-039). Smoothing and hysteresis are P1 and absent.

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
      rate and energy findings and to MIN_PAUSE_FLAW_S (0.8 s, DEC-039) for pauses: a pause is a
      measured event that must exceed the baseline by a z threshold AND be long enough to be heard as
      a hesitation. Without the second condition a baseline whose pauses are all alike (a synthetic
      voice, a very even reader) turns every 0.3 to 0.5 s breath into an "excessive pause".
    * peak_z is the largest |z| among the flagged samples, mean_z their signed mean.
    * A rolling-window rate DETECTION is window-resolution, and overlapping flagged windows merge
      into one interval; step [4] exists because that made a flaw look several times longer than the
      actual behavior.
    * With a single reference recording the baseline rate spread rests on only a few windows
      and can be very small, which makes the rate z-score hypersensitive (see BaselineStatsRecord
      n_rate_windows).

Flat pitch (DEC-042) is judged only word by word, like the pace and the loudness: the pitch movement of the words against how much the baseline
readings moved on the same words. `BaselineStats` holds only the pooled global F0 std, which is not a valid reference for a local movement, so
without the word profile's pitch part (or when too few words have enough voiced speech) flat_pitch is reported in `skipped` with the reason.

Not covered, reported in `skipped`:
    * pitch_instability, reduced_clarity: P1 flaw types.
    * any type whose feature is unavailable in the bundle (with the reason).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from app.core.config import settings
from app.schemas.common import FlawType, PauseBoundaryType
from app.schemas.contracts import BaselineStatsRecord
from app.services.features.pause import _timed_words
from app.services.grounding.normalizer import NormalizedFeatureBundle
from app.services.grounding.profile import WordObservations
from app.services.grounding.profile_detection import ProfileDetection, RunFinding, detect_runs

_EPS_S = 1e-9


def _default_min_durations() -> Dict[FlawType, float]:
    return {
        FlawType.TOO_FAST: settings.MIN_FLAW_DURATION_S,
        FlawType.TOO_SLOW: settings.MIN_FLAW_DURATION_S,
        FlawType.LOW_ENERGY: settings.MIN_FLAW_DURATION_S,
        FlawType.HIGH_ENERGY: settings.MIN_FLAW_DURATION_S,
        FlawType.EXCESSIVE_PAUSE: settings.MIN_PAUSE_FLAW_S,
        FlawType.FLAT_PITCH: settings.MIN_FLAW_DURATION_S,
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
    # Narrowing of rate intervals to the words that deviate (DEC-039): on/off and the fewest words a narrowed stretch may have.
    refine_rate: bool = settings.REFINE_RATE_BOUNDARIES
    refine_min_words: int = settings.REFINE_MIN_WORDS
    # Word-by-word comparison with the baseline's reading of the same words (DEC-040); see `profile_detection` for what each one does.
    use_profile: bool = settings.PROFILE_ENABLED
    z_run_rate: float = settings.Z_RUN_RATE
    z_run_energy: float = settings.Z_RUN_ENERGY
    run_min_words: int = settings.RUN_MIN_WORDS
    min_rate_change_pct: float = settings.MIN_RATE_CHANGE_PCT
    min_energy_change_db: float = settings.MIN_ENERGY_CHANGE_DB
    global_tempo_change_pct: float = settings.GLOBAL_TEMPO_CHANGE_PCT
    profile_min_coverage: float = settings.PROFILE_MIN_COVERAGE
    profile_min_usable_words: int = settings.PROFILE_MIN_USABLE_WORDS
    sigma_floor_rate_drift: float = settings.SIGMA_FLOOR_RATE_DRIFT
    sigma_floor_rate_word: float = settings.SIGMA_FLOOR_RATE_WORD
    sigma_floor_level_drift: float = settings.SIGMA_FLOOR_LEVEL_DRIFT_DB
    sigma_floor_level_word: float = settings.SIGMA_FLOOR_LEVEL_WORD_DB
    sigma_floor_tempo: float = settings.SIGMA_FLOOR_TEMPO
    # Flat pitch, judged word by word like the pace and the loudness (DEC-042).
    z_run_pitch: float = settings.Z_RUN_PITCH
    min_flat_pitch_change_pct: float = settings.MIN_FLAT_PITCH_CHANGE_PCT
    global_pitch_change_pct: float = settings.GLOBAL_PITCH_CHANGE_PCT
    sigma_floor_pitch_drift: float = settings.SIGMA_FLOOR_PITCH_DRIFT
    sigma_floor_pitch_word: float = settings.SIGMA_FLOOR_PITCH_WORD
    sigma_floor_pitch_scale: float = settings.SIGMA_FLOOR_PITCH_SCALE

    def __post_init__(self) -> None:
        if not (isinstance(self.refine_min_words, int) and self.refine_min_words >= 2):
            raise ValueError(f"refine_min_words must be an integer >= 2, got {self.refine_min_words}")
        if not (isinstance(self.run_min_words, int) and self.run_min_words >= 2):
            raise ValueError(f"run_min_words must be an integer >= 2, got {self.run_min_words}")
        if not (isinstance(self.profile_min_usable_words, int) and self.profile_min_usable_words >= 2):
            raise ValueError(f"profile_min_usable_words must be an integer >= 2, got {self.profile_min_usable_words}")
        for name in ("z_run_rate", "z_run_energy", "min_rate_change_pct", "min_energy_change_db", "global_tempo_change_pct"):
            value = getattr(self, name)
            if not (math.isfinite(value) and value > 0.0):
                raise ValueError(f"{name} must be a positive finite number, got {value}")
        if not (math.isfinite(self.profile_min_coverage) and 0.0 < self.profile_min_coverage <= 1.0):
            raise ValueError(f"profile_min_coverage must be in (0, 1], got {self.profile_min_coverage}")
        for name in ("sigma_floor_rate_drift", "sigma_floor_rate_word", "sigma_floor_level_drift", "sigma_floor_level_word", "sigma_floor_tempo",
                     "sigma_floor_pitch_drift", "sigma_floor_pitch_word", "sigma_floor_pitch_scale"):
            value = getattr(self, name)
            if not (math.isfinite(value) and value >= 0.0):
                raise ValueError(f"{name} must be a finite number >= 0, got {value}")
        if not (math.isfinite(self.z_run_pitch) and self.z_run_pitch > 0.0):
            raise ValueError(f"z_run_pitch must be a positive finite number, got {self.z_run_pitch}")
        for name in ("min_flat_pitch_change_pct", "global_pitch_change_pct"):
            value = getattr(self, name)
            if not (math.isfinite(value) and 0.0 < value < 100.0):
                raise ValueError(f"{name} must be between 0 and 100 (percent less pitch movement than the baseline), got {value}")
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
        stretch_rate_wpm: set only for a rate candidate narrowed to a run of words (DEC-039): the speech
            rate of that run, words per minute. Then `mean_z` is the z-score of THIS rate (not of the
            windows), `member_indices` still name the windows that triggered the detection.
        effect: the measured size of the change, in the unit severity scales it in (DEC-040): the natural-log ratio of
            durations for a pace finding, dB for a loudness finding, seconds beyond the baseline's mean for a pause. None
            for a finding of the fallback rules, whose severity then comes from the z-score alone.
        run: set for a finding of the word-by-word comparison (DEC-040): the run of words with its measured and expected values.
            Then `member_indices` are indices of the aligned words, not of windows or frames, and `mean_z` / `peak_z` are the run's z-score.
    """

    type: FlawType
    start_s: float
    end_s: float
    peak_z: float
    mean_z: float
    detection_feature: str
    member_indices: Tuple[int, ...]
    flagged_intervals: Tuple[Tuple[float, float], ...]
    stretch_rate_wpm: Optional[float] = None
    effect: Optional[float] = None
    run: Optional[RunFinding] = None

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
    """Candidates (sorted by start, end, type), the flaw types that could not be evaluated, and the
    `DetectionConfig` that produced them (so later stages state exactly the rule that was applied)."""

    candidates: List[FlawCandidate]
    skipped: Dict[str, str]
    config: "DetectionConfig" = None  # type: ignore[assignment]
    # How pace and loudness were judged: "profile" (word by word against the baseline's reading of the same words) or the fallback ("windows"
    # for pace, "frames" for loudness). `profile_note` says why the profile was not used when the baseline has one.
    modes: Dict[str, str] = field(default_factory=dict)
    profile_note: Optional[str] = None
    # Why flat pitch was not judged word by word (a key of `_PITCH_NOT_JUDGED`), when it was not.
    pitch_note: Optional[str] = None


_P1_OR_UNSUPPORTED = {
    FlawType.PITCH_INSTABILITY: "not implemented: it needs recordings of unstable pitch to calibrate against",
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
    span_start, span_end = float(times[0]), float(times[-1])    # frames are centred: this is the audio's extent
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
            intervals = [
                (max(span_start, times[a] - hop / 2.0), min(span_end, times[b] + hop / 2.0)) for a, b in pieces
            ]
            intervals = [(s, e) for s, e in intervals if e > s]       # a lone frame on a one-frame timeline has no extent
            if intervals and _long_enough(sum(e - s for s, e in intervals), minimum):
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
            candidate = _candidate(FlawType.EXCESSIVE_PAUSE, p.event.start_s, p.event.end_s, z, [i], "pause_z")
            out.append(replace(candidate, effect=float(p.event.duration_s - p.baseline_mean_s)))
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


def _best_run(scores: np.ndarray) -> Optional[Tuple[int, int]]:
    """Inclusive (first, last) of the contiguous run with the largest positive sum (maximum-subarray; the earliest wins a tie)."""
    best_sum, best = 0.0, None
    current, start = 0.0, 0
    for i, value in enumerate(scores):
        if current <= 0.0:
            current, start = float(value), i
        else:
            current += float(value)
        if current > best_sum + 1e-12:
            best_sum, best = current, (start, i)
    return best


def refine_rate_candidates(
    candidates: Sequence[FlawCandidate],
    normalized: NormalizedFeatureBundle,
    aligned: object,
    baseline: BaselineStatsRecord,
    cfg: DetectionConfig,
) -> List[FlawCandidate]:
    """Narrow each too_fast / too_slow candidate to the words that really deviate (DEC-039).

    Why: the rate is measured in rolling windows, so a flagged window is as long as the window (8 s) and neighbouring flagged windows merge:
    a 3 s fast sentence was reported as a 10 to 16 s stretch. Per-word durations are too noisy to DETECT a flaw (DEC-020), but they are good
    enough to LOCATE one inside a region that the windows already flagged.

    Method (deterministic, no free parameter besides `refine_min_words`):
      * every word gets a "slot": the time from its start to the start of the next word (a pause after it counts, up to the rate extractor's cap on a
        gap, DEC-039), so a fast stretch has short slots;
      * the reference slot is the baseline's (60 / mean rate); the window with the largest deviation gives the peak slot (60 / its rate);
        a word counts for the flaw by how far its slot lies beyond the HALFWAY slot between the two (halfway slot minus slot for too_fast, the
        reverse for too_slow);
      * the stretch is the run of consecutive words inside the flagged region with the largest summed score (maximum-subarray), which tolerates the
        odd long or short word; the same is repeated on what is left of the region, so two separate stretches stay two findings;
      * a run is accepted only if it has at least `refine_min_words` words, lasts at least the minimum duration, and its OWN rate (words / span, the
        definition of DEC-020) is beyond the same z threshold as the windows. If no run qualifies, the window candidate is kept unchanged.
    A short stretch varies more than an 8 s window (fewer words to average over), so its z-score uses the baseline's window spread scaled for the
    length: ``z = (rate - mean) / (std * sqrt(max(1, window_words / stretch_words)))`` with ``window_words = mean * window_s / 60``. Without that
    scaling the best five words of ordinary speech would look like a flaw. The narrowed candidate carries the run's rate and this z-score, so the
    evidence describes the span it labels.
    """
    mu, sigma = baseline.rate_wpm_mean, baseline.rate_wpm_std
    timed, _ = _timed_words(aligned)
    if not (len(timed) >= cfg.refine_min_words and math.isfinite(mu) and mu > 0.0 and math.isfinite(sigma) and sigma > 0.0):
        return list(candidates)
    starts = np.array([s for _, s, _ in timed], dtype=np.float64)
    ends = np.array([e for _, _, e in timed], dtype=np.float64)
    window_s = float(np.median(normalized.rate_window_end_s - normalized.rate_window_start_s)) if len(normalized.rate_window_end_s) else 0.0
    window_words = mu * window_s / 60.0       # words in a typical baseline window: what a stretch's rate is compared against
    cap = normalized.rate_max_gap_s if normalized.rate_max_gap_s is not None else float("inf")
    beyond = np.zeros(len(timed), dtype=np.float64)           # silence after each word beyond the cap: not speaking time (DEC-039)
    beyond[:-1] = np.clip(starts[1:] - ends[:-1] - cap, 0.0, None)
    slots = np.empty(len(timed), dtype=np.float64)
    slots[:-1] = starts[1:] - starts[:-1]
    slots[-1] = ends[-1] - starts[-1]
    slots -= beyond
    silent_before = np.concatenate(([0.0], np.cumsum(beyond)))     # silent_before[k]: silence beyond the cap after words 0..k-1

    out: List[FlawCandidate] = []
    for parent in candidates:
        if parent.type not in (FlawType.TOO_FAST, FlawType.TOO_SLOW) or parent.detection_feature != "rate_z" or not parent.member_indices:
            out.append(parent)
            continue
        fast = parent.type == FlawType.TOO_FAST
        z_windows = normalized.rate_z[list(parent.member_indices)]
        peak_rate = mu + (float(np.max(z_windows)) if fast else float(np.min(z_windows))) * sigma
        inside = np.flatnonzero((starts >= parent.start_s - _EPS_S) & (ends <= parent.end_s + _EPS_S))
        if not peak_rate > 0.0 or len(inside) < cfg.refine_min_words:
            out.append(parent)
            continue
        halfway = (60.0 / mu + 60.0 / peak_rate) / 2.0
        scores = (halfway - slots) if fast else (slots - halfway)
        minimum = cfg.min_duration_s[parent.type]

        def accepted(a: int, b: int) -> Optional[Tuple[float, float]]:
            n, span = b - a + 1, float(ends[b] - starts[a]) - float(silent_before[b] - silent_before[a])
            if n < cfg.refine_min_words or span <= 0.0 or not _long_enough(span, minimum):
                return None
            rate = 60.0 * n / span
            z = (rate - mu) / (sigma * math.sqrt(max(1.0, window_words / n)))
            return (rate, z) if (z > cfg.z_rate_fast if fast else z < -cfg.z_rate_slow) else None

        runs: List[Tuple[int, int, float, float]] = []
        pending = [(int(inside[0]), int(inside[-1]) + 1)]
        while pending:
            lo, hi = pending.pop()
            if hi - lo < cfg.refine_min_words:
                continue
            best = _best_run(scores[lo:hi])
            if best is None:
                continue
            a, b = lo + best[0], lo + best[1]
            verdict = accepted(a, b)
            if verdict is None:
                continue
            runs.append((a, b, verdict[0], verdict[1]))
            pending += [(lo, a), (b + 1, hi)]
        if not runs:
            out.append(parent)
            continue
        for a, b, rate, z in sorted(runs):
            start, end = float(starts[a]), float(ends[b])
            out.append(FlawCandidate(
                type=parent.type, start_s=start, end_s=end, peak_z=max(abs(parent.peak_z), abs(z)), mean_z=float(z),
                detection_feature="rate_z", member_indices=parent.member_indices, flagged_intervals=((start, end),),
                stretch_rate_wpm=float(rate),
            ))
    return out


_RUN_TYPES = {
    ("rate", True): FlawType.TOO_FAST,
    ("rate", False): FlawType.TOO_SLOW,
    ("energy", True): FlawType.HIGH_ENERGY,
    ("energy", False): FlawType.LOW_ENERGY,
    ("pitch", False): FlawType.FLAT_PITCH,
}
_RUN_FEATURE = {"rate_run": "rate_run_z", "rate_overall": "rate_overall_z", "energy_run": "energy_run_z", "pitch_run": "pitch_run_z",
                "pitch_overall": "pitch_overall_z"}
_PITCH_NOT_JUDGED = {
    "transcript_mismatch": "the words of the recording do not match the passage well enough to compare them word by word",
    "baseline_without_pitch_profile": "the baseline has no pitch profile (rebuild it with the current tools)",
    "pitch_not_measured": "the pitch of the words was not measured",
    "too_few_pitch_words": "too few words had enough voiced speech to compare their pitch with the baseline's",
}


def _profile_candidates(result: ProfileDetection) -> List[FlawCandidate]:
    """FlawCandidates for the runs the word profile found (rate: positive z = faster; energy: positive z = louder; pitch: negative z = flatter)."""
    out: List[FlawCandidate] = []
    for findings in (result.rate or [], result.energy or [], result.pitch or []):
        for run in findings:
            signal = run.kind.split("_")[0]
            out.append(FlawCandidate(
                type=_RUN_TYPES[(signal, run.z > 0.0)], start_s=run.start_s, end_s=run.end_s, peak_z=abs(run.z), mean_z=run.z,
                detection_feature=_RUN_FEATURE[run.kind], member_indices=run.word_indices,
                flagged_intervals=((run.start_s, run.end_s),), effect=run.effect, run=run,
            ))
    return out


def detect_candidates(
    normalized: NormalizedFeatureBundle,
    config: Optional[DetectionConfig] = None,
    *,
    aligned: object = None,
    baseline: Optional[BaselineStatsRecord] = None,
    observations: Optional[WordObservations] = None,
) -> CandidateDetectionResult:
    """Generate, duration-filter and merge flaw candidates from normalized features.

    With `observations` (the measured words of the reading, `profile.measure_words`) and a `baseline` that has a word profile, pace and loudness
    are judged word by word against the baseline's reading of the same words (DEC-040) when `config.use_profile` is on and the words match the
    passage; the rolling-window rate rule and the frame energy rule then do not run. Otherwise those two rules run as before, and with `aligned`
    and `baseline` and `config.refine_rate` the rate candidates are narrowed to the words that deviate (`refine_rate_candidates`, DEC-039);
    without them the window intervals are returned as before.

    Raises:
        TypeError: `normalized` is not a `NormalizedFeatureBundle`.
    """
    if not isinstance(normalized, NormalizedFeatureBundle):
        raise TypeError(f"normalized must be a NormalizedFeatureBundle, got {type(normalized).__name__}")
    cfg = config or DetectionConfig()

    word_profile = getattr(baseline, "word_profile", None) if baseline is not None else None
    profile_result: Optional[ProfileDetection] = None
    profile_note: Optional[str] = None
    pitch_note: Optional[str] = None
    if cfg.use_profile and observations is not None and baseline is not None:
        if baseline.sha256 != normalized.baseline_sha256:
            raise ValueError("the baseline given for the word profile is not the one the features were normalized with")
        if word_profile is None:
            profile_note, pitch_note = "baseline_without_profile", "baseline_without_pitch_profile"
        else:
            profile_result = detect_runs(observations, word_profile, cfg)
            if profile_result.rate is None and profile_result.energy is None:
                profile_note = profile_result.reason
                if profile_result.pitch is None:
                    pitch_note = profile_result.pitch_reason
                    profile_result = None
    rate_by_profile = profile_result is not None and profile_result.rate is not None
    energy_by_profile = profile_result is not None and profile_result.energy is not None
    pitch_by_profile = profile_result is not None and profile_result.pitch is not None
    if profile_result is not None and not pitch_by_profile:
        pitch_note = profile_result.pitch_reason

    skipped: Dict[str, str] = {k.value: v for k, v in _P1_OR_UNSUPPORTED.items()}
    if not pitch_by_profile:
        why = _PITCH_NOT_JUDGED.get(pitch_note or "")
        skipped[FlawType.FLAT_PITCH.value] = (
            f"{why}" if why else
            "pitch is judged word by word against the baseline's reading of the same words, which needs the word profile with its pitch part and the "
            "measured words (use_profile, a baseline built with the current tools)"
        )
    unavailable = normalized.unavailable
    for feature, types, by_profile in (
        ("rate", (FlawType.TOO_FAST, FlawType.TOO_SLOW), rate_by_profile),
        ("energy", (FlawType.LOW_ENERGY, FlawType.HIGH_ENERGY), energy_by_profile),
        ("pauses", (FlawType.EXCESSIVE_PAUSE,), False),
    ):
        if feature in unavailable and not by_profile:
            for ftype in types:
                skipped[ftype.value] = f"{feature} unavailable: {unavailable[feature]}"
    if normalized.energy_hop_s is None and len(normalized.energy_z) and "energy" not in unavailable and not energy_by_profile:
        for ftype in (FlawType.LOW_ENERGY, FlawType.HIGH_ENERGY):
            skipped[ftype.value] = "energy frame hop unknown"

    raw: List[FlawCandidate] = []
    if not rate_by_profile:
        raw += _rate_candidates(normalized, cfg)
    if not energy_by_profile:
        raw += _energy_candidates(normalized, cfg)
    pause_candidates = _pause_candidates(normalized, cfg)

    z_by_feature = {"rate_z": normalized.rate_z, "energy_z": normalized.energy_z}
    final = merge_candidates(raw, z_by_feature, cfg.merge_gap_s)
    if cfg.refine_rate and not rate_by_profile and aligned is not None and baseline is not None and len(normalized.rate_z):
        if baseline.sha256 != normalized.baseline_sha256:
            raise ValueError("the baseline given for refinement is not the one the features were normalized with")
        final = refine_rate_candidates(final, normalized, aligned, baseline, cfg)
    if profile_result is not None:
        final += _profile_candidates(profile_result)
    final += pause_candidates  # pauses are never merged; their floor was applied when they were created
    final.sort(key=lambda c: (c.start_s, c.end_s, c.type.value))
    modes = {"rate": "profile" if rate_by_profile else "windows", "energy": "profile" if energy_by_profile else "frames",
             "pitch": "profile" if pitch_by_profile else "not judged"}
    return CandidateDetectionResult(candidates=final, skipped=skipped, config=cfg, modes=modes, profile_note=profile_note, pitch_note=pitch_note)
