"""Grounding service package (ARCHITECTURE.md §7.5): normalization, comparison, flaw detection."""
from .normalizer import (
    NormalizationError,
    NormalizedFeatureBundle,
    NormalizedPause,
    normalize_features,
    z_score,
)

__all__ = [
    "NormalizationError",
    "NormalizedFeatureBundle",
    "NormalizedPause",
    "normalize_features",
    "z_score",
]
