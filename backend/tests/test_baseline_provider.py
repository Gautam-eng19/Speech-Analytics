"""Tests for BaselineStatsRecord and BaselineProvider (TASK-040, DEC-015).

Covers:
- Record validation (finite numbers, ordering, ids, extra fields) and the canonical sha256
- Provider lookup, integrity verification and explicit, typed failures
- Path-traversal safety of passage identifiers
- Compatibility with the API BaselineStats shape
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.core.baseline import (
    BaselineIntegrityError,
    BaselineNotFoundError,
    BaselineProvider,
)
from app.core.config import settings
from app.schemas.contracts import BaselineStatsRecord
from app.schemas.response import BaselineStats

PLACEHOLDER = "0" * 64


def _record_kwargs(**overrides):
    data = dict(
        passage_id="p001",
        dataset_version="1.0.0",
        baseline_recording_ids=["rec_a", "rec_b"],
        f0_voiced_hz_mean=150.0,
        f0_voiced_hz_std=20.0,
        f0_voiced_hz_p05=120.0,
        f0_voiced_hz_p95=185.0,
        energy_db_mean=-25.0,
        energy_db_std=5.0,
        rate_wpm_mean=140.0,
        rate_wpm_std=15.0,
        pause_within_phrase_mean_s=0.35,
        pause_within_phrase_std_s=0.07,
        pause_cross_sentence_mean_s=0.7,
        pause_cross_sentence_std_s=None,
        n_f0_voiced_frames=1000,
        n_energy_frames=1500,
        n_rate_windows=6,
        n_pauses_within_phrase=4,
        n_pauses_cross_sentence=2,
        n_pauses_unknown_boundary=0,
        config_snapshot={"energy_frame_selection": "active", "std_ddof": 1},
        sha256=PLACEHOLDER,
    )
    data.update(overrides)
    return data


def _record(**overrides) -> BaselineStatsRecord:
    return BaselineStatsRecord(**_record_kwargs(**overrides)).with_computed_sha256()


def _write(directory: Path, record: BaselineStatsRecord, name: str = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (name or f"{record.passage_id}.json")
    path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return path


# ------------------------------------------------------------------ record
def test_valid_record_and_hash_roundtrip():
    rec = _record()
    assert rec.verify_sha256()
    assert len(rec.sha256) == 64 and rec.sha256 != PLACEHOLDER
    again = BaselineStatsRecord.model_validate_json(rec.model_dump_json())
    assert again == rec and again.verify_sha256()


def test_hash_is_deterministic_and_content_sensitive():
    assert _record().sha256 == _record().sha256
    assert _record(f0_voiced_hz_mean=151.0).sha256 != _record().sha256
    assert _record(config_snapshot={"energy_frame_selection": "all", "std_ddof": 1}).sha256 != _record().sha256


def test_hash_ignores_json_formatting():
    rec = _record()
    reformatted = BaselineStatsRecord.model_validate(json.loads(json.dumps(rec.model_dump(mode="json"), indent=7)))
    assert reformatted.verify_sha256()


def test_stale_hash_fails_verification():
    rec = _record()
    tampered = rec.model_copy(update={"energy_db_mean": -10.0})
    assert not tampered.verify_sha256()


def test_response_stats_conversion_matches_api_shape():
    rec = _record(pause_cross_sentence_std_s=0.1)
    stats = rec.to_response_stats()
    assert type(stats) is BaselineStats
    assert set(stats.model_dump()) == set(BaselineStats.model_fields)
    assert stats.f0_voiced_hz_mean == 150.0 and stats.pause_cross_sentence_std_s == 0.1
    assert "passage_id" not in stats.model_dump() and "sha256" not in stats.model_dump()


@pytest.mark.parametrize(
    "overrides",
    [
        {"f0_voiced_hz_mean": float("nan")},
        {"energy_db_std": float("inf")},
        {"f0_voiced_hz_std": -1.0},
        {"f0_voiced_hz_p05": 200.0},  # p05 > p95
        {"baseline_recording_ids": []},
        {"baseline_recording_ids": ["rec_a", "rec_a"]},
        {"baseline_recording_ids": ["../evil"]},
        {"passage_id": "../p001"},
        {"dataset_version": ""},
        {"sha256": "xyz"},
        {"n_rate_windows": -1},
        {"config_snapshot": {"nested": {"a": 1}}},
    ],
)
def test_invalid_record_rejected(overrides):
    with pytest.raises(ValueError):
        BaselineStatsRecord(**_record_kwargs(**overrides))


def test_extra_fields_rejected():
    with pytest.raises(ValueError):
        BaselineStatsRecord(**_record_kwargs(), unexpected=1)


def test_missing_required_percentiles_rejected():
    kwargs = _record_kwargs()
    del kwargs["f0_voiced_hz_p05"]
    with pytest.raises(ValueError):
        BaselineStatsRecord(**kwargs)


# ---------------------------------------------------------------- provider
def test_default_directory_comes_from_settings():
    assert BaselineProvider().directory == Path(settings.DATA_DIR) / "processed" / "baseline_stats"


def test_get_returns_verified_record(tmp_path):
    rec = _record()
    _write(tmp_path, rec)
    got = BaselineProvider(tmp_path).get("p001")
    assert got == rec
    assert BaselineProvider(tmp_path).get("p001") == got  # repeatable


def test_missing_passage_raises_not_found(tmp_path):
    with pytest.raises(BaselineNotFoundError):
        BaselineProvider(tmp_path).get("p999")
    with pytest.raises(BaselineNotFoundError):
        BaselineProvider(tmp_path / "does_not_exist").get("p001")


@pytest.mark.parametrize("bad_id", ["../secret", "a/b", "a\\b", "", " p1", "p 1", ".hidden", "p001.json", None, 5])
def test_unsafe_identifiers_are_rejected_before_touching_the_filesystem(tmp_path, bad_id):
    (tmp_path.parent / "secret.json").write_text("{}", encoding="utf-8")
    provider = BaselineProvider(tmp_path)
    with pytest.raises(BaselineNotFoundError):
        provider.get(bad_id)
    assert provider.exists(bad_id) is False


def test_tampered_file_fails_integrity(tmp_path):
    rec = _record()
    path = _write(tmp_path, rec)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["rate_wpm_mean"] = 999.0
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(BaselineIntegrityError, match="sha256"):
        BaselineProvider(tmp_path).get("p001")


def test_file_for_another_passage_is_rejected(tmp_path):
    _write(tmp_path, _record(passage_id="p001"), name="p002.json")
    with pytest.raises(BaselineIntegrityError, match="describes passage"):
        BaselineProvider(tmp_path).get("p002")


def test_corrupt_and_invalid_files_raise_integrity_error(tmp_path):
    (tmp_path / "p001.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(BaselineIntegrityError):
        BaselineProvider(tmp_path).get("p001")

    (tmp_path / "p002.json").write_text(json.dumps({"passage_id": "p002"}), encoding="utf-8")
    with pytest.raises(BaselineIntegrityError):
        BaselineProvider(tmp_path).get("p002")


def test_non_finite_values_in_file_are_rejected(tmp_path):
    rec = _record()
    text = rec.model_dump_json().replace('"f0_voiced_hz_mean":150.0', '"f0_voiced_hz_mean":NaN')
    assert "NaN" in text
    (tmp_path / "p001.json").write_text(text, encoding="utf-8")
    with pytest.raises(BaselineIntegrityError):
        BaselineProvider(tmp_path).get("p001")


def test_list_and_exists(tmp_path):
    _write(tmp_path, _record(passage_id="p002"))
    _write(tmp_path, _record(passage_id="p001"))
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / "bad name.json").write_text("{}", encoding="utf-8")
    provider = BaselineProvider(tmp_path)
    assert provider.list_passages() == ["p001", "p002"]
    assert provider.exists("p001") and not provider.exists("p003")
    assert BaselineProvider(tmp_path / "missing").list_passages() == []
