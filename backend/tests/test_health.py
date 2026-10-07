"""Tests for FastAPI skeleton and health endpoint (TASK-010)."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Tuple

import pytest
from app.main import app
from app.schemas.response import HealthResponse


async def asgi_request(
    method: str,
    path: str,
    headers: list[tuple[bytes, bytes]] | None = None,
    body: bytes = b"",
) -> Tuple[int, Dict[str, Any]]:
    """Helper to perform requests directly against the ASGI app without extra dependencies."""
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method.upper(),
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": headers or [],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
    }

    status_code = [None]
    body_chunks = []

    async def send(msg: dict) -> None:
        if msg["type"] == "http.response.start":
            status_code[0] = msg["status"]
        elif msg["type"] == "http.response.body":
            body_chunks.append(msg.get("body", b""))

    async def receive() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    await app(scope, receive, send)

    raw_response = b"".join(body_chunks).decode("utf-8")
    parsed_json = json.loads(raw_response) if raw_response else {}
    return status_code[0], parsed_json


def test_app_startup_and_metadata():
    """Verify application can be instantiated and exposes correct metadata."""
    assert app.title == "Speech Analytics API"
    assert app.version == "1.0.0"


def test_health_endpoint():
    """Verify GET /api/v1/health returns 200 with schema-conforming payload."""
    status, payload = asyncio.run(asgi_request("GET", "/api/v1/health"))
    assert status == 200

    # Validate directly against canonical HealthResponse schema
    health = HealthResponse.model_validate(payload)
    assert health.status == "ok"
    assert health.config_version == "1.0.0"
    assert health.pipeline_version == "1.0.0"
    assert health.api_contract_version == "1.0.0"


def test_validation_error_handler():
    """Verify 404/invalid routes return cleanly without unhandled exceptions."""
    status, payload = asyncio.run(asgi_request("GET", "/api/v1/nonexistent"))
    assert status == 404
