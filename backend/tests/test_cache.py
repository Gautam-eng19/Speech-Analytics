"""Tests for the deterministic analysis cache (ARCHITECTURE.md §26.4, DEC-023/032)."""
from __future__ import annotations

import json
import math
import os
import uuid

import pytest
from app.core.cache import (
    ResultCache,
    analysis_id_for_key,
    is_valid_analysis_id,
    make_cache_key,
)
from app.schemas.response import AnalysisResult
from test_api_contract import valid_result_dict

PARTS = {"audio_sha256": "a" * 64, "trim_start_s": 0.5, "baseline_sha256": "b" * 64, "passage_id": "p001",
         "config_version": "1.0.0", "manual_transcript_sha256": None}


def _result(analysis_id="3f2b8c1e-0000-4000-8000-000000000001") -> AnalysisResult:
    data = valid_result_dict()
    data["analysis_id"] = analysis_id
    return AnalysisResult.model_validate(data)


# ------------------------------------------------------------------ key and id
def test_key_is_deterministic_and_independent_of_dict_order():
    assert make_cache_key(PARTS) == make_cache_key(dict(reversed(list(PARTS.items()))))
    assert len(make_cache_key(PARTS)) == 64


@pytest.mark.parametrize("field,value", [
    ("audio_sha256", "c" * 64), ("trim_start_s", 0.52), ("baseline_sha256", "d" * 64), ("passage_id", "p002"),
    ("config_version", "1.0.1"), ("manual_transcript_sha256", "e" * 64),
])
def test_every_part_changes_the_key(field, value):
    assert make_cache_key({**PARTS, field: value}) != make_cache_key(PARTS)


def test_the_trim_offset_separates_otherwise_identical_audio():
    """DEC-023: two uploads that differ only in leading silence share the trimmed-audio hash but not the key."""
    with_offset = make_cache_key({**PARTS, "trim_start_s": 0.0})
    other_offset = make_cache_key({**PARTS, "trim_start_s": 1.0})
    assert with_offset != other_offset


def test_key_rejects_nan_and_unserialisable_parts():
    with pytest.raises(ValueError):
        make_cache_key({**PARTS, "x": math.nan})
    with pytest.raises(TypeError):
        make_cache_key({**PARTS, "x": object()})


def test_analysis_id_is_a_deterministic_version_5_uuid():
    key = make_cache_key(PARTS)
    a, b = analysis_id_for_key(key), analysis_id_for_key(key)
    assert a == b and is_valid_analysis_id(a)
    assert uuid.UUID(a).version == 5
    assert analysis_id_for_key(make_cache_key({**PARTS, "passage_id": "p002"})) != a


@pytest.mark.parametrize("bad", ["", "../etc/passwd", "3F2B8C1E-0000-4000-8000-000000000001", "3f2b8c1e00004000800000000000001",
                                 "3f2b8c1e-0000-4000-8000-00000000000g", "a/b", None, 7])
def test_invalid_ids_are_rejected(bad):
    assert is_valid_analysis_id(bad) is False


# ---------------------------------------------------------------- store/load
def test_put_then_get_roundtrips_and_leaves_no_temp_files(tmp_path):
    cache = ResultCache(tmp_path / "nested" / "cache")
    result = _result()
    path = cache.put(result)
    assert path.name == f"{result.analysis_id}.json" and path.is_file()
    assert cache.get(result.analysis_id) == result
    assert cache.exists(result.analysis_id)
    assert [p.name for p in path.parent.iterdir()] == [path.name]


def test_missing_and_invalid_ids_are_misses_not_errors(tmp_path):
    cache = ResultCache(tmp_path)
    assert cache.get("3f2b8c1e-0000-4000-8000-000000000009") is None
    assert cache.get("../../etc/passwd") is None and cache.get(None) is None
    assert cache.exists("not-an-id") is False
    with pytest.raises(ValueError):
        cache.path_for("../x")
    with pytest.raises(ValueError):
        cache.path_for("3f2b8c1e-0000-4000-8000-00000000000G")


def test_unreadable_or_invalid_files_are_misses_and_get_overwritten(tmp_path):
    cache = ResultCache(tmp_path)
    result = _result()
    path = cache.path_for(result.analysis_id)
    path.write_text("{not json", encoding="utf-8")
    assert cache.get(result.analysis_id) is None
    path.write_text(json.dumps({"analysis_id": result.analysis_id}), encoding="utf-8")       # schema-invalid
    assert cache.get(result.analysis_id) is None
    cache.put(result)
    assert cache.get(result.analysis_id) == result


def test_a_file_holding_another_analysis_id_is_a_miss(tmp_path):
    cache = ResultCache(tmp_path)
    other = _result("3f2b8c1e-0000-4000-8000-0000000000aa")
    cache.path_for("3f2b8c1e-0000-4000-8000-0000000000bb").write_text(other.model_dump_json(), encoding="utf-8")
    assert cache.get("3f2b8c1e-0000-4000-8000-0000000000bb") is None


def test_a_failed_write_leaves_no_partial_or_temp_file(tmp_path, monkeypatch):
    cache = ResultCache(tmp_path)
    result = _result()

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        cache.put(result)
    assert list(tmp_path.iterdir()) == []


def test_put_replaces_an_existing_result_atomically(tmp_path):
    cache = ResultCache(tmp_path)
    first = _result()
    cache.put(first)
    data = valid_result_dict()
    data["overall_summary"] = "updated"
    second = AnalysisResult.model_validate(data)
    cache.put(second)
    assert cache.get(first.analysis_id).overall_summary == "updated"
    assert len(list(tmp_path.iterdir())) == 1
