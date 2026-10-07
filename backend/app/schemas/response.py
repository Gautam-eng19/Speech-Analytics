"""Response contract for the public API (ARCHITECTURE.md §6.3, §9.9-9.11, §21, §23).

Every field here maps to an object produced by the analytical pipeline; this
module defines SHAPE only. No analytical value is computed or defaulted here.
`AnalysisResult` is the serialization of ExplanationResult (the final pipeline
object, ARCHITECTURE.md §9.11).

Reproducibility: everything in `AnalysisResult` except `analysis_id` and
`processing_meta` is a deterministic function of (audio, baseline, config).
Use `AnalysisResult.deterministic_json()` to compare runs.
"""
from __future__ import annotations

import math
from typing import Optional, Union

from pydantic import Field, field_validator, model_validator

from .common import (
    API_CONTRACT_VERSION,
    AlignmentMethod,
    AnalysisStatus,
    ContractModel,
    ErrorCode,
    ExplanationMethod,
    FeatureName,
    FlawType,
    PauseBoundaryType,
    PauseDetectionSource,
    TranscriptSource,
)

__all__ = [
    "HealthResponse", "StatusResponse", "ErrorResponse", "AnalysisResult",
    "AudioInfo", "BaselineInfo", "AlignedWord", "FeatureSet", "BaselineStats",
    "Flaw", "ScoreSummary", "FeatureScore", "ProcessingMeta",
]

_Unit = Field(ge=0.0, le=1.0)
_NonNeg = Field(ge=0.0)


# --------------------------------------------------------------------------
# Health / status / errors
# --------------------------------------------------------------------------
class HealthResponse(ContractModel):
    """GET /api/v1/health"""

    status: str = Field(pattern="^ok$")
    config_version: str
    pipeline_version: str
    api_contract_version: str = API_CONTRACT_VERSION


class StatusResponse(ContractModel):
    """GET /api/v1/status/{analysis_id} (HTTP 200 even for not_found)."""

    analysis_id: str
    status: AnalysisStatus


class ErrorResponse(ContractModel):
    """Body of every non-2xx response (ARCHITECTURE.md §23 error format)."""

    error: ErrorCode
    detail: str = Field(min_length=1)
    analysis_id: Optional[str] = None


# --------------------------------------------------------------------------
# Input / provenance
# --------------------------------------------------------------------------
class AudioInfo(ContractModel):
    """Participant audio after preprocessing (PreprocessedAudio, §9.1)."""

    sha256: str = Field(pattern="^[0-9a-f]{64}$")
    duration_s: float = Field(gt=0.0)
    sample_rate_hz: int = Field(gt=0)
    channels: int = Field(ge=1)
    peak_dbfs: float


class BaselineInfo(ContractModel):
    """Baseline used for comparison (BaselineStats identity, §9.5, §26.3)."""

    baseline_id: str
    passage_id: str
    sha256: str = Field(pattern="^[0-9a-f]{64}$")
    dataset_version: str


class AlignedWord(ContractModel):
    """Word timing (AlignedTranscript.words, §9.3)."""

    word: str
    start_s: float = _NonNeg
    end_s: float = _NonNeg
    confidence: float = _Unit

    @model_validator(mode="after")
    def _ordered(self) -> "AlignedWord":
        if self.end_s < self.start_s:
            raise ValueError("end_s must be >= start_s")
        return self


# --------------------------------------------------------------------------
# Features (FeatureBundle, §9.4) — timelines are backend output for charts.
# --------------------------------------------------------------------------
def _same_length(**arrays: list) -> None:
    lengths = {k: len(v) for k, v in arrays.items()}
    if len(set(lengths.values())) > 1:
        raise ValueError(f"timeline arrays must have equal length, got {lengths}")


def _finite(values: list[Optional[float]], name: str) -> None:
    for v in values:
        if v is not None and not math.isfinite(v):
            raise ValueError(f"{name} contains a non-finite value")


class F0Timeline(ContractModel):
    times_s: list[float]
    # null = unvoiced frame (NaN is not valid JSON).
    values_hz: list[Optional[float]]
    voiced: list[bool]

    @model_validator(mode="after")
    def _check(self) -> "F0Timeline":
        _same_length(times_s=self.times_s, values_hz=self.values_hz, voiced=self.voiced)
        _finite(self.times_s, "times_s")
        _finite(self.values_hz, "values_hz")
        for v, voiced in zip(self.values_hz, self.voiced):
            if voiced and v is None:
                raise ValueError("voiced frame must have an F0 value")
        return self


class EnergyTimeline(ContractModel):
    times_s: list[float]
    values_db: list[float]

    @model_validator(mode="after")
    def _check(self) -> "EnergyTimeline":
        _same_length(times_s=self.times_s, values_db=self.values_db)
        _finite(self.times_s, "times_s")
        _finite(self.values_db, "values_db")
        return self


