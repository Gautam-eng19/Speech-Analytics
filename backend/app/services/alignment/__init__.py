"""Forced alignment service package (TASK-022, ARCHITECTURE.md §7.3, §12).

Public surface:
    WhisperXAligner         — core service class
    AlignmentConfig         — alignment configuration dataclass
    align                   — convenience function for alignment
    get_aligner             — access/initialize singleton aligner
    AlignmentError          — base alignment exception
    AlignmentConfigError    — configuration/input validation exception
    AlignmentModelError     — model loading failure exception
    AlignmentRuntimeError   — alignment execution failure exception
"""
from .aligner import (
    AlignmentConfig,
    AlignmentConfigError,
    AlignmentError,
    AlignmentModelError,
    AlignmentRuntimeError,
    WhisperXAligner,
    align,
    clear_alignment_model_cache,
    get_aligner,
)

__all__ = [
    "WhisperXAligner",
    "AlignmentConfig",
    "align",
    "get_aligner",
    "clear_alignment_model_cache",
    "AlignmentError",
    "AlignmentConfigError",
    "AlignmentModelError",
    "AlignmentRuntimeError",
]
