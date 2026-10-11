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
    find_active_span,
    load_audio_from_bytes,
    resample_audio,
    speech_level_dbfs,
    speech_level_normalize,
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
    # Verify loudness scaling (DEC-036): a steady sine has its peak 3 dB above its RMS, so the median speech level -26 dBFS puts the peak at -23
    assert math.isclose(res.peak_dbfs, -23.0, abs_tol=0.3)
    assert math.isclose(speech_level_dbfs(res.audio_array, res.sample_rate_hz, 30.0), -26.0, abs_tol=0.3)
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


def _speechlike(sr: int = 16000, quiet_db: float = 0.0, loud_db: float = 0.0, seconds: float = 6.0) -> np.ndarray:
    """A syllable-modulated tone with a stretch in the middle third changed by `loud_db`, the whole signal changed by `quiet_db`."""
    t = np.arange(int(seconds * sr)) / sr
    x = 0.2 * np.sin(2 * np.pi * 150.0 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 3.0 * t))
    third = len(x) // 3
    x[third:2 * third] *= 10 ** (loud_db / 20)
    return (x * 10 ** (quiet_db / 20)).astype(np.float32)


def test_speech_level_of_a_known_sine():
    sr = 16000
    sine = (1.0 * np.sin(2 * np.pi * 1000 * np.arange(sr) / sr)).astype(np.float32)  # RMS 0.707 = -3.01 dBFS
    assert speech_level_dbfs(sine, sr, 30.0) == pytest.approx(-3.01, abs=0.05)


def test_speech_level_ignores_silence_and_is_none_for_empty_or_silent_audio():
    sr = 16000
    tone = (0.1 * np.sin(2 * np.pi * 300 * np.arange(sr) / sr)).astype(np.float32)
    padded = np.concatenate([np.zeros(sr, np.float32), tone, np.zeros(sr, np.float32)])  # two thirds digital silence
    assert speech_level_dbfs(padded, sr, 30.0) == pytest.approx(speech_level_dbfs(tone, sr, 30.0), abs=0.1)
    assert speech_level_dbfs(np.empty(0, np.float32), sr, 30.0) is None
    assert speech_level_dbfs(np.zeros(sr, np.float32), sr, 30.0) is None
    assert speech_level_dbfs(tone[:100], sr, 30.0) is not None  # shorter than one frame still works


def test_speech_level_normalization_sets_the_target_level():
    audio, _ = load_audio_from_bytes(make_sine_wav_bytes(duration_s=0.5, amplitude=0.1, sample_rate=16000))  # quiet audio
    scaled, measured_peak = speech_level_normalize(audio, 16000, target_speech_level_dbfs=-26.0)
    assert speech_level_dbfs(scaled, 16000, 30.0) == pytest.approx(-26.0, abs=0.2)
    assert measured_peak == pytest.approx(20 * np.log10(np.max(np.abs(scaled))), abs=1e-6)
    assert scaled.dtype == np.float32


def test_speech_level_normalization_keeps_differences_inside_the_recording():
    """The point of DEC-036: a loud stretch stays exactly as loud as it was relative to the rest, and the rest is barely pushed down by it."""
    sr = 16000
    third = len(_speechlike()) // 3
    rms = lambda x: float(np.sqrt(np.mean(x ** 2)))
    s_base, _ = speech_level_normalize(_speechlike(), sr)
    s_loud, _ = speech_level_normalize(_speechlike(loud_db=12.0), sr)
    # one gain for the whole signal: the stretch is still exactly 12 dB above the rest of the recording
    assert 20 * np.log10(rms(s_loud[third:2 * third]) / rms(s_loud[:third])) == pytest.approx(12.0, abs=0.3)
    # the rest of the recording moves only a little (the median shifts when a third of the frames are louder: about 3 dB here),
    # where scaling by the loudest sample would have pushed it down by the full 12 dB
    drop_db = 20 * np.log10(rms(s_base[:third]) / rms(s_loud[:third]))
    assert 0.0 <= drop_db < 4.5


def test_the_overall_recording_gain_does_not_matter():
    sr = 16000
    normal, _ = speech_level_normalize(_speechlike(), sr)
    quiet, _ = speech_level_normalize(_speechlike(quiet_db=-20.0), sr)
    assert np.allclose(normal, quiet, atol=1e-4)


