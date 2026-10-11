"""Build per-passage baseline statistics (TASK-040; ARCHITECTURE.md §14, §9.5; DEC-010, DEC-015).

Offline utility: turns the ``baseline_effective`` recordings of a passage into one
`BaselineStatsRecord` JSON file under ``data/processed/baseline_stats/<passage_id>.json``,
which `app.core.baseline.BaselineProvider` serves at analysis time.

Pipeline per baseline recording (the SAME services the participant pipeline uses, so the
baseline and the participant are processed identically):

    audio file --AudioPreprocessor--> PreprocessedAudio
    stored alignment JSON (an `AlignedTranscript`, in PROCESSED-audio time) --validate_alignment-->
    F0 (voiced frames) / energy (dBFS frames) / rolling-window speech rate / pause events

Statistics (documented conventions; all pooled across the passage's baseline recordings):
    * F0:     mean, std, p05, p95 over VOICED frames, in Hz (pooled frame-weighted).
    * energy: mean, std over frames, in dBFS. By default only ACTIVE frames
              (``energy_db >= energy_active_threshold_dbfs``, the VAD constant used for
              pause detection) count, so pauses do not inflate the spread of "speaking level";
              ``--energy-frames all`` uses every frame. The choice is stored in the file.
    * rate:   mean, std over rolling-window WPM values (pooled window-weighted).
    * pauses: mean/std of pause duration per boundary type (pooled event-weighted);
              pauses of unknown boundary type are counted but not used.
    * std is the SAMPLE standard deviation (ddof=1), so it needs at least 2 observations.
    * floats are rounded to 6 decimals so the stored file (and its sha256) does not depend on
      last-bit floating-point differences between machines.

Nothing is invented: if a required statistic cannot be computed from the data (too few
observations, no active frames, ...) the build fails with an explicit `BaselineBuildError`
rather than writing zeros or defaults.

Usage:
    python scripts/dataset/build_baseline_stats.py --passage-id p001 --splits dev
    python scripts/dataset/build_baseline_stats.py --passage-id p001 p002 --splits dev test --overwrite

Provenance checks: audio and alignment files must exist and match the manifest SHA-256
(all-zero placeholder hashes, as in the schema fixtures, are rejected).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

# Make `app` importable when this file is executed as a script from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.core.baseline import BASELINE_STATS_SUBDIR  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.schemas.common import PauseBoundaryType  # noqa: E402
from app.schemas.contracts import AlignedTranscript, BaselineStatsRecord  # noqa: E402
from app.schemas.response import PauseEvent  # noqa: E402
from app.services.alignment.validator import validate_alignment  # noqa: E402
from app.services.audio import AudioPreprocessor  # noqa: E402
from app.services.features.energy import EnergyConfig, extract_energy  # noqa: E402
from app.services.features.f0 import F0Config, extract_f0  # noqa: E402
from app.services.features.pause import PauseConfig, detect_pauses  # noqa: E402
from app.services.features.rate import RateConfig, extract_rate  # noqa: E402

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
) -> BaselineStatsRecord:
    """Pool per-recording features into one hashed `BaselineStatsRecord` (pure, deterministic).

    Recordings are processed in sorted `recording_id` order, so input order never matters.

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
    return RecordingFeatures(
        recording_id=recording_id,
        f0_voiced_hz=f0.voiced_values_hz,
        energy_db=energy.values_db,
        rate_wpm=rate.words_per_min,
        pauses=pauses,
    )


# ----------------------------------------------------------------------------- dataset
def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _checked_file(data_dir: Path, rel: Any, expected_sha: Any, rec_id: str, label: str) -> Path:
    if not rel or not isinstance(rel, str):
        raise BaselineBuildError(f"{rec_id}: manifest has no '{label}'")
    path = Path(rel)
    if not path.is_absolute():
        path = data_dir.parent / path
    if not path.is_file():
        raise BaselineBuildError(f"{rec_id}: {label} not found at '{path}'")
    if not isinstance(expected_sha, str) or expected_sha == PLACEHOLDER_SHA256:
        raise BaselineBuildError(
            f"{rec_id}: manifest has a missing or placeholder SHA-256 for '{label}' "
            "(schema fixture entries cannot be used to build real baselines)"
        )
    actual = _sha256_file(path)
    if actual != expected_sha:
        raise BaselineBuildError(
            f"{rec_id}: {label} SHA-256 mismatch (manifest {expected_sha}, file {actual})"
        )
    return path


