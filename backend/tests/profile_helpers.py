"""Hand-made readings for the tests of the word profile (DEC-040): numbers only, no audio.

A passage of alphabetic "words" whose expected slot and level differ from word to word (as real words do: long words take longer, stressed ones are
louder), and readings of it that differ from take to take by a known amount. Because every reading is built from known numbers, a test can say exactly
where a stretch was made faster or louder and compare what was found with that.
"""
from __future__ import annotations

from dataclasses import replace
from typing import List, Optional, Sequence, Tuple

import numpy as np
from app.schemas.contracts import BaselineStatsRecord
from app.services.grounding.profile import WordObservations, build_word_profile, clean_token

N_WORDS = 90
GAP_CAP_S = 0.25
ACTIVE_DBFS = -50.0
PITCH_REFERENCE_HZ = 120.0
PITCH_MIN_VOICED = 5
PITCH_CLIP_ST = 6.0
VOICED_FRAMES = 12            # voiced frames of every word of a hand-made reading, out of FRAMES
FRAMES = 20


def make_tokens(n: int = N_WORDS) -> List[str]:
    """Distinct lower-case alphabetic tokens: aax, abx, acx, ..."""
    return [f"{chr(97 + i // 26)}{chr(97 + i % 26)}x" for i in range(n)]


def base_slots(n: int = N_WORDS) -> np.ndarray:
    """Expected slot of each word in seconds: 0.20 to 0.38 s by word, and 0.25 s longer after every twelfth word (a sentence end)."""
    return np.array([0.20 + 0.03 * (i % 7) + (0.25 if i % 12 == 11 else 0.0) for i in range(n)])


def base_levels(n: int = N_WORDS) -> np.ndarray:
    """Expected level of each word in dBFS: a fixed pattern of about +-3 dB around -26."""
    return -26.0 + 3.0 * np.sin(np.arange(n) * 0.9)


def base_movements(n: int = N_WORDS) -> np.ndarray:
    """Expected pitch movement of each word (semitones squared): 2 to 10, a fixed pattern (stressed words move more)."""
    return 6.0 + 4.0 * np.sin(np.arange(n) * 0.7)


def observations(
    slots: Sequence[float], levels: Sequence[float], tokens: Optional[Sequence[str]] = None, start: float = 0.5,
    movements: Optional[Sequence[float]] = None,
) -> WordObservations:
    """A reading as the analysis measures it: words that last 75 % of their slot, one after the other.

    With `movements` (pitch movement of each word, semitones squared) the reading also has the pitch part: 12 voiced frames of 20 in every word
    where the movement is a number (3 voiced frames where it is not), a median pitch of 120 Hz.
    """
    slots_a = np.asarray(slots, dtype=float)
    starts = start + np.concatenate(([0.0], np.cumsum(slots_a[:-1])))
    ends = starts + 0.75 * slots_a
    toks = tuple(tokens if tokens is not None else make_tokens(len(slots_a)))
    base = WordObservations(tuple(clean_token(t) for t in toks), starts, ends, slots_a, np.asarray(levels, dtype=float), GAP_CAP_S, ACTIVE_DBFS)
    if movements is None:
        return base
    movement = np.asarray(movements, dtype=float)
    measured = np.isfinite(movement)
    return replace(
        base, pitch_movement_st2=movement, pitch_voiced_frames=np.where(measured, VOICED_FRAMES, 3).astype(np.int64),
        pitch_frames=np.full(len(movement), FRAMES, dtype=np.int64), pitch_reference_hz=PITCH_REFERENCE_HZ, pitch_min_voiced_frames=PITCH_MIN_VOICED,
        pitch_clip_st=PITCH_CLIP_ST,
    )