def test_gain_is_capped_so_the_loudest_sample_stays_below_the_limit():
    sr = 16000
    x = _speechlike(quiet_db=-30.0)           # quiet speech ...
    x[1000] = 0.9                              # ... with one loud click that a plain gain to -26 dBFS would push far past full scale
    scaled, measured_peak = speech_level_normalize(x, sr, target_speech_level_dbfs=-26.0, max_peak_dbfs=-1.0)
    assert measured_peak == pytest.approx(-1.0, abs=0.01) and np.max(np.abs(scaled)) <= 10 ** (-1.0 / 20) + 1e-6
    assert scaled.dtype == np.float32  # also on the capped path, where the gain is a numpy float64
    assert speech_level_dbfs(scaled, sr, 30.0) < -26.0 - 1.0     # the cap won: the speech could not reach the target


def test_speech_level_normalization_edge_cases_and_determinism():
    sr = 16000
    empty, peak = speech_level_normalize(np.empty(0, np.float32), sr)
    assert len(empty) == 0 and peak == -100.0
    silent = np.zeros(sr, np.float32)
    out, peak = speech_level_normalize(silent, sr)
    assert np.array_equal(out, silent) and peak == -100.0
    x = _speechlike(loud_db=6.0)
    a, pa = speech_level_normalize(x, sr)
    b, pb = speech_level_normalize(x, sr)
    assert np.array_equal(a, b) and pa == pb


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


# ---------------------------------------------------------------------------
# TASK-013A: source-time provenance of silence trimming
# ---------------------------------------------------------------------------

TARGET_SR = 16000
VAD_FRAME_S = 0.02  # trim_silence frame size; offsets are frame-quantized


def _legacy_trim_silence(audio, sample_rate, threshold_dbfs=-50.0, frame_duration_ms=20.0):
    """Verbatim copy of trim_silence() as it was before TASK-013A (regression oracle)."""
    if len(audio) == 0:
        return audio
    frame_length = max(1, int(sample_rate * (frame_duration_ms / 1000.0)))
    n_frames = len(audio) // frame_length
    if n_frames == 0:
        rms = np.sqrt(np.mean(audio**2) + 1e-12)
        dbfs = 20.0 * np.log10(rms + 1e-12)
        return audio if dbfs >= threshold_dbfs else np.empty(0, dtype=np.float32)
    truncated_len = n_frames * frame_length
    frames = audio[:truncated_len].reshape(n_frames, frame_length)
    frame_rms = np.sqrt(np.mean(frames**2, axis=1) + 1e-12)
    frame_dbfs = 20.0 * np.log10(frame_rms + 1e-12)
    active_indices = np.where(frame_dbfs >= threshold_dbfs)[0]
    if len(active_indices) == 0:
        return np.empty(0, dtype=np.float32)
    start_sample = active_indices[0] * frame_length
    end_sample = min(len(audio), (active_indices[-1] + 1) * frame_length)
    return audio[start_sample:end_sample]


def _silent_wav_bytes(duration_s: float, sample_rate: int = TARGET_SR) -> bytes:
    buf = io.BytesIO()
    wav.write(buf, sample_rate, np.zeros(int(duration_s * sample_rate), dtype=np.int16))
    return buf.getvalue()


def _processed_audio(audio_array=None, **kwargs) -> PreprocessedAudio:
    arr = np.zeros(1600, dtype=np.float32) if audio_array is None else audio_array
    params = dict(
        sample_rate_hz=TARGET_SR,
        channels=1,
        duration_s=round(len(arr) / TARGET_SR, 4),
        audio_array=arr,
        sha256="0" * 64,
        peak_dbfs=-3.0,
    )
    params.update(kwargs)
    return PreprocessedAudio(**params)


def test_trim_provenance_leading_and_trailing_silence():
    wav_bytes = make_sine_wav_bytes(
        duration_s=0.5, sample_rate=TARGET_SR, leading_silence_s=0.5, trailing_silence_s=0.5
    )
    res = AudioPreprocessor().process(wav_bytes)

    assert abs(res.trim_start_s - 0.5) <= VAD_FRAME_S
    assert abs(res.source_duration_s - 1.5) < 1e-6
    assert abs(res.duration_s - 0.5) <= VAD_FRAME_S
    assert res.trim_start_s + res.duration_s <= res.source_duration_s + 1e-3


def test_trim_provenance_untrimmed_audio_has_zero_offset():
    res = AudioPreprocessor().process(make_sine_wav_bytes(duration_s=0.5, sample_rate=TARGET_SR))

    assert res.trim_start_s == 0.0
    assert abs(res.source_duration_s - 0.5) < 1e-6


