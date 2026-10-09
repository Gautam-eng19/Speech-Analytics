"""FastAPI dependencies: the shared analysis pipeline and result cache (overridable in tests).

The pipeline is created lazily and once per process. Constructing it is cheap: the Whisper / WhisperX models are only
loaded on the first analysis that needs them.
"""
from __future__ import annotations

import threading
from typing import Optional

from fastapi import Depends

from app.core.cache import ResultCache
from app.services.pipeline import AnalysisPipeline

_pipeline: Optional[AnalysisPipeline] = None
_lock = threading.Lock()


def get_pipeline() -> AnalysisPipeline:
    global _pipeline
    with _lock:
        if _pipeline is None:
            _pipeline = AnalysisPipeline()
        return _pipeline


def get_cache(pipeline: AnalysisPipeline = Depends(get_pipeline)) -> ResultCache:
    """The cache the pipeline writes to (so overriding the pipeline also redirects /status and /result)."""
    return pipeline.cache
