"""Backend support for the dashboard: baseline catalogue, CORS, serving the built UI, OpenAPI snapshot."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest
from api_helpers import asgi_request
from app.api.deps import get_pipeline
from app.core.baseline import BaselineProvider
from app.core.cache import ResultCache
from app.core.config import settings
from app.core.passages import PassageCatalog
from app.main import app, create_app
from app.schemas.common import API_CONTRACT_VERSION
from app.schemas.response import BaselineListResponse
from app.services.pipeline import AnalysisPipeline
from test_baseline_provider import _record, _write

ROOT = Path(__file__).resolve().parents[2]
PASSAGE_TEXT = "Welcome everyone. Today we present a system for speech delivery."


def run(coro):
    return asyncio.run(coro)


def get_json(path: str, application=None):
    status, headers, body = run(asgi_request("GET", path, application=application))
    return status, json.loads(body.decode("utf-8")) if body else None


@pytest.fixture()
def catalogue(tmp_path):
    """The app wired to a real pipeline (no models) over temporary baseline and passage files."""
    passages = tmp_path / "passages.json"
    passages.write_text(json.dumps([{"passage_id": "p001", "title": "Welcome", "text": PASSAGE_TEXT},
                                    {"passage_id": "p002", "text": "A second passage without a title."}]), encoding="utf-8")
    pipeline = AnalysisPipeline(
        baseline_provider=BaselineProvider(tmp_path / "baselines"), cache=ResultCache(tmp_path / "cache"),
        passages=PassageCatalog(passages),
    )
    app.dependency_overrides[get_pipeline] = lambda: pipeline
    try:
        yield tmp_path / "baselines"
    finally:
        app.dependency_overrides.clear()


# ------------------------------------------------------------------------------ baseline catalogue
def test_no_baselines_is_an_empty_catalogue_not_an_error(catalogue):
    status, body = get_json("/api/v1/baselines")
    assert status == 200 and body == {"baselines": [], "unavailable": []}


def test_a_baseline_is_listed_with_its_passage_and_thin_flags(catalogue):
    _write(catalogue, _record(passage_id="p001", n_rate_windows=3, n_pauses_within_phrase=10))
    status, body = get_json("/api/v1/baselines")
    assert status == 200
    parsed = BaselineListResponse.model_validate(body)
    (b,) = parsed.baselines
    assert (b.baseline_id, b.passage_id, b.dataset_version) == ("p001", "p001", "1.0.0")
    assert b.n_baseline_recordings == 2 and b.n_rate_windows == 3 and b.n_pauses_within_phrase == 10
    assert b.thin_rate_statistics is True and b.thin_pause_statistics is False                 # 3 < 5 windows, 10 >= 3 pauses
    assert b.passage_title == "Welcome" and b.passage_text == PASSAGE_TEXT and b.passage_word_count == 10
    assert len(b.sha256) == 64 and parsed.unavailable == []


def test_thin_rules_are_the_same_ones_that_produce_the_analysis_notes(catalogue, monkeypatch):
    _write(catalogue, _record(passage_id="p001", n_rate_windows=6, n_pauses_within_phrase=4))
    assert get_json("/api/v1/baselines")[1]["baselines"][0]["thin_rate_statistics"] is False
    monkeypatch.setattr(settings, "BASELINE_THIN_RATE_WINDOWS", 7)
    monkeypatch.setattr(settings, "BASELINE_THIN_PAUSES", 5)
    entry = get_json("/api/v1/baselines")[1]["baselines"][0]
    assert entry["thin_rate_statistics"] is True and entry["thin_pause_statistics"] is True


def test_several_baselines_for_one_passage_are_listed_sorted(catalogue):
    _write(catalogue, _record(passage_id="p002"))
    _write(catalogue, _record(passage_id="p001"), name="p001_speaker_b.json")
    _write(catalogue, _record(passage_id="p001"))
    body = get_json("/api/v1/baselines")[1]
    assert [(b["passage_id"], b["baseline_id"]) for b in body["baselines"]] == [
        ("p001", "p001"), ("p001", "p001_speaker_b"), ("p002", "p002")]
    assert body["baselines"][2]["passage_title"] is None and body["baselines"][2]["passage_text"].startswith("A second")


def test_the_catalogue_is_ordered_by_passage_then_baseline_not_by_file_name(catalogue):
    _write(catalogue, _record(passage_id="p002"), name="alpha.json")     # file-name order: alpha, zeta ...
    _write(catalogue, _record(passage_id="p001"), name="zeta.json")      # ... passage order: p001 (zeta), p002 (alpha)
    body = get_json("/api/v1/baselines")[1]
    assert [(b["passage_id"], b["baseline_id"]) for b in body["baselines"]] == [("p001", "zeta"), ("p002", "alpha")]


def test_a_baseline_for_an_unknown_passage_is_still_listed_without_passage_text(catalogue):
    _write(catalogue, _record(passage_id="p777"))
    (b,) = get_json("/api/v1/baselines")[1]["baselines"]
    assert b["passage_id"] == "p777" and b["passage_text"] is None and b["passage_word_count"] is None


def test_unusable_baseline_files_are_reported_with_codes_and_no_paths(catalogue):
    _write(catalogue, _record(passage_id="p001"))
    tampered = _write(catalogue, _record(passage_id="p002"), name="p002.json")
    data = json.loads(tampered.read_text(encoding="utf-8"))
    data["energy_db_mean"] += 1.0                                       # content no longer matches its sha256
    tampered.write_text(json.dumps(data), encoding="utf-8")
    (catalogue / "garbage.json").write_text("{ not json", encoding="utf-8")
    (catalogue / "folder.json").mkdir()                                 # matches the *.json glob but is not a file

    status, body = get_json("/api/v1/baselines")
    assert status == 200
    assert [b["baseline_id"] for b in body["baselines"]] == ["p001"]
    assert body["unavailable"] == [
        {"baseline_id": "folder", "reason": "unreadable"},
        {"baseline_id": "garbage", "reason": "invalid_file"},
        {"baseline_id": "p002", "reason": "integrity_check_failed"},
    ]
    assert str(catalogue.parent) not in json.dumps(body)


def test_the_catalogue_is_deterministic(catalogue):
    _write(catalogue, _record(passage_id="p001"))
    _write(catalogue, _record(passage_id="p002"))
    assert get_json("/api/v1/baselines")[1] == get_json("/api/v1/baselines")[1]


# ------------------------------------------------------------------------------------------- CORS
def test_cors_allows_configured_origins_only(monkeypatch):
    monkeypatch.setattr(settings, "CORS_ORIGINS", ["http://localhost:5173"])
    local = create_app(frontend_dist=Path("/nonexistent"))

    status, headers, _ = run(asgi_request("GET", "/api/v1/health", {"Origin": "http://localhost:5173"}, local))
    assert status == 200 and headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-credentials" not in headers

    status, headers, _ = run(asgi_request("GET", "/api/v1/health", {"Origin": "http://evil.example"}, local))
    assert status == 200 and "access-control-allow-origin" not in headers          # the request works, the browser blocks reading it

    status, headers, _ = run(asgi_request("OPTIONS", "/api/v1/analyze", {
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"}, local))
    assert status == 200 and headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "POST" in headers["access-control-allow-methods"]

    status, headers, _ = run(asgi_request("OPTIONS", "/api/v1/analyze", {
        "Origin": "http://evil.example", "Access-Control-Request-Method": "POST"}, local))
    assert status == 400 and "access-control-allow-origin" not in headers


def test_cors_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "CORS_ORIGINS", [])
    local = create_app(frontend_dist=Path("/nonexistent"))
    _, headers, _ = run(asgi_request("GET", "/api/v1/health", {"Origin": "http://localhost:5173"}, local))
    assert "access-control-allow-origin" not in headers


def test_cors_origins_setting_is_parsed_from_the_environment(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", " https://a.example , ,https://b.example ")
    from app.core.config import Settings
    assert Settings().CORS_ORIGINS == ["https://a.example", "https://b.example"]


# ------------------------------------------------------------------------------- serving the UI
@pytest.fixture()
def dist(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>Dashboard</title><div id=root></div>", encoding="utf-8")
    (root / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    return root


def test_the_built_dashboard_is_served_at_the_root_and_never_shadows_the_api(dist):
    local = create_app(frontend_dist=dist)
    status, headers, body = run(asgi_request("GET", "/", application=local))
    assert status == 200 and b"<title>Dashboard</title>" in body and headers["content-type"].startswith("text/html")
    status, headers, body = run(asgi_request("GET", "/assets/app.js", application=local))
    assert status == 200 and body == b"console.log('ok')"

    status, payload = get_json("/api/v1/health", local)
    assert status == 200 and payload["status"] == "ok" and payload["api_contract_version"] == API_CONTRACT_VERSION
    status, headers, body = run(asgi_request("GET", "/openapi.json", application=local))
    assert status == 200 and json.loads(body)["info"]["version"] == API_CONTRACT_VERSION
    status, _, _ = run(asgi_request("GET", "/docs", application=local))
    assert status == 200


def test_the_static_mount_cannot_escape_its_directory(dist, tmp_path):
    (tmp_path / "secret.txt").write_text("top secret", encoding="utf-8")
    local = create_app(frontend_dist=dist)
    for attempt in ("/../secret.txt", "/assets/../../secret.txt", "/%2e%2e/secret.txt"):
        status, _, body = run(asgi_request("GET", attempt, application=local))
        assert b"top secret" not in body, attempt


def test_without_a_built_dashboard_the_root_is_simply_not_found(tmp_path):
    local = create_app(frontend_dist=tmp_path / "missing")
    status, _, _ = run(asgi_request("GET", "/", application=local))
    assert status == 404
    assert run(asgi_request("GET", "/api/v1/health", application=local))[0] == 200


def test_a_dist_folder_without_index_html_is_not_mounted(tmp_path):
    """A half-built dist (assets but no index.html) must not be served at all."""
    half = tmp_path / "half_dist"
    (half / "assets").mkdir(parents=True)
    (half / "assets" / "app.js").write_text("console.log('stale')", encoding="utf-8")
    local = create_app(frontend_dist=half)
    assert run(asgi_request("GET", "/", application=local))[0] == 404
    assert run(asgi_request("GET", "/assets/app.js", application=local))[0] == 404
    assert run(asgi_request("GET", "/api/v1/health", application=local))[0] == 200


# --------------------------------------------------------------------------- OpenAPI snapshot
def test_the_committed_openapi_snapshot_matches_the_running_api():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "export_openapi.py"), "--check"], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, "frontend/openapi.json is out of date; run: python scripts/export_openapi.py\n" + result.stderr


def test_the_openapi_document_describes_the_catalogue_and_the_contract_version():
    document = json.loads((ROOT / "frontend" / "openapi.json").read_text(encoding="utf-8"))
    assert document["info"]["version"] == API_CONTRACT_VERSION
    assert "/api/v1/baselines" in document["paths"]
    assert {"BaselineSummary", "BaselineListResponse", "UnavailableBaseline", "AnalysisResult", "Flaw"} <= set(
        document["components"]["schemas"])