def test_trim_provenance_leading_only_silence():
    wav_bytes = make_sine_wav_bytes(duration_s=0.4, sample_rate=TARGET_SR, leading_silence_s=0.3)
    res = AudioPreprocessor().process(wav_bytes)

    assert abs(res.trim_start_s - 0.3) <= VAD_FRAME_S
    assert abs(res.source_duration_s - 0.7) < 1e-6
    assert abs(res.duration_s - 0.4) <= VAD_FRAME_S


def test_trim_provenance_trailing_only_silence():
    wav_bytes = make_sine_wav_bytes(duration_s=0.4, sample_rate=TARGET_SR, trailing_silence_s=0.3)
    res = AudioPreprocessor().process(wav_bytes)

    assert res.trim_start_s == 0.0
    assert abs(res.source_duration_s - 0.7) < 1e-6
    assert abs(res.duration_s - 0.4) <= VAD_FRAME_S


@pytest.mark.parametrize("sample_rate", [16000, 22050, 44100, 48000])
def test_trim_provenance_maps_onset_back_to_source_time(sample_rate):
    """Tone onset is at 0.5 s in the source file; offset + processed onset must recover it."""
    lead_s = 0.5
    wav_bytes = make_sine_wav_bytes(
        duration_s=0.5, sample_rate=sample_rate, leading_silence_s=lead_s, trailing_silence_s=0.25
    )
    res = AudioPreprocessor().process(wav_bytes)

    arr = np.abs(res.audio_array)
    onset_idx = int(np.argmax(arr > 0.05 * arr.max()))
    onset_processed_s = onset_idx / res.sample_rate_hz

    assert abs(res.to_source_time(onset_processed_s) - lead_s) <= 1.25 * VAD_FRAME_S
    assert abs(res.source_duration_s - 1.25) < 1e-3


def test_trim_provenance_offset_matches_retained_samples_exactly():
    """trim_start_s must equal the retained span's first sample / sample rate, with no rounding."""
    wav_bytes = make_sine_wav_bytes(
        duration_s=0.5, sample_rate=44100, leading_silence_s=0.62, trailing_silence_s=0.4
    )
    preprocessor = AudioPreprocessor()
    res = preprocessor.process(wav_bytes)

    # Re-run the same pre-trim steps to obtain the exact pre-trim signal.
    decoded, orig_sr = load_audio_from_bytes(wav_bytes)
    pre_trim = resample_audio(convert_to_mono(decoded), orig_sr, TARGET_SR)
    start, end = find_active_span(
        pre_trim, TARGET_SR, threshold_dbfs=preprocessor.vad_energy_threshold_dbfs
    )

    assert res.trim_start_s == start / TARGET_SR
    assert round(res.trim_start_s * TARGET_SR) == start
    assert len(res.audio_array) == end - start
    assert res.source_duration_s == len(pre_trim) / TARGET_SR
    expected_audio, _ = speech_level_normalize(
        pre_trim[start:end], TARGET_SR, preprocessor.target_speech_level_dbfs, preprocessor.speech_level_window_db, preprocessor.max_peak_dbfs
    )
    assert np.array_equal(res.audio_array, expected_audio)
    assert res.sha256 == compute_audio_sha256(expected_audio)


def test_trim_provenance_all_silence():
    res = AudioPreprocessor().process(_silent_wav_bytes(1.0))

    assert len(res.audio_array) == 0
    assert res.duration_s == 0.0
    assert res.trim_start_s == 0.0
    assert abs(res.source_duration_s - 1.0) < 1e-6
    assert res.to_source_time(0.0) == 0.0


def test_trim_provenance_sub_frame_audio():
    # 5 ms (80 samples) < one 20 ms VAD frame: kept whole if loud enough, dropped if silent.
    tone = AudioPreprocessor().process(make_sine_wav_bytes(duration_s=0.005, sample_rate=TARGET_SR))
    assert len(tone.audio_array) == 80
    assert tone.trim_start_s == 0.0
    assert tone.source_duration_s == 80 / TARGET_SR

    silent = AudioPreprocessor().process(_silent_wav_bytes(0.005))
    assert len(silent.audio_array) == 0
    assert silent.trim_start_s == 0.0
    assert silent.source_duration_s == 80 / TARGET_SR


def test_trim_provenance_deterministic_repeated_runs():
    wav_bytes = make_sine_wav_bytes(
        freq_hz=300.0, duration_s=0.6, sample_rate=44100, channels=2,
        leading_silence_s=0.4, trailing_silence_s=0.2,
    )
    first = AudioPreprocessor().process(wav_bytes)
    second = AudioPreprocessor().process(wav_bytes)

    assert first.trim_start_s == second.trim_start_s
    assert first.source_duration_s == second.source_duration_s
    assert first.sha256 == second.sha256
    assert np.array_equal(first.audio_array, second.audio_array)


