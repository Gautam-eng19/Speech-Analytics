"""Audio preprocessing service (ARCHITECTURE.md §7.1, §9.1, §10; DEC-P003).

Converts raw audio bytes or files into the canonical PreprocessedAudio contract:
- Validates audio format (WAV PCM / IEEE float; MP3 requires ffmpeg/av backend)
- Converts multi-channel audio to mono (averaging channels)
- Resamples to TARGET_SAMPLE_RATE (default 16 000 Hz) deterministically via polyphase filtering
- Trims leading and trailing silence using energy VAD with configurable threshold
- Peak-normalizes to TARGET_PEAK_DBFS (default -3.0 dBFS)
- Computes SHA-256 over normalized float32 PCM bytes for reproducible provenance
"""
from __future__ import annotations

import hashlib
import io
import math
from pathlib import Path
from typing import Optional, Tuple, Union

import numpy as np
import scipy.io.wavfile as wav
import scipy.signal as signal

from app.core.config import settings
from app.schemas.contracts import PreprocessedAudio


class AudioPreprocessingError(ValueError):
    """Raised when audio decoding or preprocessing fails deterministically."""
    pass


def _decode_wav(data: bytes) -> Tuple[np.ndarray, int]:
    """Decode WAV bytes using scipy.io.wavfile into float32 array."""
    try:
        sample_rate, raw_array = wav.read(io.BytesIO(data))
    except Exception as exc:
        raise AudioPreprocessingError(f"Failed to decode WAV audio: {exc}") from exc

    if sample_rate <= 0:
        raise AudioPreprocessingError(f"Invalid sample rate: {sample_rate}")

    # Convert to float32 normalized to [-1.0, 1.0] based on dtype
    if raw_array.dtype == np.int16:
        float_array = raw_array.astype(np.float32) / 32768.0
    elif raw_array.dtype == np.int32:
        float_array = raw_array.astype(np.float32) / 2147483648.0
    elif raw_array.dtype == np.uint8:
        float_array = (raw_array.astype(np.float32) - 128.0) / 128.0
    elif raw_array.dtype in (np.float32, np.float64):
        float_array = raw_array.astype(np.float32)
    else:
        raise AudioPreprocessingError(f"Unsupported audio data type: {raw_array.dtype}")

    return float_array, sample_rate


def _decode_via_av(data: bytes) -> Tuple[np.ndarray, int]:
    """Decode audio bytes (MP3/WAV/etc.) in-memory using PyAV into float32 array."""
    try:
        import av
    except ImportError as exc:
        raise AudioPreprocessingError(
            "PyAV ('av') is required for MP3 audio decoding but is not installed. "
            "Please install 'av' in your Python environment."
        ) from exc

    try:
        container = av.open(io.BytesIO(data))
    except Exception as exc:
        raise AudioPreprocessingError(f"Failed to decode audio container: {exc}") from exc

    try:
        if not container.streams.audio:
            raise AudioPreprocessingError("No audio streams found in media container.")

        stream = container.streams.audio[0]
        sample_rate = stream.rate or stream.codec_context.sample_rate
        if not sample_rate or sample_rate <= 0:
            raise AudioPreprocessingError("Invalid or missing sample rate in audio stream.")

        frames: list[np.ndarray] = []
        for frame in container.decode(audio=0):
            # frame.to_ndarray() returns shape (channels, samples) for audio
            arr = frame.to_ndarray()
            # Normalize to float32 [-1.0, 1.0] if integer format
            if arr.dtype == np.int16:
                arr = arr.astype(np.float32) / 32768.0
            elif arr.dtype == np.int32:
                arr = arr.astype(np.float32) / 2147483648.0
            elif arr.dtype == np.uint8:
                arr = (arr.astype(np.float32) - 128.0) / 128.0
            elif arr.dtype != np.float32:
                arr = arr.astype(np.float32)

            frames.append(arr)

        if not frames:
            raise AudioPreprocessingError("No audio frames decoded from media container.")

        # Concatenate along sample axis (axis=-1: (channels, total_samples))
        full_audio = np.concatenate(frames, axis=-1)
        # Transpose to (total_samples, channels) to match standard shape if multi-channel
        if full_audio.ndim == 2:
            full_audio = full_audio.T

        return full_audio, sample_rate
    except AudioPreprocessingError:
        raise
    except Exception as exc:
        raise AudioPreprocessingError(f"Failed to decode audio frames: {exc}") from exc
    finally:
        container.close()


