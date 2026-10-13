"""Baseline-relative feature normalization (TASK-041; ARCHITECTURE.md §14, §15, §9.6; DEC-010).

First stage of `services/grounding/`: turns participant feature timelines plus the passage's
`BaselineStatsRecord` into z-scores,

        z = (participant_value - baseline_mean) / baseline_std

so that the baseline is z = 0 and every deviation is expressed in baseline standard
deviations (the "contrastive" signal of the next stage).

This is baseline-relative normalization, NOT speaker adaptation: a participant whose habitual
pitch or loudness differs from the baseline speaker shows a systematic offset (documented
limitation, ARCHITECTURE.md §14.2). Optional participant calibration is a P1 feature and is not
applied here.

Rules (all deterministic, no thresholds, no scoring):
    * Missing stays missing. A value that has no meaningful z-score is NaN, never 0:
      unvoiced F0 frames, energy frames the baseline statistic does not cover, pauses of
      unknown boundary type, and any feature whose baseline spread is unusable.
    * Energy uses EXACTLY the frame rule the baseline statistics were built with. The rule
      and its threshold are read from `baseline.config_snapshot`
      (`energy_frame_selection`, `energy_active_threshold_dbfs`): with "active", frames below
      the threshold (pauses) get NaN so that silence is not scored as "low energy" against a
      speaking-level baseline; with "all", every frame is scored.
    * Zero-variance handling: a baseline std that is not finite or not strictly positive makes
      that feature's z-scores undefined. All its values are NaN and the reason is reported in
      `NormalizedFeatureBundle.unavailable`; no epsilon floor is invented.
    * A feature that was not provided, or whose analysis was skipped (e.g. speech rate with too
      few windows), is reported in `unavailable` and yields empty arrays.
    * The baseline must pass `sha256` verification so every result can name the exact
      statistics it used (`baseline_sha256`).

Units are those of the inputs (Hz, dBFS, words/min, s); z-scores are dimensionless. All times
are processed-audio time and are passed through unchanged.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from app.schemas.common import PauseBoundaryType
from app.schemas.contracts import BaselineStatsRecord
from app.schemas.response import PauseEvent

ENERGY_FRAME_SELECTIONS = ("active", "all")


class NormalizationError(ValueError):
    """Raised when normalization cannot be performed (invalid baseline or inputs)."""


def z_score(values: np.ndarray, mean: float, std: float) -> np.ndarray:
    """Element-wise ``(values - mean) / std``; NaN inputs stay NaN.

    Raises:
        NormalizationError: ``std`` is not finite and strictly positive.
    """
    if not (math.isfinite(std) and std > 0.0):
        raise NormalizationError(f"std must be finite and > 0 to compute z-scores, got {std}")
    if not math.isfinite(mean):
        raise NormalizationError(f"mean must be finite, got {mean}")
    return (np.asarray(values, dtype=np.float64) - mean) / std


def _empty() -> np.ndarray:
    return np.empty(0, dtype=np.float64)


@dataclass(frozen=True)
class NormalizedPause:
    """A pause event with its z-score against the matching baseline pause statistics.

    z_score is NaN (with an explanatory `note`) when no baseline statistic applies: unknown
    boundary type, or the baseline has no usable spread for that boundary type.
    baseline_mean_s / baseline_std_s are the statistics used (NaN when not applicable).
    """

    event: PauseEvent
    z_score: float
    baseline_mean_s: float
    baseline_std_s: float
    note: Optional[str] = None


@dataclass
class NormalizedFeatureBundle:
    """Z-scored participant features (ARCHITECTURE.md §9.6).

    Array attributes are index-aligned with their `*_times_s` and are empty when the feature is
    unavailable (see `unavailable`). NaN marks "no meaningful z-score".

    Attributes:
        baseline_passage_id / baseline_sha256: identity of the statistics used.
        f0_times_s / f0_z: pitch z-scores; NaN on unvoiced frames.
        energy_times_s / energy_z: energy z-scores; NaN on frames outside the baseline's rule.
        energy_in_baseline_rule: bool mask of frames the baseline energy statistic covers.
        rate_times_s / rate_z: speech-rate z-score per rolling window, with the nominal window
            bounds in rate_window_start_s / rate_window_end_s. rate_effective_duration_s and
            rate_word_count pass through the extractor's per-window span and word count (the
            measured interval of window k is rate_times_s[k] +/- rate_effective_duration_s[k] / 2).
        rate_max_gap_s: the rate extractor's cap on a gap between words (DEC-039; None if unknown), needed to locate a finding the same way
            the rate was measured.
        energy_hop_s: frame hop of the energy timeline in seconds (None if not derivable).
        pauses: per-event pause z-scores (same order as the input events).
        unavailable: feature name -> machine-readable reason, for everything not normalized.
    """

    baseline_passage_id: str
    baseline_sha256: str
    f0_times_s: np.ndarray = field(default_factory=_empty)
    f0_z: np.ndarray = field(default_factory=_empty)
    energy_times_s: np.ndarray = field(default_factory=_empty)
    energy_z: np.ndarray = field(default_factory=_empty)
    energy_in_baseline_rule: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=bool))
    rate_times_s: np.ndarray = field(default_factory=_empty)
    rate_z: np.ndarray = field(default_factory=_empty)
    rate_window_start_s: np.ndarray = field(default_factory=_empty)
    rate_window_end_s: np.ndarray = field(default_factory=_empty)
    rate_effective_duration_s: np.ndarray = field(default_factory=_empty)
    rate_word_count: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    rate_max_gap_s: Optional[float] = None
    energy_hop_s: Optional[float] = None
    pauses: List[NormalizedPause] = field(default_factory=list)
    unavailable: Dict[str, str] = field(default_factory=dict)


def _usable_std(std: Optional[float]) -> bool:
    return std is not None and math.isfinite(std) and std > 0.0


def _energy_rule(baseline: BaselineStatsRecord) -> "tuple[str, float]":
    snap = baseline.config_snapshot
    selection = snap.get("energy_frame_selection")
    if selection not in ENERGY_FRAME_SELECTIONS:
        raise NormalizationError(
            f"baseline config_snapshot has no valid 'energy_frame_selection' (got {selection!r}); "
            "cannot reproduce the baseline's energy frame rule"
        )
    threshold = snap.get("energy_active_threshold_dbfs")
    if selection == "active":
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold):
            raise NormalizationError(
                "baseline config_snapshot has no finite 'energy_active_threshold_dbfs' "
                "but selects active energy frames"
            )
        return selection, float(threshold)
    return selection, float("-inf")


def normalize_features(
    baseline: BaselineStatsRecord,
    *,
    f0: Any = None,
    energy: Any = None,
    rate: Any = None,
    pauses: Optional[List[PauseEvent]] = None,
) -> NormalizedFeatureBundle:
    """Normalize participant features against `baseline`.

    Args:
        baseline: Verified `BaselineStatsRecord` (e.g. from `BaselineProvider.get`).
        f0: `F0ExtractionResult` (times_s, values_hz, voiced) or None.
        energy: `EnergyExtractionResult` (times_s, values_db) or None.
        rate: `RateExtractionResult` (times_s, words_per_min, window bounds, skipped) or None.
        pauses: pause events (`PauseDetectionResult.events`) or None.

    Features that are None are reported in ``unavailable`` rather than treated as normal.

    Raises:
        NormalizationError: baseline invalid / unverified, or inputs malformed.
        TypeError: `baseline` is not a `BaselineStatsRecord`.
    """
    if not isinstance(baseline, BaselineStatsRecord):
        raise TypeError(f"baseline must be a BaselineStatsRecord, got {type(baseline).__name__}")
    if not baseline.verify_sha256():
        raise NormalizationError(
            "baseline fails sha256 verification; load it through BaselineProvider or call "
            "with_computed_sha256() on a freshly built record"
        )

    out = NormalizedFeatureBundle(
        baseline_passage_id=baseline.passage_id, baseline_sha256=baseline.sha256
    )

    # ------------------------------------------------------------------ F0
    if f0 is None:
        out.unavailable["f0"] = "not_provided"
    else:
        times = np.asarray(f0.times_s, dtype=np.float64)
        values = np.asarray(f0.values_hz, dtype=np.float64)
        voiced = np.asarray(f0.voiced, dtype=bool)
        if not (times.ndim == values.ndim == voiced.ndim == 1 and len(times) == len(values) == len(voiced)):
            raise NormalizationError("F0 times_s, values_hz and voiced must be 1D arrays of equal length")
        out.f0_times_s = times.copy()
        if _usable_std(baseline.f0_voiced_hz_std):
            z = np.full(len(values), np.nan, dtype=np.float64)
            use = voiced & np.isfinite(values)
            z[use] = z_score(values[use], baseline.f0_voiced_hz_mean, baseline.f0_voiced_hz_std)
            out.f0_z = z
        else:
            out.f0_z = np.full(len(values), np.nan, dtype=np.float64)
            out.unavailable["f0"] = "baseline_std_not_positive"

    # -------------------------------------------------------------- energy
    if energy is None:
        out.unavailable["energy"] = "not_provided"
    else:
        times = np.asarray(energy.times_s, dtype=np.float64)
        values = np.asarray(energy.values_db, dtype=np.float64)
        if not (times.ndim == values.ndim == 1 and len(times) == len(values)):
            raise NormalizationError("energy times_s and values_db must be 1D arrays of equal length")
        _, threshold = _energy_rule(baseline)
        covered = np.isfinite(values) & (values >= threshold)
        out.energy_times_s = times.copy()
        out.energy_in_baseline_rule = covered
        hop = getattr(energy, "hop_s", None)
        if hop is None and len(times) >= 2:
            hop = float(np.median(np.diff(times)))
        out.energy_hop_s = None if hop is None else float(hop)
        z = np.full(len(values), np.nan, dtype=np.float64)
        if _usable_std(baseline.energy_db_std):
            z[covered] = z_score(values[covered], baseline.energy_db_mean, baseline.energy_db_std)
        else:
            out.unavailable["energy"] = "baseline_std_not_positive"
        out.energy_z = z

    # ---------------------------------------------------------------- rate
    if rate is None:
        out.unavailable["rate"] = "not_provided"
    elif getattr(rate, "skipped", False):
        out.unavailable["rate"] = f"rate_analysis_skipped: {getattr(rate, 'skip_reason', None)}"
    else:
        times = np.asarray(rate.times_s, dtype=np.float64)
        wpm = np.asarray(rate.words_per_min, dtype=np.float64)
        w_start = np.asarray(rate.window_start_s, dtype=np.float64)
        w_end = np.asarray(rate.window_end_s, dtype=np.float64)
        n_eff, n_cnt = len(rate.effective_duration_s), len(rate.word_count)
        if not (len(times) == len(wpm) == len(w_start) == len(w_end) == n_eff == n_cnt):
            raise NormalizationError("rate arrays must have equal length")
        out.rate_times_s = times.copy()
        out.rate_window_start_s = w_start.copy()
        out.rate_window_end_s = w_end.copy()
        out.rate_effective_duration_s = np.asarray(rate.effective_duration_s, dtype=np.float64).copy()
        out.rate_word_count = np.asarray(rate.word_count, dtype=np.int64).copy()
        cap = getattr(getattr(rate, "config", None), "max_gap_s", None)
        out.rate_max_gap_s = float(cap) if isinstance(cap, (int, float)) and math.isfinite(cap) else None
        if _usable_std(baseline.rate_wpm_std):
            out.rate_z = z_score(wpm, baseline.rate_wpm_mean, baseline.rate_wpm_std)
        else:
            out.rate_z = np.full(len(wpm), np.nan, dtype=np.float64)
            out.unavailable["rate"] = "baseline_std_not_positive"

    # --------------------------------------------------------------- pauses
    if pauses is None:
        out.unavailable["pauses"] = "not_provided"
    else:
        within_ok = _usable_std(baseline.pause_within_phrase_std_s)
        cross_ok = _usable_std(baseline.pause_cross_sentence_std_s)
        nan = float("nan")
        for ev in pauses:
            if ev.boundary_type == PauseBoundaryType.WITHIN_PHRASE:
                mean, std, ok = baseline.pause_within_phrase_mean_s, baseline.pause_within_phrase_std_s, within_ok
                missing = "baseline_within_phrase_std_not_positive"
            elif ev.boundary_type == PauseBoundaryType.CROSS_SENTENCE:
                mean, std, ok = baseline.pause_cross_sentence_mean_s, baseline.pause_cross_sentence_std_s, cross_ok
                missing = "baseline_cross_sentence_std_unavailable"
            else:
                out.pauses.append(
                    NormalizedPause(ev, nan, nan, nan, note="unknown_boundary_type: no baseline statistic applies")
                )
                continue
            if ok:
                out.pauses.append(
                    NormalizedPause(ev, float(z_score(np.array([ev.duration_s]), mean, std)[0]), mean, std)
                )
            else:
                out.pauses.append(NormalizedPause(ev, nan, mean, nan if std is None else std, note=missing))

    return out
