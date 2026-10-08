"""Intermediate pipeline data contracts (ARCHITECTURE.md §9).

Defines strongly-typed internal data transfers between canonical pipeline stages.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from pydantic import ConfigDict, Field, field_validator

from .common import ContractModel, TranscriptSource


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