def load_audio_from_bytes(data: bytes) -> Tuple[np.ndarray, int]:
    """Decode raw audio bytes into float32 numpy array and sample rate.
    
    Supports WAV (PCM 16/24/32-bit and float32) and MP3 via PyAV.
    If input is empty or invalid, raises AudioPreprocessingError.
    """
    if not data:
        raise AudioPreprocessingError("Audio input data is empty.")

    # WAV detection: RIFF header
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WAVE":
        return _decode_wav(data)

    # MP3 detection: ID3 tag or MPEG sync bytes (0xFF, 0xE0+)
    is_mp3 = data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0)
    if is_mp3:
        return _decode_via_av(data)

    # For unknown/unspecified headers, attempt WAV first, then fall back to PyAV
    try:
        return _decode_wav(data)
    except AudioPreprocessingError:
        return _decode_via_av(data)


def convert_to_mono(audio: np.ndarray) -> np.ndarray:
    """Convert multi-channel audio to mono by averaging channels along the last axis."""
    if audio.ndim == 1:
        return audio
    if audio.ndim == 2:
        # Channels could be along axis 1 (standard) or axis 0
        if audio.shape[1] <= 8:
            return np.mean(audio, axis=1, dtype=np.float32)
        else:
            return np.mean(audio, axis=0, dtype=np.float32)
    raise AudioPreprocessingError(f"Unsupported array dimensions for audio: {audio.ndim}")


