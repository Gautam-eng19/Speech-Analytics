"""Word profile: measuring the words of a reading, and building the baseline's profile from the baseline readings (DEC-040).

Why a profile
    The baseline is the effective delivery of ONE passage. Comparing a participant with only the baseline's overall averages (mean rate and
    its spread over 8 s windows) ignores which words are being compared: a stretch of long words is slow, a stretch of short ones is fast,
    in EVERY reading. On real recordings the same region of the passage came out at the same rate (139 words/min) in different takes, and was
    flagged in each of them. With the baseline recordings aligned to the same words, the expectation can be made for the same place in the
    text, and what is left to compare is the delivery.

What is measured, per aligned word (processed-audio time)
    * slot  : the time from the word's start to the start of the next word. A silence after the word counts, but at most `max_gap_s` of it
              (0.25 s): pace is how fast the words are spoken, and a pause is judged by pause detection, so a pause must not also make the
              words around it look slow (a 1 s breath inside a stretch of twelve words would otherwise slow that stretch by 15 %).
              The last word's slot is its own length. A slot shorter than `MIN_SLOT_S` is an alignment artefact and is not used.
    * level : the median level (dBFS) of the word's ACTIVE frames, those at or above the baseline's activity threshold. The median ignores the
              edge frames a loose alignment boundary pulls in; fewer than `MIN_ACTIVE_FRAMES` active frames give no level.

What the profile holds (`WordProfile`, stored in the baseline file)
    * the expected slot of every passage word (geometric mean over the baseline readings) and its expected level (mean over the readings after
      removing each reading's own overall offset);
    * the spread of a run of `n` consecutive words, `sigma(n) = sqrt(drift^2 + word^2 / n)`, for the rate and for the level, measured
      leave-one-out: each baseline reading is compared with the expectation built from the OTHER readings, so the spread describes a reading
      that was not used to build the expectation, which is what a participant is.
    * the spread of the overall pace between baseline readings.

Rate statistic: ``ln(sum of observed slots / sum of expected slots)`` over a run of words (positive = slower). Using totals, not an average of
per-word ratios, keeps short words, whose slots are mostly alignment noise, from dominating. Before any run is judged the reading's own overall
pace (`overall_tempo`, the median over runs of 10 words) is removed, so a speaker who is generally quicker or slower than the baseline readers
is compared with their OWN pace and only local departures stand out; a reading that is off as a whole is judged separately (profile_detection).

Level statistic: the word's level minus the profile's, minus the reading's own median difference, averaged over a run (positive = louder).
Recordings are scaled to a common speech level (DEC-036), so only the pattern within the reading is comparable, never the overall level.

Everything here is deterministic. The profile needs at least `PROFILE_MIN_TAKES` baseline readings that match the passage text; with fewer
none is built and the analysis falls back to the overall statistics.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from scipy.optimize import nnls

from app.schemas.contracts import NoiseModel, WordProfile

PROFILE_MIN_TAKES = 3            # baseline readings needed: the expectation of one is built from the other readings (at least two)
MIN_SLOT_S = 0.05                # a slot shorter than five frames is an alignment artefact, not a measurement
MIN_ACTIVE_FRAMES = 3            # active frames a word needs for a level
MIN_MAPPED_SHARE = 0.5           # share of a reading's timed words that must match the passage for the reading to count
TEMPO_WINDOW_WORDS = 10          # run length of the overall-pace estimate (median over runs of this many words)
NOISE_GRID = (6, 10, 16, 26, 40, 60)   # run lengths at which the spread is measured; sigma(n) is fitted through them
MIN_WINDOWS_PER_ROW = 5          # runs needed at one length before it counts for the fit
DECIMALS = 6                     # stored precision, so the baseline file and its hash do not depend on last-bit differences

_TOKEN_PARTS = re.compile(r"[a-z']+")


def clean_token(word: str) -> str:
    """A word reduced to lower-case letters and apostrophes (``"morning,"`` -> ``"morning"``); empty if it has none."""
    return "".join(_TOKEN_PARTS.findall(str(word).lower().replace("’", "'")))


def passage_tokens(text: str) -> List[str]:
    """The passage as the list of its cleaned words, in order (words without a letter are dropped)."""
    return [t for t in (clean_token(w) for w in str(text).split()) if t]


def map_to_passage(tokens: Sequence[str], passage: Sequence[str]) -> np.ndarray:
    """For every token, the index of the passage word it matches, or -1.

    The words are matched as two sequences (longest matching blocks), so a word the participant added, dropped or got wrong leaves only that
    word unmatched and the rest of the reading stays aligned with the passage. A reading of exactly the passage maps word i to word i.
    """
    kept = [i for i, t in enumerate(tokens) if t]
    out = np.full(len(tokens), -1, dtype=np.int64)
    if not kept or not passage:
        return out
    matcher = SequenceMatcher(None, [tokens[i] for i in kept], list(passage), autojunk=False)
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            out[kept[block.a + k]] = block.b + k
    return out


@dataclass(frozen=True)
class WordObservations:
    """What was measured on each aligned word of one reading (arrays are indexed like the aligned words; NaN = not measurable)."""

    tokens: Tuple[str, ...]
    start_s: np.ndarray
    end_s: np.ndarray
    slot_s: np.ndarray
    level_db: np.ndarray
    max_gap_s: float
    active_threshold_dbfs: float

    @property
    def n_words(self) -> int:
        return len(self.tokens)

    @property
    def n_timed(self) -> int:
        return int(np.count_nonzero(np.isfinite(self.start_s)))


def measure_words(aligned: Any, energy: Any, *, max_gap_s: float, active_threshold_dbfs: float) -> WordObservations:
    """Slot and level of every aligned word (see the module docstring).

    `aligned` is an `AlignedTranscript` (or anything with a `words` list); `energy` an `EnergyExtractionResult` (`times_s`, `values_db`).
    Words without a time, and a word followed by an untimed word, get no slot; they are never guessed.

    Raises:
        TypeError: `aligned` has no `words` list.
        ValueError: the energy arrays are not one-dimensional and equal in length, or a parameter is not usable.
    """
    words = getattr(aligned, "words", None)
    if not isinstance(words, (list, tuple)):
        raise TypeError(f"Expected an AlignedTranscript (an object with a `words` list), got {type(aligned).__name__}.")
    if not (math.isfinite(max_gap_s) and max_gap_s > 0.0):
        raise ValueError(f"max_gap_s must be a positive finite number, got {max_gap_s}")
    if not math.isfinite(active_threshold_dbfs):
        raise ValueError(f"active_threshold_dbfs must be finite, got {active_threshold_dbfs}")
    times = np.asarray(energy.times_s, dtype=np.float64)
    values = np.asarray(energy.values_db, dtype=np.float64)
    if times.ndim != 1 or times.shape != values.shape:
        raise ValueError("energy.times_s and energy.values_db must be 1D arrays of equal length")

    n = len(words)
    tokens = tuple(clean_token(getattr(w, "word", "")) for w in words)
    start = np.full(n, np.nan)
    end = np.full(n, np.nan)
    for i, w in enumerate(words):
        s, e = getattr(w, "start_s", None), getattr(w, "end_s", None)
        if s is not None and e is not None and math.isfinite(s) and math.isfinite(e):
            start[i], end[i] = float(s), float(e)

    slot = np.full(n, np.nan)
    level = np.full(n, np.nan)
    active = values >= active_threshold_dbfs
    for i in range(n):
        if not math.isfinite(start[i]):
            continue
        if i + 1 < n:
            if math.isfinite(start[i + 1]):
                silence_beyond_cap = max(0.0, (start[i + 1] - end[i]) - max_gap_s)
                value = start[i + 1] - start[i] - silence_beyond_cap
            else:
                value = math.nan
        else:
            value = end[i] - start[i]
        if math.isfinite(value) and value >= MIN_SLOT_S:
            slot[i] = value
        lo = int(np.searchsorted(times, start[i], side="left"))
        hi = int(np.searchsorted(times, end[i], side="right"))
        frames = values[lo:hi][active[lo:hi]]
        if len(frames) >= MIN_ACTIVE_FRAMES:
            level[i] = float(np.median(frames))
    return WordObservations(tokens, start, end, slot, level, float(max_gap_s), float(active_threshold_dbfs))


# ------------------------------------------------------------------------------------------------ run statistics
def window_log_ratio(observed: np.ndarray, expected: np.ndarray, n: int) -> np.ndarray:
    """``ln(sum observed / sum expected)`` over every run of `n` consecutive entries (empty if there are fewer than `n` entries)."""
    if n < 1 or n > len(observed):
        return np.empty(0, dtype=np.float64)
    co = np.concatenate(([0.0], np.cumsum(observed)))
    ce = np.concatenate(([0.0], np.cumsum(expected)))
    return np.log((co[n:] - co[:-n]) / (ce[n:] - ce[:-n]))


def overall_tempo(observed: np.ndarray, expected: np.ndarray, window: int = TEMPO_WINDOW_WORDS) -> float:
    """The reading's overall pace against the expectation: the median log ratio over runs of `window` words (positive = slower).

    A median, so a stretch that is much faster or slower than the rest does not move it unless it covers about half of the reading.
    """
    n = min(window, len(observed))
    if n < 1:
        return 0.0
    return float(np.median(window_log_ratio(observed, expected, n)))


def window_mean(values: np.ndarray, n: int) -> np.ndarray:
    """Mean of every run of `n` consecutive entries (empty if there are fewer than `n` entries)."""
    if n < 1 or n > len(values):
        return np.empty(0, dtype=np.float64)
    c = np.concatenate(([0.0], np.cumsum(values)))
    return (c[n:] - c[:-n]) / n


def noise_sigma(model: NoiseModel, n: np.ndarray | int, *, drift_floor: float = 0.0, word_floor: float = 0.0) -> np.ndarray | float:
    """``sqrt(drift^2 + word^2 / n)`` with the two parts not allowed below the given floors (see `NoiseModel`)."""
    drift = max(float(model.drift), drift_floor)
    word = max(float(model.word), word_floor)
    return np.sqrt(drift ** 2 + word ** 2 / np.asarray(n, dtype=np.float64)) if isinstance(n, np.ndarray) else math.sqrt(drift ** 2 + word ** 2 / n)


def _fit_noise(windows: Mapping[int, np.ndarray]) -> Optional[NoiseModel]:
    """Fit ``mean(window value^2) = drift^2 + word^2 / n`` over the run lengths by non-negative least squares (None if nothing to fit)."""
    rows = [(n, float(np.mean(v ** 2))) for n, v in sorted(windows.items()) if len(v) >= MIN_WINDOWS_PER_ROW]
    if not rows:
        return None
    if len(rows) == 1:
        n, mean_square = rows[0]
        return NoiseModel(drift=0.0, word=round(math.sqrt(mean_square * n), DECIMALS))
    design = np.array([[1.0, 1.0 / n] for n, _ in rows])
    target = np.array([m for _, m in rows])
    coefficients, _ = nnls(design, target)
    return NoiseModel(drift=round(math.sqrt(coefficients[0]), DECIMALS), word=round(math.sqrt(coefficients[1]), DECIMALS))


# ------------------------------------------------------------------------------------------------ the profile
def _geometric_mean(values: np.ndarray) -> np.ndarray:
    """Column-wise geometric mean ignoring NaN; NaN where fewer than two values exist."""
    logs = np.log(values)
    counts = np.sum(np.isfinite(logs), axis=0)
    total = np.sum(np.where(np.isfinite(logs), logs, 0.0), axis=0)
    out = np.full(values.shape[1], np.nan)
    ok = counts >= 2
    out[ok] = np.exp(total[ok] / counts[ok])
    return out


def _column_mean(values: np.ndarray) -> np.ndarray:
    """Column-wise mean ignoring NaN; NaN where fewer than two values exist."""
    counts = np.sum(np.isfinite(values), axis=0)
    total = np.sum(np.where(np.isfinite(values), values, 0.0), axis=0)
    out = np.full(values.shape[1], np.nan)
    ok = counts >= 2
    out[ok] = total[ok] / counts[ok]
    return out


def _median_or_zero(values: np.ndarray) -> float:
    values = values[np.isfinite(values)]
    return float(np.median(values)) if len(values) else 0.0


def _level_profile(levels: np.ndarray) -> np.ndarray:
    """Expected level per word from several readings: each reading's own overall offset (its median difference) is removed first."""
    first = _column_mean(levels)
    offsets = np.array([_median_or_zero(row - first) for row in levels])
    return _column_mean(levels - offsets[:, None])


