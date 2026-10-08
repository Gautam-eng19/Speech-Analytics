"""Unit and contract tests for MFCC Feature Extraction (TASK-031).

Covers:
1.  Valid synthetic audio — basic extraction succeeds.
2.  Correct output shape — (T, C) = frames × coefficients.
3.  Correct time-axis behaviour — monotonic, uniform spacing, origin at 0.
4.  Deterministic repeated execution — bit-identical results for identical inputs.
5.  Expected configuration propagation — config snapshot preserved in result.
6.  Invalid sample rate — raises ValueError with informative message.
7.  Invalid / non-mono input — raises ValueError.
8.  Empty audio — raises ValueError.
9.  Invalid configuration values — MFCCConfig raises ValueError.
10. Finite numerical output — no NaN / Inf in mfcc_matrix.
11. Canonical audio container support — PreprocessedAudio duck-typing.
12. Summary dict — correct keys and list lengths.
13. FeatureBundle dict — correct keys.
14. Convenience function extract_mfcc — produces same result as MFCCExtractor.

Tests MUST NOT download external models or require network access.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pytest

from app.services.features.mfcc import (
    MFCCConfig,
    MFCCExtractionResult,
    MFCCExtractor,
    extract_mfcc,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sine(
    frequency_hz: float = 220.0,
    duration_s: float = 1.0,
    sample_rate: int = 16000,
    amplitude: float = 0.8,
) -> np.ndarray:
    """Synthesize a float32 mono sine wave at the given frequency."""
    n = int(duration_s * sample_rate)
    t = np.linspace(0.0, duration_s, n, endpoint=False, dtype=np.float32)
    return (amplitude * np.sin(2.0 * np.pi * frequency_hz * t)).astype(np.float32)


def _make_noise(n_samples: int = 16000, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.uniform(-0.5, 0.5, n_samples).astype(np.float32)


# ---------------------------------------------------------------------------
# 1. Valid synthetic audio — basic extraction succeeds
# ---------------------------------------------------------------------------

def test_basic_extraction_succeeds() -> None:
    """Test 1: extract_mfcc succeeds on valid mono float32 audio."""
    audio = _make_sine()
    result = extract_mfcc(audio, sample_rate=16000)
    assert isinstance(result, MFCCExtractionResult)


# ---------------------------------------------------------------------------
# 2. Correct output shape — (T, C) = frames × coefficients
# ---------------------------------------------------------------------------

def test_output_shape_frames_x_coefficients() -> None:
    """Test 2: mfcc_matrix is (n_frames, n_mfcc) — frames × coefficients."""
    sr = 16000
    n_mfcc = 13
    config = MFCCConfig(sample_rate=sr, n_mfcc=n_mfcc)
    audio = _make_sine(duration_s=1.0, sample_rate=sr)

    result = extract_mfcc(audio, config=config)

    assert result.mfcc_matrix.ndim == 2, "mfcc_matrix must be 2D"
    n_frames, n_coeffs = result.mfcc_matrix.shape
    assert n_coeffs == n_mfcc, (
        f"Expected {n_mfcc} coefficients (columns), got {n_coeffs}"
    )
    assert n_frames > 0, "Expected at least one frame"
    # times_s and mfcc_matrix must have the same number of rows
    assert len(result.times_s) == n_frames


def test_output_shape_reflects_n_mfcc_config() -> None:
    """Test 2 (variant): changing n_mfcc changes the number of columns."""
    sr = 16000
    audio = _make_sine(duration_s=0.5, sample_rate=sr)

    for n_mfcc in (6, 13, 20):
        config = MFCCConfig(sample_rate=sr, n_mfcc=n_mfcc, n_mels=40)
        result = extract_mfcc(audio, config=config)
        assert result.mfcc_matrix.shape[1] == n_mfcc, (
            f"n_mfcc={n_mfcc}: expected {n_mfcc} columns, "
            f"got {result.mfcc_matrix.shape[1]}"
        )
        assert result.n_coefficients == n_mfcc


# ---------------------------------------------------------------------------
# 3. Correct time-axis behaviour
# ---------------------------------------------------------------------------

def test_time_axis_monotonic_uniform_origin() -> None:
    """Test 3: times_s is strictly monotonic, uniformly spaced, starts at 0."""
    sr = 16000
    hop = 160
    config = MFCCConfig(sample_rate=sr, hop_length=hop)
    audio = _make_sine(duration_s=0.5, sample_rate=sr)

    result = extract_mfcc(audio, config=config)
    ts = result.times_s

    assert ts[0] == 0.0, f"First timestamp should be 0.0, got {ts[0]}"
    assert np.all(np.diff(ts) > 0), "Timestamps must be strictly monotonically increasing"

    expected_step = hop / sr  # 0.01 s
    diffs = np.diff(ts)
    assert np.allclose(diffs, expected_step, atol=1e-6), (
        f"Timestamp spacing should be {expected_step:.4f} s; got min={diffs.min():.6f}, "
        f"max={diffs.max():.6f}"
    )


def test_time_axis_length_matches_mfcc_rows() -> None:
    """Test 3 (variant): len(times_s) == number of rows in mfcc_matrix."""
    audio = _make_sine(duration_s=0.8)
    result = extract_mfcc(audio, sample_rate=16000)
    assert len(result.times_s) == result.mfcc_matrix.shape[0]
    assert result.n_frames == result.mfcc_matrix.shape[0]


# ---------------------------------------------------------------------------
# 4. Deterministic repeated execution
# ---------------------------------------------------------------------------

def test_deterministic_repeated_extraction() -> None:
    """Test 4: same input + same config → bit-identical results (ARCHITECTURE.md §2)."""
    sr = 16000
    audio = _make_sine(frequency_hz=200.0, duration_s=0.5, sample_rate=sr)
    config = MFCCConfig(sample_rate=sr)

    extractor = MFCCExtractor(config=config)
    r1 = extractor.extract(audio)
    r2 = extractor.extract(audio)

    assert np.array_equal(r1.times_s, r2.times_s), "times_s must be bit-identical"
    assert np.array_equal(r1.mfcc_matrix, r2.mfcc_matrix), (
        "mfcc_matrix must be bit-identical for repeated calls with the same input"
    )


def test_deterministic_across_extractor_instances() -> None:
    """Test 4 (variant): two separate MFCCExtractor instances yield identical output."""
    sr = 16000
    audio = _make_noise(n_samples=sr)
    config = MFCCConfig(sample_rate=sr, n_mfcc=13)

    r1 = MFCCExtractor(config=config).extract(audio)
    r2 = MFCCExtractor(config=config).extract(audio)

    assert np.array_equal(r1.mfcc_matrix, r2.mfcc_matrix)


# ---------------------------------------------------------------------------
# 5. Configuration propagation
# ---------------------------------------------------------------------------

def test_config_propagated_to_result() -> None:
    """Test 5: config snapshot is preserved in the result object."""
    sr = 16000
    n_mfcc = 10
    n_fft = 512
    hop = 160
    n_mels = 32
    fmin = 50.0
    fmax = 7000.0
    lifter = 0

    config = MFCCConfig(
        sample_rate=sr,
        n_mfcc=n_mfcc,
        n_fft=n_fft,
        hop_length=hop,
        n_mels=n_mels,
        fmin=fmin,
        fmax=fmax,
        lifter=lifter,
    )
    audio = _make_sine(duration_s=0.5, sample_rate=sr)
    result = extract_mfcc(audio, config=config)

    assert result.config is config
    assert result.config.sample_rate == sr
    assert result.config.n_mfcc == n_mfcc
    assert result.config.n_fft == n_fft
    assert result.config.hop_length == hop
    assert result.config.n_mels == n_mels
    assert result.config.fmin == fmin
    assert result.config.fmax == fmax


# ---------------------------------------------------------------------------
# 6. Invalid sample rate
# ---------------------------------------------------------------------------

def test_mismatched_sample_rate_raises_value_error() -> None:
    """Test 6: audio sample rate != config.sample_rate raises ValueError."""
    config = MFCCConfig(sample_rate=16000)
    audio = _make_sine(duration_s=0.3, sample_rate=16000)  # audio is fine

    # Pass mismatched sample_rate argument
    with pytest.raises(ValueError, match="sample rate"):
        MFCCExtractor(config=config).extract(audio, sample_rate=22050)


def test_container_sample_rate_conflict_raises_value_error() -> None:
    """Test 6 (variant): container.sample_rate_hz conflicts with explicit argument."""

    @dataclass
    class MockAudio:
        audio_array: np.ndarray
        sample_rate_hz: int

    mock = MockAudio(audio_array=np.zeros(1600, dtype=np.float32), sample_rate_hz=16000)
    config = MFCCConfig(sample_rate=16000)

    with pytest.raises(ValueError, match="Sample rate conflict"):
        MFCCExtractor(config=config).extract(mock, sample_rate=22050)


# ---------------------------------------------------------------------------
# 7. Invalid / non-mono input
# ---------------------------------------------------------------------------

def test_multichannel_array_raises_value_error() -> None:
    """Test 7: 2D multichannel array raises ValueError with 'mono' in message."""
    stereo = np.zeros((2, 16000), dtype=np.float32)
    with pytest.raises(ValueError, match="mono"):
        extract_mfcc(stereo, sample_rate=16000)


def test_2d_multichannel_raises_value_error() -> None:
    """Test 7 (variant): (N, 2) shape also raises ValueError."""
    stereo = np.zeros((16000, 2), dtype=np.float32)
    with pytest.raises(ValueError, match="mono"):
        extract_mfcc(stereo, sample_rate=16000)


def test_squeezable_2d_mono_is_accepted() -> None:
    """Test 7 (variant): (1, N) or (N, 1) degenerate 2D shapes are accepted."""
    audio_1n = np.zeros((1, 8000), dtype=np.float32) + 0.1
    result = extract_mfcc(audio_1n, sample_rate=16000)
    assert result.n_frames > 0

    audio_n1 = np.zeros((8000, 1), dtype=np.float32) + 0.1
    result2 = extract_mfcc(audio_n1, sample_rate=16000)
    assert result2.n_frames > 0


def test_non_array_type_raises_type_error() -> None:
    """Test 7 (variant): non-array type raises TypeError."""
    with pytest.raises(TypeError, match="Expected audio to be a numpy.ndarray"):
        extract_mfcc("not_audio")  # type: ignore


# ---------------------------------------------------------------------------
# 8. Empty audio
# ---------------------------------------------------------------------------

def test_empty_array_raises_value_error() -> None:
    """Test 8: empty 1D array raises ValueError."""
    with pytest.raises(ValueError, match="non-empty"):
        extract_mfcc(np.array([], dtype=np.float32), sample_rate=16000)


# ---------------------------------------------------------------------------
# 9. Invalid configuration values
# ---------------------------------------------------------------------------

def test_config_invalid_sample_rate() -> None:
    """Test 9a: non-positive sample_rate."""
    with pytest.raises(ValueError, match="sample_rate"):
        MFCCConfig(sample_rate=0)

    with pytest.raises(ValueError, match="sample_rate"):
        MFCCConfig(sample_rate=-8000)


def test_config_invalid_n_mfcc() -> None:
    """Test 9b: non-positive n_mfcc."""
    with pytest.raises(ValueError, match="n_mfcc"):
        MFCCConfig(n_mfcc=0)


def test_config_invalid_n_fft() -> None:
    """Test 9c: non-positive n_fft."""
    with pytest.raises(ValueError, match="n_fft"):
        MFCCConfig(n_fft=-1)


def test_config_invalid_hop_length() -> None:
    """Test 9d: non-positive hop_length."""
    with pytest.raises(ValueError, match="hop_length"):
        MFCCConfig(hop_length=0)


def test_config_invalid_n_mels() -> None:
    """Test 9e: non-positive n_mels."""
    with pytest.raises(ValueError, match="n_mels"):
        MFCCConfig(n_mels=0)


def test_config_fmax_le_fmin() -> None:
    """Test 9f: fmax <= fmin raises ValueError."""
    with pytest.raises(ValueError, match="fmax"):
        MFCCConfig(fmin=3000.0, fmax=2000.0)

    with pytest.raises(ValueError, match="fmax"):
        MFCCConfig(fmin=4000.0, fmax=4000.0)


def test_config_fmin_negative() -> None:
    """Test 9g: negative fmin raises ValueError."""
    with pytest.raises(ValueError, match="fmin"):
        MFCCConfig(fmin=-100.0)


def test_config_fmax_exceeds_nyquist() -> None:
    """Test 9h: fmax > Nyquist raises ValueError."""
    with pytest.raises(ValueError, match="Nyquist"):
        MFCCConfig(sample_rate=16000, fmax=9000.0)  # Nyquist = 8000


def test_config_n_mfcc_exceeds_n_mels() -> None:
    """Test 9i: n_mfcc > n_mels raises ValueError."""
    with pytest.raises(ValueError, match="n_mfcc"):
        MFCCConfig(n_mfcc=50, n_mels=40)


def test_config_lifter_negative() -> None:
    """Test 9j: negative lifter raises ValueError."""
    with pytest.raises(ValueError, match="lifter"):
        MFCCConfig(lifter=-1)


def test_config_invalid_norm() -> None:
    """Test 9k: unrecognized norm value raises ValueError."""
    with pytest.raises(ValueError, match="norm"):
        MFCCConfig(norm="invalid_norm")


# ---------------------------------------------------------------------------
# 10. Finite numerical output
# ---------------------------------------------------------------------------

def test_output_is_finite() -> None:
    """Test 10: mfcc_matrix and times_s contain no NaN or Inf values."""
    audio = _make_sine(duration_s=1.0)
    result = extract_mfcc(audio, sample_rate=16000)

    assert np.all(np.isfinite(result.mfcc_matrix)), (
        "mfcc_matrix must not contain NaN or Inf"
    )
    assert np.all(np.isfinite(result.times_s)), (
        "times_s must not contain NaN or Inf"
    )


def test_non_finite_audio_raises_value_error() -> None:
    """Test 10 (variant): audio with NaN raises ValueError."""
    audio = _make_sine(duration_s=0.5)
    audio[100] = float("nan")
    with pytest.raises(ValueError, match="non-finite"):
        extract_mfcc(audio, sample_rate=16000)

    audio2 = _make_sine(duration_s=0.5)
    audio2[50] = float("inf")
    with pytest.raises(ValueError, match="non-finite"):
        extract_mfcc(audio2, sample_rate=16000)


# ---------------------------------------------------------------------------
# 11. Canonical audio container support
# ---------------------------------------------------------------------------

def test_canonical_container_input() -> None:
    """Test 11: duck-typed PreprocessedAudio container is accepted and produces same result."""

    @dataclass
    class MockPreprocessedAudio:
        audio_array: np.ndarray
        sample_rate_hz: int
        duration_s: float
        channels: int = 1

    sr = 16000
    raw = _make_sine(frequency_hz=180.0, duration_s=0.5, sample_rate=sr)
    container = MockPreprocessedAudio(
        audio_array=raw, sample_rate_hz=sr, duration_s=0.5
    )

    res_raw = extract_mfcc(raw, sample_rate=sr)
    res_container = extract_mfcc(container)

    assert np.array_equal(res_raw.times_s, res_container.times_s)
    assert np.array_equal(res_raw.mfcc_matrix, res_container.mfcc_matrix)


# ---------------------------------------------------------------------------
# 12. Summary dict
# ---------------------------------------------------------------------------

def test_summary_dict_keys_and_lengths() -> None:
    """Test 12: to_summary_dict returns correct keys and lists of length n_mfcc."""
    n_mfcc = 13
    config = MFCCConfig(sample_rate=16000, n_mfcc=n_mfcc)
    audio = _make_sine(duration_s=0.5)
    result = extract_mfcc(audio, config=config)

    summary = result.to_summary_dict()
    assert "mean_13" in summary
    assert "std_13" in summary
    assert len(summary["mean_13"]) == n_mfcc
    assert len(summary["std_13"]) == n_mfcc
    # All values must be Python floats (JSON-serializable)
    assert all(isinstance(v, float) for v in summary["mean_13"])
    assert all(isinstance(v, float) for v in summary["std_13"])


def test_summary_dict_std_non_negative() -> None:
    """Test 12 (variant): standard deviations are non-negative."""
    audio = _make_sine(duration_s=1.0)
    result = extract_mfcc(audio, sample_rate=16000)
    summary = result.to_summary_dict()
    assert all(v >= 0.0 for v in summary["std_13"])


# ---------------------------------------------------------------------------
# 13. FeatureBundle dict
# ---------------------------------------------------------------------------

def test_feature_bundle_dict_keys() -> None:
    """Test 13: to_feature_bundle_dict returns expected keys for FeatureBundle."""
    audio = _make_sine(duration_s=0.5)
    result = extract_mfcc(audio, sample_rate=16000)

    bundle = result.to_feature_bundle_dict()
    assert "mfcc_times_s" in bundle
    assert "mfcc_matrix" in bundle

    # Values are independent copies (not references to internal arrays)
    assert bundle["mfcc_matrix"] is not result.mfcc_matrix
    assert bundle["mfcc_times_s"] is not result.times_s

    # Shapes and content must match
    assert np.array_equal(bundle["mfcc_times_s"], result.times_s)
    assert np.array_equal(bundle["mfcc_matrix"], result.mfcc_matrix)


# ---------------------------------------------------------------------------
# 14. Convenience function extract_mfcc == MFCCExtractor.extract
# ---------------------------------------------------------------------------

def test_convenience_function_matches_extractor() -> None:
    """Test 14: extract_mfcc produces identical results to MFCCExtractor.extract."""
    sr = 16000
    config = MFCCConfig(sample_rate=sr)
    audio = _make_noise(n_samples=sr)

    res_func = extract_mfcc(audio, config=config, sample_rate=sr)
    res_class = MFCCExtractor(config=config).extract(audio, sample_rate=sr)

    assert np.array_equal(res_func.times_s, res_class.times_s)
    assert np.array_equal(res_func.mfcc_matrix, res_class.mfcc_matrix)


# ---------------------------------------------------------------------------
# Additional: matrix dtype and frame count
# ---------------------------------------------------------------------------

def test_mfcc_matrix_dtype_is_float32() -> None:
    """mfcc_matrix dtype must be float32 (matches FeatureBundle convention)."""
    audio = _make_sine(duration_s=0.5)
    result = extract_mfcc(audio, sample_rate=16000)
    assert result.mfcc_matrix.dtype == np.float32


def test_times_s_dtype_is_float64() -> None:
    """times_s dtype must be float64 for timestamp precision."""
    audio = _make_sine(duration_s=0.5)
    result = extract_mfcc(audio, sample_rate=16000)
    assert result.times_s.dtype == np.float64


def test_silence_produces_finite_mfcc() -> None:
    """Silent audio (all zeros) must still produce finite MFCC coefficients."""
    sr = 16000
    audio = np.zeros(sr, dtype=np.float32)
    result = extract_mfcc(audio, sample_rate=sr)
    # Librosa computes log(eps) for silent audio; result must still be finite
    assert np.all(np.isfinite(result.mfcc_matrix))
    assert result.n_frames > 0
