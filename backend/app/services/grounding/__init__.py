"""Grounding service package (ARCHITECTURE.md §7.5): normalization, comparison, flaw detection."""
from .candidates import (
    CandidateDetectionResult,
    DetectionConfig,
    FlawCandidate,
    detect_candidates,
    merge_candidates,
)
from .severity import SeverityConfig, compute_severity, severity_components
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
    "SeverityConfig",
    "compute_severity",
    "severity_components",
    "NormalizationError",
    "NormalizedFeatureBundle",
    "NormalizedPause",
    "normalize_features",
    "z_score",
]
