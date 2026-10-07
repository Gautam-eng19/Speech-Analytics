"""FastAPI main application entry point (ARCHITECTURE.md §5, §23; DEC-003)."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routes import analyze, health
from app.schemas.common import ErrorCode, ERROR_HTTP_STATUS
from app.schemas.response import ErrorResponse


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Speech Analytics API",
        description="Track C — Contrastive Speech Analytics & Temporal Flaw Grounding API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Register standardized exception handler replacing default 422 with ErrorResponse (api-contract.md §Errors)
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        error_resp = ErrorResponse(
            error=ErrorCode.VALIDATION_ERROR,
            detail=str(exc),
            analysis_id=None,
        )
        return JSONResponse(
            status_code=ERROR_HTTP_STATUS[ErrorCode.VALIDATION_ERROR],
            content=error_resp.model_dump(),
        )

    # Include API routers under /api/v1 prefix per api-contract.md
    app.include_router(health.router, prefix="/api/v1", tags=["Health"])
    app.include_router(analyze.router, prefix="/api/v1", tags=["Analysis"])

    return app


app = create_app()
