"""API tests for the orchestrated endpoints: POST /analyze, GET /status/{id}, GET /result/{id} (DEC-016, DEC-032).

The pipeline is replaced by a fake, so these tests cover the HTTP layer: error mapping, what reaches the pipeline, that
internal error text never leaks, threading, and result retrieval from the cache.
"""
from __future__ import annotations

import asyncio
import threading

import pytest
from api_helpers import FakePipeline, asgi_get, install
from app.core.cache import ResultCache
from app.main import app
from app.schemas.common import ERROR_HTTP_STATUS, AnalysisStatus, ErrorCode
from app.schemas.response import AnalysisResult, ErrorResponse, StatusResponse
from app.services.pipeline import PipelineError
from test_api_contract import valid_result_dict
from test_upload import asgi_post_multipart

FIELDS = {"baseline_id": "b1", "passage_id": "p001"}
WAV = {"participant_audio": ("a.wav", b"RIFFxxxxWAVE", "audio/wav")}
KNOWN_ID = "3f2b8c1e-0000-4000-8000-000000000001"


def _result(analysis_id: str = KNOWN_ID) -> AnalysisResult:
    data = valid_result_dict()
    data["analysis_id"] = analysis_id
    return AnalysisResult.model_validate(data)


def _post(fields=None, files=None):
    # `None` means "use the valid default"; an explicit empty dict must stay empty (e.g. a request without a file).
    return asyncio.run(asgi_post_multipart(
        "/api/v1/analyze", FIELDS if fields is None else fields, WAV if files is None else files))


# ------------------------------------------------------------ error mapping
@pytest.mark.parametrize("code", [
    ErrorCode.AUDIO_TOO_LONG, ErrorCode.UNSUPPORTED_AUDIO_FORMAT, ErrorCode.VALIDATION_ERROR,
    ErrorCode.BASELINE_NOT_FOUND, ErrorCode.PROCESSING_ERROR,
])
def test_pipeline_errors_map_to_the_documented_status_and_body(code):
    install(FakePipeline(error=PipelineError(code, "specific detail")))
    status, body = _post()
    assert status == ERROR_HTTP_STATUS[code]
    err = ErrorResponse.model_validate(body)
    assert err.error == code and err.detail == "specific detail" and err.analysis_id is None


def test_unexpected_exceptions_become_a_generic_processing_error_without_leaking_details():
    install(FakePipeline(error=RuntimeError("secret internal path /srv/models/x.pt")))
    status, body = _post()
    assert status == 500
    err = ErrorResponse.model_validate(body)
    assert err.error == ErrorCode.PROCESSING_ERROR
    assert "secret" not in err.detail and "/srv" not in err.detail


# --------------------------------------------- validation happens before the pipeline
@pytest.mark.parametrize("fields,files", [
    ({"baseline_id": "b1"}, WAV),                                                                  # missing passage_id
    (FIELDS, {}),                                                                                  # no file
    (FIELDS, {"participant_audio": ("a.ogg", b"x", "audio/ogg")}),                                 # bad extension
    (FIELDS, {"participant_audio": ("a.wav", b"", "audio/wav")}),                                  # empty
    (FIELDS, {"participant_audio": ("a.wav", b"x", "audio/mpeg")}),                                # type mismatch
    ({**FIELDS, "config_version": "9.9.9"}, WAV),                                                  # config mismatch
    ({**FIELDS, "baseline_id": "../etc/passwd"}, WAV),                                             # unsafe id
])
def test_invalid_requests_never_reach_the_pipeline(fields, files):
    fake = install(FakePipeline(result=_result()))
    status, body = _post(fields, files)
    assert status in (400, 422)
    ErrorResponse.model_validate(body)
    assert fake.calls == []


def test_oversized_upload_is_rejected_before_the_pipeline(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "MAX_UPLOAD_BYTES", 10)
    fake = install(FakePipeline(result=_result()))
    status, body = _post(files={"participant_audio": ("a.wav", b"A" * 50, "audio/wav")})
    assert status == 400 and body["error"] == "FILE_TOO_LARGE" and fake.calls == []


# ----------------------------------------------------------------- threading
def test_the_pipeline_runs_in_a_worker_thread_not_on_the_event_loop():
    seen = []

    class Recording(FakePipeline):
        def analyze(self, audio_bytes, request):
            seen.append(threading.current_thread())
            return super().analyze(audio_bytes, request)

    install(Recording(result=_result()))
    status, _ = _post()
    assert status == 200 and len(seen) == 1
    assert seen[0] is not threading.main_thread()


