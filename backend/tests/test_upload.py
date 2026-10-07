"""Tests for audio upload and validation endpoint (TASK-012)."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

import pytest
from app.core.config import settings
from app.main import app
from app.schemas.common import ErrorCode
from app.schemas.response import ErrorResponse


def build_multipart(
    fields: Dict[str, str],
    files: Dict[str, Tuple[str, bytes, str]],
) -> Tuple[List[Tuple[bytes, bytes]], bytes]:
    """Helper to encode multipart/form-data payload without external libraries."""
    boundary = "----WebKitFormBoundaryTest7MA4YWxkTrZu0gW"
    chunks: List[bytes] = []

    for name, value in fields.items():
        chunk = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode("utf-8")
        chunks.append(chunk)

    for name, (filename, content, content_type) in files.items():
        chunk = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8") + content + b"\r\n"
        chunks.append(chunk)

    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(chunks)
    headers = [
        (b"content-type", f"multipart/form-data; boundary={boundary}".encode("ascii")),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    return headers, body


async def asgi_post_multipart(
    path: str,
    fields: Dict[str, str],
    files: Dict[str, Tuple[str, bytes, str]],
) -> Tuple[int, Dict[str, Any]]:
    """Send an ASGI POST request with multipart body."""
    headers, body = build_multipart(fields, files)
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": headers,
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


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

def test_valid_audio_upload_wav():
    """Verify that a valid WAV upload passes validation and returns 200."""
    fields = {"baseline_id": "b_test_01", "passage_id": "p001"}
    files = {"participant_audio": ("test_sample.wav", b"RIFFfake1234WAVEfmt ", "audio/wav")}

    status, resp = asyncio.run(asgi_post_multipart("/api/v1/analyze", fields, files))
    assert status == 200
    assert resp["status"] == "valid"
    assert resp["filename"] == "test_sample.wav"
    assert resp["content_type"] == "audio/wav"
    assert resp["baseline_id"] == "b_test_01"
    assert resp["passage_id"] == "p001"
    assert resp["size_bytes"] == len(b"RIFFfake1234WAVEfmt ")


def test_valid_audio_upload_mp3():
    """Verify that a valid MP3 upload passes validation and returns 200."""
    fields = {"baseline_id": "b_test_01", "passage_id": "p001"}
    files = {"participant_audio": ("sample.mp3", b"ID3fake1234data", "audio/mpeg")}

    status, resp = asyncio.run(asgi_post_multipart("/api/v1/analyze", fields, files))
    assert status == 200
    assert resp["status"] == "valid"
    assert resp["filename"] == "sample.mp3"
    assert resp["content_type"] == "audio/mpeg"


def test_missing_audio_file():
    """Verify missing audio file triggers ErrorResponse with VALIDATION_ERROR and HTTP 422."""
    fields = {"baseline_id": "b_test_01", "passage_id": "p001"}
    files = {}

    status, resp = asyncio.run(asgi_post_multipart("/api/v1/analyze", fields, files))
    assert status == 422
    err = ErrorResponse.model_validate(resp)
    assert err.error == ErrorCode.VALIDATION_ERROR
    assert "participant_audio file is required" in err.detail


def test_missing_required_form_fields():
    """Verify missing baseline_id or passage_id triggers ErrorResponse with VALIDATION_ERROR."""
    fields = {"baseline_id": "b_test_01"}  # missing passage_id
    files = {"participant_audio": ("test.wav", b"RIFF1234WAVE", "audio/wav")}

    status, resp = asyncio.run(asgi_post_multipart("/api/v1/analyze", fields, files))
    assert status == 422
    err = ErrorResponse.model_validate(resp)
    assert err.error == ErrorCode.VALIDATION_ERROR


def test_unsupported_audio_extension():
    """Verify unsupported file extension (e.g. .ogg or .txt) triggers UNSUPPORTED_AUDIO_FORMAT and HTTP 400."""
    fields = {"baseline_id": "b1", "passage_id": "p1"}
    files = {"participant_audio": ("audio.ogg", b"OGGDATA", "audio/ogg")}

    status, resp = asyncio.run(asgi_post_multipart("/api/v1/analyze", fields, files))
    assert status == 400
    err = ErrorResponse.model_validate(resp)
    assert err.error == ErrorCode.UNSUPPORTED_AUDIO_FORMAT
    assert "unsupported audio extension" in err.detail


def test_extension_content_type_mismatch():
    """Verify mismatch between extension and MIME type is rejected with UNSUPPORTED_AUDIO_FORMAT."""
    fields = {"baseline_id": "b1", "passage_id": "p1"}
    files = {"participant_audio": ("audio.wav", b"DATA", "audio/mpeg")}  # .wav with audio/mpeg

    status, resp = asyncio.run(asgi_post_multipart("/api/v1/analyze", fields, files))
    assert status == 400
    err = ErrorResponse.model_validate(resp)
    assert err.error == ErrorCode.UNSUPPORTED_AUDIO_FORMAT


def test_empty_audio_file():
    """Verify 0-byte audio file is rejected with VALIDATION_ERROR and HTTP 422."""
    fields = {"baseline_id": "b1", "passage_id": "p1"}
    files = {"participant_audio": ("empty.wav", b"", "audio/wav")}

    status, resp = asyncio.run(asgi_post_multipart("/api/v1/analyze", fields, files))
    assert status == 422
    err = ErrorResponse.model_validate(resp)
    assert err.error == ErrorCode.VALIDATION_ERROR
    assert "empty" in err.detail


def test_oversized_audio_file(monkeypatch):
    """Verify file exceeding MAX_UPLOAD_BYTES triggers FILE_TOO_LARGE and HTTP 400."""
    # Temporarily set max upload bytes limit to 50 bytes for test
    monkeypatch.setattr(settings, "MAX_UPLOAD_BYTES", 50)

    fields = {"baseline_id": "b1", "passage_id": "p1"}
    files = {"participant_audio": ("large.wav", b"A" * 100, "audio/wav")}

    status, resp = asyncio.run(asgi_post_multipart("/api/v1/analyze", fields, files))
    assert status == 400
    err = ErrorResponse.model_validate(resp)
    assert err.error == ErrorCode.FILE_TOO_LARGE
    assert "exceeds limit" in err.detail


def test_config_version_mismatch():
    """Verify mismatch in config_version returns CONFIG_VERSION_MISMATCH and HTTP 400."""
    fields = {
        "baseline_id": "b1",
        "passage_id": "p1",
        "config_version": "999.0.0",  # server is 1.0.0
    }
    files = {"participant_audio": ("test.wav", b"RIFF1234WAVE", "audio/wav")}

    status, resp = asyncio.run(asgi_post_multipart("/api/v1/analyze", fields, files))
    assert status == 400
    err = ErrorResponse.model_validate(resp)
    assert err.error == ErrorCode.CONFIG_VERSION_MISMATCH