def build_word_profile(
    takes: Sequence[WordObservations], passage: Sequence[str], *, max_gap_s: float, active_threshold_dbfs: float,
) -> Optional[WordProfile]:
    """The word profile of a passage from its baseline readings, or None if there is not enough to build one.

    A reading counts only if at least `MIN_MAPPED_SHARE` of its timed words match the passage text; at least `PROFILE_MIN_TAKES` readings must
    count. Readings are taken in the order given; the result does not depend on it beyond last-bit rounding, which is removed.
    """
    n_words = len(passage)
    if n_words == 0:
        return None
    slot_rows: List[np.ndarray] = []
    level_rows: List[np.ndarray] = []
    for obs in takes:
        idx = map_to_passage(obs.tokens, passage)
        timed = np.isfinite(obs.start_s)
        mapped = idx >= 0
        if not timed.any() or np.count_nonzero(mapped & timed) / np.count_nonzero(timed) < MIN_MAPPED_SHARE:
            continue
        slot_row = np.full(n_words, np.nan)
        level_row = np.full(n_words, np.nan)
        slot_row[idx[mapped]] = obs.slot_s[mapped]
        level_row[idx[mapped]] = obs.level_db[mapped]
        slot_rows.append(slot_row)
        level_rows.append(level_row)
    if len(slot_rows) < PROFILE_MIN_TAKES:
        return None
    slot = np.vstack(slot_rows)
    level = np.vstack(level_rows)
    n_takes = len(slot_rows)

    expected_slot = _geometric_mean(slot)
    expected_level = _level_profile(level)

    # Leave-one-out: how far is a reading from the expectation built from the OTHER readings?
    rate_runs: List[Tuple[np.ndarray, np.ndarray]] = []
    level_runs: List[np.ndarray] = []
    tempos: List[float] = []
    for b in range(n_takes):
        others_slot = _geometric_mean(np.delete(slot, b, axis=0))
        usable = np.isfinite(slot[b]) & np.isfinite(others_slot)
        if np.count_nonzero(usable) >= TEMPO_WINDOW_WORDS:
            observed, expected = slot[b][usable], others_slot[usable]
            tempo = overall_tempo(observed, expected)
            tempos.append(tempo)
            rate_runs.append((observed, expected * math.exp(tempo)))
        others_level = _level_profile(np.delete(level, b, axis=0))
        usable = np.isfinite(level[b]) & np.isfinite(others_level)
        if np.count_nonzero(usable) >= 2:
            difference = level[b][usable] - others_level[usable]
            level_runs.append(difference - float(np.median(difference)))
    rate_noise = _fit_noise({
        n: np.concatenate([window_log_ratio(o, e, n) for o, e in rate_runs]) if rate_runs else np.empty(0) for n in NOISE_GRID
    })
    level_noise = _fit_noise({
        n: np.concatenate([window_mean(d, n) for d in level_runs]) if level_runs else np.empty(0) for n in NOISE_GRID
    })
    if rate_noise is None or level_noise is None:
        return None
    tempo_sd = float(np.std(tempos, ddof=1)) if len(tempos) >= 2 else 0.0

    def rounded(values: np.ndarray) -> List[Optional[float]]:
        return [round(float(v), DECIMALS) if math.isfinite(v) else None for v in values]

    return WordProfile(
        words=list(passage), slot_s=rounded(expected_slot), level_db=rounded(expected_level), n_takes=n_takes,
        rate_noise=rate_noise, level_noise=level_noise, tempo_sd=round(tempo_sd, DECIMALS),
        tempo_window_words=TEMPO_WINDOW_WORDS, max_gap_s=float(max_gap_s), active_threshold_dbfs=float(active_threshold_dbfs),
    )