def _config_snapshot(prefix: str, cfg: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if is_dataclass(cfg):
        for key, value in asdict(cfg).items():
            if isinstance(value, bool) or isinstance(value, (str, int)):
                out[f"{prefix}.{key}"] = value
            elif isinstance(value, float) and math.isfinite(value):
                out[f"{prefix}.{key}"] = value
    return out


def build_for_passage(
    data_dir: Path,
    passage_id: str,
    splits: Sequence[str],
    config: Optional[BaselineBuildConfig] = None,
) -> BaselineStatsRecord:
    """Build the baseline statistics of one passage from the dataset manifest.

    Uses every `baseline_effective` recording of `passage_id` whose split is in `splits`.
    """
    manifest_path = data_dir / "metadata" / "manifest.json"
    if not manifest_path.is_file():
        raise BaselineBuildError(f"manifest not found: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BaselineBuildError(f"cannot read manifest {manifest_path}: {exc}") from exc
    if not isinstance(manifest, list):
        raise BaselineBuildError("manifest.json must contain a JSON array")

    chosen = [
        r for r in manifest
        if isinstance(r, dict)
        and r.get("category") == "baseline_effective"
        and r.get("passage_id") == passage_id
        and r.get("split") in set(splits)
    ]
    if not chosen:
        raise BaselineBuildError(
            f"no baseline_effective recordings for passage '{passage_id}' in splits {sorted(set(splits))}"
        )
    versions = {r.get("dataset_version") for r in chosen}
    if len(versions) != 1 or not all(isinstance(v, str) and v for v in versions):
        raise BaselineBuildError(f"baseline recordings must share one dataset_version, got {sorted(map(str, versions))}")

    features: List[RecordingFeatures] = []
    for rec in sorted(chosen, key=lambda r: str(r.get("recording_id"))):
        rec_id = str(rec.get("recording_id"))
        audio_path = _checked_file(data_dir, rec.get("audio_file"), rec.get("sha256_audio"), rec_id, "audio_file")
        align_path = _checked_file(
            data_dir, rec.get("alignment_file"), rec.get("sha256_alignment"), rec_id, "alignment_file"
        )
        try:
            aligned = AlignedTranscript.model_validate_json(align_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise BaselineBuildError(f"{rec_id}: alignment file is not a valid AlignedTranscript: {exc}") from exc
        features.append(extract_recording_features(rec_id, audio_path.read_bytes(), aligned))

    snapshot: Dict[str, Any] = {"splits": ",".join(sorted(set(splits)))}
    snapshot["preprocess.target_sample_rate"] = settings.TARGET_SAMPLE_RATE
    snapshot["preprocess.target_peak_dbfs"] = settings.TARGET_PEAK_DBFS
    snapshot["preprocess.vad_energy_threshold_dbfs"] = settings.VAD_ENERGY_THRESHOLD_DBFS
    for prefix, cfg in (
        ("f0", F0Config()), ("energy", EnergyConfig()), ("rate", RateConfig()), ("pause", PauseConfig()),
    ):
        snapshot.update(_config_snapshot(prefix, cfg))

    return aggregate_baseline_stats(passage_id, versions.pop(), features, config, snapshot)


def write_stats(record: BaselineStatsRecord, output_dir: Path, overwrite: bool = False) -> Path:
    """Write `record` as `<output_dir>/<passage_id>.json` (refuses to overwrite by default)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{record.passage_id}.json"
    if path.exists() and not overwrite:
        raise BaselineBuildError(f"{path} already exists (use --overwrite to replace it)")
    text = json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
    path.write_text(text + "\n", encoding="utf-8")
    return path


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build per-passage baseline statistics (TASK-040).")
    parser.add_argument("--data-dir", type=Path, default=Path("data"), help="data/ root (default: data)")
    parser.add_argument("--passage-id", nargs="+", required=True, help="passage id(s) to build")
    parser.add_argument(
        "--splits", nargs="+", required=True, choices=["dev", "test"],
        help="dataset splits whose baseline recordings may contribute (explicit on purpose)",
    )
    parser.add_argument("--output-dir", type=Path, default=None,
                        help=f"output directory (default: <data-dir>/{BASELINE_STATS_SUBDIR})")
    parser.add_argument("--energy-frames", choices=ENERGY_FRAME_SELECTIONS, default="active",
                        help="energy statistic over active frames only (default) or all frames")
    parser.add_argument("--overwrite", action="store_true", help="replace existing stats files")
    args = parser.parse_args(argv)

    output_dir = args.output_dir or (args.data_dir / BASELINE_STATS_SUBDIR)
    config = BaselineBuildConfig(energy_frame_selection=args.energy_frames)
    status = 0
    for passage_id in args.passage_id:
        try:
            record = build_for_passage(args.data_dir, passage_id, args.splits, config)
            path = write_stats(record, output_dir, overwrite=args.overwrite)
        except BaselineBuildError as exc:
            print(f"[FAIL] {passage_id}: {exc}", file=sys.stderr)
            status = 1
            continue
        print(f"[OK] {passage_id}: wrote {path} (sha256 {record.sha256[:12]}…, "
              f"{len(record.baseline_recording_ids)} recording(s))")
    return status


if __name__ == "__main__":
    sys.exit(main())
