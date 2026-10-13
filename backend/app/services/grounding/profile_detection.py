"""Rate and loudness findings from the baseline's word profile (DEC-040; ARCHITECTURE.md §17 steps 1-3).

The participant's words are matched to the passage words, and every word is compared with what the baseline readings did with THE SAME WORD:

    rate     the total time a run of words took against the total time the baseline readings took for them
    loudness the run's mean level against the baseline's level for those words

A finding is a run of at least `run_min_words` consecutive words whose deviation, in units of the spread a baseline reading itself shows over a
run of that length (`WordProfile.rate_noise` / `level_noise`, measured leave-one-out), exceeds the threshold AND is large enough to matter in
practice (`min_rate_change_pct`, `min_energy_change_db`). Statistical and practical significance are both required: a baseline with an
unusually even reading must not turn a change nobody can hear into a flaw.

Which run is reported: every run is scored (a scan over all start words and lengths, vectorised); the run with the largest z-score wins,
its words are taken out, and the scan repeats, so separate stretches stay separate findings. For a stretch of speech that is faster than the
rest, adding a normal word lowers the average deviation faster than it lowers the spread, so the best run ends where the deviation does: the
boundaries are those of words, not of an 8 s window. Fast and slow findings (and loud and quiet ones) compete in the same scan and never overlap.

Overall pace and level are removed first:
    * rate: the reading's overall pace against the baseline (`overall_tempo`, positive = slower) is divided out, so someone who speaks
      generally quicker or slower than the baseline readers is judged against their own pace, and only local departures stand out. A reading
      that is off as a whole is judged on its own, as one finding over the whole reading, only if it differs from the baseline by more than
      `global_tempo_change_pct` AND by more than the spread of the overall pace between baseline readings (`WordProfile.tempo_sd`).
    * loudness: the reading's median difference from the profile is removed. Recordings are scaled to a common speech level (DEC-036), so
      only louder and quieter stretches WITHIN a reading are meaningful.

Spread floors (`sigma_floor_*`): a very even baseline would give a tiny spread and make every deviation look huge; the spread is never taken
below the floors. The floors, thresholds and minimums are `DetectionConfig` fields (settings, environment-overridable) and part of the
analysis fingerprint.

The profile is used only if the participant's words match the passage well enough (`profile_min_coverage` of the timed words) and enough of
them can be compared (`profile_min_usable_words`); otherwise the caller falls back to the overall statistics and says so.

Pure functions, deterministic; no flaw severity, evidence or explanation is produced here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

import numpy as np

from app.schemas.common import FlawType
from app.schemas.contracts import WordProfile
from app.services.grounding.profile import WordObservations, map_to_passage, noise_sigma, overall_tempo, window_mean

MAX_RUNS_PER_SIGNAL = 8          # findings per signal in one reading: more than this is a reading that is off as a whole
_EPS = 1e-9


@dataclass(frozen=True)
class RunFinding:
    """One run of words that deviates from the baseline's reading of the same words.

    `kind`: "rate_run", "rate_overall" or "energy_run". `z` is signed: positive = faster (rate) or louder (energy) than expected.
    `observed` and `expected` are words per minute (rate) or dBFS (energy) over the run, `effect` the size of the change in the units that
    severity uses (natural-log ratio of durations for the rate, dB for the loudness). `sigma_equiv` = |observed - expected| / |z|, the spread
    in the same units as `observed`, so the evidence can state z = (observed - expected) / spread.
    """

    kind: str
    first_word: int
    last_word: int
    start_s: float
    end_s: float
    z: float
    observed: float
    expected: float
    sigma_equiv: float
    effect: float
    n_words: int
    word_indices: Tuple[int, ...]


@dataclass(frozen=True)
class ProfileDetection:
    """What the profile found. `rate` / `energy` are None when the profile could not be used for that signal (see `reason`)."""

    rate: Optional[List[RunFinding]]
    energy: Optional[List[RunFinding]]
    reason: Optional[str]
    coverage: float
    n_usable_rate: int = 0
    n_usable_level: int = 0
    tempo: float = 0.0


def _find_runs(
    *, size: int, min_words: int, stat: Callable[[int], np.ndarray], sigma: Callable[[int], float], min_abs: float, min_duration_s: float,
    starts_s: np.ndarray, ends_s: np.ndarray, z_threshold: float, max_runs: int,
) -> List[Tuple[int, int, float, float]]:
    """Scan every run of `min_words` or more of `size` entries; return (first, n, statistic, z) of the best runs, best first.

    `stat(n)` gives the signed statistic of every run of `n` consecutive entries. A run qualifies if |statistic| >= `min_abs`, it lasts at least
    `min_duration_s`, it shares no entry with an earlier result and |statistic| / sigma(n) is strictly above `z_threshold`. The best run (largest
    z; on a tie the shorter, then the earlier) is taken, its entries are removed, and the scan repeats up to `max_runs` times.
    """
    used = np.zeros(size, dtype=bool)
    found: List[Tuple[int, int, float, float]] = []
    for _ in range(max_runs):
        taken = np.concatenate(([0], np.cumsum(used, dtype=np.int64)))
        best: Optional[Tuple[int, int, float, float]] = None
        best_z = z_threshold
        for n in range(min_words, size + 1):
            values = stat(n)
            free = (taken[n:] - taken[:-n]) == 0
            long_enough = (ends_s[n - 1:] - starts_s[: size - n + 1]) + _EPS >= min_duration_s
            z = np.abs(values) / sigma(n)
            z = np.where(free & long_enough & (np.abs(values) >= min_abs), z, -np.inf)
            j = int(np.argmax(z))
            if z[j] > best_z + 1e-12:
                best_z, best = float(z[j]), (j, n, float(values[j]), float(z[j]))
        if best is None:
            break
        found.append(best)
        used[best[0]: best[0] + best[1]] = True
    return found


def _rate_findings(
    obs: WordObservations, usable: np.ndarray, expected_slot: np.ndarray, profile: WordProfile, rules: Any,
    min_duration_fast: float, min_duration_slow: float,
) -> Tuple[List[RunFinding], float]:
    pos = np.flatnonzero(usable)
    s = obs.slot_s[pos]
    e = expected_slot[pos]
    size = len(pos)
    starts, ends = obs.start_s[pos], obs.end_s[pos]
    tau = overall_tempo(s, e, profile.tempo_window_words)
    out: List[RunFinding] = []

    # The reading as a whole: only if it differs from the baseline by a lot AND by more than baseline readings differ among themselves.
    spread_tempo = max(float(profile.tempo_sd), float(rules.sigma_floor_tempo))
    if abs(tau) >= math.log1p(rules.global_tempo_change_pct / 100.0) and abs(tau) / spread_tempo > rules.z_run_rate:
        observed = 60.0 * size / float(np.sum(s))
        expected = 60.0 * size / float(np.sum(e))
        z = -tau / spread_tempo                      # positive = faster than the baseline readers
        duration = float(ends[-1] - starts[0])
        if duration + _EPS >= (min_duration_fast if z > 0 else min_duration_slow):
            out.append(RunFinding(
                kind="rate_overall", first_word=int(pos[0]), last_word=int(pos[-1]), start_s=float(starts[0]), end_s=float(ends[-1]), z=z,
                observed=observed, expected=expected, sigma_equiv=abs(observed - expected) / abs(z), effect=abs(tau), n_words=size,
                word_indices=tuple(int(i) for i in pos),
            ))

    adjusted = e * math.exp(tau)
    cs = np.concatenate(([0.0], np.cumsum(s)))
    ce = np.concatenate(([0.0], np.cumsum(adjusted)))
    floor_drift, floor_word = rules.sigma_floor_rate_drift, rules.sigma_floor_rate_word
    runs = _find_runs(
        size=size, min_words=rules.run_min_words,
        stat=lambda n: np.log((cs[n:] - cs[:-n]) / (ce[n:] - ce[:-n])),
        sigma=lambda n: noise_sigma(profile.rate_noise, n, drift_floor=floor_drift, word_floor=floor_word),
        min_abs=math.log1p(rules.min_rate_change_pct / 100.0), min_duration_s=min(min_duration_fast, min_duration_slow),
        starts_s=starts, ends_s=ends, z_threshold=rules.z_run_rate, max_runs=MAX_RUNS_PER_SIGNAL,
    )
    for first, n, log_ratio, _z in runs:
        last = first + n - 1
        fast = log_ratio < 0.0
        duration = float(ends[last] - starts[first])
        if duration + _EPS < (min_duration_fast if fast else min_duration_slow):
            continue
        z = abs(log_ratio) / noise_sigma(profile.rate_noise, n, drift_floor=floor_drift, word_floor=floor_word)
        z = z if fast else -z
        observed = 60.0 * n / float(np.sum(s[first: last + 1]))
        expected = 60.0 * n / float(np.sum(adjusted[first: last + 1]))
        out.append(RunFinding(
            kind="rate_run", first_word=int(pos[first]), last_word=int(pos[last]), start_s=float(starts[first]), end_s=float(ends[last]),
            z=z, observed=observed, expected=expected, sigma_equiv=abs(observed - expected) / abs(z), effect=abs(log_ratio), n_words=n,
            word_indices=tuple(int(i) for i in pos[first: last + 1]),
        ))
    return out, tau


def _energy_findings(
    obs: WordObservations, usable: np.ndarray, expected_level: np.ndarray, profile: WordProfile, rules: Any,
    min_duration_loud: float, min_duration_quiet: float,
) -> List[RunFinding]:
    pos = np.flatnonzero(usable)
    level = obs.level_db[pos]
    expected = expected_level[pos]
    size = len(pos)
    starts, ends = obs.start_s[pos], obs.end_s[pos]
    difference = level - expected
    offset = float(np.median(difference))
    centred = difference - offset
    floor_drift, floor_word = rules.sigma_floor_level_drift, rules.sigma_floor_level_word
    runs = _find_runs(
        size=size, min_words=rules.run_min_words, stat=lambda n: window_mean(centred, n),
        sigma=lambda n: noise_sigma(profile.level_noise, n, drift_floor=floor_drift, word_floor=floor_word),
        min_abs=rules.min_energy_change_db, min_duration_s=min(min_duration_loud, min_duration_quiet),
        starts_s=starts, ends_s=ends, z_threshold=rules.z_run_energy, max_runs=MAX_RUNS_PER_SIGNAL,
    )
    out: List[RunFinding] = []
    for first, n, mean_difference, _z in runs:
        last = first + n - 1
        loud = mean_difference > 0.0
        duration = float(ends[last] - starts[first])
        if duration + _EPS < (min_duration_loud if loud else min_duration_quiet):
            continue
        z = mean_difference / noise_sigma(profile.level_noise, n, drift_floor=floor_drift, word_floor=floor_word)
        observed = float(np.mean(level[first: last + 1]))
        expected_mean = float(np.mean(expected[first: last + 1])) + offset
        out.append(RunFinding(
            kind="energy_run", first_word=int(pos[first]), last_word=int(pos[last]), start_s=float(starts[first]), end_s=float(ends[last]),
            z=z, observed=observed, expected=expected_mean, sigma_equiv=abs(observed - expected_mean) / abs(z), effect=abs(mean_difference),
            n_words=n, word_indices=tuple(int(i) for i in pos[first: last + 1]),
        ))
    return out


def detect_runs(obs: WordObservations, profile: WordProfile, rules: Any) -> ProfileDetection:
    """Findings of the word profile for one reading. `rules` is a `DetectionConfig` (any object with the fields used here).

    Either signal is None when the profile cannot be used for it, and `reason` says why: ``transcript_mismatch`` (too few of the participant's
    words match the passage), ``too_few_words`` (too few comparable words).
    """
    index = map_to_passage(obs.tokens, profile.words)
    timed = np.isfinite(obs.start_s)
    n_timed = int(np.count_nonzero(timed))
    matched = (index >= 0) & timed
    coverage = float(np.count_nonzero(matched)) / n_timed if n_timed else 0.0
    if coverage < rules.profile_min_coverage:
        return ProfileDetection(None, None, "transcript_mismatch", coverage)

    expected_slot = np.full(len(index), np.nan)
    expected_level = np.full(len(index), np.nan)
    slots = np.array([math.nan if v is None else v for v in profile.slot_s])
    levels = np.array([math.nan if v is None else v for v in profile.level_db])
    expected_slot[index >= 0] = slots[index[index >= 0]]
    expected_level[index >= 0] = levels[index[index >= 0]]
    usable_rate = np.isfinite(obs.slot_s) & np.isfinite(expected_slot)
    usable_level = np.isfinite(obs.level_db) & np.isfinite(expected_level)
    n_rate, n_level = int(np.count_nonzero(usable_rate)), int(np.count_nonzero(usable_level))

    minimum = rules.min_duration_s
    rate: Optional[List[RunFinding]] = None
    energy: Optional[List[RunFinding]] = None
    tau = 0.0
    if n_rate >= rules.profile_min_usable_words and n_rate >= rules.run_min_words:
        rate, tau = _rate_findings(obs, usable_rate, expected_slot, profile, rules, minimum[FlawType.TOO_FAST], minimum[FlawType.TOO_SLOW])
    if n_level >= rules.profile_min_usable_words and n_level >= rules.run_min_words:
        energy = _energy_findings(obs, usable_level, expected_level, profile, rules, minimum[FlawType.HIGH_ENERGY], minimum[FlawType.LOW_ENERGY])
    reason = None if (rate is not None and energy is not None) else "too_few_words"
    return ProfileDetection(rate, energy, reason, coverage, n_rate, n_level, tau)
