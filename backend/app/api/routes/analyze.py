"""Analysis endpoint: POST /api/v1/analyze (api-contract.md).

Validates the multipart upload (presence, extension, size, content type, config_version) with the public request schemas, then runs the
analysis pipeline synchronously in a worker thread and returns the `AnalysisResult`. Pipeline failures are returned as `ErrorResponse`
with the mapped status code; unexpected exceptions become a generic PROCESSING_ERROR (details are logged, never returned).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.api.deps import get_pipeline
from app.api.responses import error_response
from app.core.config import settings
from app.schemas.common import ErrorCode, SpeakerGender
from app.schemas.request import AnalyzeRequest, AudioUploadMeta, ALLOWED_AUDIO_EXTENSIONS
from app.schemas.response import AnalysisResult, ErrorResponse
from app.services.pipeline import AnalysisPipeline, PipelineError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/analyze",
    response_model=AnalysisResult,
    summary="Analyse a participant recording against a baseline",
    description=(
        "Accepts participant audio and analysis parameters via multipart/form-data, validates them, and runs the full "
        "analysis pipeline synchronously. Returns the structured, evidence-backed AnalysisResult."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Invalid input, file too large, audio too long or format unsupported"},
        404: {"model": ErrorResponse, "description": "Baseline not found"},
        422: {"model": ErrorResponse, "description": "Validation error in request fields or audio content"},
        500: {"model": ErrorResponse, "description": "Processing error"},
    },
)
async def analyze_audio(
    participant_audio: Optional[UploadFile] = File(None, description="Audio file in WAV or MP3 format"),
    baseline_id: Optional[str] = Form(None),
    passage_id: Optional[str] = Form(None),
    speaker_gender: Optional[str] = Form(None),
    config_version: Optional[str] = Form(None),
    manual_transcript: Optional[str] = Form(None),
    pipeline: AnalysisPipeline = Depends(get_pipeline),
):
    """Receive multipart/form-data, validate fields and file part per."""
    # 1. Validate file presence
    if participant_audio is None or not participant_audio.filename:
        return error_response(
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
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            f"Invalid request parameters: {exc}",
        )

    # 3. Check config_version mismatch if provided
    if parsed_request.config_version is not None:
        if parsed_request.config_version != settings.CONFIG_VERSION:
            return error_response(
                ErrorCode.CONFIG_VERSION_MISMATCH,
                f"Client config_version '{parsed_request.config_version}' does not match server '{settings.CONFIG_VERSION}'",
            )

    # 4. Check file extension first
    filename = os.path.basename((participant_audio.filename or "").replace("\\", "/"))
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        return error_response(
            ErrorCode.UNSUPPORTED_AUDIO_FORMAT,
            f"unsupported audio extension '{ext}'; expected WAV or MP3",
        )

    # 5. Read file contents and validate size
    try:
        content = await participant_audio.read()
    except Exception as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            f"Failed to read audio file: {exc}",
        )

    size_bytes = len(content)
    if size_bytes == 0:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "uploaded audio is empty",
        )

    if size_bytes > settings.MAX_UPLOAD_BYTES:
        return error_response(
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
            return error_response(
                ErrorCode.UNSUPPORTED_AUDIO_FORMAT,
                err_msg,
            )
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            err_msg,
        )

    # Validation succeeded: run the pipeline (CPU-bound, synchronous per) off the event loop.
    try:
        return await run_in_threadpool(pipeline.analyze, content, parsed_request)
    except PipelineError as exc:
        return error_response(exc.code, exc.detail)
    except Exception:  # noqa: BLE001 - never leak internals; the traceback is logged
        logger.exception("unexpected error while analysing %s", meta.filename)
        return error_response(ErrorCode.PROCESSING_ERROR, "An unexpected error occurred while analysing the audio.")
