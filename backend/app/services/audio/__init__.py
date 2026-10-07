"""Audio service package exports (ARCHITECTURE.md §7.1)."""
from .preprocessor import (
    AudioPreprocessingError,
    AudioPreprocessor,
    compute_audio_sha256,
    convert_to_mono,
    load_audio_from_bytes,
    peak_normalize,
    resample_audio,
    trim_silence,
)

__all__ = [
    "AudioPreprocessingError",
    "AudioPreprocessor",
    "compute_audio_sha256",
    "convert_to_mono",
    "load_audio_from_bytes",
    "peak_normalize",
    "resample_audio",
    "trim_silence",
]
