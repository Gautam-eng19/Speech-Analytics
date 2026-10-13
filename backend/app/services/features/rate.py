"""Rolling-window speech-rate Feature Extraction Service (TASK-033).

Single canonical implementation of speech-rate extraction under
`backend/app/services/features/` (ARCHITECTURE.md §7.4, §9.4, §13.4;
DECISIONS.md DEC-020, DEC-P004).

Algorithm (DEC-020):
    Rolling-window words-per-minute over `AlignedTranscript.words`:

        rate_wpm(window)     = n_words_in_window / effective_duration_s * 60
        effective_duration_s = max(word.end_s) - min(word.start_s)   (words in window)

    It is NOT derived from individual word durations (explicitly forbidden: too noisy).

Amendment (DEC-039): a silence longer than ``max_gap_s`` (default 1.0 s) between two words is counted as
``max_gap_s`` when the rate is computed, so a deliberate long pause is reported by pause detection and does
not also make the surrounding window look slow. The window's span (``effective_duration_s``, used to
place findings in time) is unchanged; the rate divides by ``speaking_duration_s`` = span minus the part of
each gap beyond ``max_gap_s``. Gaps up to ``max_gap_s`` (all natural pauses) count in full, as before.

Implementation choices where DEC-020 / §13.4 are silent (documented here, to be
confirmed by the team leader):
    * Window grid: window k covers ``[k * step_s, k * step_s + window_s)`` in
      processed-audio time, for k = 0 .. while ``k * step_s <= last word start``.
      Window starts are computed by multiplication (not accumulated addition) so the
      grid is exactly reproducible.
    * Membership: a word belongs to a window when ``window_start <= word.start_s <
      window_end``. A word can therefore appear in several overlapping windows
      (``window_s / step_s`` of them), and a word that straddles the window end is
      still counted whole.
    * Time axis: each rate value is reported at the midpoint of its effective span,
      ``(min word.start_s + max word.end_s) / 2`` — the time the measurement actually
      describes — not at the nominal window centre (which can lie beyond the speech
      for tail windows). The nominal window bounds are kept alongside for grounding.
    * Windows with fewer than ``min_words`` words, or with a non-positive effective
      duration, are skipped (no value is invented).
    * If fewer than ``min_windows`` valid windows exist the whole analysis is
      reported as skipped (``skipped=True`` with a reason and empty arrays), as
      §13.4 requires; callers must not treat a skipped result as "normal rate".

Words with missing or non-finite timestamps are never used and never guessed; their
number is reported in ``n_words_unaligned``.

Stateless & extraction only: no normalization, baseline comparison or flaw detection.
Units: seconds and words per minute. All times are processed-audio time.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np


@dataclass(frozen=True)
class RateConfig:
    """Explicit configuration for rolling-window speech rate.

    Defaults are the PROPOSED values of ARCHITECTURE.md §13.4 / DEC-020 (not calibrated):
    window_s=8.0, step_s=4.0, min_words=5, min_windows=2; ``max_gap_s=1.0`` is DEC-039.
    """

    window_s: float = 8.0
    step_s: float = 4.0
    min_words: int = 5
    min_windows: int = 2
    max_gap_s: float = 1.0

    def __post_init__(self) -> None:
        if not (math.isfinite(self.window_s) and self.window_s > 0.0):
            raise ValueError(f"window_s must be a positive finite number, got {self.window_s}")
        if not (math.isfinite(self.step_s) and self.step_s > 0.0):
            raise ValueError(f"step_s must be a positive finite number, got {self.step_s}")
        if self.min_words < 2:
            raise ValueError(
                f"min_words must be >= 2 (a rate needs a non-trivial span), got {self.min_words}"
            )
        if self.min_windows < 1:
            raise ValueError(f"min_windows must be >= 1, got {self.min_windows}")
        if not (math.isfinite(self.max_gap_s) and self.max_gap_s > 0.0):
            raise ValueError(f"max_gap_s must be a positive finite number, got {self.max_gap_s}")


def _empty_f64() -> np.ndarray:
    return np.empty(0, dtype=np.float64)


def _empty_i64() -> np.ndarray:
    return np.empty(0, dtype=np.int64)


@dataclass
class RateExtractionResult:
    """Rolling-window speech-rate measurements (one entry per valid window).

    Array attributes are index-aligned and empty when ``skipped`` is True.

    Attributes:
        times_s: Midpoint of each window's effective span, seconds.
        words_per_min: Speech rate per window, words per minute.
        window_start_s / window_end_s: Nominal window bounds, seconds.
        word_count: Number of words in each window.
        effective_duration_s: ``max(end) - min(start)`` of each window's words, seconds.
        speaking_duration_s: ``effective_duration_s`` minus the part of every gap longer than ``config.max_gap_s``;
            the duration the rate divides by.
        n_words_total: Words in the input transcript.
        n_words_unaligned: Words ignored because start or end time was missing/non-finite.
        n_valid_windows: Valid windows found (before applying ``min_windows``).
        skipped: True when no usable rate timeline could be produced.
        skip_reason: Machine-readable reason when skipped, else None.
        config: Snapshot of the configuration used.
    """

    config: RateConfig
    n_words_total: int = 0
    n_words_unaligned: int = 0
    n_valid_windows: int = 0
    skipped: bool = False
    skip_reason: Optional[str] = None
    times_s: np.ndarray = field(default_factory=_empty_f64)
    words_per_min: np.ndarray = field(default_factory=_empty_f64)
    window_start_s: np.ndarray = field(default_factory=_empty_f64)
    window_end_s: np.ndarray = field(default_factory=_empty_f64)
    word_count: np.ndarray = field(default_factory=_empty_i64)
    effective_duration_s: np.ndarray = field(default_factory=_empty_f64)
    speaking_duration_s: np.ndarray = field(default_factory=_empty_f64)

    @property
    def total_windows(self) -> int:
        """Number of rate values in the timeline."""
        return len(self.times_s)

    def to_timeline_dict(self) -> Dict[str, List[float]]:
        """Serialize to the API response `SpeechRateTimeline` shape (ARCHITECTURE.md §6.3)."""
        return {
            "times_s": [float(t) for t in self.times_s],
            "words_per_min": [float(v) for v in self.words_per_min],
        }

    def to_feature_bundle_dict(self) -> Dict[str, np.ndarray]:
        """Export fields matching the internal `FeatureBundle` (ARCHITECTURE.md §9.4)."""
        return {
            "rate_times_s": self.times_s.copy(),
            "rate_wpm": self.words_per_min.copy(),
        }


class RateExtractor:
    """Deterministic rolling-window speech-rate extractor."""

    def __init__(self, config: Optional[RateConfig] = None) -> None:
        self.config = config or RateConfig()

    def extract(self, aligned: Any) -> RateExtractionResult:
        """Compute the rate timeline from an `AlignedTranscript` (or any object with `.words`).

        Raises:
            TypeError: `aligned` has no `words` sequence.
        """
        words = getattr(aligned, "words", None)
        if not isinstance(words, (list, tuple)):
            raise TypeError(
                "Expected an AlignedTranscript (an object with a `words` list), "
                f"got {type(aligned).__name__}."
            )

        starts: List[float] = []
        ends: List[float] = []
        for w in words:
            s = getattr(w, "start_s", None)
            e = getattr(w, "end_s", None)
            if s is None or e is None or not (math.isfinite(s) and math.isfinite(e)):
                continue
            starts.append(float(s))
            ends.append(float(e))

        cfg = self.config
        result = RateExtractionResult(
            config=cfg,
            n_words_total=len(words),
            n_words_unaligned=len(words) - len(starts),
        )

        if not starts:
            result.skipped = True
            result.skip_reason = "no_aligned_words"
            return result

        start_arr = np.asarray(starts, dtype=np.float64)
        end_arr = np.asarray(ends, dtype=np.float64)

        n_grid = int(math.floor(float(start_arr.max()) / cfg.step_s)) + 1

        t_mid: List[float] = []
        wpm: List[float] = []
        w_start: List[float] = []
        w_end: List[float] = []
        counts: List[int] = []
        eff: List[float] = []
        speaking: List[float] = []

        for k in range(n_grid):
            ws = k * cfg.step_s
            we = ws + cfg.window_s
            member = (start_arr >= ws) & (start_arr < we)
            n = int(np.count_nonzero(member))
            if n < cfg.min_words:
                continue
            span_start = float(start_arr[member].min())
            span_end = float(end_arr[member].max())
            effective = span_end - span_start
            if not effective > 0.0:
                continue
            members = np.flatnonzero(member)
            gaps = start_arr[members[1:]] - end_arr[members[:-1]]
            beyond = float(np.clip(gaps - cfg.max_gap_s, 0.0, None).sum())      # silence beyond max_gap_s is not speaking time (DEC-039)
            speaking_s = effective - beyond
            if not speaking_s > 0.0:
                continue
            t_mid.append((span_start + span_end) / 2.0)
            wpm.append(n / speaking_s * 60.0)
            w_start.append(ws)
            w_end.append(we)
            counts.append(n)
            eff.append(effective)
            speaking.append(speaking_s)

        result.n_valid_windows = len(wpm)

        if len(wpm) < cfg.min_windows:
            result.skipped = True
            result.skip_reason = f"insufficient_windows: {len(wpm)} valid < min_windows {cfg.min_windows}"
            return result

        result.times_s = np.asarray(t_mid, dtype=np.float64)
        result.words_per_min = np.asarray(wpm, dtype=np.float64)
        result.window_start_s = np.asarray(w_start, dtype=np.float64)
        result.window_end_s = np.asarray(w_end, dtype=np.float64)
        result.word_count = np.asarray(counts, dtype=np.int64)
        result.effective_duration_s = np.asarray(eff, dtype=np.float64)
        result.speaking_duration_s = np.asarray(speaking, dtype=np.float64)
        return result


def extract_rate(aligned: Any, config: Optional[RateConfig] = None) -> RateExtractionResult:
    """Functional convenience entrypoint for speech-rate extraction."""
    return RateExtractor(config=config).extract(aligned)