# ------------------------------------------------------------ status / result
def test_status_and_result_for_a_stored_analysis(tmp_path):
    cache = ResultCache(tmp_path)
    stored = _result()
    cache.put(stored)
    install(FakePipeline(cache=cache))

    status, body = asyncio.run(asgi_get(f"/api/v1/status/{KNOWN_ID}"))
    assert status == 200
    assert StatusResponse.model_validate(body).status == AnalysisStatus.DONE

    status, body = asyncio.run(asgi_get(f"/api/v1/result/{KNOWN_ID}"))
    assert status == 200 and AnalysisResult.model_validate(body) == stored


def test_status_and_result_for_unknown_ids(tmp_path):
    install(FakePipeline(cache=ResultCache(tmp_path)))
    unknown = "3f2b8c1e-0000-4000-8000-0000000000ff"

    status, body = asyncio.run(asgi_get(f"/api/v1/status/{unknown}"))
    assert status == 200                                                       # HTTP 200 even for not_found (contract)
    parsed = StatusResponse.model_validate(body)
    assert parsed.status == AnalysisStatus.NOT_FOUND and parsed.analysis_id == unknown

    status, body = asyncio.run(asgi_get(f"/api/v1/result/{unknown}"))
    assert status == 404
    err = ErrorResponse.model_validate(body)
    assert err.error == ErrorCode.RESULT_NOT_FOUND and err.analysis_id == unknown


@pytest.mark.parametrize("bad_id", ["not-an-id", "12345", "..%2f..%2fetc%2fpasswd", "3F2B8C1E-0000-4000-8000-000000000001"])
def test_malformed_ids_are_not_found_and_not_echoed_in_errors(tmp_path, bad_id):
    install(FakePipeline(cache=ResultCache(tmp_path)))
    status, body = asyncio.run(asgi_get(f"/api/v1/result/{bad_id}"))
    assert status == 404 and body["error"] == "RESULT_NOT_FOUND" and body["analysis_id"] is None
    status, body = asyncio.run(asgi_get(f"/api/v1/status/{bad_id}"))
    assert status == 200 and body["status"] == "not_found"


def test_a_corrupt_stored_file_is_reported_as_not_found(tmp_path):
    cache = ResultCache(tmp_path)
    cache.path_for(KNOWN_ID).write_text("{broken", encoding="utf-8")
    install(FakePipeline(cache=cache))
    assert asyncio.run(asgi_get(f"/api/v1/status/{KNOWN_ID}"))[1]["status"] == "not_found"
    assert asyncio.run(asgi_get(f"/api/v1/result/{KNOWN_ID}"))[0] == 404


# ------------------------------------------------------------ real dependency wiring
def test_the_default_pipeline_is_created_lazily_once_and_without_loading_models(monkeypatch):
    from app.api import deps
    from app.services.pipeline import AnalysisPipeline

    monkeypatch.setattr(deps, "_pipeline", None)
    first = deps.get_pipeline()
    assert isinstance(first, AnalysisPipeline) and deps.get_pipeline() is first
    assert first._transcriber is None and first._aligner is None            # Whisper / WhisperX are created on first use only
    assert deps.get_cache(first) is first.cache


def test_the_result_endpoints_are_plain_functions_so_disk_reads_never_block_the_event_loop():
    import inspect

    from app.api.routes import results
    assert not inspect.iscoroutinefunction(results.get_status) and not inspect.iscoroutinefunction(results.get_result)


# ------------------------------------------------------------------- schema
def test_openapi_documents_all_endpoints_and_the_result_model():
    spec = app.openapi()
    assert set(spec["paths"]) == {
        "/api/v1/health", "/api/v1/analyze", "/api/v1/status/{analysis_id}", "/api/v1/result/{analysis_id}",
        "/api/v1/baselines", "/api/v1/custom/baselines", "/api/v1/custom/baselines/{baseline_id}"}
    ok = spec["paths"]["/api/v1/analyze"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok["$ref"].endswith("/AnalysisResult")
    schemas = spec["components"]["schemas"]
    assert {"notes", "config_fingerprint"} <= set(schemas["AnalysisResult"]["properties"])
    assert {"rule", "affected_words", "warnings"} <= set(schemas["Flaw"]["properties"])
