"""Intermediate pipeline data contracts (ARCHITECTURE.md §9).

Defines strongly-typed internal data transfers between canonical pipeline stages.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from pydantic import ConfigDict, Field, field_validator, model_validator

from .common import AlignmentMethod, ContractModel, TranscriptSource


class PreprocessedAudio(ContractModel):
    """Audio output of services/audio preprocessing (ARCHITECTURE.md §9.1)."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    sample_rate_hz: int = Field(gt=0, description="Sampling rate in Hz (always TARGET_SAMPLE_RATE)")
    channels: int = Field(ge=1, le=1, description="Number of channels (always 1/mono)")
    duration_s: float = Field(ge=0.0, description="Duration in seconds")
    audio_array: np.ndarray = Field(description="1D float32 normalized PCM audio array")
    sha256: str = Field(pattern="^[0-9a-f]{64}$", description="SHA-256 hex digest of audio_array bytes")
    peak_dbfs: float = Field(description="Measured peak loudness in dBFS after normalization")

    @field_validator("audio_array")
    @classmethod
    def _validate_audio_array(cls, v: np.ndarray) -> np.ndarray:
        if not isinstance(v, np.ndarray):
            raise ValueError("audio_array must be a numpy ndarray")
        if v.ndim != 1:
            raise ValueError("audio_array must be a 1D mono array")
        if v.dtype != np.float32:
            raise ValueError("audio_array must have dtype float32")
        return v


class WordTiming(ContractModel):
    """Whisper-reported approximate word timing for a single word (ARCHITECTURE.md §9.2).

    These are Whisper's own word timestamps, NOT forced-alignment timestamps.
    TASK-022 (forced alignment) will produce a separate AlignedTranscript with
    more accurate boundaries. Fields are Optional because Whisper does not
    guarantee per-word timestamps in all conditions.
    """

    word: str = Field(min_length=1)
    approx_start_s: Optional[float] = Field(default=None, ge=0.0)
    approx_end_s: Optional[float] = Field(default=None, ge=0.0)
    probability: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class TranscriptSegment(ContractModel):
    """A single Whisper segment (contiguous speech chunk with timing).

    Segments are the primary temporal unit returned by Whisper before forced
    alignment. Each segment may contain multiple words.
    """

    segment_id: int = Field(ge=0)
    text: str
    start_s: float = Field(ge=0.0)
    end_s: float = Field(ge=0.0)
    # Segment-level confidence proxy from Whisper's no-speech probability.
    # None when Whisper does not report it.
    no_speech_prob: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    # Word-level timings within this segment (populated when word_timestamps=True).
    words: list[WordTiming] = Field(default_factory=list)


class Transcript(ContractModel):
    """Output of services/transcription/ (ARCHITECTURE.md §9.2).

    Contains the full ASR transcript text plus Whisper's own word/segment
    timestamps. This is the INPUT to TASK-022 (forced alignment); it is NOT
    a replacement for AlignedTranscript.
    """

    text: str = Field(description="Full transcript string")
    segments: list[TranscriptSegment] = Field(default_factory=list)
    # Flat word list derived from segments — convenience for TASK-022.
    words: list[WordTiming] = Field(default_factory=list)
    model_name: str = Field(description="Whisper model identifier, e.g. 'whisper_base'")
    source: TranscriptSource = Field(description="'asr' or 'manual'")
    language: Optional[str] = Field(
        default=None, description="ISO 639-1 language code detected or configured"
    )


class AlignedWord(ContractModel):
    """Word-level forced alignment entry (ARCHITECTURE.md §9.3)."""

    word: str = Field(min_length=1, description="Aligned word token text")
    start_s: Optional[float] = Field(
        default=None, ge=0.0, description="Start timestamp in seconds (None if unaligned)"
    )
    end_s: Optional[float] = Field(
        default=None, ge=0.0, description="End timestamp in seconds (None if unaligned)"
    )
    confidence: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Alignment confidence score in [0.0, 1.0] if provided"
    )

    @model_validator(mode="after")
    def _check_ordering(self) -> "AlignedWord":
        if self.start_s is not None and self.end_s is not None:
            if self.end_s < self.start_s:
                raise ValueError(
                    f"end_s ({self.end_s}) must be >= start_s ({self.start_s})"
                )
        return self


# Alias for backward-compatibility or alternative naming
AlignedWordTiming = AlignedWord


class AlignedTranscript(ContractModel):
    """Output of services/alignment/ (ARCHITECTURE.md §7.3, §9.3, §12).

    Contains word-level forced alignment timing, alignment method provenance,
    and total coverage statistics. Consumed by downstream feature extraction
    and grounding services.
    """

    text: str = Field(description="Full transcript text (preserved from input Transcript)")
    words: list[AlignedWord] = Field(
        default_factory=list, description="List of aligned word timings"
    )
    alignment_method: AlignmentMethod = Field(
        description="Method used for alignment: 'whisperx' | 'whisper_word_timestamps' | 'manual'"
    )
    total_coverage_pct: float = Field(
        ge=0.0,
        le=1.0,
        description="Fraction of audio covered by aligned words in [0.0, 1.0]",
    )


class AlignmentValidationResult(ContractModel):
    """Validation result for AlignedTranscript (TASK-023, ARCHITECTURE.md §12).

    Distinguishes valid from invalid alignments, providing machine-readable
    deterministic error reasons and warnings.
    """

    is_valid: bool = Field(description="True if the aligned transcript passed all validation checks")
    errors: list[str] = Field(
        default_factory=list, description="Deterministic validation error reasons"
    )
    warnings: list[str] = Field(
        default_factory=list, description="Deterministic validation warning messages"
    )

    @property
    def valid(self) -> bool:
        """Convenience alias for is_valid."""
        return self.is_valid

    @property
    def messages(self) -> list[str]:
        """All deterministic error and warning messages combined."""
        return [*self.errors, *self.warnings]

    def __bool__(self) -> bool:
        return self.is_valid


ValidationResult = AlignmentValidationResult
