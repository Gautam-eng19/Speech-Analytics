"""Unit tests for audio preprocessing service (TASK-013)."""
from __future__ import annotations

import io
import math
import numpy as np
import pytest
import scipy.io.wavfile as wav

from app.schemas.contracts import PreprocessedAudio
from app.services.audio import (
    AudioPreprocessingError,
    AudioPreprocessor,
    compute_audio_sha256,
    convert_to_mono,
    load_audio_from_bytes,
    peak_normalize,
    resample_audio,
    trim_silence,
)


def make_sine_wav_bytes(
    freq_hz: float = 440.0,
    duration_s: float = 1.0,
    sample_rate: int = 44100,
    amplitude: float = 0.5,
    channels: int = 1,
    leading_silence_s: float = 0.0,
    trailing_silence_s: float = 0.0,
) -> bytes:
    """Helper to generate in-memory PCM 16-bit WAV bytes."""
    lead_samples = int(leading_silence_s * sample_rate)
    trail_samples = int(trailing_silence_s * sample_rate)
    tone_samples = int(duration_s * sample_rate)

    t = np.linspace(0, duration_s, tone_samples, endpoint=False, dtype=np.float32)
    tone = amplitude * np.sin(2 * np.pi * freq_hz * t)

    lead = np.zeros(lead_samples, dtype=np.float32)
    trail = np.zeros(trail_samples, dtype=np.float32)
    full_mono = np.concatenate([lead, tone, trail])

    if channels == 1:
        data = (full_mono * 32767.0).astype(np.int16)
    elif channels == 2:
        # Stereo: duplicate to 2 channels
        stereo = np.column_stack([full_mono, full_mono])
        data = (stereo * 32767.0).astype(np.int16)
    else:
        multi = np.tile(full_mono[:, None], (1, channels))
        data = (multi * 32767.0).astype(np.int16)

    buffer = io.BytesIO()
    wav.write(buffer, sample_rate, data)
    return buffer.getvalue()


def make_sine_mp3_bytes(
    freq_hz: float = 440.0,
    duration_s: float = 1.0,
    sample_rate: int = 44100,
    amplitude: float = 0.5,
) -> bytes:
    """Helper to generate real in-memory MP3 bytes using PyAV."""
    import av

    buffer = io.BytesIO()
    container = av.open(buffer, mode="w", format="mp3")
    stream = container.add_stream("mp3", rate=sample_rate)

    t = np.linspace(0, duration_s, int(duration_s * sample_rate), endpoint=False, dtype=np.float32)
    tone = (amplitude * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)

    frame = av.AudioFrame.from_ndarray(tone.reshape(1, -1), format="fltp", layout="mono")
    frame.sample_rate = sample_rate

    for packet in stream.encode(frame):
        container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)

    container.close()
    return buffer.getvalue()


def test_wav_input_decoding():
    """Verify loading WAV bytes into float32 array with correct sample rate."""
    wav_bytes = make_sine_wav_bytes(freq_hz=440.0, duration_s=0.5, sample_rate=22050, amplitude=0.8)
    audio, sr = load_audio_from_bytes(wav_bytes)

    assert sr == 22050
    assert audio.dtype == np.float32
    assert len(audio) == int(0.5 * 22050)
    assert np.max(np.abs(audio)) > 0.7


def test_mp3_input_decoding():
    """Verify that real MP3 bytes are decoded and enter canonical pipeline."""
    mp3_bytes = make_sine_mp3_bytes(freq_hz=440.0, duration_s=1.0, sample_rate=44100, amplitude=0.5)

    preprocessor = AudioPreprocessor()
    res = preprocessor.process(mp3_bytes)

    assert isinstance(res, PreprocessedAudio)
    assert res.sample_rate_hz == 16000
    assert res.channels == 1
    assert res.audio_array.dtype == np.float32
    assert len(res.audio_array) > 0
    # Expected duration close to 1.0s (resampled to 16 kHz)
    assert 0.9 <= res.duration_s <= 1.1
    # Verify peak normalization: within tolerance of target -3.0 dBFS
    assert math.isclose(res.peak_dbfs, -3.0, abs_tol=0.05)
    # Check deterministic hash exists and non-empty
    assert len(res.sha256) == 64


