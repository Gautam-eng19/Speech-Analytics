"""Audio upload validation endpoint (ARCHITECTURE.md §6.1, §10, §23; api-contract.md).

TASK-012: Handles multipart/form-data upload, validates file presence, format,
and size limits using centralized configuration and Pydantic schemas.
Does not perform analytical processing or feature extraction.
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.schemas.common import ErrorCode, ERROR_HTTP_STATUS, SpeakerGender
from app.schemas.request import AnalyzeRequest, AudioUploadMeta, ALLOWED_AUDIO_EXTENSIONS
from app.schemas.response import ErrorResponse

router = APIRouter()


def _error_response(error: ErrorCode, detail: str) -> JSONResponse:
    """Helper to return standardized ErrorResponse matching HTTP mapping."""
    status_code = ERROR_HTTP_STATUS.get(error, status.HTTP_400_BAD_REQUEST)
    err = ErrorResponse(
        error=error,
        detail=detail,
        analysis_id=None,
    )
    return JSONResponse(status_code=status_code, content=err.model_dump())


@router.post(
    "/analyze",
    summary="Upload and validate audio for analysis",
    description=(
        "Accepts participant audio and analysis parameters via multipart/form-data. "
        "Validates upload parameters, format, and size limits per canonical contract."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Invalid input, file too large, or format unsupported"},
        422: {"model": ErrorResponse, "description": "Validation error in request fields"},
    },
)
async def analyze_audio(
    participant_audio: Optional[UploadFile] = File(None, description="Audio file in WAV or MP3 format"),
    baseline_id: Optional[str] = Form(None),
    passage_id: Optional[str] = Form(None),
    speaker_gender: Optional[str] = Form(None),
    config_version: Optional[str] = Form(None),
    manual_transcript: Optional[str] = Form(None),
):
    """Receive multipart/form-data, validate fields and file part per TASK-012."""
    # 1. Validate file presence
    if participant_audio is None or not participant_audio.filename:
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "participant_audio file is required",
        )

    # 2. Validate form fields using AnalyzeRequest schema
    try:
        gender_enum = SpeakerGender(speaker_gender) if speaker_gender is not None else None
        parsed_request = AnalyzeRequest(
            baseline_id=baseline_id,
            passage_id=passage_id,
            speaker_gender=gender_enum,
            config_version=config_version,
            manual_transcript=manual_transcript,
        )
    except Exception as exc:
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            f"Invalid request parameters: {exc}",
        )

    # 3. Check config_version mismatch if provided (ARCHITECTURE.md §23)
    if parsed_request.config_version is not None:
        if parsed_request.config_version != settings.CONFIG_VERSION:
            return _error_response(
                ErrorCode.CONFIG_VERSION_MISMATCH,
                f"Client config_version '{parsed_request.config_version}' does not match server '{settings.CONFIG_VERSION}'",
            )

    # 4. Check file extension first
    filename = os.path.basename((participant_audio.filename or "").replace("\\", "/"))
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        return _error_response(
            ErrorCode.UNSUPPORTED_AUDIO_FORMAT,
            f"unsupported audio extension '{ext}'; expected WAV or MP3",
        )

    # 5. Read file contents and validate size
    try:
        content = await participant_audio.read()
    except Exception as exc:
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            f"Failed to read audio file: {exc}",
        )

    size_bytes = len(content)
    if size_bytes == 0:
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "uploaded audio is empty",
        )

    if size_bytes > settings.MAX_UPLOAD_BYTES:
        return _error_response(
            ErrorCode.FILE_TOO_LARGE,
            f"upload of {size_bytes} bytes exceeds limit of {settings.MAX_UPLOAD_BYTES} bytes",
        )

    # 6. Validate content type and metadata using AudioUploadMeta schema
    content_type = participant_audio.content_type or ""
    try:
        meta = AudioUploadMeta(
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
        )
        meta.ensure_within_limit(settings.MAX_UPLOAD_BYTES)
    except Exception as exc:
        # If the content-type does not match or is unsupported
        err_msg = str(exc)
        if "unsupported content type" in err_msg or "does not match content type" in err_msg or "unsupported audio extension" in err_msg:
            return _error_response(
                ErrorCode.UNSUPPORTED_AUDIO_FORMAT,
                err_msg,
            )
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            err_msg,
        )

    # Validation succeeded.
    # Note: Analytical pipeline (preprocessing, ASR, alignment, feature extraction, scoring)
    # is owned by subsequent tasks (TASK-013, TASK-021, TASK-022, TASK-040, etc.).
    return {
        "status": "valid",
        "filename": meta.filename,
        "content_type": meta.content_type,
        "size_bytes": meta.size_bytes,
        "baseline_id": parsed_request.baseline_id,
        "passage_id": parsed_request.passage_id,
    }
