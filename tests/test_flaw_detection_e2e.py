"""End-to-end flaw-candidate detection on synthetic speech with injected, known flaws.

Real chain, no mocks: preprocessing -> F0 / energy / speech rate / pauses -> baseline statistics
(built from a clean baseline recording) -> normalization -> candidate detection.

The participant is the baseline's own delivery for the first 12 words, then three flaws are
injected at known times (all in processed-audio time; the audio starts and ends with speech, so
nothing is trimmed):

    words 12-19   very quiet  (amplitude x0.1, about -20 dB)       -> low_energy
    gap after 19  1.5 s of silence mid-phrase                       -> excessive_pause
    words 20-35   fast        (0.2 s words, 0.03 s gaps)             -> too_fast

Also checked: clean takes (the baseline itself, a different clean take, and one ~4x longer) produce
NO candidates, so false positives neither appear nor grow with recording length.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "dataset"))

import build_baseline_stats as bbs  # noqa: E402
from app.schemas.common import FlawType  # noqa: E402
from app.services.audio import AudioPreprocessor  # noqa: E402
from app.services.features.energy import extract_energy  # noqa: E402
from app.services.features.f0 import extract_f0  # noqa: E402
from app.services.features.pause import detect_pauses  # noqa: E402
from app.services.features.rate import extract_rate  # noqa: E402
from app.services.grounding import detect_candidates, normalize_features  # noqa: E402
from synthetic_speech import build_speech, normal_delivery  # noqa: E402

GAPS = {5: 0.4, 11: 0.6, 17: 0.3}
HOP = 0.01


def _process(items):
    wav, aligned = build_speech(items)
    audio = AudioPreprocessor().process(wav)
    assert audio.trim_start_s == 0.0                        # alignment times == processed times
    f0, energy, rate = extract_f0(audio), extract_energy(audio), extract_rate(aligned)
    pauses = detect_pauses(aligned=aligned, energy=energy).events
    return aligned, f0, energy, rate, pauses


@pytest.fixture(scope="module")
def baseline():
    _, f0, energy, rate, pauses = _process(normal_delivery(24, special_gaps=GAPS))
    rec = bbs.RecordingFeatures("rec_base", f0.voiced_values_hz, energy.values_db, rate.words_per_min, pauses)
    return bbs.aggregate_baseline_stats("p001", "1.0.0", [rec])


def _detect(baseline, items):
    aligned, f0, energy, rate, pauses = _process(items)
    normalized = normalize_features(baseline, f0=f0, energy=energy, rate=rate, pauses=pauses)
    return aligned, normalized, detect_candidates(normalized)


@pytest.fixture(scope="module")
def flawed(baseline):
    items: List = (
        normal_delivery(12, special_gaps=GAPS) + [("gap", 0.6)]
        + normal_delivery(8, amp_scale=0.1, start_index=12) + [("gap", 1.5)]
        + normal_delivery(16, word_dur=0.2, gap=0.03, start_index=20)
    )
    return _detect(baseline, items)


def _one(result, ftype: FlawType):
    found = [c for c in result.candidates if c.type == ftype]
    assert len(found) == 1, f"expected exactly one {ftype.value}, got {len(found)}"
    return found[0]


def test_exactly_the_injected_flaw_types_are_found(flawed):
    _, _, result = flawed
    assert sorted(c.type.value for c in result.candidates) == ["excessive_pause", "low_energy", "too_fast"]


def test_quiet_speech_is_located_as_low_energy(flawed):
    aligned, _, result = flawed
    w = aligned.words
    low = _one(result, FlawType.LOW_ENERGY)
    assert low.start_s == pytest.approx(w[12].start_s, abs=2 * HOP)
    assert low.end_s == pytest.approx(w[19].end_s, abs=2 * HOP)
    assert low.mean_z < -5 and low.peak_z >= abs(low.mean_z)
    # The silence around it is not "low energy": the flaw ends where the quiet words end.
    assert low.end_s <= w[19].end_s + 2 * HOP


def test_long_pause_is_located_exactly(flawed):
    aligned, _, result = flawed
    w = aligned.words
    pause = _one(result, FlawType.EXCESSIVE_PAUSE)
    assert pause.start_s == pytest.approx(w[19].end_s, abs=0.02)
    assert pause.end_s == pytest.approx(w[20].start_s, abs=0.02)
    assert pause.peak_z > 10 and pause.member_indices == (2,)


def test_fast_speech_is_flagged_at_window_resolution(flawed):
    aligned, normalized, result = flawed
    w = aligned.words
    fast = _one(result, FlawType.TOO_FAST)
    # Ends with the fast words, overlaps them, and stays clear of the clean first window...
    assert fast.end_s == pytest.approx(w[35].end_s, abs=0.05)
    assert fast.start_s < w[20].start_s and fast.end_s > w[20].start_s
    assert fast.start_s >= 8.0
    # ...but, as a rolling-window finding, it begins earlier than the fast words themselves.
    assert fast.start_s < w[20].start_s - 1.0
    assert fast.mean_z > 10


def test_clean_first_stretch_has_no_candidates(flawed):
    aligned, _, result = flawed
    first_flaw_start = min(c.start_s for c in result.candidates)
    assert first_flaw_start >= aligned.words[12].start_s - 2 * HOP


def test_pipeline_is_deterministic(baseline, flawed):
    items = (
        normal_delivery(12, special_gaps=GAPS) + [("gap", 0.6)]
        + normal_delivery(8, amp_scale=0.1, start_index=12) + [("gap", 1.5)]
        + normal_delivery(16, word_dur=0.2, gap=0.03, start_index=20)
    )
    _, _, again = _detect(baseline, items)
    assert again.candidates == flawed[2].candidates


@pytest.mark.parametrize(
    "label,items",
    [
        ("baseline itself", normal_delivery(24, special_gaps=GAPS)),
        ("different clean take", normal_delivery(24, special_gaps={6: 0.35, 12: 0.6, 18: 0.3})),
        ("long clean take (4x)", normal_delivery(96, special_gaps={k: g for r in range(4) for k, g in
                                                                  {5 + 24 * r: 0.4, 11 + 24 * r: 0.6, 17 + 24 * r: 0.3}.items()})),
    ],
)
def test_clean_delivery_produces_no_candidates(baseline, label, items):
    _, _, result = _detect(baseline, items)
    assert result.candidates == [], f"{label}: unexpected {[(c.type.value, c.start_s, c.end_s) for c in result.candidates]}"


def test_unsupported_types_are_reported_in_the_result(flawed):
    _, _, result = flawed
    assert set(result.skipped) == {"flat_pitch", "pitch_instability", "reduced_clarity"}
