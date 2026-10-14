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

    * word profile (DEC-040): when the passage text is known and at least three recordings match it, how the SAME words were read in the
              baseline recordings, word by word (expected slot and level of every passage word, and the spread of a run of words measured
              leave-one-out). Pace and loudness are then judged against it instead of against the overall statistics above, which
              stay in the file for the fallback and for display. See `app.services.grounding.profile`.

Nothing is invented: if a required statistic cannot be computed from the data (too few
observations, no active frames, ...) the build fails with an explicit `BaselineBuildError`
rather than writing zeros or defaults. The word profile is the one exception that is optional: without
it the file is still valid, and the analysis says that it compared with the overall averages.

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
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


# Make `app` importable when this file is executed as a script from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.core.baseline import BASELINE_STATS_SUBDIR  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.passages import PassageCatalog  # noqa: E402
from app.schemas.contracts import AlignedTranscript, BaselineStatsRecord  # noqa: E402
from app.services.features.energy import EnergyConfig  # noqa: E402
from app.services.grounding.profile import measure_words  # noqa: E402,F401  (other tools reach it through this module)
from app.services.features.f0 import F0Config  # noqa: E402
from app.services.features.pause import PauseConfig  # noqa: E402
from app.services.features.rate import RateConfig  # noqa: E402

# The implementation lives in the backend (DEC-044) so that the custom-passage service builds baselines exactly the way this tool does.
from app.services.baseline_builder import (  # noqa: E402,F401
    ENERGY_FRAME_SELECTIONS, PLACEHOLDER_SHA256, BaselineBuildConfig, BaselineBuildError, RecordingFeatures,
    _config_snapshot, aggregate_baseline_stats, extract_recording_features,
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

    passage_text = PassageCatalog(data_dir / "metadata" / "passages.json").get_text(passage_id)

    snapshot: Dict[str, Any] = {"splits": ",".join(sorted(set(splits)))}
    snapshot["preprocess.target_sample_rate"] = settings.TARGET_SAMPLE_RATE
    snapshot["preprocess.target_speech_level_dbfs"] = settings.TARGET_SPEECH_LEVEL_DBFS
    snapshot["preprocess.speech_level_window_db"] = settings.SPEECH_LEVEL_WINDOW_DB
    snapshot["preprocess.max_peak_dbfs"] = settings.MAX_PEAK_DBFS
    snapshot["preprocess.vad_energy_threshold_dbfs"] = settings.VAD_ENERGY_THRESHOLD_DBFS
    for prefix, cfg in (
        ("f0", F0Config()), ("energy", EnergyConfig()), ("rate", RateConfig()), ("pause", PauseConfig()),
    ):
        snapshot.update(_config_snapshot(prefix, cfg))

    return aggregate_baseline_stats(passage_id, versions.pop(), features, config, snapshot, passage_text=passage_text)


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
        profile = "word profile built" if record.word_profile is not None else "NO word profile (needs the passage text and 3 matching recordings)"
        if record.word_profile is not None:
            profile += ", pitch part built" if record.word_profile.pitch is not None else ", NO pitch part (too little voiced speech in the recordings)"
        print(f"[OK] {passage_id}: wrote {path} (sha256 {record.sha256[:12]}…, "
              f"{len(record.baseline_recording_ids)} recording(s), {profile})")
    return status


if __name__ == "__main__":
    sys.exit(main())