def resample_audio(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """Deterministically resample 1D float32 audio to target sample rate using polyphase filtering."""
    if orig_sr == target_sr:
        return audio
    if len(audio) == 0:
        return audio

    # Compute greatest common divisor for rational resampling factor
    gcd = math.gcd(orig_sr, target_sr)
    up = target_sr // gcd
    down = orig_sr // gcd

    resampled = signal.resample_poly(audio, up, down).astype(np.float32)
    return resampled


def trim_silence(
    audio: np.ndarray,
    sample_rate: int,
    threshold_dbfs: float = -50.0,
    frame_duration_ms: float = 20.0,
) -> np.ndarray:
    """Trim leading and trailing silence using energy VAD with configurable threshold.
    
    Divides audio into non-overlapping frames, computes RMS energy in dBFS,
    and identifies the first and last frames exceeding threshold_dbfs.
    """
    if len(audio) == 0:
        return audio

    frame_length = max(1, int(sample_rate * (frame_duration_ms / 1000.0)))
    n_frames = len(audio) // frame_length

    if n_frames == 0:
        # Audio is shorter than a single frame: evaluate directly
        rms = np.sqrt(np.mean(audio**2) + 1e-12)
        dbfs = 20.0 * np.log10(rms + 1e-12)
        return audio if dbfs >= threshold_dbfs else np.empty(0, dtype=np.float32)

    # Reshape frames and compute RMS
    truncated_len = n_frames * frame_length
    frames = audio[:truncated_len].reshape(n_frames, frame_length)
    frame_rms = np.sqrt(np.mean(frames**2, axis=1) + 1e-12)
    frame_dbfs = 20.0 * np.log10(frame_rms + 1e-12)

    active_indices = np.where(frame_dbfs >= threshold_dbfs)[0]
    if len(active_indices) == 0:
        # Entire audio is below silence threshold
        return np.empty(0, dtype=np.float32)

    start_sample = active_indices[0] * frame_length
    end_sample = min(len(audio), (active_indices[-1] + 1) * frame_length)

    return audio[start_sample:end_sample]


def peak_normalize(audio: np.ndarray, target_peak_dbfs: float = -3.0) -> Tuple[np.ndarray, float]:
    """Peak-normalize audio to target_peak_dbfs (default -3.0 dBFS).
    
    target_amplitude = 10 ^ (target_peak_dbfs / 20).
    Returns normalized audio and the measured peak dBFS.
    """
    if len(audio) == 0:
        return audio, -100.0

    current_peak = np.max(np.abs(audio))
    if current_peak < 1e-9:
        return audio, -100.0

    target_peak = 10.0 ** (target_peak_dbfs / 20.0)
    gain = target_peak / current_peak
    normalized = (audio * gain).astype(np.float32)

    measured_peak = np.max(np.abs(normalized))
    measured_peak_dbfs = float(20.0 * np.log10(measured_peak + 1e-12))

    return normalized, measured_peak_dbfs


def compute_audio_sha256(audio: np.ndarray) -> str:
    """Compute deterministic SHA-256 hex digest of normalized float32 PCM bytes."""
    return hashlib.sha256(audio.tobytes()).hexdigest()


class AudioPreprocessor:
    """Service class encapsulating canonical audio preprocessing (ARCHITECTURE.md §7.1, §10)."""

    def __init__(
        self,
        target_sample_rate: int = settings.TARGET_SAMPLE_RATE,
        target_peak_dbfs: float = settings.TARGET_PEAK_DBFS,
        vad_energy_threshold_dbfs: float = settings.VAD_ENERGY_THRESHOLD_DBFS,
        max_duration_s: float = settings.MAX_DURATION_S,
    ) -> None:
        self.target_sample_rate = target_sample_rate
        self.target_peak_dbfs = target_peak_dbfs
        self.vad_energy_threshold_dbfs = vad_energy_threshold_dbfs
        self.max_duration_s = max_duration_s

    def process(self, audio_input: Union[bytes, str, Path]) -> PreprocessedAudio:
        """Execute canonical preprocessing on audio bytes or file path.
        
        Steps:
        1. Read & decode audio to float32
        2. Convert multi-channel to mono
        3. Resample to target_sample_rate (16000 Hz)
        4. Trim leading/trailing silence using VAD
        5. Peak-normalize to target_peak_dbfs (-3 dBFS)
        6. Validate duration against max_duration_s
        7. Compute SHA-256 over float32 PCM bytes
        8. Return PreprocessedAudio contract
        """
        if isinstance(audio_input, (str, Path)):
            path = Path(audio_input)
            if not path.is_file():
                raise AudioPreprocessingError(f"Audio file not found: {path}")
            raw_bytes = path.read_bytes()
        elif isinstance(audio_input, bytes):
            raw_bytes = audio_input
        else:
            raise AudioPreprocessingError(f"Unsupported audio input type: {type(audio_input)}")

        # 1. Decode
        audio_array, orig_sr = load_audio_from_bytes(raw_bytes)

        # 2. Mono conversion
        mono_audio = convert_to_mono(audio_array)

        # 3. Resample to 16 kHz
        resampled_audio = resample_audio(mono_audio, orig_sr, self.target_sample_rate)

        # 4. Silence trimming
        trimmed_audio = trim_silence(
            resampled_audio,
            self.target_sample_rate,
            threshold_dbfs=self.vad_energy_threshold_dbfs,
        )

        # Handle all-silence edge case
        if len(trimmed_audio) == 0:
            # If input was pure silence, retain empty float32 array
            final_audio = np.empty(0, dtype=np.float32)
            peak_dbfs = -100.0
        else:
            # 5. Peak normalize
            final_audio, peak_dbfs = peak_normalize(trimmed_audio, self.target_peak_dbfs)

        # 6. Duration
        duration_s = float(len(final_audio)) / float(self.target_sample_rate)
        if duration_s > self.max_duration_s:
            raise AudioPreprocessingError(
                f"Audio duration {duration_s:.1f}s exceeds maximum allowed duration {self.max_duration_s:.1f}s"
            )

        # 7. Deterministic SHA256
        sha256_digest = compute_audio_sha256(final_audio)

        # 8. Construct PreprocessedAudio contract
        return PreprocessedAudio(
            sample_rate_hz=self.target_sample_rate,
            channels=1,
            duration_s=round(duration_s, 4),
            audio_array=final_audio,
            sha256=sha256_digest,
            peak_dbfs=round(peak_dbfs, 2),
        )
