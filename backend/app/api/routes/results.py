"""Result retrieval endpoints: GET /status/{analysis_id} and GET /result/{analysis_id} (ARCHITECTURE.md §23, DEC-016).

Results are read from the deterministic file cache, so they persist across restarts. At P0 the analysis is synchronous, so
the only statuses are `done` and `not_found`. The handlers are plain functions (not coroutines) because they read and validate a file:
FastAPI runs them in its thread pool, so they never block the event loop.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_cache
from app.api.responses import error_response
from app.core.cache import ResultCache, is_valid_analysis_id
from app.schemas.common import AnalysisStatus, ErrorCode
from app.schemas.response import AnalysisResult, ErrorResponse, StatusResponse

router = APIRouter()


@router.get(
    "/status/{analysis_id}",
    response_model=StatusResponse,
    summary="Status of a stored analysis",
    description="`done` if a valid stored result exists for the id, otherwise `not_found` (HTTP 200 in both cases).",
)
def get_status(analysis_id: str, cache: ResultCache = Depends(get_cache)) -> StatusResponse:
    found = cache.get(analysis_id) is not None
    return StatusResponse(analysis_id=analysis_id, status=AnalysisStatus.DONE if found else AnalysisStatus.NOT_FOUND)


@router.get(
    "/result/{analysis_id}",
    response_model=AnalysisResult,
    summary="Stored analysis result",
    responses={404: {"model": ErrorResponse, "description": "No stored result for this id"}},
)
def get_result(analysis_id: str, cache: ResultCache = Depends(get_cache)):
    result = cache.get(analysis_id)
    if result is None:
        return error_response(
            ErrorCode.RESULT_NOT_FOUND,
            "No stored result for this analysis id.",
            analysis_id if is_valid_analysis_id(analysis_id) else None,
        )
    return result
