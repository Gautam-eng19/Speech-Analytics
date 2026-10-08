"""Mel-Frequency Cepstral Coefficient (MFCC) Feature Extraction Service (TASK-031).

Single canonical implementation of MFCC feature extraction under
`backend/app/services/features/` (ARCHITECTURE.md §7.4, §9.4, §13.2;
DECISIONS.md DEC-P004).

Algorithm:
    `librosa.feature.mfcc` computes MFCCs from the short-time Fourier transform (STFT)
    of the input signal via a mel-filterbank and discrete cosine transform (DCT).

    The full pipeline inside librosa is:
        1. STFT with Hann window of `n_fft` samples, hop of `hop_length` samples
        2. Power spectrum  → mel-spectrogram with `n_mels` triangular filter bands
           covering [fmin, fmax] Hz
        3. Log-magnitude mel-spectrogram → `n_mfcc` DCT coefficients

    Librosa returns coefficients × frames (C, T).  This module EXPLICITLY transposes
    to frames × coefficients (T, C) before returning, so that downstream temporal
    analysis iterates over frames as rows — consistent with the FeatureBundle contract
    `mfcc_matrix: np.ndarray — shape (n_frames, 13)` (ARCHITECTURE.md §9.4).

Determinism guarantee:
    Same audio array + same MFCCConfig → bit-identical MFCCExtractionResult.
    librosa.feature.mfcc is fully deterministic given a fixed input and parameters.

Analytical contract:
    1. Deterministic numerical extraction: identical audio + identical config
       produces identical outputs.
    2. Timestamped measurements: explicit frame-centre timestamps in seconds via
       `librosa.times_like`, matching the identical convention used by F0.
    3. Stateless & extraction only: this service does NOT normalise, compare to
       baseline, detect flaws, or compute scores.
    4. This service MUST NOT resample or otherwise modify the incoming audio array.

Primary use at P0:
    Summary statistics (`mfcc_summary` in the API response: mean and std per
    coefficient across the whole recording).  See ARCHITECTURE.md §13.2.

Primary use at P1:
    Word-segment cosine distance for Reduced Clarity evidence, which requires the
    full frame matrix.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

import librosa
import numpy as np


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MFCCConfig:
    """Explicit, centralized configuration for MFCC extraction.

    All defaults are aligned with ARCHITECTURE.md §13.2 and the project's
    16 kHz speech target.

    Attributes:
        sample_rate:  Expected sample rate (Hz).  Must match the input audio.
                      Default: 16 000 Hz (TARGET_SAMPLE_RATE).
        n_mfcc:       Number of MFCC coefficients to return (MFCC_N_COEFFS).
                      Default: 13 (standard for speech).
        n_fft:        FFT window size in samples (MFCC_N_FFT).
                      Default: 512 (~32 ms at 16 kHz; balances frequency resolution
                      for speech while keeping latency short).
        hop_length:   Frame hop in samples (MFCC_HOP_LENGTH).
                      Default: 160 (10 ms at 16 kHz; matches F0 hop for aligned
                      temporal grids across features).
        n_mels:       Number of mel filter bands (MFCC_N_MELS).
                      Default: 40 (standard for speech recognition).
        fmin:         Lowest frequency for the mel filterbank in Hz (MFCC_FMIN_HZ).
                      Default: 0.0 (include DC and sub-speech energy, librosa default).
        fmax:         Highest frequency for the mel filterbank in Hz (MFCC_FMAX_HZ).
                      Default: 8 000.0 (Nyquist for 16 kHz; covers full speech band).
        lifter:       Liftering coefficient applied to the cepstrum (0 = disabled).
                      Default: 0 (disabled for simplicity and interpretability; P1
                      could enable sine-liftering to de-emphasize high-index coefficients).
        center:       If True, pad signal so frame 0 is centred on sample 0
                      (librosa convention).  Produces the same number of frames
                      as `librosa.times_like`.  Default: True.
        norm:         Normalisation applied to the mel filterbank.  'slaney' divides
                      each filter by its bandwidth, producing a unit-energy (area-normalised)
                      filterbank.  Default: None (no normalisation — raw filter output).
    """

    sample_rate: int = 16000
    n_mfcc: int = 13
    n_fft: int = 512
    hop_length: int = 160
    n_mels: int = 40
    fmin: float = 0.0
    fmax: float = 8000.0
    lifter: int = 0
    center: bool = True
    norm: Optional[str] = None

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError(
                f"sample_rate must be a positive integer, got {self.sample_rate}"
            )
        if self.n_mfcc <= 0:
            raise ValueError(
                f"n_mfcc must be a positive integer, got {self.n_mfcc}"
            )
        if self.n_fft <= 0:
            raise ValueError(
                f"n_fft must be a positive integer, got {self.n_fft}"
            )
        if self.hop_length <= 0:
            raise ValueError(
                f"hop_length must be a positive integer, got {self.hop_length}"
            )
        if self.n_mels <= 0:
            raise ValueError(
                f"n_mels must be a positive integer, got {self.n_mels}"
            )
        if self.fmin < 0.0:
            raise ValueError(
                f"fmin must be >= 0.0, got {self.fmin}"
            )
        nyquist = self.sample_rate / 2.0
        if self.fmax <= self.fmin:
            raise ValueError(
                f"fmax ({self.fmax}) must be strictly greater than fmin ({self.fmin})"
            )
        if self.fmax > nyquist:
            raise ValueError(
                f"fmax ({self.fmax} Hz) exceeds Nyquist frequency ({nyquist} Hz) "
                f"for sample_rate={self.sample_rate} Hz"
            )
        if self.n_mfcc > self.n_mels:
            raise ValueError(
                f"n_mfcc ({self.n_mfcc}) must be <= n_mels ({self.n_mels})"
            )
        if self.lifter < 0:
            raise ValueError(
                f"lifter must be >= 0 (0 = disabled), got {self.lifter}"
            )
        if self.norm is not None and self.norm not in ("slaney",):
            raise ValueError(
                f"norm must be None or 'slaney', got {self.norm!r}"
            )


# ---------------------------------------------------------------------------
# Result object
# ---------------------------------------------------------------------------

@dataclass
class MFCCExtractionResult:
    """Output bundle of timestamped MFCC frame matrix.

    Matrix orientation (ARCHITECTURE.md §9.4):
        `mfcc_matrix` is stored as **frames × coefficients** — shape (T, C) —
        where T is the number of analysis frames and C = `config.n_mfcc`.

        Rationale: downstream temporal analysis iterates over frames (rows), so
        row-major frame ordering minimises slicing complexity.  librosa returns
        the transposed shape (C, T) internally; this module explicitly converts.

    Attributes:
        times_s:      Frame-centre timestamps in seconds, shape (T,), float64.
                      Computed via `librosa.times_like` with the same hop_length
                      and sample_rate as the MFCC, guaranteeing exact alignment.
        mfcc_matrix:  MFCC frame matrix, shape (T, C), float32.
                      Row i corresponds to frame centred at `times_s[i]`.
                      Column j contains the (j+1)-th cepstral coefficient.
        config:       Frozen snapshot of MFCCConfig used for extraction.
    """

    times_s: np.ndarray          # shape (T,) float64 — frame-centre timestamps in seconds
    mfcc_matrix: np.ndarray      # shape (T, C) float32 — frames × coefficients
    config: MFCCConfig

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def n_frames(self) -> int:
        """Total number of analysis frames."""
        return len(self.times_s)

    @property
    def n_coefficients(self) -> int:
        """Number of MFCC coefficients per frame."""
        return self.mfcc_matrix.shape[1] if self.mfcc_matrix.ndim == 2 else 0

    @property
    def mean_per_coefficient(self) -> np.ndarray:
        """Mean of each MFCC coefficient across all frames, shape (C,), float64."""
        if self.n_frames == 0:
            return np.zeros(self.config.n_mfcc, dtype=np.float64)
        return self.mfcc_matrix.mean(axis=0).astype(np.float64)

    @property
    def std_per_coefficient(self) -> np.ndarray:
        """Standard deviation of each MFCC coefficient across all frames, shape (C,), float64."""
        if self.n_frames == 0:
            return np.zeros(self.config.n_mfcc, dtype=np.float64)
        return self.mfcc_matrix.std(axis=0).astype(np.float64)

    def to_summary_dict(self) -> Dict[str, List[float]]:
        """Return summary statistics matching the API `mfcc_summary` field (ARCHITECTURE.md §6.3).

        Returns:
            dict with keys:
                - ``mean_13``: list of float — mean MFCC per coefficient
                - ``std_13``:  list of float — std  MFCC per coefficient
        """
        return {
            "mean_13": [float(v) for v in self.mean_per_coefficient],
            "std_13":  [float(v) for v in self.std_per_coefficient],
        }

    def to_feature_bundle_dict(self) -> Dict[str, Any]:
        """Export fields matching internal ``FeatureBundle`` contract (ARCHITECTURE.md §9.4)."""
        return {
            "mfcc_times_s": self.times_s.copy(),
            "mfcc_matrix":  self.mfcc_matrix.copy(),
        }


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------

def _coerce_audio_and_sample_rate(
    audio: Union[np.ndarray, Any],
    sample_rate: Optional[int],
    config_sample_rate: int,
) -> Tuple[np.ndarray, int]:
    """Validate and extract a numeric audio array and resolved sample rate.

    Accepts:
        - 1D numpy ndarray of float32 / float64.
        - Canonical container object with ``.audio_array`` attribute (and optional
          ``.sample_rate_hz``), e.g. ``PreprocessedAudio``.

    Raises:
        TypeError:  If `audio` is not a numpy array or a recognized container.
        ValueError: If the array is not 1D mono, is empty, contains non-finite
                    values, or the sample rate conflicts.
    """
    if hasattr(audio, "audio_array"):
        arr = getattr(audio, "audio_array")
        container_sr: Optional[int] = getattr(audio, "sample_rate_hz", None)
        if (
            sample_rate is not None
            and container_sr is not None
            and sample_rate != container_sr
        ):
            raise ValueError(
                f"Sample rate conflict: provided argument ({sample_rate} Hz) does not "
                f"match container sample_rate_hz ({container_sr} Hz)."
            )
        resolved_sr = sample_rate or container_sr or config_sample_rate
    else:
        arr = audio
        resolved_sr = sample_rate or config_sample_rate

    if not isinstance(arr, np.ndarray):
        raise TypeError(
            f"Expected audio to be a numpy.ndarray or container with .audio_array, "
            f"got {type(arr).__name__}."
        )

    # Allow squeezing degenerate 2D mono shapes like (1, N) or (N, 1)
    if arr.ndim > 1:
        if arr.ndim == 2 and (arr.shape[0] == 1 or arr.shape[1] == 1):
            arr = arr.squeeze()
        else:
            raise ValueError(
                f"Audio signal must be mono (1D), got shape {arr.shape}. "
                f"Multichannel audio must be downmixed before feature extraction."
            )

    if arr.ndim != 1 or arr.size == 0:
        raise ValueError("Audio signal must be a non-empty 1D array.")

    if not np.all(np.isfinite(arr)):
        raise ValueError(
            "Audio signal contains non-finite values (NaN or Inf). "
            "Ensure preprocessing removes or replaces non-finite samples."
        )

    if not np.issubdtype(arr.dtype, np.floating):
        arr = arr.astype(np.float32)

    return arr, resolved_sr


# ---------------------------------------------------------------------------
# Extractor class
# ---------------------------------------------------------------------------

class MFCCExtractor:
    """Deterministic MFCC feature extractor.

    Wraps `librosa.feature.mfcc` with explicit configuration, input validation,
    and guaranteed frame × coefficient output orientation.
    """

    def __init__(self, config: Optional[MFCCConfig] = None) -> None:
        self.config = config or MFCCConfig()

    def extract(
        self,
        audio: Union[np.ndarray, Any],
        sample_rate: Optional[int] = None,
    ) -> MFCCExtractionResult:
        """Extract timestamped MFCC frame matrix from a preprocessed audio signal.

        Args:
            audio:       1D float32/float64 numpy array (mono PCM at config.sample_rate)
                         OR a canonical audio container with ``.audio_array`` and
                         ``.sample_rate_hz`` attributes (e.g. ``PreprocessedAudio``).
            sample_rate: Optional explicit sample rate in Hz.  When provided it must
                         match both the container attribute (if any) and
                         ``config.sample_rate``.  If omitted, ``config.sample_rate``
                         is used.

        Returns:
            MFCCExtractionResult containing:
                - ``times_s``     — frame-centre timestamps, shape (T,), float64
                - ``mfcc_matrix`` — frames × coefficients, shape (T, C), float32
                - ``config``      — frozen config snapshot for reproducibility

        Raises:
            TypeError:  Non-array / unrecognized input.
            ValueError: Non-mono, empty, non-finite, or mismatched-sample-rate audio;
                        invalid configuration parameters.
        """
        cfg = self.config
        arr, resolved_sr = _coerce_audio_and_sample_rate(
            audio=audio,
            sample_rate=sample_rate,
            config_sample_rate=cfg.sample_rate,
        )

        if resolved_sr != cfg.sample_rate:
            raise ValueError(
                f"Audio sample rate ({resolved_sr} Hz) does not match extractor "
                f"configuration ({cfg.sample_rate} Hz).  Resample before calling "
                f"MFCCExtractor, or create a matching MFCCConfig."
            )

        # ------------------------------------------------------------------
        # Core MFCC computation (deterministic — no randomness in librosa MFCC).
        #
        # librosa.feature.mfcc returns shape (n_mfcc, n_frames) — coefficients × frames.
        # We EXPLICITLY TRANSPOSE to (n_frames, n_mfcc) — frames × coefficients —
        # before storing, as documented in MFCCExtractionResult and ARCHITECTURE.md §9.4.
        # ------------------------------------------------------------------
        raw_mfcc: np.ndarray = librosa.feature.mfcc(
            y=arr,
            sr=cfg.sample_rate,
            n_mfcc=cfg.n_mfcc,
            n_fft=cfg.n_fft,
            hop_length=cfg.hop_length,
            n_mels=cfg.n_mels,
            fmin=cfg.fmin,
            fmax=cfg.fmax,
            lifter=cfg.lifter,
            center=cfg.center,
            norm=cfg.norm,
        )
        # raw_mfcc.shape == (n_mfcc, n_frames) — librosa convention
        # Transpose → (n_frames, n_mfcc) for temporal-first downstream use
        mfcc_matrix = raw_mfcc.T.astype(np.float32)

        # Compute frame-centre timestamps matching librosa's internal frame grid.
        # times_like uses the same hop_length & sr, so times_s[i] is the centre
        # of the i-th STFT frame — identical convention to F0's times_s.
        times_s: np.ndarray = librosa.times_like(
            raw_mfcc,
            sr=cfg.sample_rate,
            hop_length=cfg.hop_length,
        ).astype(np.float64)

        return MFCCExtractionResult(
            times_s=times_s,
            mfcc_matrix=mfcc_matrix,
            config=cfg,
        )


# ---------------------------------------------------------------------------
# Functional convenience entrypoint
# ---------------------------------------------------------------------------

def extract_mfcc(
    audio: Union[np.ndarray, Any],
    config: Optional[MFCCConfig] = None,
    sample_rate: Optional[int] = None,
) -> MFCCExtractionResult:
    """Functional convenience entrypoint for MFCC extraction.

    Args:
        audio:       1D numpy array of PCM samples or canonical audio container.
        config:      Optional MFCCConfig.  If omitted, default MFCCConfig() is
                     constructed.  If the audio has a ``.sample_rate_hz`` that
                     differs from 16 000 Hz and no explicit config is supplied,
                     a matching MFCCConfig is auto-constructed.
        sample_rate: Optional sample rate override.

    Returns:
        MFCCExtractionResult with timestamped MFCC matrix.
    """
    if config is None:
        inferred_sr = sample_rate
        if inferred_sr is None and hasattr(audio, "sample_rate_hz"):
            inferred_sr = getattr(audio, "sample_rate_hz")
        if inferred_sr is not None and inferred_sr != MFCCConfig.sample_rate:
            config = MFCCConfig(sample_rate=inferred_sr)
        else:
            config = MFCCConfig()

    extractor = MFCCExtractor(config=config)
    return extractor.extract(audio=audio, sample_rate=sample_rate)
