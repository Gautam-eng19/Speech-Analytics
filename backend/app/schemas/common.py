"""Shared building blocks for the public API contract (TASK-002).

Contains only: the strict base model, enumerations, and the contract version.
Every enum value maps to a concept defined in ARCHITECTURE.md / DECISIONS.md.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

# Version of the *shape* of the public API (independent of CONFIG_VERSION /
# PIPELINE_VERSION, which version analytical behaviour). Bump:
#   - MAJOR on breaking changes (URL prefix /api/v1 -> /api/v2 as well)
#   - MINOR on backward-compatible additions (new optional fields)
API_CONTRACT_VERSION = "1.0.0"


class ContractModel(BaseModel):
    """Base for all contract models: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


class _StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class FlawType(_StrEnum):
    """ARCHITECTURE.md §17/§21. P0 = first six; P1 = last two (DEC-013)."""

    TOO_FAST = "too_fast"
    TOO_SLOW = "too_slow"
    EXCESSIVE_PAUSE = "excessive_pause"
    FLAT_PITCH = "flat_pitch"
    LOW_ENERGY = "low_energy"
    HIGH_ENERGY = "high_energy"
    PITCH_INSTABILITY = "pitch_instability"  # P1
    REDUCED_CLARITY = "reduced_clarity"  # P1


class FeatureName(_StrEnum):
    """Feature score dimensions (ARCHITECTURE.md §20). mfcc/clarity are P1."""

    SPEECH_RATE = "speech_rate"
    PITCH = "pitch"
    PAUSES = "pauses"
    ENERGY = "energy"
    MFCC = "mfcc"
    CLARITY = "clarity"


class AlignmentMethod(_StrEnum):
    """DEC-009."""

    WHISPERX = "whisperx"
    WHISPER_WORD_TIMESTAMPS = "whisper_word_timestamps"
    MANUAL = "manual"


class TranscriptSource(_StrEnum):
    """ARCHITECTURE.md §9.2."""

    ASR = "asr"
    MANUAL = "manual"


class PauseDetectionSource(_StrEnum):
    """DEC-011."""

    VAD = "vad"
    ALIGNMENT = "alignment"
    BOTH = "both"


class PauseBoundaryType(_StrEnum):
    """DEC-011 / §9.4."""

    WITHIN_PHRASE = "within_phrase"
    CROSS_SENTENCE = "cross_sentence"
    UNKNOWN = "unknown"


class ExplanationMethod(_StrEnum):
    """DEC-018 / §22."""

    TEMPLATE = "template"
    GEMINI = "gemini"


class SpeakerGender(_StrEnum):
    """Optional request hint (ARCHITECTURE.md §6.1)."""

    MALE = "male"
    FEMALE = "female"


class AnalysisStatus(_StrEnum):
    """GET /status values.

    P0 (synchronous, DEC-016) only ever emits DONE and NOT_FOUND.
    PROCESSING and FAILED are reserved for the DEC-016 async upgrade path and
    are not emitted unless that upgrade is approved and implemented.
    """

    DONE = "done"
    NOT_FOUND = "not_found"
    PROCESSING = "processing"  # reserved (DEC-016 upgrade path)
    FAILED = "failed"  # reserved (DEC-016 upgrade path)


class ErrorCode(_StrEnum):
    """Machine-readable error codes (ARCHITECTURE.md §23 error format)."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNSUPPORTED_AUDIO_FORMAT = "UNSUPPORTED_AUDIO_FORMAT"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    AUDIO_TOO_LONG = "AUDIO_TOO_LONG"
    CONFIG_VERSION_MISMATCH = "CONFIG_VERSION_MISMATCH"
    BASELINE_NOT_FOUND = "BASELINE_NOT_FOUND"
    RESULT_NOT_FOUND = "RESULT_NOT_FOUND"
    PROCESSING_ERROR = "PROCESSING_ERROR"


# HTTP status per error code, following the status codes listed in
# ARCHITECTURE.md §23 (400 invalid input, 404 not found, 422 validation, 500).
ERROR_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.UNSUPPORTED_AUDIO_FORMAT: 400,
    ErrorCode.FILE_TOO_LARGE: 400,
    ErrorCode.AUDIO_TOO_LONG: 400,
    ErrorCode.CONFIG_VERSION_MISMATCH: 400,
    ErrorCode.BASELINE_NOT_FOUND: 404,
    ErrorCode.RESULT_NOT_FOUND: 404,
    ErrorCode.PROCESSING_ERROR: 500,
}
