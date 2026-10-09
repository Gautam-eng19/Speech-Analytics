"""Shared error response helper for the API routes (api-contract.md §Errors)."""
from __future__ import annotations

from typing import Optional

from fastapi import status
from fastapi.responses import JSONResponse

from app.schemas.common import ERROR_HTTP_STATUS, ErrorCode
from app.schemas.response import ErrorResponse


def error_response(error: ErrorCode, detail: str, analysis_id: Optional[str] = None) -> JSONResponse:
    """A JSONResponse carrying an `ErrorResponse` body with the HTTP status mapped from `error`."""
    body = ErrorResponse(error=error, detail=detail, analysis_id=analysis_id)
    return JSONResponse(status_code=ERROR_HTTP_STATUS.get(error, status.HTTP_400_BAD_REQUEST), content=body.model_dump())
