"""Grounding service package (ARCHITECTURE.md §7.5): normalization, comparison, flaw detection."""
from .candidates import (
    CandidateDetectionResult,
    DetectionConfig,
    FlawCandidate,
    detect_candidates,
    merge_candidates,
    refine_rate_candidates,
)
from .flaws import EvidenceError, GroundedFlaw, clip_to_audio, ground_flaws, to_api_flaw
from .profile import WordObservations, build_word_profile, map_to_passage, measure_words, passage_tokens
from .profile_detection import ProfileDetection, RunFinding, detect_runs
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
    "refine_rate_candidates",
    "WordObservations",
    "build_word_profile",
    "map_to_passage",
    "measure_words",
    "passage_tokens",
    "ProfileDetection",
    "RunFinding",
    "detect_runs",
    "EvidenceError",
    "GroundedFlaw",
    "ground_flaws",
    "clip_to_audio",
    "to_api_flaw",
    "SeverityConfig",
    "compute_severity",
    "severity_components",
    "NormalizationError",
    "NormalizedFeatureBundle",
    "NormalizedPause",
    "normalize_features",
    "z_score",
]
