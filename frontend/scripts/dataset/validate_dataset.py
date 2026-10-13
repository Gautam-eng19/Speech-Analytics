"""Dataset schema validation script.

Validates the integrity, schema conformance, speaker-split separation,
and SHA-256 provenance for the Track C Contrastive Speech Analytics dataset.
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

CANONICAL_FLAW_TYPES: Set[str] = {
    # P0 Flaws
    "too_fast",
    "too_slow",
    "excessive_pause",
    "flat_pitch",
    "low_energy",
    "high_energy",
    # P1 Flaws
    "pitch_instability",
    "reduced_clarity",
}

VALID_CATEGORIES: Set[str] = {
    "baseline_effective",
    "flawed_human_controlled",
    "flawed_synthetic",
    "clean_control",
}

VALID_SPLITS: Set[str] = {"dev", "test"}


def compute_sha256(filepath: Path) -> str:
    """Compute hex SHA-256 digest of a file."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class DatasetValidator:
    def __init__(self, data_dir: Path, check_files_exist: bool = False):
        self.data_dir = data_dir
        self.check_files_exist = check_files_exist
        self.metadata_dir = data_dir / "metadata"
        self.annotations_dir = data_dir / "annotations"
        self.raw_dir = data_dir / "raw"
        self.processed_dir = data_dir / "processed"
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def validate_all(self) -> bool:
        """Run all validation checks and return True if no errors."""
        self.errors.clear()
        self.warnings.clear()

        print(f"Validating dataset structure in: {self.data_dir.resolve()}")

        # 1. Check directories
        for d in [self.metadata_dir, self.annotations_dir, self.raw_dir, self.processed_dir]:
            if not d.exists() or not d.is_dir():
                self.errors.append(f"Missing required directory: {d}")

        if self.errors:
            return False

        # 2. Check metadata files exist
        manifest_file = self.metadata_dir / "manifest.json"
        passages_file = self.metadata_dir / "passages.json"
        speakers_file = self.metadata_dir / "speakers.json"

        for f in [manifest_file, passages_file, speakers_file]:
            if not f.exists():
                self.errors.append(f"Missing required metadata file: {f}")

        if self.errors:
            return False

        # 3. Load JSON files
        try:
            with open(passages_file, "r", encoding="utf-8") as f:
                passages = json.load(f)
            with open(speakers_file, "r", encoding="utf-8") as f:
                speakers = json.load(f)
            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as e:
            self.errors.append(f"Failed to parse metadata JSON files: {e}")
            return False

        # 4. Validate Passages
        passage_ids = self._validate_passages(passages)

        # 5. Validate Speakers & Splits
        speaker_splits = self._validate_speakers(speakers)

        # 6. Validate Manifest & Cross-references
        self._validate_manifest(manifest, passage_ids, speaker_splits)

        # Print summary
        if self.warnings:
            print("\nWARNINGS:")
            for w in self.warnings:
                print(f"  [WARN] {w}")

        if self.errors:
            print("\nERRORS:")
            for e in self.errors:
                print(f"  [FAIL] {e}")
            print(f"\nDataset validation FAILED with {len(self.errors)} error(s).")
            return False

        print(f"\nDataset validation PASSED ({len(manifest)} recording(s), {len(passages)} passage(s), {len(speakers)} speaker(s)).")
        return True

    def _validate_passages(self, passages: Any) -> Set[str]:
        passage_ids: Set[str] = set()
        if not isinstance(passages, list):
            self.errors.append("passages.json must contain a JSON array.")
            return passage_ids

        for idx, p in enumerate(passages):
            if not isinstance(p, dict):
                self.errors.append(f"Passage item at index {idx} must be an object.")
                continue
            pid = p.get("passage_id")
            if not pid or not isinstance(pid, str):
                self.errors.append(f"Passage index {idx} missing valid 'passage_id'.")
                continue
            if pid in passage_ids:
                self.errors.append(f"Duplicate passage_id: '{pid}'.")
            passage_ids.add(pid)

            if not p.get("text") or not isinstance(p.get("text"), str):
                self.errors.append(f"Passage '{pid}' must include a non-empty 'text' string.")
            if not p.get("title") or not isinstance(p.get("title"), str):
                self.errors.append(f"Passage '{pid}' must include a 'title' string.")

        return passage_ids

    def _validate_speakers(self, speakers: Any) -> Dict[str, str]:
        speaker_splits: Dict[str, str] = {}
        if not isinstance(speakers, list):
            self.errors.append("speakers.json must contain a JSON array.")
            return speaker_splits

        for idx, s in enumerate(speakers):
            if not isinstance(s, dict):
                self.errors.append(f"Speaker item at index {idx} must be an object.")
                continue
            spk_id = s.get("speaker_id")
            if not spk_id or not isinstance(spk_id, str):
                self.errors.append(f"Speaker index {idx} missing valid 'speaker_id'.")
                continue
            if spk_id in speaker_splits:
                self.errors.append(f"Duplicate speaker_id: '{spk_id}'.")

            split = s.get("split")
            if split not in VALID_SPLITS:
                self.errors.append(f"Speaker '{spk_id}' has invalid split '{split}'. Must be one of {VALID_SPLITS}.")
            else:
                speaker_splits[spk_id] = split

        # Enforce speaker separation check
        dev_speakers = {s for s, sp in speaker_splits.items() if sp == "dev"}
        test_speakers = {s for s, sp in speaker_splits.items() if sp == "test"}
        overlap = dev_speakers.intersection(test_speakers)
        if overlap:
            self.errors.append(f"CRITICAL: Speaker overlap between dev and test: {overlap}. Rule DEC-017 violated.")

        return speaker_splits

    def _validate_manifest(
        self,
        manifest: Any,
        passage_ids: Set[str],
        speaker_splits: Dict[str, str],
    ) -> None:
        if not isinstance(manifest, list):
            self.errors.append("manifest.json must contain a JSON array.")
            return

        recording_ids: Set[str] = set()
        baseline_passages: Set[str] = set()
        dev_baseline_passages: Set[str] = set()

        for idx, rec in enumerate(manifest):
            if not isinstance(rec, dict):
                self.errors.append(f"Manifest entry index {idx} must be an object.")
                continue

            rec_id = rec.get("recording_id")
            if not rec_id or not isinstance(rec_id, str):
                self.errors.append(f"Manifest entry {idx} missing valid 'recording_id'.")
                continue
            if rec_id in recording_ids:
                self.errors.append(f"Duplicate recording_id in manifest: '{rec_id}'.")
            recording_ids.add(rec_id)

            # Passage check
            pid = rec.get("passage_id")
            if pid not in passage_ids:
                self.errors.append(f"Recording '{rec_id}' references unknown passage_id '{pid}'.")

            # Speaker check & split match
            spk_id = rec.get("speaker_id")
            if spk_id not in speaker_splits:
                self.errors.append(f"Recording '{rec_id}' references unknown speaker_id '{spk_id}'.")
            else:
                expected_split = speaker_splits[spk_id]
                actual_split = rec.get("split")
                if actual_split != expected_split:
                    self.errors.append(
                        f"Recording '{rec_id}' split '{actual_split}' does not match speaker '{spk_id}' split '{expected_split}'."
                    )

            # Category check
            cat = rec.get("category")
            if cat not in VALID_CATEGORIES:
                self.errors.append(f"Recording '{rec_id}' has invalid category '{cat}'. Must be one of {VALID_CATEGORIES}.")
            elif cat == "baseline_effective":
                baseline_passages.add(pid)
                if rec.get("split") == "dev":
                    dev_baseline_passages.add(pid)

            # Synthetic check
            is_synth = rec.get("is_synthetic")
            if not isinstance(is_synth, bool):
                self.errors.append(f"Recording '{rec_id}' missing boolean 'is_synthetic'.")
            elif is_synth and cat != "flawed_synthetic":
                self.warnings.append(f"Recording '{rec_id}' marked is_synthetic=True but category is '{cat}'.")

            # Duration and audio metadata
            dur = rec.get("duration_s")
            if dur is None or not (isinstance(dur, (int, float)) and dur > 0):
                self.errors.append(f"Recording '{rec_id}' must have a positive 'duration_s'.")

            # Checksums presence
            sha_audio = rec.get("sha256_audio")
            if not sha_audio or not (isinstance(sha_audio, str) and len(sha_audio) == 64):
                self.errors.append(f"Recording '{rec_id}' missing valid 64-char hex 'sha256_audio'.")

            # File verification if requested
            audio_path_rel = rec.get("audio_file")
            if not audio_path_rel or not isinstance(audio_path_rel, str):
                self.errors.append(f"Recording '{rec_id}' missing 'audio_file'.")
            elif self.check_files_exist:
                audio_path = Path(audio_path_rel)
                if not audio_path.is_absolute():
                    audio_path = self.data_dir.parent / audio_path
                if not audio_path.exists():
                    self.errors.append(f"Recording '{rec_id}' audio file does not exist at '{audio_path}'.")
                elif sha_audio:
                    calc_hash = compute_sha256(audio_path)
                    if calc_hash != sha_audio:
                        self.errors.append(f"Recording '{rec_id}' sha256_audio mismatch: expected {sha_audio}, got {calc_hash}.")

            # Annotations verification
            ann_path_rel = rec.get("annotation_file")
            if cat in {"flawed_human_controlled", "flawed_synthetic"}:
                if not ann_path_rel:
                    self.errors.append(f"Flawed recording '{rec_id}' must specify an 'annotation_file'.")
                else:
                    self._validate_annotation_file(rec_id, ann_path_rel, dur)
            elif cat in {"baseline_effective", "clean_control"}:
                if ann_path_rel is not None:
                    self.warnings.append(f"Recording '{rec_id}' of category '{cat}' has non-null annotation_file.")

        # Baseline coverage checks
        for pid in passage_ids:
            if pid not in baseline_passages:
                self.warnings.append(f"Passage '{pid}' has no baseline_effective recordings registered.")
            elif pid not in dev_baseline_passages:
                self.warnings.append(
                    f"Passage '{pid}' has no baseline_effective recordings in 'dev' split. "
                    "Calibration on dev split requires at least one dev baseline per passage."
                )

    def _validate_annotation_file(self, rec_id: str, ann_path_rel: str, duration_s: Any) -> None:
        ann_path = Path(ann_path_rel)
        if not ann_path.is_absolute():
            ann_path = self.data_dir.parent / ann_path

        if not ann_path.exists():
            if self.check_files_exist:
                self.errors.append(f"Annotation file '{ann_path}' for recording '{rec_id}' does not exist.")
            return

        try:
            with open(ann_path, "r", encoding="utf-8") as f:
                ann_data = json.load(f)
        except Exception as e:
            self.errors.append(f"Failed to read annotation file '{ann_path}': {e}")
            return

        flaws = ann_data.get("flaws", [])
        if not isinstance(flaws, list):
            self.errors.append(f"Annotation file '{ann_path}' 'flaws' field must be an array.")
            return

        for f_idx, flaw in enumerate(flaws):
            ftype = flaw.get("flaw_type")
            if ftype not in CANONICAL_FLAW_TYPES:
                self.errors.append(
                    f"Annotation '{ann_path}' flaw #{f_idx} has invalid flaw_type '{ftype}'. Must be in {CANONICAL_FLAW_TYPES}."
                )

            start = flaw.get("start_s")
            end = flaw.get("end_s")
            if start is None or end is None:
                self.errors.append(f"Annotation '{ann_path}' flaw #{f_idx} missing start_s or end_s.")
            elif not (isinstance(start, (int, float)) and isinstance(end, (int, float))):
                self.errors.append(f"Annotation '{ann_path}' flaw #{f_idx} start_s and end_s must be numeric.")
            elif start < 0 or end <= start:
                self.errors.append(f"Annotation '{ann_path}' flaw #{f_idx} invalid interval [{start}, {end}].")
            elif isinstance(duration_s, (int, float)) and end > duration_s + 0.5:
                self.errors.append(
                    f"Annotation '{ann_path}' flaw #{f_idx} end_s ({end}s) exceeds recording duration ({duration_s}s)."
                )


def main():
    parser = argparse.ArgumentParser(description="Validate Track C speech analytics dataset schema and integrity.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Path to the data/ root directory (default: data)",
    )
    parser.add_argument(
        "--check-files",
        action="store_true",
        help="Verify actual audio and alignment files exist on disk and verify SHA-256 hashes.",
    )
    args = parser.parse_args()

    validator = DatasetValidator(data_dir=args.data_dir, check_files_exist=args.check_files)
    success = validator.validate_all()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
