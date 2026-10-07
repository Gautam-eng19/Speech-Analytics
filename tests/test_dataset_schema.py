"""Standard library runner for dataset schema tests."""

import json
import shutil
import sys
import tempfile
from pathlib import Path

# Add scripts directory
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "dataset"))

from validate_dataset import DatasetValidator, CANONICAL_FLAW_TYPES


def create_temp_dataset(tmp_path: Path):
    data_dir = tmp_path / "data"
    for subdir in ["raw", "processed", "metadata", "annotations"]:
        (data_dir / subdir).mkdir(parents=True)

    passages = [
        {
            "passage_id": "p001",
            "title": "Test Passage",
            "text": "This is test speech content.",
            "target_word_count": 5,
        }
    ]
    speakers = [
        {"speaker_id": "spk_01", "split": "dev", "gender": "f"},
        {"speaker_id": "spk_test_01", "split": "test", "gender": "m"},
    ]
    manifest = [
        {
            "recording_id": "rec_01",
            "passage_id": "p001",
            "speaker_id": "spk_01",
            "category": "baseline_effective",
            "split": "dev",
            "audio_file": "data/raw/rec_01.wav",
            "duration_s": 5.0,
            "sample_rate_hz": 16000,
            "channels": 1,
            "sha256_audio": "a" * 64,
            "alignment_file": "data/processed/rec_01.json",
            "sha256_alignment": "b" * 64,
            "annotation_file": None,
            "is_synthetic": False,
        }
    ]

    with open(data_dir / "metadata" / "passages.json", "w", encoding="utf-8") as f:
        json.dump(passages, f)
    with open(data_dir / "metadata" / "speakers.json", "w", encoding="utf-8") as f:
        json.dump(speakers, f)
    with open(data_dir / "metadata" / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f)

    return data_dir


def test_valid_dataset():
    temp_dir = Path(tempfile.mkdtemp())
    try:
        data_dir = create_temp_dataset(temp_dir)
        validator = DatasetValidator(data_dir)
        assert validator.validate_all() is True, "Expected valid dataset to pass"
        assert len(validator.errors) == 0
        print("  PASS: test_valid_dataset")
    finally:
        shutil.rmtree(temp_dir)


def test_speaker_split_overlap_rejected():
    temp_dir = Path(tempfile.mkdtemp())
    try:
        data_dir = create_temp_dataset(temp_dir)
        speakers = [
            {"speaker_id": "spk_01", "split": "dev"},
            {"speaker_id": "spk_01", "split": "test"},
        ]
        with open(data_dir / "metadata" / "speakers.json", "w", encoding="utf-8") as f:
            json.dump(speakers, f)

        validator = DatasetValidator(data_dir)
        assert validator.validate_all() is False, "Expected speaker overlap to fail"
        assert any("Duplicate speaker_id" in err or "CRITICAL: Speaker overlap" in err for err in validator.errors)
        print("  PASS: test_speaker_split_overlap_rejected")
    finally:
        shutil.rmtree(temp_dir)


def test_invalid_flaw_type_rejected():
    temp_dir = Path(tempfile.mkdtemp())
    try:
        data_dir = create_temp_dataset(temp_dir)
        ann_file = data_dir / "annotations" / "rec_flaw.flaws.json"
        ann_data = {
            "recording_id": "rec_flaw",
            "passage_id": "p001",
            "flaws": [
                {
                    "flaw_id": "f1",
                    "flaw_type": "completely_unsupported_flaw",
                    "start_s": 1.0,
                    "end_s": 2.0,
                }
            ],
        }
        with open(ann_file, "w", encoding="utf-8") as f:
            json.dump(ann_data, f)

        with open(data_dir / "metadata" / "manifest.json", "r", encoding="utf-8") as f:
            manifest = json.load(f)

        manifest.append({
            "recording_id": "rec_flaw",
            "passage_id": "p001",
            "speaker_id": "spk_01",
            "category": "flawed_human_controlled",
            "split": "dev",
            "audio_file": "data/raw/rec_flaw.wav",
            "duration_s": 5.0,
            "sample_rate_hz": 16000,
            "channels": 1,
            "sha256_audio": "c" * 64,
            "alignment_file": "data/processed/rec_flaw.json",
            "sha256_alignment": "d" * 64,
            "annotation_file": str(ann_file),
            "is_synthetic": False,
        })

        with open(data_dir / "metadata" / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        validator = DatasetValidator(data_dir)
        assert validator.validate_all() is False, "Expected unsupported flaw type to fail"
        assert any("invalid flaw_type" in err for err in validator.errors)
        print("  PASS: test_invalid_flaw_type_rejected")
    finally:
        shutil.rmtree(temp_dir)


def test_flaw_end_before_start_rejected():
    temp_dir = Path(tempfile.mkdtemp())
    try:
        data_dir = create_temp_dataset(temp_dir)
        ann_file = data_dir / "annotations" / "rec_flaw_inverted.flaws.json"
        ann_data = {
            "recording_id": "rec_flaw_inverted",
            "passage_id": "p001",
            "flaws": [
                {
                    "flaw_id": "f1",
                    "flaw_type": "too_fast",
                    "start_s": 3.0,
                    "end_s": 1.5,
                }
            ],
        }
        with open(ann_file, "w", encoding="utf-8") as f:
            json.dump(ann_data, f)

        with open(data_dir / "metadata" / "manifest.json", "r", encoding="utf-8") as f:
            manifest = json.load(f)

        manifest.append({
            "recording_id": "rec_flaw_inverted",
            "passage_id": "p001",
            "speaker_id": "spk_01",
            "category": "flawed_human_controlled",
            "split": "dev",
            "audio_file": "data/raw/rec_flaw_inverted.wav",
            "duration_s": 5.0,
            "sample_rate_hz": 16000,
            "channels": 1,
            "sha256_audio": "e" * 64,
            "alignment_file": "data/processed/rec_flaw_inverted.json",
            "sha256_alignment": "f" * 64,
            "annotation_file": str(ann_file),
            "is_synthetic": False,
        })

        with open(data_dir / "metadata" / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        validator = DatasetValidator(data_dir)
        assert validator.validate_all() is False, "Expected inverted interval to fail"
        assert any("invalid interval" in err for err in validator.errors)
        print("  PASS: test_flaw_end_before_start_rejected")
    finally:
        shutil.rmtree(temp_dir)


def test_dev_baseline_warning():
    temp_dir = Path(tempfile.mkdtemp())
    try:
        data_dir = create_temp_dataset(temp_dir)
        # Modify the baseline to be in 'test' split instead of 'dev'
        with open(data_dir / "metadata" / "manifest.json", "r", encoding="utf-8") as f:
            manifest = json.load(f)
        manifest[0]["split"] = "test"
        manifest[0]["speaker_id"] = "spk_test_01"
        with open(data_dir / "metadata" / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        validator = DatasetValidator(data_dir)
        assert validator.validate_all() is True, "Validation should pass (warnings do not fail validation)"
        assert any("no baseline_effective recordings in 'dev' split" in w for w in validator.warnings)
        print("  PASS: test_dev_baseline_warning")
    finally:
        shutil.rmtree(temp_dir)


if __name__ == "__main__":
    print("Running Dataset Schema Validation Test Suite...")
    test_valid_dataset()
    test_speaker_split_overlap_rejected()
    test_invalid_flaw_type_rejected()
    test_flaw_end_before_start_rejected()
    test_dev_baseline_warning()
    print("All 5 test cases PASSED successfully.")
