"""Custom passages: POST /api/v1/custom/baselines and DELETE /api/v1/custom/baselines/{baseline_id} (API contract 1.3.0; DEC-044).

A user supplies their own passage text and 2 to 6 recordings of a good reading; the service makes a baseline from them
(`app.services.custom`) that `POST /analyze` and `GET /baselines` then treat like any other. The work is CPU-bound and synchronous (as
the analysis is, DEC-016); it holds the pipeline's lock because the speech models are shared. Nothing of the uploaded audio is kept.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.api.deps import get_custom_service
from app.api.responses import error_response
from app.schemas.common import ErrorCode
from app.schemas.response import CustomBaselineDeleted, CustomBaselineResult, ErrorResponse
from app.services.custom import CustomBaselineService, CustomError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/custom/baselines",
    response_model=CustomBaselineResult,
    summary="Make a baseline from your own passage and recordings",
    description=(
        "Accepts the passage text (`passage_text`, optional `title`) and 2 to 6 recordings of a good reading of it (`baseline_audio`, WAV or MP3), "
        "aligns each recording to the text, checks that it reads the passage, and stores a baseline under a `custom-…` id. Use that id as "
        "`baseline_id` and `passage_id` in `POST /analyze`. Only statistics are stored, never the audio. The same text and recordings give the same id."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Unsupported or oversized audio"},
        422: {"model": ErrorResponse, "description": "The passage or a recording is not usable"},
        500: {"model": ErrorResponse, "description": "Processing error"},
    },
)
async def create_custom_baseline(
    passage_text: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    baseline_audio: Optional[List[UploadFile]] = File(None),
    service: CustomBaselineService = Depends(get_custom_service),
):
    if passage_text is None or not passage_text.strip():
        return error_response(ErrorCode.VALIDATION_ERROR, "Enter the passage text that the recordings will read.")
    uploads = [u for u in (baseline_audio or []) if u is not None and u.filename]
    files = []
    for upload in uploads:
        try:
            files.append((upload.filename or "recording", await upload.read()))
        except Exception as exc:  # noqa: BLE001
            return error_response(ErrorCode.VALIDATION_ERROR, f"Failed to read “{upload.filename}”: {exc}")
    try:
        return await run_in_threadpool(service.create, passage_text, title, files)
    except CustomError as exc:
        return error_response(exc.code, exc.detail)
    except Exception:  # noqa: BLE001 - never leak internals; the traceback is logged
        logger.exception("unexpected error while making a custom baseline")
        return error_response(ErrorCode.PROCESSING_ERROR, "An unexpected error occurred while making the baseline.")


@router.delete(
    "/custom/baselines/{baseline_id}",
    response_model=CustomBaselineDeleted,
    summary="Delete a custom baseline",
    description="Removes a baseline made from a user's own passage and recordings, and its passage text. Project baselines cannot be deleted.",
    responses={404: {"model": ErrorResponse, "description": "No such custom baseline"}, 422: {"model": ErrorResponse, "description": "Not a custom id"}},
)
async def delete_custom_baseline(baseline_id: str, service: CustomBaselineService = Depends(get_custom_service)):
    try:
        return await run_in_threadpool(service.delete, baseline_id)
    except CustomError as exc:
        return error_response(exc.code, exc.detail)
