"""Deterministic scoring service package (ARCHITECTURE.md §7.6, §20)."""
from .scoring import (
    FEATURE_FOR_FLAW,
    ScoringConfig,
    ScoringError,
    ScoringResult,
    evaluated_features,
    score_analysis,
)

__all__ = [
    "FEATURE_FOR_FLAW",
    "ScoringConfig",
    "ScoringError",
    "ScoringResult",
    "evaluated_features",
    "score_analysis",
]
