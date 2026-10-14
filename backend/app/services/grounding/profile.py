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

Pitch movement (DEC-042), when the pitch track is given: the pitch of each voiced frame is expressed in semitones from the reading's OWN median
pitch, so the speaker's register drops out and only how far the voice moves is left. A word's movement is the mean squared deviation (semitones
squared) of its voiced frames, each deviation clipped at `deviation_clip_st` (a tracking error must not dominate), at least `MIN_MOVEMENT_ST2`
(a word that does not move at all would give a zero, whose logarithm is not defined); a word needs `min_voiced_frames` voiced frames. The statistic
of a run of words is ``0.5 * ln(sum of observed movement / sum of expected movement)``: the natural-log ratio of the root-mean-square movement
(negative = the voice moved less than the baseline's did on the same words). The reading's own overall movement (median over runs of 10 words)
is removed first, exactly as the overall pace is, so a reserved speaker is compared with their own range.

Everything here is deterministic. The profile needs at least `PROFILE_MIN_TAKES` baseline readings that match the passage text; with fewer
none is built and the analysis falls back to the overall statistics.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from scipy.optimize import nnls

from app.schemas.contracts import NoiseModel, PitchProfile, WordProfile

PROFILE_MIN_TAKES = 3            # baseline readings needed: the expectation of one is built from the other readings (at least two)
MIN_SLOT_S = 0.05                # a slot shorter than five frames is an alignment artefact, not a measurement
MIN_ACTIVE_FRAMES = 3            # active frames a word needs for a level
MIN_MAPPED_SHARE = 0.5           # share of a reading's timed words that must match the passage for the reading to count
TEMPO_WINDOW_WORDS = 10          # run length of the overall-pace estimate (median over runs of this many words)
NOISE_GRID = (6, 10, 16, 26, 40, 60)   # run lengths at which the spread is measured; sigma(n) is fitted through them
MIN_WINDOWS_PER_ROW = 5          # runs needed at one length before it counts for the fit
DECIMALS = 6                     # stored precision, so the baseline file and its hash do not depend on last-bit differences
MIN_MOVEMENT_ST2 = 0.01          # the smallest pitch movement a word can have (semitones squared, 0.1 semitone root mean square)
MIN_PITCH_FRAMES_FOR_REFERENCE = 20   # voiced frames a reading needs for its median pitch to mean anything

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
    # Pitch movement (DEC-042); None when no pitch track was given or it had too little voiced speech to give a reference.
    pitch_movement_st2: Optional[np.ndarray] = None   # mean squared deviation of the word's voiced frames from the reading's median pitch; NaN = not measurable
    pitch_voiced_frames: Optional[np.ndarray] = None  # voiced frames of each word
    pitch_frames: Optional[np.ndarray] = None         # all frames of each word
    pitch_reference_hz: float = math.nan              # the reading's median pitch
    pitch_min_voiced_frames: int = 0
    pitch_clip_st: float = math.nan

    @property
    def n_words(self) -> int:
        return len(self.tokens)

    @property
    def n_timed(self) -> int:
        return int(np.count_nonzero(np.isfinite(self.start_s)))


def measure_words(
    aligned: Any, energy: Any, *, max_gap_s: float, active_threshold_dbfs: float,
    f0: Any = None, pitch_min_voiced_frames: int = 5, pitch_deviation_clip_st: float = 6.0,
) -> WordObservations:
    """Slot and level of every aligned word, and with `f0` its pitch movement (see the module docstring).

    `aligned` is an `AlignedTranscript` (or anything with a `words` list); `energy` an `EnergyExtractionResult` (`times_s`, `values_db`); `f0` an
    `F0ExtractionResult` (`times_s`, `values_hz`, `voiced`) or None. Words without a time, and a word followed by an untimed word, get no slot;
    they are never guessed.

    Raises:
        TypeError: `aligned` has no `words` list.
        ValueError: the energy (or pitch) arrays are not one-dimensional and equal in length, or a parameter is not usable.
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
    observations = WordObservations(tokens, start, end, slot, level, float(max_gap_s), float(active_threshold_dbfs))
    if f0 is None:
        return observations
    movement = _pitch_movement(f0, start, end, pitch_min_voiced_frames, pitch_deviation_clip_st)
    if movement is None:
        return observations
    return replace(observations, **movement)


def _pitch_movement(f0: Any, start: np.ndarray, end: np.ndarray, min_voiced_frames: int, clip_st: float) -> Optional[Dict[str, Any]]:
    """The pitch part of `WordObservations` (a dict of its fields), or None if the pitch track has too little voiced speech."""
    if not (isinstance(min_voiced_frames, int) and min_voiced_frames >= 1):
        raise ValueError(f"pitch_min_voiced_frames must be an integer >= 1, got {min_voiced_frames}")
    if not (math.isfinite(clip_st) and clip_st > 0.0):
        raise ValueError(f"pitch_deviation_clip_st must be a positive finite number, got {clip_st}")
    times = np.asarray(f0.times_s, dtype=np.float64)
    track_values = getattr(f0, "track_values_hz", None)          # the more permissive voicing of the pitch track, when the extractor gave it
    track_voiced = getattr(f0, "track_voiced", None)
    values = np.asarray(f0.values_hz if track_values is None or track_voiced is None else track_values, dtype=np.float64)
    voiced = np.asarray(f0.voiced if track_values is None or track_voiced is None else track_voiced, dtype=bool)
    if times.ndim != 1 or times.shape != values.shape or times.shape != voiced.shape:
        raise ValueError("f0.times_s, f0.values_hz and f0.voiced must be 1D arrays of equal length")
    usable = voiced & np.isfinite(values) & (values > 0.0)
    if int(np.count_nonzero(usable)) < MIN_PITCH_FRAMES_FOR_REFERENCE:
        return None
    reference = float(np.median(values[usable]))
    semitones = np.full(len(values), np.nan)
    semitones[usable] = 12.0 * np.log2(values[usable] / reference)
    n = len(start)
    movement = np.full(n, np.nan)
    n_voiced = np.zeros(n, dtype=np.int64)
    n_frames = np.zeros(n, dtype=np.int64)
    for i in range(n):
        if not math.isfinite(start[i]):
            continue
        lo = int(np.searchsorted(times, start[i], side="left"))
        hi = int(np.searchsorted(times, end[i], side="right"))
        frames = semitones[lo:hi]
        frames = frames[np.isfinite(frames)]
        n_frames[i], n_voiced[i] = hi - lo, len(frames)
        if len(frames) >= min_voiced_frames:
            movement[i] = max(MIN_MOVEMENT_ST2, float(np.mean(np.minimum(np.abs(frames), clip_st) ** 2)))
    return {
        "pitch_movement_st2": movement, "pitch_voiced_frames": n_voiced, "pitch_frames": n_frames, "pitch_reference_hz": reference,
        "pitch_min_voiced_frames": int(min_voiced_frames), "pitch_clip_st": float(clip_st),
    }


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


def movement_log_ratio(observed: np.ndarray, expected: np.ndarray, n: int) -> np.ndarray:
    """The natural-log ratio of the root-mean-square pitch movement over every run of `n` words: ``0.5 * ln(sum observed / sum expected)``."""
    return 0.5 * window_log_ratio(observed, expected, n)


def overall_movement(observed: np.ndarray, expected: np.ndarray, window: int = TEMPO_WINDOW_WORDS) -> float:
    """The reading's overall pitch movement against the expectation: the median of `movement_log_ratio` over runs of `window` words (negative = flatter)."""
    n = min(window, len(observed))
    if n < 1:
        return 0.0
    return float(np.median(movement_log_ratio(observed, expected, n)))


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
    pitch_rows: List[np.ndarray] = []
    pitch_settings: Optional[Tuple[int, float]] = None
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
        if obs.pitch_movement_st2 is not None:
            pitch_row = np.full(n_words, np.nan)
            pitch_row[idx[mapped]] = obs.pitch_movement_st2[mapped]
            pitch_rows.append(pitch_row)
            pitch_settings = pitch_settings or (obs.pitch_min_voiced_frames, obs.pitch_clip_st)
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

    pitch = _build_pitch_profile(pitch_rows, pitch_settings) if pitch_settings is not None and len(pitch_rows) >= PROFILE_MIN_TAKES else None
    return WordProfile(
        words=list(passage), slot_s=rounded(expected_slot), level_db=rounded(expected_level), n_takes=n_takes,
        rate_noise=rate_noise, level_noise=level_noise, tempo_sd=round(tempo_sd, DECIMALS),
        tempo_window_words=TEMPO_WINDOW_WORDS, max_gap_s=float(max_gap_s), active_threshold_dbfs=float(active_threshold_dbfs),
        pitch=pitch,
    )


def _build_pitch_profile(rows: Sequence[np.ndarray], settings: Tuple[int, float]) -> Optional[PitchProfile]:
    """The pitch part of the profile from the baseline readings' per-word pitch movement (None if there is not enough to fit the spread)."""
    movement = np.vstack(rows)
    expected = _column_mean(movement)
    runs: List[Tuple[np.ndarray, np.ndarray]] = []
    scales: List[float] = []
    for b in range(len(rows)):
        others = _column_mean(np.delete(movement, b, axis=0))
        usable = np.isfinite(movement[b]) & np.isfinite(others)
        if np.count_nonzero(usable) >= TEMPO_WINDOW_WORDS:
            observed, expectation = movement[b][usable], others[usable]
            scale = overall_movement(observed, expectation)
            scales.append(scale)
            runs.append((observed, expectation * math.exp(2.0 * scale)))
    noise = _fit_noise({n: np.concatenate([movement_log_ratio(o, e, n) for o, e in runs]) if runs else np.empty(0) for n in NOISE_GRID})
    if noise is None or not np.isfinite(expected).any():
        return None
    scale_sd = float(np.std(scales, ddof=1)) if len(scales) >= 2 else 0.0
    return PitchProfile(
        movement_st2=[round(float(v), DECIMALS) if math.isfinite(v) else None for v in expected], noise=noise, scale_sd=round(scale_sd, DECIMALS),
        min_voiced_frames=int(settings[0]), deviation_clip_st=float(settings[1]),
    )
