"""Grounding service package (ARCHITECTURE.md §7.5): normalization, comparison, flaw detection."""
from .candidates import (
    CandidateDetectionResult,
    DetectionConfig,
    FlawCandidate,
    detect_candidates,
    merge_candidates,
)
from .normalizer import (
    NormalizationError,
    NormalizedFeatureBundle,
    NormalizedPause,
    normalize_features,
    z_score,
)

__all__ = [
    "CandidateDetectionResult",
    "DetectionConfig",
    "FlawCandidate",
    "detect_candidates",
    "merge_candidates",
    "NormalizationError",
    "NormalizedFeatureBundle",
    "NormalizedPause",
    "normalize_features",
    "z_score",
]
