"""Intermediate pipeline data contracts (ARCHITECTURE.md §9).

Defines strongly-typed internal data transfers between canonical pipeline stages.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Optional, Union

import numpy as np
from pydantic import ConfigDict, Field, field_validator, model_validator

from .common import AlignmentMethod, ContractModel, TranscriptSource
from .request import ID_PATTERN
from .response import BaselineStats


# Slack for comparing rounded durations in PreprocessedAudio trim-bound validation.
_TRIM_BOUND_TOLERANCE_S = 1e-3


class PreprocessedAudio(ContractModel):
    """Audio output of services/audio preprocessing (ARCHITECTURE.md §9.1)."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    sample_rate_hz: int = Field(gt=0, description="Sampling rate in Hz (always TARGET_SAMPLE_RATE)")
    channels: int = Field(ge=1, le=1, description="Number of channels (always 1/mono)")
    duration_s: float = Field(ge=0.0, description="Duration in seconds")
    audio_array: np.ndarray = Field(description="1D float32 normalized PCM audio array")
    sha256: str = Field(pattern="^[0-9a-f]{64}$", description="SHA-256 hex digest of audio_array bytes")
    peak_dbfs: float = Field(description="Measured peak loudness in dBFS after normalization")
    # Source-time provenance of silence trimming (TASK-013A). All downstream analysis
    # timestamps are in processed-audio time (0 = first retained sample); these fields
    # record where that origin sits in the pre-trim signal. Defaults keep untrimmed /
    # legacy constructors valid. Conversion to source time is done once, at response assembly.
    trim_start_s: float = Field(
        default=0.0,
        ge=0.0,
        allow_inf_nan=False,
        description=(
            "Offset in seconds, within the decoded/mono/resampled pre-trim signal, "
            "at which the retained audio begins (0.0 if nothing was trimmed or all audio was silent)"
        ),
    )
    source_duration_s: Optional[float] = Field(
        default=None,
        ge=0.0,
        allow_inf_nan=False,
        description="Duration in seconds of the pre-trim signal (None if unknown)",
    )

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

    @model_validator(mode="after")
    def _check_trim_bounds(self) -> "PreprocessedAudio":
        # duration_s is rounded to 4 d.p. upstream, hence the small tolerance.
        if (
            self.source_duration_s is not None
            and self.trim_start_s + self.duration_s > self.source_duration_s + _TRIM_BOUND_TOLERANCE_S
        ):
            raise ValueError(
                f"trim_start_s ({self.trim_start_s}) + duration_s ({self.duration_s}) "
                f"exceeds source_duration_s ({self.source_duration_s})"
            )
        return self

    def to_source_time(self, t_s: float) -> float:
        """Map a processed-audio timestamp to the pre-trim (source) timeline."""
        return t_s + self.trim_start_s


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


class BaselineStatsRecord(BaselineStats):
    """Persisted baseline statistics for one passage (ARCHITECTURE.md §9.5, DEC-015, TASK-040).

    Extends the API `BaselineStats` (the numeric statistics, defined once in
    `schemas/response.py`) with the identity, provenance and evidence-count fields of
    §9.5. It is what `core.baseline.BaselineProvider.get(passage_id)` returns and what
    `scripts/dataset/build_baseline_stats.py` writes.

    Units: Hz (f0), dBFS (energy), words per minute (rate), seconds (pauses).

    Evidence counts say how much data each statistic rests on, so consumers can see thin
    baselines instead of trusting a number that came from very few observations.

    `sha256` is the SHA-256 of the canonical JSON of every other field (sorted keys, compact
    separators, no NaN); it identifies the exact statistics used in an analysis and feeds the
    cache key (§26.4). Use `with_computed_sha256()` to set it and `verify_sha256()` to check it.
    """

    passage_id: str = Field(pattern=ID_PATTERN)
    dataset_version: str = Field(min_length=1)
    baseline_recording_ids: list[str] = Field(min_length=1)
    # Required here (optional in the API model): the builder always computes them.
    f0_voiced_hz_p05: float
    f0_voiced_hz_p95: float
    n_f0_voiced_frames: int = Field(ge=0)
    n_energy_frames: int = Field(ge=0)
    n_rate_windows: int = Field(ge=0)
    n_pauses_within_phrase: int = Field(ge=0)
    n_pauses_cross_sentence: int = Field(ge=0)
    n_pauses_unknown_boundary: int = Field(ge=0)
    # Parameters that define how the statistics were computed (e.g. which energy frames count).
    config_snapshot: dict[str, Union[str, int, float, bool]]
    sha256: str = Field(pattern="^[0-9a-f]{64}$")

    @field_validator("baseline_recording_ids")
    @classmethod
    def _recording_ids_valid(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("baseline_recording_ids must be unique")
        if any(not re.match(ID_PATTERN, rid) for rid in v):
            raise ValueError("baseline_recording_ids contain an invalid identifier")
        return v

    @model_validator(mode="after")
    def _check_statistics(self) -> "BaselineStatsRecord":
        for name, value in self.model_dump().items():
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.f0_voiced_hz_p05 > self.f0_voiced_hz_p95:
            raise ValueError("f0_voiced_hz_p05 must be <= f0_voiced_hz_p95")
        return self

    def canonical_json(self) -> str:
        """Canonical JSON of every field except `sha256` (the hashed content)."""
        return json.dumps(
            self.model_dump(mode="json", exclude={"sha256"}),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def compute_sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def verify_sha256(self) -> bool:
        """True if the stored `sha256` matches the content."""
        return self.sha256 == self.compute_sha256()

    def with_computed_sha256(self) -> "BaselineStatsRecord":
        """Return a copy whose `sha256` matches its content."""
        return self.model_copy(update={"sha256": self.compute_sha256()})

    def to_response_stats(self) -> BaselineStats:
        """The numeric statistics in the public API shape (`AnalysisResult.baseline_stats`)."""
        return BaselineStats(**{name: getattr(self, name) for name in BaselineStats.model_fields})