def reading(
    seed: int, *, jitter: float = 0.12, level_jitter: float = 1.2, tempo: float = 1.0, level_offset: float = 0.0, n: int = N_WORDS,
    stretches: Sequence[Tuple[int, int, float]] = (), loud: Sequence[Tuple[int, int, float]] = (), tokens: Optional[Sequence[str]] = None,
    pitch: bool = False, expressive: float = 1.0, movement_jitter: float = 0.45, flat: Sequence[Tuple[int, int, float]] = (),
) -> WordObservations:
    """One reading: each word's slot is its expected slot times `tempo` times a random factor (log-normal, spread `jitter`); its level is the expected
    level plus `level_offset` plus noise (`level_jitter` dB). `stretches` are (first, last, factor): those words' slots are multiplied by factor (0.6 =
    faster); `loud` are (first, last, dB): those words' levels are raised by dB (negative = quieter). Indices are 0-based and inclusive.

    With `pitch` the reading has pitch movement too: each word's movement is its expected movement times `expressive` squared (how expressive the
    speaker is, 1.0 like the baseline readers) times a log-normal factor of spread `movement_jitter`; `flat` are (first, last, factor): the pitch of those
    words moves `factor` times as far (0.3 = nearly monotone), so their movement is multiplied by factor squared."""
    rng = np.random.default_rng(seed)
    slots = base_slots(n) * tempo * np.exp(rng.normal(0.0, jitter, n))
    levels = base_levels(n) + level_offset + rng.normal(0.0, level_jitter, n)
    for first, last, factor in stretches:
        slots[first:last + 1] *= factor
    for first, last, db in loud:
        levels[first:last + 1] += db
    movements = None
    if pitch:
        pitch_rng = np.random.default_rng(seed + 7919)          # its own stream: a reading's pace and level do not change when pitch is added
        movements = base_movements(n) * expressive ** 2 * np.exp(pitch_rng.normal(0.0, movement_jitter, n))
        for first, last, factor in flat:
            movements[first:last + 1] *= factor ** 2
    return observations(slots, levels, tokens, movements=movements)


def baseline_readings(count: int = 6, **kw) -> List[WordObservations]:
    """The baseline: `count` readings by two speakers whose overall pace differs by about 10 %, as dev speakers' do."""
    return [reading(1000 + k, tempo=0.95 if k % 2 == 0 else 1.05, **({"expressive": 1.0 if k % 2 == 0 else 0.85, **kw} if kw.get("pitch") else kw))
            for k in range(count)]


def make_profile(count: int = 6, n: int = N_WORDS, **kw):
    """The word profile of the hand-made passage (None if it cannot be built). `pitch=True` gives the baseline readings a pitch part too."""
    return build_word_profile(baseline_readings(count, n=n, **kw), make_tokens(n), max_gap_s=GAP_CAP_S, active_threshold_dbfs=ACTIVE_DBFS)


def baseline_record(**overrides) -> BaselineStatsRecord:
    """A valid baseline record (numbers of no importance), with a fresh hash; pass `word_profile=make_profile()` to give it a profile."""
    data = dict(
        passage_id="p001", dataset_version="1.0.0", baseline_recording_ids=["rec_a", "rec_b"],
        f0_voiced_hz_mean=150.0, f0_voiced_hz_std=20.0, f0_voiced_hz_p05=120.0, f0_voiced_hz_p95=185.0,
        energy_db_mean=-25.0, energy_db_std=5.0, rate_wpm_mean=100.0, rate_wpm_std=10.0,
        pause_within_phrase_mean_s=0.4, pause_within_phrase_std_s=0.1, pause_cross_sentence_mean_s=0.9, pause_cross_sentence_std_s=0.2,
        n_f0_voiced_frames=100, n_energy_frames=100, n_rate_windows=5, n_pauses_within_phrase=3, n_pauses_cross_sentence=2,
        n_pauses_unknown_boundary=0, config_snapshot={"energy_frame_selection": "active", "energy_active_threshold_dbfs": -50.0}, sha256="0" * 64,
    )
    data.update(overrides)
    return BaselineStatsRecord(**data).with_computed_sha256()