def test_missing_av_raises_clear_error(monkeypatch):
    """Verify that if PyAV is not installed, an informative AudioPreprocessingError is raised."""
    import builtins

    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "av":
            raise ImportError("No module named 'av'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    mp3_bytes = b"ID3\x03\x00\x00\x00\x00\x00\x00fake_mp3_content"
    with pytest.raises(AudioPreprocessingError, match="PyAV \\('av'\\) is required for MP3"):
        load_audio_from_bytes(mp3_bytes)


def test_stereo_to_mono_conversion():
    """Verify stereo 2D array is averaged to 1D mono float32 array."""
    wav_bytes = make_sine_wav_bytes(duration_s=0.2, sample_rate=16000, channels=2)
    stereo, _ = load_audio_from_bytes(wav_bytes)
    assert stereo.ndim == 2
    assert stereo.shape[1] == 2

    mono = convert_to_mono(stereo)
    assert mono.ndim == 1
    assert mono.dtype == np.float32
    assert len(mono) == len(stereo)


def test_sample_rate_resampling():
    """Verify audio is resampled from 44.1 kHz to target 16 kHz."""
    wav_bytes = make_sine_wav_bytes(duration_s=1.0, sample_rate=44100)
    audio, orig_sr = load_audio_from_bytes(wav_bytes)

    resampled = resample_audio(audio, orig_sr, 16000)
    assert resampled.dtype == np.float32
    # Expect approximately 16000 samples (+/- a few filter tap samples)
    assert abs(len(resampled) - 16000) <= 10


def test_silence_trimming():
    """Verify leading and trailing silence are trimmed based on VAD energy threshold."""
    wav_bytes = make_sine_wav_bytes(
        freq_hz=440.0,
        duration_s=0.5,
        sample_rate=16000,
        leading_silence_s=0.5,
        trailing_silence_s=0.5,
    )
    audio, sr = load_audio_from_bytes(wav_bytes)
    assert len(audio) == int(1.5 * 16000)

    trimmed = trim_silence(audio, sr, threshold_dbfs=-50.0)
    # Should trim ~1.0s of silence, leaving roughly 0.5s of tone
    trimmed_duration = len(trimmed) / sr
    assert 0.45 <= trimmed_duration <= 0.55


def test_peak_normalization():
    """Verify peak normalization brings maximum amplitude to -3 dBFS."""
    wav_bytes = make_sine_wav_bytes(duration_s=0.5, amplitude=0.1)  # Quiet audio
    audio, _ = load_audio_from_bytes(wav_bytes)

    norm_audio, measured_peak_dbfs = peak_normalize(audio, target_peak_dbfs=-3.0)
    expected_peak = 10.0 ** (-3.0 / 20.0)  # ~0.7079

    assert np.isclose(np.max(np.abs(norm_audio)), expected_peak, atol=1e-3)
    assert np.isclose(measured_peak_dbfs, -3.0, atol=0.1)


def test_deterministic_repeated_preprocessing():
    """Verify repeated preprocessing runs on identical input yield bit-identical output and SHA256."""
    wav_bytes = make_sine_wav_bytes(freq_hz=500.0, duration_s=1.2, sample_rate=48000, channels=2)

    preprocessor = AudioPreprocessor()
    result1 = preprocessor.process(wav_bytes)
    result2 = preprocessor.process(wav_bytes)

    assert isinstance(result1, PreprocessedAudio)
    assert result1.sha256 == result2.sha256
    assert np.array_equal(result1.audio_array, result2.audio_array)
    assert result1.duration_s == result2.duration_s
    assert result1.peak_dbfs == result2.peak_dbfs
    assert result1.sample_rate_hz == 16000
    assert result1.channels == 1


def test_sha256_different_for_different_audio():
    """Verify distinct audio inputs produce distinct SHA-256 provenance hashes."""
    wav_1 = make_sine_wav_bytes(freq_hz=440.0, duration_s=0.5)
    wav_2 = make_sine_wav_bytes(freq_hz=880.0, duration_s=0.5)

    preprocessor = AudioPreprocessor()
    res1 = preprocessor.process(wav_1)
    res2 = preprocessor.process(wav_2)

    assert res1.sha256 != res2.sha256


def test_invalid_corrupt_input_raises_deterministic_error():
    """Verify corrupted or invalid bytes raise AudioPreprocessingError."""
    preprocessor = AudioPreprocessor()
    with pytest.raises(AudioPreprocessingError, match="Failed to decode audio"):
        preprocessor.process(b"NOT_A_VALID_WAV_HEADER_CORRUPTED_STREAM")


def test_empty_audio_raises_error():
    """Verify empty input bytes raise AudioPreprocessingError."""
    preprocessor = AudioPreprocessor()
    with pytest.raises(AudioPreprocessingError, match="empty"):
        preprocessor.process(b"")


def test_short_audio_edge_case():
    """Verify very short audio (e.g. 5ms) does not crash and processes properly."""
    wav_bytes = make_sine_wav_bytes(duration_s=0.005, sample_rate=16000)
    preprocessor = AudioPreprocessor()
    res = preprocessor.process(wav_bytes)

    assert res.sample_rate_hz == 16000
    assert res.channels == 1
    assert len(res.audio_array) > 0


def test_all_silence_audio_edge_case():
    """Verify pure silence audio does not divide by zero or crash."""
    silence = np.zeros(16000, dtype=np.int16)
    buf = io.BytesIO()
    wav.write(buf, 16000, silence)

    preprocessor = AudioPreprocessor()
    res = preprocessor.process(buf.getvalue())
    assert res.sample_rate_hz == 16000
    assert res.channels == 1
    assert len(res.audio_array) == 0
    assert res.duration_s == 0.0
