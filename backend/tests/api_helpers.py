"""Helpers for API tests: a fake pipeline and a raw-ASGI GET (no HTTP client dependency)."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from app.core.cache import ResultCache
from app.main import app
from app.api.deps import get_cache, get_pipeline
from app.schemas.request import AnalyzeRequest


class FakePipeline:
    """Stands in for `AnalysisPipeline`: records calls, returns a canned result or raises a canned error."""

    def __init__(self, result: Any = None, error: Optional[BaseException] = None, cache: Optional[ResultCache] = None) -> None:
        self.result = result
        self.error = error
        self.cache = cache
        self.calls: List[Tuple[bytes, AnalyzeRequest]] = []

    def analyze(self, audio_bytes: bytes, request: AnalyzeRequest) -> Any:
        self.calls.append((audio_bytes, request))
        if self.error is not None:
            raise self.error
        return self.result


def install(fake: FakePipeline) -> FakePipeline:
    """Route the app's pipeline (and, through it, its cache) to `fake`."""
    app.dependency_overrides[get_pipeline] = lambda: fake
    if fake.cache is not None:
        app.dependency_overrides[get_cache] = lambda: fake.cache
    return fake


async def asgi_get(path: str) -> Tuple[int, Dict[str, Any]]:
    """GET `path` against the ASGI app and return (status, parsed JSON body)."""
    scope = {
        "type": "http", "http_version": "1.1", "method": "GET", "path": path, "raw_path": path.encode("ascii"),
        "query_string": b"", "headers": [], "client": ("127.0.0.1", 12345), "server": ("127.0.0.1", 8000),
    }
    status = [None]
    chunks: List[bytes] = []

    async def send(msg: dict) -> None:
        if msg["type"] == "http.response.start":
            status[0] = msg["status"]
        elif msg["type"] == "http.response.body":
            chunks.append(msg.get("body", b""))

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    await app(scope, receive, send)
    raw = b"".join(chunks).decode("utf-8")
    return status[0], (json.loads(raw) if raw else {})


async def asgi_request(
    method: str, path: str, headers: Optional[Dict[str, str]] = None, application: Any = None
) -> Tuple[int, Dict[str, str], bytes]:
    """Send any request to `application` (default: the shared app) and return (status, lower-cased response headers, raw body)."""
    target = application if application is not None else app
    scope = {
        "type": "http", "http_version": "1.1", "method": method, "path": path, "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()],
        "client": ("127.0.0.1", 12345), "server": ("127.0.0.1", 8000),
    }
    status = [0]
    response_headers: Dict[str, str] = {}
    chunks: List[bytes] = []

    async def send(msg: dict) -> None:
        if msg["type"] == "http.response.start":
            status[0] = msg["status"]
            response_headers.update({k.decode("latin-1").lower(): v.decode("latin-1") for k, v in msg.get("headers", [])})
        elif msg["type"] == "http.response.body":
            chunks.append(msg.get("body", b""))

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    await target(scope, receive, send)
    return status[0], response_headers, b"".join(chunks)