def test_sha256_ignores_amount_of_trimmed_silence():
    """Documents that sha256 identifies the processed signal only; the offset is separate."""
    short_lead = AudioPreprocessor().process(
        make_sine_wav_bytes(duration_s=0.5, sample_rate=TARGET_SR, leading_silence_s=0.2)
    )
    long_lead = AudioPreprocessor().process(
        make_sine_wav_bytes(duration_s=0.5, sample_rate=TARGET_SR, leading_silence_s=0.6)
    )

    assert short_lead.sha256 == long_lead.sha256
    assert np.array_equal(short_lead.audio_array, long_lead.audio_array)
    assert short_lead.trim_start_s != long_lead.trim_start_s


def test_find_active_span_results():
    sr = TARGET_SR
    frame = int(sr * VAD_FRAME_S)
    tone = (0.5 * np.sin(2 * np.pi * 440 * np.arange(frame * 5) / sr)).astype(np.float32)
    padded = np.concatenate([np.zeros(frame * 3, np.float32), tone, np.zeros(frame * 2, np.float32)])

    assert find_active_span(padded, sr) == (frame * 3, frame * 8)
    assert find_active_span(np.zeros(sr, np.float32), sr) is None
    assert find_active_span(np.empty(0, np.float32), sr) is None
    assert find_active_span(tone[:80], sr) == (0, 80)  # sub-frame, active
    assert find_active_span(np.zeros(80, np.float32), sr) is None  # sub-frame, silent


def test_trim_silence_unchanged_from_legacy_behavior():
    """trim_silence() must be value- and dtype-identical to its pre-TASK-013A implementation."""
    rng = np.random.default_rng(1234)
    sr = TARGET_SR
    frame = int(sr * VAD_FRAME_S)

    def burst(n, amp):
        return (amp * rng.standard_normal(n)).astype(np.float32)

    cases = [
        np.empty(0, np.float32),
        np.zeros(sr, np.float32),
        np.zeros(80, np.float32),
        burst(80, 0.3),
        burst(frame * 4, 0.3),
        np.concatenate([np.zeros(frame * 2 + 7, np.float32), burst(frame * 3 + 11, 0.3), np.zeros(frame + 5, np.float32)]),
        np.concatenate([burst(frame * 2, 0.3), np.zeros(frame * 3, np.float32), burst(frame * 2, 0.3)]),
        np.concatenate([np.zeros(frame, np.float32), burst(frame, 1e-4), np.zeros(frame, np.float32)]),  # below -50 dBFS
    ]
    for audio in cases:
        for threshold in (-50.0, -30.0):
            expected = _legacy_trim_silence(audio, sr, threshold_dbfs=threshold)
            actual = trim_silence(audio, sr, threshold_dbfs=threshold)
            assert actual.dtype == expected.dtype
            assert np.array_equal(actual, expected)


def test_preprocessed_audio_trim_fields_default_for_legacy_construction():
    audio = _processed_audio()

    assert audio.trim_start_s == 0.0
    assert audio.source_duration_s is None
    assert audio.to_source_time(1.25) == 1.25


def test_preprocessed_audio_to_source_time_adds_offset():
    audio = _processed_audio(trim_start_s=0.5, source_duration_s=1.0)

    assert audio.to_source_time(0.0) == 0.5
    assert audio.to_source_time(0.25) == 0.75


def test_preprocessed_audio_accepts_trim_bounds_within_tolerance():
    # 0.1 s of audio starting at 0.9 s of a 1.0 s source (exactly fits).
    assert _processed_audio(trim_start_s=0.9, source_duration_s=1.0).source_duration_s == 1.0
    # Rounded-duration slack (<= 1 ms) is tolerated.
    assert _processed_audio(trim_start_s=0.9, source_duration_s=0.9995).trim_start_s == 0.9


@pytest.mark.parametrize(
    "kwargs",
    [
        {"trim_start_s": -0.01},
        {"trim_start_s": float("nan")},
        {"trim_start_s": float("inf")},
        {"source_duration_s": -1.0},
        {"source_duration_s": float("nan")},
        {"trim_start_s": 0.95, "source_duration_s": 1.0},  # 0.95 + 0.1 > 1.0 + tolerance
        {"trim_start_s": 2.0, "source_duration_s": 1.0},
    ],
)
def test_preprocessed_audio_rejects_invalid_trim_fields(kwargs):
    with pytest.raises(ValueError):
        _processed_audio(**kwargs)
