"""Baseline statistics from baseline recordings: per-recording features and their pooling (TASK-040; ARCHITECTURE.md §14, §9.5; DEC-010, DEC-015, DEC-044).

The one implementation of how baseline recordings become a `BaselineStatsRecord`. It is used by the offline dataset tool
(`scripts/dataset/build_baseline_stats.py`, which re-exports these names) and by the custom-passage service
(`app.services.custom`), so a baseline made from a user's own recordings is built exactly like one made from the project dataset.

Pipeline per baseline recording (the SAME services the participant pipeline uses, so the baseline and the participant are processed identically):

    audio --AudioPreprocessor--> PreprocessedAudio
    an alignment (an `AlignedTranscript` in PROCESSED-audio time) --validate_alignment-->
    F0 (voiced frames) / energy (dBFS frames) / rolling-window speech rate / pause events / per-word measurements

Conventions (all stored in the output file): F0 mean/std/p05/p95 over voiced frames; energy mean/std over active frames; rate mean/std over rolling
windows; pause duration mean/std per boundary type; sample standard deviation (ddof=1); floats rounded to 6 decimals so the file and its sha256 do
not depend on last-bit differences between machines; the optional word profile (DEC-040, DEC-042) when the passage text is known and at least three
recordings match it. Nothing is invented: a statistic that cannot be computed fails with `BaselineBuildError`.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from app.core.config import settings
from app.schemas.common import PauseBoundaryType
from app.schemas.contracts import AlignedTranscript, BaselineStatsRecord
from app.schemas.response import PauseEvent
from app.services.alignment.validator import validate_alignment
from app.services.audio import AudioPreprocessor
from app.services.features.energy import extract_energy
from app.services.features.f0 import extract_f0
from app.services.features.pause import detect_pauses
from app.services.features.rate import extract_rate
from app.services.grounding.profile import WordObservations, build_word_profile, measure_words, passage_tokens

PLACEHOLDER_SHA256 = "0" * 64
ENERGY_FRAME_SELECTIONS = ("active", "all")
STD_DDOF = 1


class BaselineBuildError(ValueError):
    """Raised when baseline statistics cannot be built from the provided data."""


@dataclass(frozen=True)
class BaselineBuildConfig:
    """Conventions that define how the statistics are computed (stored in the output file)."""

    energy_frame_selection: str = "active"
    energy_active_threshold_dbfs: float = settings.VAD_ENERGY_THRESHOLD_DBFS
    decimals: int = 6

    def __post_init__(self) -> None:
        if self.energy_frame_selection not in ENERGY_FRAME_SELECTIONS:
            raise ValueError(
                f"energy_frame_selection must be one of {ENERGY_FRAME_SELECTIONS}, "
                f"got {self.energy_frame_selection!r}"
            )
        if not math.isfinite(self.energy_active_threshold_dbfs):
            raise ValueError("energy_active_threshold_dbfs must be finite")
        if not (0 <= self.decimals <= 12):
            raise ValueError(f"decimals must be in [0, 12], got {self.decimals}")


@dataclass(frozen=True)
class RecordingFeatures:
    """Features of ONE baseline recording, in the units the statistics use.

    f0_voiced_hz: F0 of voiced frames only (Hz); energy_db: all energy frames (dBFS);
    rate_wpm: valid rolling-window rates (words/min); pauses: detected pause events.
    """

    recording_id: str
    f0_voiced_hz: np.ndarray
    energy_db: np.ndarray
    rate_wpm: np.ndarray
    pauses: Sequence[PauseEvent]
    words: Optional[WordObservations] = None      # per-word slot and level (DEC-040); None: this recording adds nothing to the word profile


# --------------------------------------------------------------------------- aggregation
def _pooled(arrays: Sequence[np.ndarray], name: str) -> np.ndarray:
    values = (
        np.concatenate([np.asarray(a, dtype=np.float64).ravel() for a in arrays])
        if arrays
        else np.empty(0, dtype=np.float64)
    )
    if not np.all(np.isfinite(values)):
        raise BaselineBuildError(f"{name} contains non-finite values")
    return values


def _mean_std(values: np.ndarray, name: str, unit: str) -> "tuple[float, float]":
    if len(values) < 2:
        raise BaselineBuildError(
            f"cannot compute {name} mean/std ({unit}): {len(values)} observation(s), at least 2 required"
        )
    return float(np.mean(values)), float(np.std(values, ddof=STD_DDOF))


def aggregate_baseline_stats(
    passage_id: str,
    dataset_version: str,
    recordings: Sequence[RecordingFeatures],
    config: Optional[BaselineBuildConfig] = None,
    extra_snapshot: Optional[Dict[str, Any]] = None,
    passage_text: Optional[str] = None,
) -> BaselineStatsRecord:
    """Pool per-recording features into one hashed `BaselineStatsRecord` (pure, deterministic).

    Recordings are processed in sorted `recording_id` order, so input order never matters. With `passage_text` and the per-word measurements of at
    least three recordings that match it, the record also carries the word profile (DEC-040); otherwise `word_profile` is None.

    Raises:
        BaselineBuildError: no recordings, duplicate ids, non-finite data, or a required
            statistic cannot be computed from the available observations.
    """
    cfg = config or BaselineBuildConfig()
    if not recordings:
        raise BaselineBuildError("at least one baseline recording is required")
    ids = [r.recording_id for r in recordings]
    if len(set(ids)) != len(ids):
        raise BaselineBuildError("duplicate recording_id in baseline recordings")
    ordered = sorted(recordings, key=lambda r: r.recording_id)

    def rnd(x: float) -> float:
        return round(float(x), cfg.decimals)

    # F0 (voiced frames).
    f0 = _pooled([r.f0_voiced_hz for r in ordered], "F0 values")
    f0_mean, f0_std = _mean_std(f0, "F0", "Hz, voiced frames")
    f0_p05, f0_p95 = (float(v) for v in np.percentile(f0, [5.0, 95.0]))

    # Energy (active frames by default).
    energy_all = _pooled([r.energy_db for r in ordered], "energy values")
    if cfg.energy_frame_selection == "active":
        energy = energy_all[energy_all >= cfg.energy_active_threshold_dbfs]
    else:
        energy = energy_all
    energy_mean, energy_std = _mean_std(
        energy, f"energy ({cfg.energy_frame_selection} frames)", "dBFS"
    )

    # Speech rate (rolling windows).
    rate = _pooled([r.rate_wpm for r in ordered], "rate values")
    rate_mean, rate_std = _mean_std(rate, "speech rate", "words/min, rolling windows")

    # Pauses, per boundary type.
    within: List[float] = []
    cross: List[float] = []
    unknown = 0
    for r in ordered:
        for p in r.pauses:
            if p.boundary_type == PauseBoundaryType.WITHIN_PHRASE:
                within.append(p.duration_s)
            elif p.boundary_type == PauseBoundaryType.CROSS_SENTENCE:
                cross.append(p.duration_s)
            else:
                unknown += 1
    within_arr = _pooled([np.asarray(within)], "within-phrase pause durations")
    cross_arr = _pooled([np.asarray(cross)], "cross-sentence pause durations")
    within_mean, within_std = _mean_std(within_arr, "within-phrase pause duration", "s")
    if len(cross_arr) < 1:
        raise BaselineBuildError(
            "cannot compute cross-sentence pause mean (s): no cross-sentence pauses in the baseline"
        )
    cross_mean = float(np.mean(cross_arr))
    cross_std: Optional[float] = (
        float(np.std(cross_arr, ddof=STD_DDOF)) if len(cross_arr) >= 2 else None
    )

    word_profile = None
    if passage_text:
        measured = [r.words for r in ordered if r.words is not None]
        if measured:
            word_profile = build_word_profile(
                measured, passage_tokens(passage_text), max_gap_s=measured[0].max_gap_s, active_threshold_dbfs=measured[0].active_threshold_dbfs,
            )

    snapshot: Dict[str, Any] = {
        "energy_frame_selection": cfg.energy_frame_selection,
        "energy_active_threshold_dbfs": cfg.energy_active_threshold_dbfs,
        "std_ddof": STD_DDOF,
        "percentile_method": "linear",
        "round_decimals": cfg.decimals,
        "pooling": "frames, windows and events pooled across baseline recordings",
    }
    snapshot.update(extra_snapshot or {})

    record = BaselineStatsRecord(
        passage_id=passage_id,
        dataset_version=dataset_version,
        baseline_recording_ids=[r.recording_id for r in ordered],
        f0_voiced_hz_mean=rnd(f0_mean),
        f0_voiced_hz_std=rnd(f0_std),
        f0_voiced_hz_p05=rnd(f0_p05),
        f0_voiced_hz_p95=rnd(f0_p95),
        energy_db_mean=rnd(energy_mean),
        energy_db_std=rnd(energy_std),
        rate_wpm_mean=rnd(rate_mean),
        rate_wpm_std=rnd(rate_std),
        pause_within_phrase_mean_s=rnd(within_mean),
        pause_within_phrase_std_s=rnd(within_std),
        pause_cross_sentence_mean_s=rnd(cross_mean),
        pause_cross_sentence_std_s=None if cross_std is None else rnd(cross_std),
        n_f0_voiced_frames=int(len(f0)),
        n_energy_frames=int(len(energy)),
        n_rate_windows=int(len(rate)),
        n_pauses_within_phrase=len(within),
        n_pauses_cross_sentence=len(cross),
        n_pauses_unknown_boundary=unknown,
        config_snapshot=snapshot,
        word_profile=word_profile,
        sha256=PLACEHOLDER_SHA256,
    )
    return record.with_computed_sha256()


# ----------------------------------------------------------------- per-recording features
def extract_recording_features(
    recording_id: str, audio_bytes: bytes, aligned: AlignedTranscript
) -> RecordingFeatures:
    """Run the canonical services on one baseline recording.

    The alignment must be in PROCESSED-audio time (i.e. produced from `PreprocessedAudio`);
    `validate_alignment` rejects structurally invalid or out-of-bounds alignments.
    """
    audio = AudioPreprocessor().process(audio_bytes)
    if len(audio.audio_array) == 0:
        raise BaselineBuildError(f"{recording_id}: audio is silent after preprocessing")

    validation = validate_alignment(aligned, audio_duration_s=audio.duration_s)
    if not validation.is_valid:
        raise BaselineBuildError(f"{recording_id}: invalid alignment: {'; '.join(validation.errors)}")

    f0 = extract_f0(audio)
    energy = extract_energy(audio)
    rate = extract_rate(aligned)
    pauses = detect_pauses(aligned=aligned, energy=energy).events
    words = measure_words(
        aligned, energy, max_gap_s=settings.PROFILE_GAP_CAP_S, active_threshold_dbfs=settings.VAD_ENERGY_THRESHOLD_DBFS,
        f0=f0, pitch_min_voiced_frames=settings.PITCH_MIN_VOICED_FRAMES, pitch_deviation_clip_st=settings.PITCH_DEVIATION_CLIP_ST,
    )
    return RecordingFeatures(
        recording_id=recording_id,
        f0_voiced_hz=f0.voiced_values_hz,
        energy_db=energy.values_db,
        rate_wpm=rate.words_per_min,
        pauses=pauses,
        words=words,
    )


def default_config_snapshot(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The preprocessing and feature settings in effect, as stored in a baseline file's `config_snapshot` (provenance only)."""
    from app.services.features.energy import EnergyConfig
    from app.services.features.f0 import F0Config
    from app.services.features.pause import PauseConfig
    from app.services.features.rate import RateConfig

    snapshot: Dict[str, Any] = dict(extra or {})
    snapshot["preprocess.target_sample_rate"] = settings.TARGET_SAMPLE_RATE
    snapshot["preprocess.target_speech_level_dbfs"] = settings.TARGET_SPEECH_LEVEL_DBFS
    snapshot["preprocess.speech_level_window_db"] = settings.SPEECH_LEVEL_WINDOW_DB
    snapshot["preprocess.max_peak_dbfs"] = settings.MAX_PEAK_DBFS
    snapshot["preprocess.vad_energy_threshold_dbfs"] = settings.VAD_ENERGY_THRESHOLD_DBFS
    for prefix, cfg in (("f0", F0Config()), ("energy", EnergyConfig()), ("rate", RateConfig()), ("pause", PauseConfig())):
        snapshot.update(_config_snapshot(prefix, cfg))
    return snapshot


def _config_snapshot(prefix: str, cfg: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if is_dataclass(cfg):
        for key, value in asdict(cfg).items():
            if isinstance(value, bool) or isinstance(value, (str, int)):
                out[f"{prefix}.{key}"] = value
            elif isinstance(value, float) and math.isfinite(value):
                out[f"{prefix}.{key}"] = value
    return out
