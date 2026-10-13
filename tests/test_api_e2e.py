"""A real HTTP round trip through the app (DEC-016, DEC-032): upload -> orchestrated pipeline -> cache -> /status and /result.

The app, the multipart parsing, the real `AnalysisPipeline`, the real response serialisation and the file cache are all in play;
only Whisper and WhisperX are replaced by exact-timing stand-ins (they cannot be downloaded in CI). The point is what the
fake-pipeline API tests cannot show: that a real result survives JSON serialisation as a valid contract object, that retrieval
returns exactly what the upload returned, and that failures reach the client as documented errors without internal text.
"""
from __future__ import annotations

import asyncio
import json
import math
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "backend" / "tests"))

from api_helpers import asgi_get  # noqa: E402
from app.api.deps import get_pipeline  # noqa: E402
from app.core.baseline import BaselineProvider  # noqa: E402
from app.core.cache import ResultCache  # noqa: E402
from app.core.passages import PassageCatalog  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.response import AnalysisResult, ErrorResponse, StatusResponse  # noqa: E402
from app.services.pipeline import AnalysisPipeline  # noqa: E402
from synthetic_speech import FakeAligner, FakeTranscriber, build_speech, normal_delivery  # noqa: E402
from test_pipeline_e2e import FLAWED_ITEMS, GAPS, _record_from, _write_baseline  # noqa: E402
from test_upload import asgi_post_multipart  # noqa: E402

FIELDS = {"baseline_id": "p001", "passage_id": "p001"}


@pytest.fixture()
def served(tmp_path):
    """The app wired to a real pipeline whose only fakes are the two models; yields (pipeline, wav bytes)."""
    _write_baseline(_record_from(normal_delivery(24, special_gaps=GAPS)), tmp_path / "baselines", "p001")
    wav, aligned = build_speech(FLAWED_ITEMS)
    pipeline = AnalysisPipeline(
        transcriber=FakeTranscriber(aligned.text), aligner=FakeAligner(aligned),
        baseline_provider=BaselineProvider(tmp_path / "baselines"), cache=ResultCache(tmp_path / "cache"),
        passages=PassageCatalog(tmp_path / "none.json"),
    )
    app.dependency_overrides[get_pipeline] = lambda: pipeline
    try:
        yield pipeline, wav
    finally:
        app.dependency_overrides.clear()


def post(wav: bytes, fields=FIELDS, filename: str = "take.wav"):
    return asyncio.run(asgi_post_multipart("/api/v1/analyze", fields, {"participant_audio": (filename, wav, "audio/wav")}))


def assert_all_finite(value: Any, path: str = "$") -> None:
    """json.loads accepts NaN / Infinity; the contract must never contain them."""
    if isinstance(value, float):
        assert math.isfinite(value), f"non-finite number at {path}"
    elif isinstance(value, dict):
        for k, v in value.items():
            assert_all_finite(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            assert_all_finite(v, f"{path}[{i}]")


def test_upload_result_is_a_valid_finite_contract_object_with_the_injected_flaws(served):
    pipeline, wav = served
    status, body = post(wav)
    assert status == 200
    assert_all_finite(body)
    result = AnalysisResult.model_validate(body)
    assert [f["type"] for f in body["flaws"]] == ["low_energy", "excessive_pause", "too_fast"]
    assert all(f["explanation"] and f["recommendation"] and f["rule"] and f["evidence"] for f in body["flaws"])
    assert body["processing_meta"]["cached"] is False and result.scores.composite_score < 100.0
    assert {n["code"] for n in body["notes"]} >= {"thresholds_uncalibrated", "pitch_not_scored"}
    assert body["config_fingerprint"] and body["baseline"]["sha256"] and body["audio"]["sha256"]


def test_the_stored_result_is_exactly_what_the_upload_returned(served):
    _, wav = served
    _, posted = post(wav)
    analysis_id = posted["analysis_id"]

    status, stored = asyncio.run(asgi_get(f"/api/v1/result/{analysis_id}"))
    assert status == 200 and stored == posted

    status, state = asyncio.run(asgi_get(f"/api/v1/status/{analysis_id}"))
    assert status == 200 and StatusResponse.model_validate(state).status.value == "done"


def test_a_repeated_upload_is_answered_from_the_cache_with_the_same_id_and_content(served):
    pipeline, wav = served
    _, first = post(wav)
    _, second = post(wav)
    assert second["processing_meta"]["cached"] is True and second["analysis_id"] == first["analysis_id"]
    assert AnalysisResult.model_validate(second).deterministic_json() == AnalysisResult.model_validate(first).deterministic_json()
    assert pipeline._transcriber.calls == 1 and pipeline._aligner.calls == 1


def test_a_baseline_that_does_not_exist_is_a_documented_404_without_server_paths(served, tmp_path):
    _, wav = served
    status, body = post(wav, {"baseline_id": "nope", "passage_id": "p001"})
    assert status == 404
    err = ErrorResponse.model_validate(body)
    assert err.error.value == "BASELINE_NOT_FOUND" and "'nope'" in err.detail
    assert str(tmp_path) not in err.detail and "baselines" not in err.detail


def test_a_file_that_passes_upload_checks_but_is_not_audio_is_a_400_with_a_fixed_message(served):
    _, _ = served
    status, body = post(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    assert status == 400
    err = ErrorResponse.model_validate(body)
    assert err.error.value == "UNSUPPORTED_AUDIO_FORMAT"
    assert err.detail == "The audio could not be decoded. Upload a valid WAV or MP3 recording."
    assert json.dumps(body).count("Errno") == 0


def test_a_failed_upload_leaves_nothing_to_retrieve(served, tmp_path):
    _, _ = served
    post(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    assert list((tmp_path / "cache").glob("*.json")) == []
