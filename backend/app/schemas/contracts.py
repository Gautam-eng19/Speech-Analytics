"""Intermediate pipeline data contracts.

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
    """Audio output of services/audio preprocessing."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    sample_rate_hz: int = Field(gt=0, description="Sampling rate in Hz (always TARGET_SAMPLE_RATE)")
    channels: int = Field(ge=1, le=1, description="Number of channels (always 1/mono)")
    duration_s: float = Field(ge=0.0, description="Duration in seconds")
    audio_array: np.ndarray = Field(description="1D float32 normalized PCM audio array")
    sha256: str = Field(pattern="^[0-9a-f]{64}$", description="SHA-256 hex digest of audio_array bytes")
    peak_dbfs: float = Field(description="Measured peak loudness in dBFS after normalization")
    # Source-time provenance of silence trimming. All downstream analysis
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
    """Whisper-reported approximate word timing for a single word.

    These are Whisper's own word timestamps, NOT forced-alignment timestamps.
    Forced alignment produces a separate AlignedTranscript with
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
    """Output of services/transcription/.

    Contains the full ASR transcript text plus Whisper's own word/segment
    timestamps. This is the INPUT to forced alignment; it is NOT
    a replacement for AlignedTranscript.
    """

    text: str = Field(description="Full transcript string")
    segments: list[TranscriptSegment] = Field(default_factory=list)
    # Flat word list derived from segments — convenience for.
    words: list[WordTiming] = Field(default_factory=list)
    model_name: str = Field(description="Whisper model identifier, e.g. 'whisper_base'")
    source: TranscriptSource = Field(description="'asr' or 'manual'")
    language: Optional[str] = Field(
        default=None, description="ISO 639-1 language code detected or configured"
    )


class AlignedWord(ContractModel):
    """Word-level forced alignment entry."""

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
    """Output of services/alignment/.

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
    """Validation result for AlignedTranscript.

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


class NoiseModel(ContractModel):
    """How much an average over `n` consecutive words varies between readings of the same passage.

    ``sigma(n) = sqrt(drift**2 + word**2 / n)``: `word` is the part that averages out as more words are taken (each word is a little
    faster, slower, louder or quieter by chance), `drift` is the part that does not (a whole stretch of the reading is slightly faster or
    louder). Units are those of the quantity it describes (natural-log ratio of durations for the rate, dB for the loudness).
    """

    drift: float = Field(ge=0.0, allow_inf_nan=False)
    word: float = Field(ge=0.0, allow_inf_nan=False)


class PitchProfile(ContractModel):
    """How much the pitch of the SAME words moved in the baseline recordings; part of the `WordProfile`.

    Pitch is measured in semitones from the reading's OWN median pitch, so the speaker's register does not matter, only how far the voice moves
    around its usual level. For one word, the movement is the mean squared deviation (semitones squared) of its voiced frames, each deviation
    clipped at `deviation_clip_st` so a tracking error cannot dominate; a word needs `min_voiced_frames` voiced frames to be measured.

    * `movement_st2[i]`: expected movement of word i of the passage, the mean over the baseline recordings (``None`` where fewer than two
      recordings measured the word).
    * `noise`: spread of a run of `n` words in natural-log ratio of the root-mean-square movement, leave-one-out like the other spreads.
    * `scale_sd`: spread of a reading's OVERALL movement between baseline recordings (natural log of the root-mean-square ratio, leave-one-out):
      speakers differ in how expressive they are, and a reading is only called flat as a whole if it is further off than that.
    """

    movement_st2: list[Optional[float]]
    noise: NoiseModel
    scale_sd: float = Field(ge=0.0, allow_inf_nan=False)
    min_voiced_frames: int = Field(ge=1)
    deviation_clip_st: float = Field(gt=0.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _check_pitch_profile(self) -> "PitchProfile":
        for value in self.movement_st2:
            if value is not None and not (math.isfinite(value) and value >= 0.0):
                raise ValueError("movement_st2 values must be finite numbers >= 0 or null")
        return self


class WordProfile(ContractModel):
    """How the SAME words were read in the baseline recordings, word by word.

    The baseline is the effective delivery of one passage, so the comparison can be made at the same place in the text: a long word takes
    longer than a short one, and a rate measured over a fixed stretch of TIME says as much about the words in it as about the speaker.
    `words[i]` is the i-th word of the passage (lower-case letters and apostrophes only); the other lists are indexed the same way and
    hold ``None`` where fewer than two baseline recordings measured the word.

    * `slot_s`: expected slot of the word, the time from its start to the start of the next word (a silence after it counts, up to
      `max_gap_s`): the geometric mean over the baseline recordings.
    * `level_db`: expected level of the word, the median level of its active frames, after removing each recording's own overall level
      offset (the mean over the baseline recordings).
    * `rate_noise`, `level_noise`: spread of a run of words, measured by comparing each baseline recording with the others
      (leave-one-out), so it describes a recording that was NOT used to build the expectation; see `NoiseModel`.
    * `tempo_sd`: spread of the overall pace between baseline recordings (natural log of the duration ratio), leave-one-out.
    """

    words: list[str] = Field(min_length=1)
    slot_s: list[Optional[float]]
    level_db: list[Optional[float]]
    n_takes: int = Field(ge=3)
    rate_noise: NoiseModel
    level_noise: NoiseModel
    tempo_sd: float = Field(ge=0.0, allow_inf_nan=False)
    tempo_window_words: int = Field(ge=2)
    max_gap_s: float = Field(gt=0.0, allow_inf_nan=False)
    active_threshold_dbfs: float = Field(allow_inf_nan=False)
    # How much the pitch of the same words moved. Absent in a profile built before it, or when the baseline recordings had too little
    # voiced speech; flat pitch is then not judged and the analysis says so.
    pitch: Optional[PitchProfile] = None

    @model_validator(mode="after")
    def _check_profile(self) -> "WordProfile":
        n = len(self.words)
        if len(self.slot_s) != n or len(self.level_db) != n:
            raise ValueError("words, slot_s and level_db must have the same length")
        if self.pitch is not None and len(self.pitch.movement_st2) != n:
            raise ValueError("pitch.movement_st2 must have one entry per word")
        if any(not w for w in self.words):
            raise ValueError("profile words must not be empty")
        for value in self.slot_s:
            if value is not None and not (math.isfinite(value) and value > 0.0):
                raise ValueError("slot_s values must be positive finite numbers or null")
        for value in self.level_db:
            if value is not None and not math.isfinite(value):
                raise ValueError("level_db values must be finite numbers or null")
        return self


class BaselineStatsRecord(BaselineStats):
    """Persisted baseline statistics for one passage.

    Extends the API `BaselineStats` (the numeric statistics, defined once in
    `schemas/response.py`) with the identity, provenance and evidence-count fields of
    §9.5. It is what `core.baseline.BaselineProvider.get(passage_id)` returns and what
    `scripts/dataset/build_baseline_stats.py` writes.

    Units: Hz (f0), dBFS (energy), words per minute (rate), seconds (pauses).

    Evidence counts say how much data each statistic rests on, so consumers can see thin
    baselines instead of trusting a number that came from very few observations.

    `sha256` is the SHA-256 of the canonical JSON of every other field (sorted keys, compact
    separators, no NaN); it identifies the exact statistics used in an analysis and feeds the
    cache key. Use `with_computed_sha256()` to set it and `verify_sha256()` to check it.
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
    # How the same words were read in the baseline recordings. Absent in baselines built before it, and when the passage text or
    # enough recordings were not available; the analysis then falls back to the overall statistics above and says so.
    word_profile: Optional[WordProfile] = None
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
        """Canonical JSON of every field except `sha256` (the hashed content).

        A missing `word_profile` is left out of the content, so a baseline file written before the profile existed still verifies; so is a missing
        `word_profile.pitch`, for a profile written before the pitch part existed.
        """
        content = self.model_dump(mode="json", exclude={"sha256"})
        if content.get("word_profile") is None:
            content.pop("word_profile", None)
        elif content["word_profile"].get("pitch") is None:
            content["word_profile"].pop("pitch", None)
        return json.dumps(
            content,
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
