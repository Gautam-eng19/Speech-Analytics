"""FastAPI main application entry point."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import analyze, catalog, custom, health, results
from app.core.config import settings
from app.schemas.common import API_CONTRACT_VERSION, ErrorCode, ERROR_HTTP_STATUS
from app.schemas.response import ErrorResponse


def create_app(frontend_dist: Optional[Path] = None) -> FastAPI:
    """Create and configure the FastAPI application.

    If a built dashboard exists (`frontend_dist`, default `settings.FRONTEND_DIST_DIR`, must contain index.html) it is served
    at "/" by the same process, after the API routes, so one `uvicorn` command serves both.
    """
    app = FastAPI(
        title="Speech Analytics API",
        description="Track C — Contrastive Speech Analytics & Temporal Flaw Grounding API",
        version=API_CONTRACT_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Browsers on another origin (the Vite dev server) may call the API. No credentials are used or accepted.
    if settings.CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Accept"],
            allow_credentials=False,
            max_age=600,
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
    app.include_router(results.router, prefix="/api/v1", tags=["Analysis"])
    app.include_router(catalog.router, prefix="/api/v1", tags=["Catalogue"])
    app.include_router(custom.router, prefix="/api/v1", tags=["Custom passages"])

    # The dashboard comes last so that every API route (and /docs, /openapi.json) takes precedence over it.
    dist = Path(frontend_dist) if frontend_dist is not None else Path(settings.FRONTEND_DIST_DIR)
    if (dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=dist, html=True), name="dashboard")

    return app


app = create_app()
