"""Unit and contract tests for Fundamental Frequency (Pitch/F0) Feature Extraction (TASK-030).

Covers:
- Deterministic repeated extraction
- Known synthetic voiced signals (accuracy & low variance)
- Silent and unvoiced signals (explicit NaN & unvoiced flags)
- Strict timestamp ordering and uniform spacing
- Output structure and compatibility with F0Timeline response schema
- Range containment (all voiced F0 values strictly within [fmin, fmax])
- Explicit unvoiced representation without fake pitch interpolation
- Canonical audio container support (PreprocessedAudio duck-typing)
- Comprehensive validation of invalid inputs and invalid configurations
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pytest
from app.schemas.response import F0Timeline
from app.services.features.f0 import (
    F0Config,
    F0ExtractionResult,
    F0Extractor,
    extract_f0,
)


def _generate_sine(
    frequency_hz: float,
    duration_s: float = 1.0,
    sample_rate: int = 16000,
    amplitude: float = 0.8,
) -> np.ndarray:
    """Helper to synthesize pure tone float32 PCM audio."""
    n_samples = int(duration_s * sample_rate)
    t = np.linspace(0.0, duration_s, n_samples, endpoint=False, dtype=np.float32)
    return (amplitude * np.sin(2.0 * np.pi * frequency_hz * t)).astype(np.float32)


def test_deterministic_repeated_extraction() -> None:
    """Verify same input + same configuration produces bit-identical outputs (ARCHITECTURE.md §2)."""
    sr = 16000
    # Create multi-frequency composite signal
    audio = _generate_sine(180.0, duration_s=0.5, sample_rate=sr) + 0.3 * _generate_sine(
        360.0, duration_s=0.5, sample_rate=sr
    )
    config = F0Config(sample_rate=sr, fmin=75.0, fmax=500.0, hop_length=160)

    extractor = F0Extractor(config=config)
    res1 = extractor.extract(audio)
    res2 = extractor.extract(audio)

    # Identical timestamps
    assert np.array_equal(res1.times_s, res2.times_s)
    # Identical voicing decisions
    assert np.array_equal(res1.voiced, res2.voiced)
    # Identical voicing probabilities
    assert np.allclose(res1.voiced_prob, res2.voiced_prob, atol=1e-12)
    # Identical NaN locations
    assert np.array_equal(np.isnan(res1.values_hz), np.isnan(res2.values_hz))
    # Identical pitch values for voiced frames
    assert np.allclose(
        res1.values_hz[res1.voiced],
        res2.values_hz[res2.voiced],
        atol=1e-12,
    )


def test_known_synthetic_voiced_signal_220hz() -> None:
    """Verify accurate extraction of known 220 Hz fundamental frequency within 1% margin."""
    sr = 16000
    freq_target = 220.0
    audio = _generate_sine(freq_target, duration_s=1.0, sample_rate=sr)

    res = extract_f0(audio, sample_rate=sr)

    # The majority of frames should be detected as voiced
    assert res.voiced_ratio >= 0.85
    voiced_hz = res.voiced_values_hz
    assert len(voiced_hz) > 0

    # Mean frequency should be within 1 Hz of 220 Hz
    mean_f0 = float(np.mean(voiced_hz))
    assert abs(mean_f0 - freq_target) < 1.0

    # Stable tone should exhibit minimal standard deviation
    std_f0 = float(np.std(voiced_hz))
    assert std_f0 < 2.0


def test_known_synthetic_voiced_signal_130hz() -> None:
    """Verify extraction of typical low male pitch (130 Hz)."""
    sr = 16000
    freq_target = 130.0
    audio = _generate_sine(freq_target, duration_s=1.0, sample_rate=sr)

    res = extract_f0(audio, sample_rate=sr)
    assert res.voiced_ratio >= 0.85
    voiced_hz = res.voiced_values_hz
    assert len(voiced_hz) > 0
    mean_f0 = float(np.mean(voiced_hz))
    assert abs(mean_f0 - freq_target) < 1.5


def test_known_synthetic_pitch_shift() -> None:
    """Verify pitch tracking over a step change: 160 Hz -> 320 Hz."""
    sr = 16000
    part1 = _generate_sine(160.0, duration_s=0.5, sample_rate=sr)
    part2 = _generate_sine(320.0, duration_s=0.5, sample_rate=sr)
    audio = np.concatenate([part1, part2])

    res = extract_f0(audio, sample_rate=sr)

    # Frames well within the first half (e.g. 0.15s to 0.35s)
    mask_first_half = (res.times_s >= 0.15) & (res.times_s <= 0.35) & res.voiced
    assert np.any(mask_first_half)
    mean_first = float(np.mean(res.values_hz[mask_first_half]))
    assert abs(mean_first - 160.0) < 2.0

    # Frames well within the second half (e.g. 0.65s to 0.85s)
    mask_second_half = (res.times_s >= 0.65) & (res.times_s <= 0.85) & res.voiced
    assert np.any(mask_second_half)
    mean_second = float(np.mean(res.values_hz[mask_second_half]))
    assert abs(mean_second - 320.0) < 2.0


def test_silent_signal() -> None:
    """Verify silent audio produces 100% unvoiced frames with NaN values and zero voiced ratio."""
    sr = 16000
    audio = np.zeros(sr, dtype=np.float32)  # 1.0 s silence

    res = extract_f0(audio, sample_rate=sr)

    assert res.total_frames > 0
    assert res.voiced_count == 0
    assert res.unvoiced_count == res.total_frames
    assert res.voiced_ratio == 0.0
    assert np.all(~res.voiced)
    assert np.all(np.isnan(res.values_hz))
    assert len(res.voiced_values_hz) == 0

    # Ensure to_timeline_dict maps all unvoiced frames to None
    tl = res.to_timeline_dict()
    assert all(v is None for v in tl["values_hz"])
    assert all(not b for b in tl["voiced"])


def test_unvoiced_noise_signal() -> None:
    """Verify white noise with no periodicity is overwhelmingly unvoiced."""
    rng = np.random.default_rng(42)
    sr = 16000
    noise = (rng.uniform(-0.1, 0.1, sr)).astype(np.float32)

    res = extract_f0(noise, sample_rate=sr)
    # White noise has no harmonic pitch; should have low voicing ratio (< 10%)
    assert res.voiced_ratio < 0.10


def test_timestamp_ordering_and_spacing() -> None:
    """Verify timestamps are strictly monotonic and uniformly spaced at hop_length/sr."""
    sr = 16000
    hop = 160
    audio = _generate_sine(200.0, duration_s=0.6, sample_rate=sr)
    config = F0Config(sample_rate=sr, hop_length=hop)

    res = extract_f0(audio, config=config)

    # Monotonicity
    assert np.all(np.diff(res.times_s) > 0)
    # Origin
    assert res.times_s[0] == 0.0
    # Uniform frame step = 160 / 16000 = 0.01s (10 ms)
    expected_step = hop / sr
    diffs = np.diff(res.times_s)
    assert np.allclose(diffs, expected_step, atol=1e-6)

    # Length consistency
    assert len(res.times_s) == len(res.values_hz)
    assert len(res.times_s) == len(res.voiced)
    assert len(res.times_s) == len(res.voiced_prob)


def test_expected_output_structure_and_schema_validation() -> None:
    """Verify output data structures and compatibility with API F0Timeline Pydantic model."""
    audio = _generate_sine(220.0, duration_s=0.5, sample_rate=16000)
    res = extract_f0(audio)

    # Types
    assert isinstance(res, F0ExtractionResult)
    assert isinstance(res.times_s, np.ndarray)
    assert isinstance(res.values_hz, np.ndarray)
    assert isinstance(res.voiced, np.ndarray)
    assert isinstance(res.voiced_prob, np.ndarray)
    assert isinstance(res.config, F0Config)

    # FeatureBundle dictionary export
    bundle = res.to_feature_bundle_dict()
    assert "f0_times_s" in bundle
    assert "f0_values_hz" in bundle
    assert "f0_voiced" in bundle
    assert "f0_voiced_prob" in bundle

    # Timeline serialization
    tl_dict = res.to_timeline_dict()
    assert "times_s" in tl_dict
    assert "values_hz" in tl_dict
    assert "voiced" in tl_dict

    # Must pass Pydantic contract validation without errors
    pydantic_model = F0Timeline.model_validate(tl_dict)
    assert len(pydantic_model.times_s) == res.total_frames
    assert len(pydantic_model.values_hz) == res.total_frames
    assert len(pydantic_model.voiced) == res.total_frames


def test_f0_values_within_configured_range() -> None:
    """Verify all voiced F0 values remain bounded within [fmin, fmax]."""
    fmin = 100.0
    fmax = 400.0
    audio = _generate_sine(250.0, duration_s=0.5, sample_rate=16000)
    config = F0Config(fmin=fmin, fmax=fmax)

    res = extract_f0(audio, config=config)

    voiced_hz = res.voiced_values_hz
    assert len(voiced_hz) > 0
    assert np.all(voiced_hz >= fmin)
    assert np.all(voiced_hz <= fmax)


def test_explicit_unvoiced_representation_without_fake_pitch() -> None:
    """Verify unvoiced segments (e.g. pauses) are explicitly NaN and never interpolated."""
    sr = 16000
    tone1 = _generate_sine(220.0, duration_s=0.3, sample_rate=sr)
    silence = np.zeros(int(0.4 * sr), dtype=np.float32)
    tone2 = _generate_sine(220.0, duration_s=0.3, sample_rate=sr)
    audio = np.concatenate([tone1, silence, tone2])

    res = extract_f0(audio, sample_rate=sr)

    # In the middle silence window (0.4s to 0.6s)
    silence_mask = (res.times_s >= 0.40) & (res.times_s <= 0.60)
    assert np.any(silence_mask)
    # Must NOT have fake pitch (e.g. 0 Hz or interpolated 220 Hz)
    assert np.all(~res.voiced[silence_mask])
    assert np.all(np.isnan(res.values_hz[silence_mask]))


def test_canonical_audio_container_input() -> None:
    """Verify duck-typed support for PreprocessedAudio objects."""

    @dataclass
    class MockPreprocessedAudio:
        audio_array: np.ndarray
        sample_rate_hz: int
        duration_s: float
        channels: int = 1

    sr = 16000
    raw = _generate_sine(220.0, duration_s=0.4, sample_rate=sr)
    container = MockPreprocessedAudio(
        audio_array=raw,
        sample_rate_hz=sr,
        duration_s=0.4,
    )

    res_raw = extract_f0(raw, sample_rate=sr)
    res_container = extract_f0(container)

    assert np.array_equal(res_raw.times_s, res_container.times_s)
    assert np.array_equal(res_raw.voiced, res_container.voiced)
    assert np.allclose(res_raw.voiced_prob, res_container.voiced_prob, atol=1e-12)


def test_invalid_audio_inputs() -> None:
    """Verify rejection of invalid, empty, or multi-channel audio."""
    # Empty
    with pytest.raises(ValueError, match="non-empty"):
        extract_f0(np.array([], dtype=np.float32))

    # Multichannel (2 x N)
    with pytest.raises(ValueError, match="mono"):
        extract_f0(np.zeros((2, 1600), dtype=np.float32))

    # Non-finite values
    bad_audio = np.ones(1600, dtype=np.float32)
    bad_audio[10] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        extract_f0(bad_audio)

    bad_inf = np.ones(1600, dtype=np.float32)
    bad_inf[10] = np.inf
    with pytest.raises(ValueError, match="non-finite"):
        extract_f0(bad_inf)

    # Wrong type
    with pytest.raises(TypeError, match="Expected audio to be a numpy.ndarray"):
        extract_f0("not_audio")  # type: ignore


def test_invalid_configurations() -> None:
    """Verify validation of configuration parameter constraints."""
    with pytest.raises(ValueError, match="sample_rate"):
        F0Config(sample_rate=0)

    with pytest.raises(ValueError, match="frame_length"):
        F0Config(frame_length=-10)

    with pytest.raises(ValueError, match="hop_length"):
        F0Config(hop_length=0)

    with pytest.raises(ValueError, match="fmin"):
        F0Config(fmin=-5.0)

    with pytest.raises(ValueError, match="fmax"):
        F0Config(fmin=300.0, fmax=200.0)

    with pytest.raises(ValueError, match="voiced_prob_threshold"):
        F0Config(voiced_prob_threshold=-0.1)

    with pytest.raises(ValueError, match="voiced_prob_threshold"):
        F0Config(voiced_prob_threshold=1.5)


def test_sample_rate_mismatch_error() -> None:
    """Verify error raised on explicit sample rate conflict."""
    @dataclass
    class MockAudio:
        audio_array: np.ndarray
        sample_rate_hz: int

    mock = MockAudio(audio_array=np.zeros(1600, dtype=np.float32), sample_rate_hz=16000)

    # Argument contradicts container attribute
    with pytest.raises(ValueError, match="Sample rate conflict"):
        extract_f0(mock, sample_rate=22050)

    # Config contradicts audio sample rate
    config = F0Config(sample_rate=16000)
    with pytest.raises(ValueError, match="Audio sample rate .* does not match"):
        F0Extractor(config=config).extract(
            np.zeros(1600, dtype=np.float32),
            sample_rate=22050,
        )
