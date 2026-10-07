"""Fundamental Frequency (Pitch/F0) Feature Extraction Service (TASK-030).

Single canonical implementation of Pitch/F0 feature extraction under
`backend/app/services/features/` (ARCHITECTURE.md §7.4, §9.4, §13.1;
DECISIONS.md DEC-010, DEC-P004).

Algorithm:
    Probabilistic YIN (pYIN) via `librosa.pyin` (Mauch & Dixon, 2014).
    pYIN estimates fundamental frequency (F0) on frame-level intervals
    using a hidden Markov model (HMM) Viterbi decoding over pitch candidate
    probabilities, producing both candidate F0, a voiced flag, and voicing
    posterior probabilities.

Analytical Contract:
    1. Deterministic numerical extraction: identical audio + identical config
       produces identical outputs.
    2. Explicit unvoiced representation: unvoiced frames contain NaN in `values_hz`
       and False in `voiced`. Fake pitch values (e.g. 0 Hz or interpolated values)
       are strictly forbidden.
    3. Timestamped measurements: explicit frame center timestamps in seconds.
    4. Stateless & extraction only: this service does NOT classify flaws,
       normalize relative to baseline, or compute scores.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

import librosa
import numpy as np


@dataclass(frozen=True)
class F0Config:
    """Explicit configuration parameters for Pitch/F0 extraction.

    Values and defaults are aligned with ARCHITECTURE.md §13.1:
    - TARGET_SAMPLE_RATE: 16 000 Hz
    - F0_HOP_LENGTH: 160 samples (10.0 ms frame hop at 16 kHz)
    - Frame length: 2048 samples (128.0 ms window at 16 kHz)
    - F0_FMIN_HZ: 75.0 Hz (covers deep adult male pitch registers)
    - F0_FMAX_HZ: 500.0 Hz (covers high female / expressive pitch registers)
    - F0_VOICED_PROB_THRESHOLD: 0.85 (probabilistic threshold for voicing confidence)
    """

    sample_rate: int = 16000
    frame_length: int = 2048
    hop_length: int = 160
    fmin: float = 75.0
    fmax: float = 500.0
    voiced_prob_threshold: Optional[float] = 0.85
    center: bool = True
    fill_na: float = float("nan")

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError(f"sample_rate must be positive, got {self.sample_rate}")
        if self.frame_length <= 0:
            raise ValueError(f"frame_length must be positive, got {self.frame_length}")
        if self.hop_length <= 0:
            raise ValueError(f"hop_length must be positive, got {self.hop_length}")
        if self.fmin <= 0.0:
            raise ValueError(f"fmin must be positive, got {self.fmin}")
        if self.fmax <= self.fmin:
            raise ValueError(f"fmax ({self.fmax}) must be strictly greater than fmin ({self.fmin})")
        if self.voiced_prob_threshold is not None:
            if not (0.0 <= self.voiced_prob_threshold <= 1.0):
                raise ValueError(
                    f"voiced_prob_threshold must be between 0.0 and 1.0, got {self.voiced_prob_threshold}"
                )


@dataclass
class F0ExtractionResult:
    """Output bundle of timestamped F0/pitch measurements.

    Attributes:
        times_s: Frame center timestamps in seconds (1D float64 array).
        values_hz: Frame-level F0 in Hz (1D float64 array). Unvoiced frames
            contain np.nan.
        voiced: Frame-level boolean voicing flags (1D bool array).
        voiced_prob: Frame-level estimated voicing probability in [0.0, 1.0]
            (1D float64 array).
        config: Snapshot of configuration used for extraction.
    """

    times_s: np.ndarray
    values_hz: np.ndarray
    voiced: np.ndarray
    voiced_prob: np.ndarray
    config: F0Config

    @property
    def total_frames(self) -> int:
        """Total number of analysis frames."""
        return len(self.times_s)

    @property
    def voiced_count(self) -> int:
        """Number of frames identified as voiced."""
        return int(np.sum(self.voiced))

    @property
    def unvoiced_count(self) -> int:
        """Number of frames identified as unvoiced."""
        return int(np.sum(~self.voiced))

    @property
    def voiced_ratio(self) -> float:
        """Fraction of total frames identified as voiced in [0.0, 1.0]."""
        if self.total_frames == 0:
            return 0.0
        return float(self.voiced_count / self.total_frames)

    @property
    def voiced_values_hz(self) -> np.ndarray:
        """Contiguous array of finite Hz values for voiced frames only.

        Useful for downstream speaker statistics, baseline calculations, and z-scoring.
        """
        return self.values_hz[self.voiced]

    def to_timeline_dict(self) -> Dict[str, List[Any]]:
        """Serialize to dictionary matching API response schema `F0Timeline` (ARCHITECTURE.md §6.3, §23).

        Unvoiced frames are mapped to Python `None` (valid JSON null), preventing
        invalid NaN tokens in HTTP responses while maintaining strict index alignment.
        """
        values_json: List[Optional[float]] = [
            float(v) if is_v and np.isfinite(v) else None
            for v, is_v in zip(self.values_hz, self.voiced)
        ]
        return {
            "times_s": [float(t) for t in self.times_s],
            "values_hz": values_json,
            "voiced": [bool(b) for b in self.voiced],
        }

    def to_feature_bundle_dict(self) -> Dict[str, np.ndarray]:
        """Export fields matching internal intermediate `FeatureBundle` (ARCHITECTURE.md §9.4)."""
        return {
            "f0_times_s": self.times_s.copy(),
            "f0_values_hz": self.values_hz.copy(),
            "f0_voiced": self.voiced.copy(),
            "f0_voiced_prob": self.voiced_prob.copy(),
        }


def _coerce_audio_and_sample_rate(
    audio: Union[np.ndarray, Any],
    sample_rate: Optional[int],
    config_sample_rate: int,
) -> Tuple[np.ndarray, int]:
    """Validate and normalize numeric audio array and sample rate.

    Accepts:
        - 1D numpy ndarray of float32/float64.
        - Canonical container object with `.audio_array` (and optional `.sample_rate_hz`).
    """
    if hasattr(audio, "audio_array"):
        arr = getattr(audio, "audio_array")
        container_sr = getattr(audio, "sample_rate_hz", None)
        if sample_rate is not None and container_sr is not None and sample_rate != container_sr:
            raise ValueError(
                f"Sample rate conflict: provided argument ({sample_rate} Hz) does not match "
                f"container sample_rate_hz ({container_sr} Hz)."
            )
        resolved_sr = sample_rate or container_sr or config_sample_rate
    else:
        arr = audio
        resolved_sr = sample_rate or config_sample_rate

    if not isinstance(arr, np.ndarray):
        raise TypeError(
            f"Expected audio to be a numpy.ndarray or container with .audio_array, got {type(arr).__name__}."
        )

    # Allow squeezing 2D mono shapes like (1, N) or (N, 1)
    if arr.ndim > 1:
        if arr.ndim == 2 and (arr.shape[0] == 1 or arr.shape[1] == 1):
            arr = arr.squeeze()
        else:
            raise ValueError(
                f"Audio signal must be mono (1D), got shape {arr.shape}. Multichannel audio must be downmixed."
            )

    if arr.ndim != 1 or arr.size == 0:
        raise ValueError("Audio signal must be a non-empty 1D array.")

    if not np.all(np.isfinite(arr)):
        raise ValueError("Audio signal contains non-finite values (NaN or Inf).")

    if not np.issubdtype(arr.dtype, np.floating):
        arr = arr.astype(np.float32)

    return arr, resolved_sr


class F0Extractor:
    """Deterministic fundamental frequency (F0/pitch) feature extractor."""

    def __init__(self, config: Optional[F0Config] = None) -> None:
        self.config = config or F0Config()

    def extract(
        self,
        audio: Union[np.ndarray, Any],
        sample_rate: Optional[int] = None,
    ) -> F0ExtractionResult:
        """Extract timestamped F0/pitch measurements from an audio signal.

        Args:
            audio: 1D numpy array of audio PCM samples or canonical audio container.
            sample_rate: Optional sample rate. If omitted, uses `self.config.sample_rate`.

        Returns:
            F0ExtractionResult with timestamped Hz values, voicing flags, and probabilities.
        """
        arr, resolved_sr = _coerce_audio_and_sample_rate(
            audio=audio,
            sample_rate=sample_rate,
            config_sample_rate=self.config.sample_rate,
        )

        if resolved_sr != self.config.sample_rate:
            raise ValueError(
                f"Audio sample rate ({resolved_sr} Hz) does not match extractor configuration "
                f"({self.config.sample_rate} Hz). Resample input or configure matching F0Config."
            )

        # Run deterministic pYIN extraction
        raw_f0, voiced_flag, voiced_probs = librosa.pyin(
            y=arr,
            fmin=self.config.fmin,
            fmax=self.config.fmax,
            sr=self.config.sample_rate,
            frame_length=self.config.frame_length,
            hop_length=self.config.hop_length,
            center=self.config.center,
            fill_na=self.config.fill_na,
        )

        # Compute explicit frame center timestamps in seconds
        times_s = librosa.times_like(
            raw_f0,
            sr=self.config.sample_rate,
            hop_length=self.config.hop_length,
        ).astype(np.float64)

        # Voicing decision: pYIN Viterbi path combined with configured probability threshold
        if self.config.voiced_prob_threshold is not None:
            is_voiced = voiced_flag & (voiced_probs >= self.config.voiced_prob_threshold)
        else:
            is_voiced = voiced_flag.copy()

        # Enforce analytical contract:
        # - Voiced frames must have finite F0 within [fmin, fmax]
        # - Unvoiced frames MUST have NaN in values_hz and False in voiced
        values_hz = np.where(is_voiced, raw_f0, np.nan).astype(np.float64)

        out_of_bounds = is_voiced & (
            (values_hz < self.config.fmin)
            | (values_hz > self.config.fmax)
            | np.isnan(values_hz)
        )
        if np.any(out_of_bounds):
            is_voiced[out_of_bounds] = False
            values_hz[out_of_bounds] = np.nan

        voiced = is_voiced.astype(bool)
        voiced_prob = np.clip(voiced_probs.astype(np.float64), 0.0, 1.0)

        return F0ExtractionResult(
            times_s=times_s,
            values_hz=values_hz,
            voiced=voiced,
            voiced_prob=voiced_prob,
            config=self.config,
        )


def extract_f0(
    audio: Union[np.ndarray, Any],
    config: Optional[F0Config] = None,
    sample_rate: Optional[int] = None,
) -> F0ExtractionResult:
    """Functional convenience entrypoint for F0 extraction.

    Args:
        audio: 1D numpy array of audio PCM samples or canonical audio container.
        config: Optional configuration. If omitted, default F0Config is used.
            If omitted and audio provides a sample_rate_hz different from default 16kHz,
            a matching F0Config is automatically initialized.
        sample_rate: Optional sample rate override.

    Returns:
        F0ExtractionResult containing timestamped F0 measurements.
    """
    if config is None:
        inferred_sr = sample_rate
        if inferred_sr is None and hasattr(audio, "sample_rate_hz"):
            inferred_sr = getattr(audio, "sample_rate_hz")
        if inferred_sr is not None and inferred_sr != F0Config.sample_rate:
            config = F0Config(sample_rate=inferred_sr)
        else:
            config = F0Config()

    extractor = F0Extractor(config=config)
    return extractor.extract(audio=audio, sample_rate=sample_rate)
