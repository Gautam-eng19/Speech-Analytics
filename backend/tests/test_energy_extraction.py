"""Unit and contract tests for energy / loudness feature extraction (TASK-032).

Covers:
- Known-amplitude signals (RMS -> dBFS accuracy, relative level differences)
- Digital silence (finite floor value, never -inf / NaN)
- Time axis (frame-centre timestamps, spacing, frame count)
- Deterministic repeated extraction and output isolation (copies)
- Compatibility with the EnergyTimeline response schema and canonical audio container
- Short audio edge cases
- Invalid inputs and invalid configurations
- Quiet-audio warning
"""
from __future__ import annotations

import logging

import numpy as np
import pytest
from app.schemas.contracts import PreprocessedAudio
from app.schemas.response import EnergyTimeline
from app.services.features.energy import (
    EnergyConfig,
    EnergyExtractionResult,
    EnergyExtractor,
    extract_energy,
)

SR = 16000


def _sine(freq_hz: float = 1000.0, duration_s: float = 1.0, amplitude: float = 0.5, sr: int = SR) -> np.ndarray:
    n = int(duration_s * sr)
    t = np.arange(n, dtype=np.float64) / sr
    return (amplitude * np.sin(2.0 * np.pi * freq_hz * t)).astype(np.float32)


def _interior(result: EnergyExtractionResult) -> slice:
    """Frames whose analysis window lies fully inside the signal (no zero padding)."""
    pad_frames = int(np.ceil((result.config.frame_length // 2) / result.config.hop_length)) + 1
    return slice(pad_frames, result.total_frames - pad_frames)


def _container(arr: np.ndarray, sr: int = SR) -> PreprocessedAudio:
    return PreprocessedAudio(
        sample_rate_hz=sr,
        channels=1,
        duration_s=round(len(arr) / sr, 4),
        audio_array=arr,
        sha256="0" * 64,
        peak_dbfs=-3.0,
    )


# ----------------------------------------------------------------- accuracy
def test_known_amplitude_matches_rms_db():
    # 1 kHz at 16 kHz => 512-sample window holds exactly 32 cycles => RMS = A / sqrt(2).
    amp = 0.5
    res = extract_energy(_sine(amplitude=amp))
    expected_db = 20.0 * np.log10(amp / np.sqrt(2.0))
    assert np.allclose(res.values_db[_interior(res)], expected_db, atol=1e-3)


def test_halving_amplitude_lowers_level_by_6_db():
    loud = extract_energy(_sine(amplitude=0.5))
    quiet = extract_energy(_sine(amplitude=0.25))
    diff = loud.values_db[_interior(loud)] - quiet.values_db[_interior(quiet)]
    assert np.allclose(diff, 20.0 * np.log10(2.0), atol=1e-3)


def test_loud_then_quiet_segment_levels_follow_signal():
    audio = np.concatenate([_sine(amplitude=0.5, duration_s=1.0), _sine(amplitude=0.05, duration_s=1.0)])
    res = extract_energy(audio)
    first = res.values_db[(res.times_s > 0.1) & (res.times_s < 0.9)]
    second = res.values_db[(res.times_s > 1.1) & (res.times_s < 1.9)]
    assert np.all(first > second + 15.0)  # 20 dB amplitude drop


def test_edge_frames_use_zero_padding():
    # Frame 0 is centred on sample 0: half its 512-sample window is zero padding and the other
    # half is exactly 16 cycles of the 1 kHz tone, so its mean power is half of an interior
    # frame's (-3.01 dB). This pins the padding mode, which must not depend on the librosa default.
    res = extract_energy(_sine(amplitude=0.5))
    interior_db = float(res.values_db[_interior(res)][0])
    assert res.values_db[0] == pytest.approx(interior_db - 10.0 * np.log10(2.0), abs=1e-3)


def test_digital_silence_gives_finite_floor():
    res = extract_energy(np.zeros(SR, dtype=np.float32))
    assert np.all(np.isfinite(res.values_db))
    assert np.allclose(res.values_db, -180.0)


# ---------------------------------------------------------------- time axis
def test_time_axis_and_frame_count():
    n = SR  # 1 s
    res = extract_energy(_sine(duration_s=1.0))
    cfg = res.config
    assert res.total_frames == 1 + n // cfg.hop_length
    assert res.times_s[0] == 0.0
    assert np.allclose(np.diff(res.times_s), cfg.hop_length / cfg.sample_rate)
    assert res.hop_s == pytest.approx(0.01)
    assert len(res.values_db) == len(res.times_s)
    assert res.times_s.dtype == np.float64 and res.values_db.dtype == np.float64


# -------------------------------------------------------------- determinism
def test_deterministic_repeated_extraction():
    audio = _sine(freq_hz=313.0, amplitude=0.4)
    a = extract_energy(audio)
    b = extract_energy(audio)
    assert np.array_equal(a.times_s, b.times_s)
    assert np.array_equal(a.values_db, b.values_db)


def test_input_audio_not_modified_and_outputs_are_copies():
    audio = _sine()
    before = audio.copy()
    res = extract_energy(audio)
    assert np.array_equal(audio, before)
    bundle = res.to_feature_bundle_dict()
    bundle["energy_db"][:] = 0.0
    assert not np.all(res.values_db == 0.0)
    assert set(bundle) == {"energy_times_s", "energy_db"}


# ------------------------------------------------------------ schema / input
def test_timeline_dict_matches_response_schema():
    res = extract_energy(_sine(duration_s=0.5))
    timeline = EnergyTimeline(**res.to_timeline_dict())
    assert len(timeline.times_s) == res.total_frames
    assert all(isinstance(v, float) for v in timeline.values_db)


def test_accepts_canonical_audio_container():
    arr = _sine(duration_s=0.5)
    from_container = extract_energy(_container(arr))
    from_array = extract_energy(arr)
    assert np.array_equal(from_container.values_db, from_array.values_db)


def test_container_with_other_sample_rate_infers_matching_config():
    sr = 8000
    res = extract_energy(_container(_sine(sr=sr, duration_s=0.5), sr=sr))
    assert res.config.sample_rate == sr
    assert res.hop_s == pytest.approx(160 / 8000)


def test_float64_input_is_accepted():
    res = extract_energy(_sine().astype(np.float64))
    assert res.total_frames > 0


# --------------------------------------------------------------- edge cases
@pytest.mark.parametrize("n_samples", [1, 10, 100, 511, 512])
def test_very_short_audio_does_not_crash(n_samples):
    res = extract_energy(_sine(duration_s=1.0)[:n_samples])
    assert res.total_frames >= 1
    assert np.all(np.isfinite(res.values_db))


def test_quiet_audio_logs_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="app.services.features.energy"):
        extract_energy(_sine(amplitude=1e-5))  # about -103 dBFS
    assert any("Very quiet audio" in r.message for r in caplog.records)


def test_normal_audio_does_not_log_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="app.services.features.energy"):
        extract_energy(_sine(amplitude=0.5))
    assert not caplog.records


# ------------------------------------------------------------------ invalid
def test_empty_audio_rejected():
    with pytest.raises(ValueError, match="non-empty"):
        extract_energy(np.empty(0, dtype=np.float32))


def test_non_finite_audio_rejected():
    audio = _sine()
    audio[10] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        extract_energy(audio)


def test_multichannel_audio_rejected():
    with pytest.raises(ValueError, match="mono"):
        extract_energy(np.zeros((2, 1000), dtype=np.float32))


def test_non_array_input_rejected():
    with pytest.raises(TypeError):
        extract_energy([0.1, 0.2, 0.3])  # type: ignore[arg-type]


def test_sample_rate_mismatch_rejected():
    with pytest.raises(ValueError, match="does not match"):
        EnergyExtractor().extract(_sine(), sample_rate=8000)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sample_rate": 0},
        {"frame_length": 0},
        {"hop_length": -1},
        {"rms_floor": 0.0},
        {"rms_floor": float("nan")},
        {"quiet_warning_dbfs": float("inf")},
    ],
)
def test_invalid_config_rejected(kwargs):
    with pytest.raises(ValueError):
        EnergyConfig(**kwargs)