class SpeechRateTimeline(ContractModel):
    times_s: list[float]
    words_per_min: list[float]

    @model_validator(mode="after")
    def _check(self) -> "SpeechRateTimeline":
        _same_length(times_s=self.times_s, words_per_min=self.words_per_min)
        _finite(self.times_s, "times_s")
        _finite(self.words_per_min, "words_per_min")
        return self


class PauseEvent(ContractModel):
    start_s: float = _NonNeg
    end_s: float = _NonNeg
    duration_s: float = _NonNeg
    detection_source: PauseDetectionSource
    boundary_type: PauseBoundaryType

    @model_validator(mode="after")
    def _ordered(self) -> "PauseEvent":
        if self.end_s < self.start_s:
            raise ValueError("end_s must be >= start_s")
        return self


class MfccSummary(ContractModel):
    """P1 (optional at P0)."""

    mean_13: list[float] = Field(min_length=13, max_length=13)
    std_13: list[float] = Field(min_length=13, max_length=13)


class ClarityTimeline(ContractModel):
    """P1 acoustic clarity proxy (DEC-012), not an intelligibility score."""

    times_s: list[float]
    hf_ratio: list[float]

    @model_validator(mode="after")
    def _check(self) -> "ClarityTimeline":
        _same_length(times_s=self.times_s, hf_ratio=self.hf_ratio)
        return self


class FeatureSet(ContractModel):
    f0_timeline: F0Timeline
    energy_timeline: EnergyTimeline
    speech_rate_timeline: SpeechRateTimeline
    pause_events: list[PauseEvent]
    mfcc_summary: Optional[MfccSummary] = None  # P1
    clarity_timeline: Optional[ClarityTimeline] = None  # P1


class BaselineStats(ContractModel):
    """Baseline statistics used for normalization (§9.5)."""

    f0_voiced_hz_mean: float
    f0_voiced_hz_std: float = _NonNeg
    energy_db_mean: float
    energy_db_std: float = _NonNeg
    rate_wpm_mean: float
    rate_wpm_std: float = _NonNeg
    pause_within_phrase_mean_s: float = _NonNeg
    pause_within_phrase_std_s: float = _NonNeg
    pause_cross_sentence_mean_s: float = _NonNeg
    # Needed for the cross-sentence pause z-score (§16: baseline_std_for_type);
    # not listed in §9.5. See docs/api-contract.md "Assumptions".
    pause_cross_sentence_std_s: Optional[float] = Field(default=None, ge=0.0)
    f0_voiced_hz_p05: Optional[float] = None
    f0_voiced_hz_p95: Optional[float] = None
    hf_ratio_mean: Optional[float] = None  # P1
    hf_ratio_std: Optional[float] = Field(default=None, ge=0.0)  # P1


# --------------------------------------------------------------------------
# Evidence — one model per flaw family, fields exactly as ARCHITECTURE.md §21.
# All values come from the analytical pipeline; never from an LLM.
# --------------------------------------------------------------------------
class RateEvidence(ContractModel):  # too_fast, too_slow
    rate_participant_wpm: float
    rate_baseline_mean_wpm: float
    rate_baseline_std_wpm: float
    rate_delta_wpm: float
    rate_delta_pct: float
    rate_z_score: float
    peak_z_score: float
    window_duration_s: float = Field(gt=0.0)
    word_count_in_window: int = Field(ge=0)


class PauseEvidence(ContractModel):  # excessive_pause
    pause_duration_s: float = _NonNeg
    pause_baseline_mean_s: float
    pause_baseline_std_s: float
    pause_delta_s: float
    pause_z_score: float
    boundary_type: PauseBoundaryType
    detection_source: PauseDetectionSource


class FlatPitchEvidence(ContractModel):  # flat_pitch
    f0_std_hz_in_window: float
    f0_std_baseline_hz: float
    f0_std_z: float
    f0_voiced_fraction: float = _Unit
    window_duration_s: float = Field(gt=0.0)


class EnergyEvidence(ContractModel):  # low_energy, high_energy
    energy_mean_db: float
    energy_baseline_mean_db: float
    energy_baseline_std_db: float
    energy_delta_db: float
    energy_z_score: float
    window_duration_s: float = Field(gt=0.0)


class PitchInstabilityEvidence(ContractModel):  # pitch_instability (P1)
    f0_var_hz_in_window: float
    f0_var_baseline_hz: float
    f0_var_z: float
    window_duration_s: float = Field(gt=0.0)


class ClarityEvidence(ContractModel):  # reduced_clarity (P1)
    hf_ratio_mean: float
    hf_ratio_baseline_mean: float
    hf_ratio_z: float
    window_duration_s: float = Field(gt=0.0)


