"""Energy / loudness Feature Extraction Service.

Single canonical implementation of frame-level energy extraction under
`backend/app/services/features/`.

Algorithm:
    `librosa.feature.rms` computes the root-mean-square amplitude of each analysis
    frame of the (float PCM, full-scale = 1.0) signal. RMS is converted to dBFS:

        energy_db = 20 * log10(max(rms, rms_floor))

    `rms_floor` (1e-9, i.e. -180 dBFS) is the architecture's `max(rms, 1e-9)` guard,
    so digital silence yields a finite -180.0 dB, never -inf or NaN.

Analytical contract:
    1. Deterministic: identical audio + identical config produces identical output.
       The padding mode is pinned ("constant" zero padding) so results do not depend
       on the librosa default of a particular version.
    2. Timestamped: frame-centre times in seconds (same convention and hop as F0 and
       MFCC, `librosa.times_like`), in processed-audio time.
    3. Units: values are dBFS relative to full-scale float PCM. Because preprocessing
       scales every recording so that its typical speech level is TARGET_SPEECH_LEVEL_DBFS
, these are *relative loudness* values comparable between recordings that
       went through the same preprocessing, not absolute sound-pressure levels.
    4. Stateless & extraction only: no normalization, baseline comparison, flaw
       detection or scoring happens here.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

import librosa
import numpy as np

from .f0 import _coerce_audio_and_sample_rate

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnergyConfig:
    """Explicit configuration for energy extraction.

    Defaults (PROPOSED starting values, not calibrated):
    - sample_rate: 16 000 Hz (TARGET_SAMPLE_RATE)
    - hop_length: 160 samples (10 ms), identical to the F0 and MFCC hop so all
      frame-level feature timelines share one time grid.
    - frame_length: 512 samples (32 ms), identical to the MFCC window.
      does not fix an RMS window; 32 ms resolves syllable-scale energy changes and
      pause boundaries while smoothing individual pitch periods.
    - rms_floor: 1e-9 (-180 dBFS), the architecture's `max(rms, 1e-9)` guard.
    - quiet_warning_dbfs: -70.0; a mean level below this logs a warning because the
      recording is extremely quiet (failure condition).
      Reliability handling itself belongs to the grounding stage.

    Frames are always centred (zero-padded by frame_length // 2 at both ends), so
    frame i is centred at ``i * hop_length / sample_rate`` seconds.
    """

    sample_rate: int = 16000
    frame_length: int = 512
    hop_length: int = 160
    rms_floor: float = 1e-9
    quiet_warning_dbfs: float = -70.0

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError(f"sample_rate must be positive, got {self.sample_rate}")
        if self.frame_length <= 0:
            raise ValueError(f"frame_length must be positive, got {self.frame_length}")
        if self.hop_length <= 0:
            raise ValueError(f"hop_length must be positive, got {self.hop_length}")
        if not (self.rms_floor > 0.0 and np.isfinite(self.rms_floor)):
            raise ValueError(f"rms_floor must be a positive finite number, got {self.rms_floor}")
        if not np.isfinite(self.quiet_warning_dbfs):
            raise ValueError(f"quiet_warning_dbfs must be finite, got {self.quiet_warning_dbfs}")


@dataclass
class EnergyExtractionResult:
    """Frame-level energy measurements.

    Attributes:
        times_s: Frame-centre timestamps in seconds (1D float64).
        values_db: Frame RMS energy in dBFS (1D float64, always finite).
        config: Snapshot of the configuration used.
    """

    times_s: np.ndarray
    values_db: np.ndarray
    config: EnergyConfig

    @property
    def total_frames(self) -> int:
        return len(self.times_s)

    @property
    def hop_s(self) -> float:
        """Frame hop in seconds."""
        return self.config.hop_length / self.config.sample_rate

    @property
    def mean_db(self) -> float:
        """Arithmetic mean of frame dBFS values (0 frames cannot occur for valid input)."""
        return float(np.mean(self.values_db))

    def to_timeline_dict(self) -> Dict[str, List[float]]:
        """Serialize to the API response `EnergyTimeline` shape."""
        return {
            "times_s": [float(t) for t in self.times_s],
            "values_db": [float(v) for v in self.values_db],
        }

    def to_feature_bundle_dict(self) -> Dict[str, np.ndarray]:
        """Export fields matching the internal `FeatureBundle`."""
        return {
            "energy_times_s": self.times_s.copy(),
            "energy_db": self.values_db.copy(),
        }


def frame_energy_db(audio: np.ndarray, config: EnergyConfig) -> np.ndarray:
    """Loudness (dBFS RMS, always finite) of every centred analysis frame of a mono float signal.

    The single definition of "frame loudness": the energy timeline is this function plus frame times, and the loudness scaling of
    the preprocessing step measures the speech level with the very same frames.
    """
    rms = librosa.feature.rms(
        y=audio,
        frame_length=config.frame_length,
        hop_length=config.hop_length,
        center=True,
        pad_mode="constant",
    )[0].astype(np.float64)
    return 20.0 * np.log10(np.maximum(rms, config.rms_floor))


class EnergyExtractor:
    """Deterministic frame-level RMS energy (dBFS) extractor."""

    def __init__(self, config: Optional[EnergyConfig] = None) -> None:
        self.config = config or EnergyConfig()

    def extract(
        self,
        audio: Union[np.ndarray, Any],
        sample_rate: Optional[int] = None,
    ) -> EnergyExtractionResult:
        """Extract timestamped energy from a mono audio signal.

        Args:
            audio: 1D numpy array of PCM samples (full-scale = 1.0) or a canonical
                container exposing `.audio_array` (e.g. `PreprocessedAudio`).
            sample_rate: Optional sample rate; must equal `config.sample_rate`.

        Raises:
            ValueError: empty / non-finite / non-mono audio, or a sample-rate mismatch.
            TypeError: unsupported audio type.
        """
        arr, resolved_sr = _coerce_audio_and_sample_rate(
            audio=audio,
            sample_rate=sample_rate,
            config_sample_rate=self.config.sample_rate,
        )

        if resolved_sr != self.config.sample_rate:
            raise ValueError(
                f"Audio sample rate ({resolved_sr} Hz) does not match extractor configuration "
                f"({self.config.sample_rate} Hz). Resample input or configure matching EnergyConfig."
            )

        values_db = frame_energy_db(arr, self.config)
        times_s = librosa.times_like(
            values_db,
            sr=self.config.sample_rate,
            hop_length=self.config.hop_length,
        ).astype(np.float64)

        result = EnergyExtractionResult(times_s=times_s, values_db=values_db, config=self.config)
        if result.mean_db < self.config.quiet_warning_dbfs:
            logger.warning(
                "Very quiet audio: mean energy %.1f dBFS is below %.1f dBFS; "
                "energy-based findings will be unreliable.",
                result.mean_db,
                self.config.quiet_warning_dbfs,
            )
        return result


def extract_energy(
    audio: Union[np.ndarray, Any],
    config: Optional[EnergyConfig] = None,
    sample_rate: Optional[int] = None,
) -> EnergyExtractionResult:
    """Functional convenience entrypoint for energy extraction.

    If `config` is omitted and the audio container reports a `sample_rate_hz` other
    than the default 16 kHz, a matching `EnergyConfig` is created (same behaviour as
    `extract_f0`).
    """
    if config is None:
        inferred_sr = sample_rate
        if inferred_sr is None and hasattr(audio, "sample_rate_hz"):
            inferred_sr = getattr(audio, "sample_rate_hz")
        if inferred_sr is not None and inferred_sr != EnergyConfig.sample_rate:
            config = EnergyConfig(sample_rate=inferred_sr)
        else:
            config = EnergyConfig()

    return EnergyExtractor(config=config).extract(audio=audio, sample_rate=sample_rate)
