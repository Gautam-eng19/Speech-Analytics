"""FastAPI dependencies: the shared analysis pipeline and result cache (overridable in tests).

The pipeline is created lazily and once per process. Constructing it is cheap: the Whisper / WhisperX models are only
loaded on the first analysis that needs them.
"""
from __future__ import annotations

import threading
from typing import Optional

from fastapi import Depends

from app.core.cache import ResultCache
from app.services.custom import CustomBaselineService, CustomStore
from app.services.pipeline import AnalysisPipeline

_pipeline: Optional[AnalysisPipeline] = None
_lock = threading.Lock()


def get_pipeline() -> AnalysisPipeline:
    global _pipeline
    with _lock:
        if _pipeline is None:
            _pipeline = AnalysisPipeline()
        return _pipeline


_custom: Optional[CustomBaselineService] = None
_custom_pipeline: Optional[AnalysisPipeline] = None


def get_custom_service(pipeline: AnalysisPipeline = Depends(get_pipeline)) -> CustomBaselineService:
    """The custom-passage service. It shares the pipeline's speech models and lock (the models are heavy and the work is CPU-bound)."""
    global _custom, _custom_pipeline
    with _lock:
        if _custom is None or _custom_pipeline is not pipeline:
            _custom_pipeline = pipeline
            _custom = CustomBaselineService(
                CustomStore(), preprocessor=pipeline.preprocessor, get_aligner=pipeline._get_aligner,
                get_transcriber=pipeline._get_transcriber, lock=pipeline._lock,
            )
        return _custom


def get_cache(pipeline: AnalysisPipeline = Depends(get_pipeline)) -> ResultCache:
    """The cache the pipeline writes to (so overriding the pipeline also redirects /status and /result)."""
    return pipeline.cache