Evidence = Union[
    RateEvidence, PauseEvidence, FlatPitchEvidence,
    EnergyEvidence, PitchInstabilityEvidence, ClarityEvidence,
]

_EVIDENCE_FOR_TYPE: dict[FlawType, type] = {
    FlawType.TOO_FAST: RateEvidence,
    FlawType.TOO_SLOW: RateEvidence,
    FlawType.EXCESSIVE_PAUSE: PauseEvidence,
    FlawType.FLAT_PITCH: FlatPitchEvidence,
    FlawType.LOW_ENERGY: EnergyEvidence,
    FlawType.HIGH_ENERGY: EnergyEvidence,
    FlawType.PITCH_INSTABILITY: PitchInstabilityEvidence,
    FlawType.REDUCED_CLARITY: ClarityEvidence,
}


class Flaw(ContractModel):
    """GroundedFlaw (§9.9) + explanation fields (§9.11)."""

    flaw_id: str = Field(pattern=r"^flaw_\d{3,}$")
    type: FlawType
    start_s: float = _NonNeg
    end_s: float = _NonNeg
    duration_s: float = _NonNeg
    severity: float = _Unit
    reliability: float = _Unit  # 1.0 at P0 (§19)
    low_confidence: bool
    evidence: Evidence
    explanation: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)
    explanation_method: ExplanationMethod

    @model_validator(mode="after")
    def _grounded(self) -> "Flaw":
        if self.end_s <= self.start_s:
            raise ValueError("flaw must have end_s > start_s (temporal grounding)")
        if abs(self.duration_s - (self.end_s - self.start_s)) > 0.01:
            raise ValueError("duration_s must equal end_s - start_s")
        expected = _EVIDENCE_FOR_TYPE[self.type]
        if not isinstance(self.evidence, expected):
            raise ValueError(
                f"flaw type '{self.type.value}' requires {expected.__name__} evidence"
            )
        return self


# --------------------------------------------------------------------------
# Scores (ScoredResult, §9.10)
# --------------------------------------------------------------------------
class FeatureScore(ContractModel):
    score: float = Field(ge=0.0, le=100.0)
    weight: float = _Unit  # read from config, never hard-coded
    flaw_count: int = Field(ge=0)
    penalty_total: float = _NonNeg


class ScoreSummary(ContractModel):
    feature_scores: dict[FeatureName, FeatureScore]
    composite_score: float = Field(ge=0.0, le=100.0)
    scoring_version: str

    @field_validator("feature_scores")
    @classmethod
    def _canonical_order(cls, v: dict[FeatureName, FeatureScore]):
        # Deterministic key order regardless of construction order.
        order = list(FeatureName)
        return {k: v[k] for k in sorted(v, key=order.index)}


# --------------------------------------------------------------------------
# Non-deterministic run information (excluded from reproducibility checks)
# --------------------------------------------------------------------------
class ProcessingMeta(ContractModel):
    whisper_model: Optional[str] = None  # null when transcript is manual
    transcript_source: TranscriptSource
    processing_time_s: float = _NonNeg
    cached: bool


# --------------------------------------------------------------------------
# Final result
# --------------------------------------------------------------------------
class AnalysisResult(ContractModel):
    """GET /api/v1/result/{id} and 200 body of POST /api/v1/analyze."""

    api_contract_version: str = API_CONTRACT_VERSION
    analysis_id: str = Field(min_length=1)
    config_version: str
    pipeline_version: str
    audio: AudioInfo
    baseline: BaselineInfo
    alignment_method: AlignmentMethod
    transcript: str
    alignment: list[AlignedWord]
    features: FeatureSet
    baseline_stats: BaselineStats
    flaws: list[Flaw]
    scores: ScoreSummary
    overall_summary: Optional[str] = None
    processing_meta: ProcessingMeta

    @model_validator(mode="after")
    def _consistent(self) -> "AnalysisResult":
        if self.scores.scoring_version != self.config_version:
            # §20: scoring_version is the same as config_version.
            raise ValueError("scores.scoring_version must equal config_version")
        ids = [f.flaw_id for f in self.flaws]
        if len(ids) != len(set(ids)):
            raise ValueError("flaw_id values must be unique")
        for f in self.flaws:
            if f.end_s > self.audio.duration_s + 0.01:
                raise ValueError(f"{f.flaw_id} extends beyond audio duration")
        return self

    def deterministic_json(self) -> str:
        """Canonical JSON of the reproducible part of the result.

        Excludes `analysis_id` and `processing_meta` (run-specific).
        Same input + same config must yield an identical string.
        """
        return self.model_dump_json(exclude={"analysis_id", "processing_meta"})
