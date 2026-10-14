"""Integration test: baseline builder <-> normalizer consistency (+).

Property: normalizing a recording against baseline statistics built FROM that same recording
must give a zero mean and unit (sample) standard deviation for every feature. This only holds if
the builder and the normalizer apply identical frame rules (voiced F0 frames, active energy
frames, the same pause types), so it guards against the two drifting apart.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pytest
import scipy.io.wavfile as wavfile

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "dataset"))

import build_baseline_stats as bbs  # noqa: E402
from app.schemas.common import AlignmentMethod, PauseBoundaryType  # noqa: E402
from app.schemas.contracts import AlignedTranscript, AlignedWord  # noqa: E402
from app.services.audio import AudioPreprocessor  # noqa: E402
from app.services.features.energy import extract_energy  # noqa: E402
from app.services.features.f0 import extract_f0  # noqa: E402
from app.services.features.pause import detect_pauses  # noqa: E402
from app.services.features.rate import extract_rate  # noqa: E402
from app.services.grounding import normalize_features  # noqa: E402

SR = 16000
SPECIAL_GAPS = {5: 0.4, 11: 0.6, 17: 0.3}  # seconds; others 0.1 s


def _recording():
    """24 tone 'words' with varying pitch/loudness and three real pauses (2 within, 1 across)."""
    chunks, words, cursor = [], [], 0
    for i in range(24):
        n_word = int(0.4 * SR)
        freq, amp = 110.0 + 12.0 * (i % 6), 0.3 + 0.05 * (i % 5)
        t = np.arange(n_word) / SR
        chunks.append(amp * np.sin(2 * np.pi * freq * t))
        text = f"w{i}." if i == 11 else f"w{i}"
        words.append(AlignedWord(word=text, start_s=cursor / SR, end_s=(cursor + n_word) / SR, confidence=0.9))
        cursor += n_word
        if i < 23:
            n_gap = int(SPECIAL_GAPS.get(i, 0.1) * SR)
            chunks.append(np.zeros(n_gap))
            cursor += n_gap
    buf = io.BytesIO()
    wavfile.write(buf, SR, (np.concatenate(chunks) * 32767).astype(np.int16))
    transcript = AlignedTranscript(
        text=" ".join(w.word for w in words), words=words,
        alignment_method=AlignmentMethod.WHISPERX, total_coverage_pct=0.8,
    )
    return buf.getvalue(), transcript


@pytest.fixture(scope="module")
def pipeline():
    wav_bytes, aligned = _recording()
    audio = AudioPreprocessor().process(wav_bytes)
    f0 = extract_f0(audio)
    energy = extract_energy(audio)
    rate = extract_rate(aligned)
    pauses = detect_pauses(aligned=aligned, energy=energy).events
    features = bbs.RecordingFeatures(
        recording_id="rec_self", f0_voiced_hz=f0.voiced_values_hz, energy_db=energy.values_db,
        rate_wpm=rate.words_per_min, pauses=pauses,
    )
    baseline = bbs.aggregate_baseline_stats("p001", "1.0.0", [features])
    return baseline, f0, energy, rate, pauses


def _check_standardised(z: np.ndarray, label: str) -> None:
    valid = z[~np.isnan(z)]
    assert len(valid) >= 2, label
    assert abs(float(np.mean(valid))) < 1e-3, f"{label}: mean {np.mean(valid)}"
    assert abs(float(np.std(valid, ddof=1)) - 1.0) < 1e-3, f"{label}: std {np.std(valid, ddof=1)}"


def test_baseline_has_usable_spread_for_every_feature(pipeline):
    baseline = pipeline[0]
    assert baseline.f0_voiced_hz_std > 1.0 and baseline.energy_db_std > 0.1 and baseline.rate_wpm_std > 0.0
    assert baseline.pause_within_phrase_std_s > 0.0 and baseline.n_pauses_cross_sentence == 1


def test_normalizing_the_baseline_recording_against_itself_is_standard_normal(pipeline):
    baseline, f0, energy, rate, pauses = pipeline
    result = normalize_features(baseline, f0=f0, energy=energy, rate=rate, pauses=pauses)

    assert result.unavailable == {}
    _check_standardised(result.f0_z, "f0")
    _check_standardised(result.energy_z, "energy")
    _check_standardised(result.rate_z, "rate")

    within = [p.z_score for p in result.pauses if p.event.boundary_type == PauseBoundaryType.WITHIN_PHRASE]
    assert len(within) == 2 and abs(sum(within)) < 1e-3
    cross = [p for p in result.pauses if p.event.boundary_type == PauseBoundaryType.CROSS_SENTENCE]
    assert len(cross) == 1 and np.isnan(cross[0].z_score) and cross[0].note  # single pause: no std => undefined


def test_masks_match_the_frames_the_baseline_was_built_from(pipeline):
    baseline, f0, energy, rate, pauses = pipeline
    result = normalize_features(baseline, f0=f0, energy=energy)
    assert int(np.count_nonzero(~np.isnan(result.f0_z))) == baseline.n_f0_voiced_frames
    assert int(np.count_nonzero(~np.isnan(result.energy_z))) == baseline.n_energy_frames
    assert int(np.count_nonzero(result.energy_in_baseline_rule)) == baseline.n_energy_frames


def test_the_same_pipeline_run_twice_normalizes_identically(pipeline):
    baseline, f0, energy, rate, pauses = pipeline
    a = normalize_features(baseline, f0=f0, energy=energy, rate=rate, pauses=pauses)
    b = normalize_features(baseline, f0=f0, energy=energy, rate=rate, pauses=pauses)
    for name in ("f0_z", "energy_z", "rate_z"):
        assert np.array_equal(getattr(a, name), getattr(b, name), equal_nan=True)
