"""Pause detection Feature Extraction Service.

Single canonical implementation of pause detection under
`backend/app/services/features/`.

Two independent signals, either of which alone is sufficient:

    Signal A — energy VAD:
        frame is "unvoiced" if ``energy_db < vad_energy_threshold_dbfs``; a candidate is a
        contiguous run of such frames lasting ``>= vad_min_pause_s``.
    Signal B — alignment gap:
        gap between consecutive aligned words, ``next.start_s - prev.end_s``, is a
        candidate when ``>= align_min_gap_s``.

Combination:
    * candidates that AGREE are merged into one event with ``detection_source="both"``;
    * a candidate with no agreeing partner becomes a ``"vad"`` or ``"alignment"`` event.

Implementation choices (documented here):
    * "Agree (overlap > 50 %)" is measured against the SHORTER of the two intervals:
      ``overlap > agreement_overlap_fraction * min(len_vad, len_gap)`` (strict).
    * A merged ("both") event spans the UNION of the agreeing intervals. Agreement is
      transitive, so one long VAD run covering two alignment gaps yields one event.
    * Candidates that overlap by less than the agreement fraction stay separate events,
      so two events can overlap in time in that rare case.
    * Duration thresholds are inclusive (``>=``) with a 1e-9 s tolerance so a pause
      exactly on the threshold is not lost to floating-point rounding.
    * VAD runs that touch the first or last energy frame are ignored: they are
      leading/trailing silence, not a pause between stretches of speech.
    * Boundary type: let ``m`` be the pause midpoint. If ``m`` lies strictly inside a
      timed word -> ``within_phrase``. Otherwise take the timed word ending at/before
      ``m`` and the timed word starting at/after ``m``; if either is missing ->
      ``unknown``; if the preceding word's text ends in sentence-final punctuation
      (``.``, ``?`` or ``!``, optionally followed by closing quotes/brackets) ->
      ``cross_sentence``, else ``within_phrase``. Abbreviations such as "Dr." are
      therefore misclassified as sentence ends — a known limitation of a punctuation rule.

Not every silence is a flaw: this service only DETECTS and classifies pauses. Comparing
them with the baseline (excessive-pause logic) belongs to the grounding stage.

Preconditions: aligned words are in chronological order (see
`services.alignment.validate_alignment`). Words with missing or non-finite timings are
never used and never guessed; adjacent pairs involving them are counted in
``n_gap_pairs_skipped_unaligned``. All times are processed-audio time, in seconds.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core.config import settings
from app.schemas.common import PauseBoundaryType, PauseDetectionSource
from app.schemas.response import PauseEvent

_EPS_S = 1e-9
_SENTENCE_END_RE = re.compile(r"[.?!]+[\"'”’)\]}]*$")


@dataclass(frozen=True)
class PauseConfig:
    """Explicit configuration for pause detection.

    Defaults (PROPOSED values of, not calibrated):
    - vad_energy_threshold_dbfs: ``settings.VAD_ENERGY_THRESHOLD_DBFS`` (-50 dBFS)
    - vad_min_pause_s: 0.2
    - align_min_gap_s: 0.15
    - agreement_overlap_fraction: 0.5
    """

    vad_energy_threshold_dbfs: float = settings.VAD_ENERGY_THRESHOLD_DBFS
    vad_min_pause_s: float = 0.2
    align_min_gap_s: float = 0.15
    agreement_overlap_fraction: float = 0.5

    def __post_init__(self) -> None:
        if not math.isfinite(self.vad_energy_threshold_dbfs):
            raise ValueError(
                f"vad_energy_threshold_dbfs must be finite, got {self.vad_energy_threshold_dbfs}"
            )
        if not (math.isfinite(self.vad_min_pause_s) and self.vad_min_pause_s > 0.0):
            raise ValueError(f"vad_min_pause_s must be positive and finite, got {self.vad_min_pause_s}")
        if not (math.isfinite(self.align_min_gap_s) and self.align_min_gap_s > 0.0):
            raise ValueError(f"align_min_gap_s must be positive and finite, got {self.align_min_gap_s}")
        if not (0.0 <= self.agreement_overlap_fraction < 1.0):
            raise ValueError(
                f"agreement_overlap_fraction must be in [0.0, 1.0), got {self.agreement_overlap_fraction}"
            )


@dataclass
class PauseDetectionResult:
    """Detected pause events and detection diagnostics.

    Attributes:
        events: Pause events sorted by (start_s, end_s); API `PauseEvent` models.
        signals_used: Which signals were available: subset of ("vad", "alignment").
        n_vad_candidates: VAD candidates found before combination.
        n_alignment_candidates: Alignment-gap candidates found before combination.
        n_gap_pairs_skipped_unaligned: Adjacent word pairs skipped (missing timings).
        config: Snapshot of the configuration used.
    """

    events: List[PauseEvent]
    signals_used: Tuple[str, ...]
    n_vad_candidates: int
    n_alignment_candidates: int
    n_gap_pairs_skipped_unaligned: int
    config: PauseConfig

    def to_event_dicts(self) -> List[Dict[str, Any]]:
        """JSON-ready list matching the API `pause_events` shape."""
        return [e.model_dump(mode="json") for e in self.events]


Interval = Tuple[float, float]


def _overlap_s(a: Interval, b: Interval) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def _vad_candidates(energy: Any, cfg: PauseConfig) -> List[Interval]:
    """Signal A: contiguous low-energy runs bounded by non-silent frames on both sides."""
    times = np.asarray(energy.times_s, dtype=np.float64)
    values = np.asarray(energy.values_db, dtype=np.float64)
    if times.ndim != 1 or times.shape != values.shape:
        raise ValueError("energy.times_s and energy.values_db must be 1D arrays of equal length")
    n = len(values)
    if n == 0:
        return []

    hop_s = float(energy.hop_s)
    low = values < cfg.vad_energy_threshold_dbfs

    padded = np.concatenate(([False], low, [False])).astype(np.int8)
    edges = np.diff(padded)
    run_starts = np.flatnonzero(edges == 1)
    run_ends = np.flatnonzero(edges == -1) - 1  # inclusive last low frame

    out: List[Interval] = []
    for i0, i1 in zip(run_starts, run_ends):
        if i0 == 0 or i1 == n - 1:
            continue  # leading / trailing silence, not a pause between speech
        duration = (int(i1) - int(i0) + 1) * hop_s
        if duration + _EPS_S < cfg.vad_min_pause_s:
            continue
        out.append((float(times[i0]) - hop_s / 2.0, float(times[i1]) + hop_s / 2.0))
    return out


def _timed_words(aligned: Any) -> Tuple[List[Tuple[str, float, float]], List[Optional[Tuple[str, float, float]]]]:
    """Return (timed words in order, per-word entries with None for untimed words)."""
    words = getattr(aligned, "words", None)
    if not isinstance(words, (list, tuple)):
        raise TypeError(
            "Expected an AlignedTranscript (an object with a `words` list), "
            f"got {type(aligned).__name__}."
        )
    per_word: List[Optional[Tuple[str, float, float]]] = []
    for w in words:
        s = getattr(w, "start_s", None)
        e = getattr(w, "end_s", None)
        if s is None or e is None or not (math.isfinite(s) and math.isfinite(e)):
            per_word.append(None)
        else:
            per_word.append((str(getattr(w, "word", "")), float(s), float(e)))
    return [w for w in per_word if w is not None], per_word


def _alignment_candidates(
    per_word: List[Optional[Tuple[str, float, float]]], cfg: PauseConfig
) -> Tuple[List[Interval], int]:
    """Signal B: gaps between consecutive aligned words."""
    out: List[Interval] = []
    skipped = 0
    for prev, nxt in zip(per_word, per_word[1:]):
        if prev is None or nxt is None:
            skipped += 1
            continue
        gap_start, gap_end = prev[2], nxt[1]
        if gap_end - gap_start + _EPS_S >= cfg.align_min_gap_s and gap_end > gap_start:
            out.append((gap_start, gap_end))
    return out, skipped


def _classify_boundary(interval: Interval, timed: List[Tuple[str, float, float]]) -> PauseBoundaryType:
    mid = (interval[0] + interval[1]) / 2.0
    for _, w_start, w_end in timed:
        if w_start < mid < w_end:
            return PauseBoundaryType.WITHIN_PHRASE
    prev_word: Optional[str] = None
    prev_end = -math.inf
    has_next = False
    for text, w_start, w_end in timed:
        if w_end <= mid and w_end >= prev_end:
            prev_word, prev_end = text, w_end
        if w_start >= mid:
            has_next = True
    if prev_word is None or not has_next:
        return PauseBoundaryType.UNKNOWN
    if _SENTENCE_END_RE.search(prev_word.strip()):
        return PauseBoundaryType.CROSS_SENTENCE
    return PauseBoundaryType.WITHIN_PHRASE


class PauseDetector:
    """Deterministic pause detector combining energy VAD and alignment gaps."""

    def __init__(self, config: Optional[PauseConfig] = None) -> None:
        self.config = config or PauseConfig()

    def detect(self, aligned: Any = None, energy: Any = None) -> PauseDetectionResult:
        """Detect pauses.

        Args:
            aligned: `AlignedTranscript` (signal B and boundary classification), or None.
            energy: `EnergyExtractionResult` (signal A), or None.

        At least one of the two must be provided; the other signal is then simply
        unavailable (reported in ``signals_used``), never assumed to have found nothing.

        Raises:
            ValueError: neither input provided, or malformed energy arrays.
            TypeError: `aligned` / `energy` are not of the expected shape.
        """
        if aligned is None and energy is None:
            raise ValueError("detect() needs at least one of `aligned` or `energy`.")
        if energy is not None and not all(hasattr(energy, a) for a in ("times_s", "values_db", "hop_s")):
            raise TypeError(
                "Expected an EnergyExtractionResult (with times_s, values_db, hop_s), "
                f"got {type(energy).__name__}."
            )

        cfg = self.config
        signals: List[str] = []

        vad: List[Interval] = []
        if energy is not None:
            signals.append("vad")
            vad = _vad_candidates(energy, cfg)

        gaps: List[Interval] = []
        skipped = 0
        timed: List[Tuple[str, float, float]] = []
        if aligned is not None:
            signals.append("alignment")
            timed, per_word = _timed_words(aligned)
            gaps, skipped = _alignment_candidates(per_word, cfg)

        # Union-find over candidates; edge = the two signals agree.
        nodes: List[Tuple[str, Interval]] = [("vad", iv) for iv in vad] + [("alignment", iv) for iv in gaps]
        parent = list(range(len(nodes)))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(len(vad)):
            for j in range(len(vad), len(nodes)):
                a, b = nodes[i][1], nodes[j][1]
                overlap = _overlap_s(a, b)
                shorter = min(a[1] - a[0], b[1] - b[0])
                if overlap > 0.0 and overlap > cfg.agreement_overlap_fraction * shorter:
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        parent[max(ri, rj)] = min(ri, rj)

        groups: Dict[int, List[int]] = {}
        for idx in range(len(nodes)):
            groups.setdefault(find(idx), []).append(idx)

        events: List[PauseEvent] = []
        for members in groups.values():
            kinds = {nodes[i][0] for i in members}
            start = min(nodes[i][1][0] for i in members)
            end = max(nodes[i][1][1] for i in members)
            if kinds == {"vad", "alignment"}:
                source = PauseDetectionSource.BOTH
            elif kinds == {"vad"}:
                source = PauseDetectionSource.VAD
            else:
                source = PauseDetectionSource.ALIGNMENT
            events.append(
                PauseEvent(
                    start_s=start,
                    end_s=end,
                    duration_s=end - start,
                    detection_source=source,
                    boundary_type=_classify_boundary((start, end), timed),
                )
            )
        events.sort(key=lambda e: (e.start_s, e.end_s, e.detection_source.value))

        return PauseDetectionResult(
            events=events,
            signals_used=tuple(signals),
            n_vad_candidates=len(vad),
            n_alignment_candidates=len(gaps),
            n_gap_pairs_skipped_unaligned=skipped,
            config=cfg,
        )


def detect_pauses(
    aligned: Any = None,
    energy: Any = None,
    config: Optional[PauseConfig] = None,
) -> PauseDetectionResult:
    """Functional convenience entrypoint for pause detection."""
    return PauseDetector(config=config).detect(aligned=aligned, energy=energy)
