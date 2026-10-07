"""Health check endpoint (ARCHITECTURE.md §6.3, §23; api-contract.md)."""
from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings
from app.schemas.response import HealthResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health check",
    description="Returns server status, config version, pipeline version, and API contract version.",
)
async def get_health() -> HealthResponse:
    """Return health status matching HealthResponse schema."""
    return HealthResponse(
        status="ok",
        config_version=settings.CONFIG_VERSION,
        pipeline_version=settings.PIPELINE_VERSION,
    )
