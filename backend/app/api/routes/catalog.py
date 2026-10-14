"""Baseline catalogue: GET /api/v1/baselines (API contract 1.2.0).

Lists the baselines an analysis can be run against, with the passage each one describes, so the dashboard can offer a choice
instead of asking for ids. Baseline files that exist but cannot be used are listed separately with a short reason code (never a
server path), so a broken file is visible rather than silently missing.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_pipeline
from app.core.baseline import (
    BaselineError,
    BaselineIntegrityError,
    is_custom_id,
    pause_statistics_thin,
    rate_statistics_thin,
)
from app.schemas.response import BaselineListResponse, BaselineSummary, UnavailableBaseline
from app.services.pipeline import AnalysisPipeline

router = APIRouter()


@router.get(
    "/baselines",
    response_model=BaselineListResponse,
    summary="Baselines available for analysis",
    description="Usable baselines with their passage (title, reference text) and whether their statistics are thin; "
    "files that exist but cannot be used are listed under `unavailable` with a reason code.",
)
def list_baselines(pipeline: AnalysisPipeline = Depends(get_pipeline)) -> BaselineListResponse:
    provider, passages = pipeline.baseline_provider, pipeline.passages
    usable: list[BaselineSummary] = []
    unusable: list[UnavailableBaseline] = []
    for baseline_id in provider.list_baselines():
        try:
            record = provider.load(baseline_id)
        except BaselineIntegrityError as exc:
            unusable.append(UnavailableBaseline(baseline_id=baseline_id, reason=exc.code))  # type: ignore[arg-type]
            continue
        except BaselineError:
            unusable.append(UnavailableBaseline(baseline_id=baseline_id, reason="unreadable"))
            continue
        info = passages.get(record.passage_id)
        usable.append(
            BaselineSummary(
                baseline_id=baseline_id,
                passage_id=record.passage_id,
                dataset_version=record.dataset_version,
                sha256=record.sha256,
                n_baseline_recordings=len(record.baseline_recording_ids),
                n_rate_windows=record.n_rate_windows,
                n_pauses_within_phrase=record.n_pauses_within_phrase,
                thin_rate_statistics=rate_statistics_thin(record),
                thin_pause_statistics=pause_statistics_thin(record),
                passage_title=info.title if info else None,
                passage_text=info.text if info else None,
                passage_word_count=len(info.text.split()) if info else None,
                custom=is_custom_id(baseline_id),
            )
        )
    usable.sort(key=lambda b: (b.passage_id, b.baseline_id))
    unusable.sort(key=lambda b: b.baseline_id)
    return BaselineListResponse(baselines=usable, unavailable=unusable)
