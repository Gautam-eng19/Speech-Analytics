"""Intermediate pipeline data contracts (ARCHITECTURE.md §9).

Defines strongly-typed internal data transfers between canonical pipeline stages.
"""
from __future__ import annotations

import numpy as np
from pydantic import ConfigDict, Field, field_validator

from .common import ContractModel


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
