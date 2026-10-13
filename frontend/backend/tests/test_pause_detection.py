"""Unit and contract tests for pause detection (TASK-034, DEC-011).

Covers:
- VAD-only, alignment-only and "both" events, with exact intervals
- Agreement rule (>50 % of the shorter interval), union interval, non-agreeing candidates
- Inclusive duration thresholds, including floating-point boundary cases
- Strict energy threshold, leading/trailing low-energy runs ignored
- Boundary classification (cross_sentence / within_phrase / unknown)
- Missing word timings are never bridged or guessed
- Either signal alone, neither signal (error), wrong input types
- Deterministic, sorted output; compatibility with the PauseEvent response schema
- Integration with real energy extraction on a tone-silence-tone signal
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple

import numpy as np
import pytest
from app.schemas.common import AlignmentMethod, PauseBoundaryType, PauseDetectionSource
from app.schemas.contracts import AlignedTranscript, AlignedWord
from app.schemas.response import PauseEvent
from app.services.features.energy import EnergyConfig, EnergyExtractionResult, extract_energy
from app.services.features.pause import PauseConfig, PauseDetector, detect_pauses

HOP_S = 0.01
SPEECH_DB = -20.0
SILENT_DB = -70.0

WordSpec = Tuple[str, Optional[float], Optional[float]]


def _aligned(specs: Sequence[WordSpec]) -> AlignedTranscript:
    return AlignedTranscript(
        text=" ".join(w for w, _, _ in specs),
        words=[AlignedWord(word=w, start_s=s, end_s=e, confidence=0.9) for w, s, e in specs],
        alignment_method=AlignmentMethod.WHISPERX,
        total_coverage_pct=1.0,
    )


def _energy(n_frames: int, low_runs: Sequence[Tuple[int, int]] = (), low_db: float = SILENT_DB) -> EnergyExtractionResult:
    """Synthetic energy timeline: speech level everywhere except inclusive low-frame runs."""
    values = np.full(n_frames, SPEECH_DB, dtype=np.float64)
    for first, last in low_runs:
        values[first:last + 1] = low_db
    cfg = EnergyConfig()  # 16 kHz, hop 160 -> 10 ms frames
    times = np.arange(n_frames, dtype=np.float64) * cfg.hop_length / cfg.sample_rate
    return EnergyExtractionResult(times_s=times, values_db=values, config=cfg)


# ------------------------------------------------------------------ VAD only
def test_vad_only_pause_interval_and_source():
    energy = _energy(300, low_runs=[(100, 129)])  # 30 frames = 0.3 s
    res = detect_pauses(energy=energy)
    assert res.signals_used == ("vad",)
    assert len(res.events) == 1
    ev = res.events[0]
    assert ev.start_s == pytest.approx(100 * HOP_S - HOP_S / 2)
    assert ev.end_s == pytest.approx(129 * HOP_S + HOP_S / 2)
    assert ev.duration_s == pytest.approx(0.30)
    assert ev.detection_source == PauseDetectionSource.VAD
    assert ev.boundary_type == PauseBoundaryType.UNKNOWN  # no transcript => cannot classify


def test_vad_run_shorter_than_minimum_ignored_and_exact_minimum_kept():
    short = detect_pauses(energy=_energy(300, low_runs=[(100, 118)]))  # 19 frames = 0.19 s
    assert short.events == [] and short.n_vad_candidates == 0
    exact = detect_pauses(energy=_energy(300, low_runs=[(100, 119)]))  # 20 frames = 0.20 s
    assert len(exact.events) == 1  # inclusive threshold


def test_energy_exactly_at_threshold_is_not_a_pause():
    energy = _energy(300, low_runs=[(100, 140)], low_db=-50.0)  # strict "<" threshold
    assert detect_pauses(energy=energy).events == []


def test_leading_and_trailing_low_energy_are_not_pauses():
    energy = _energy(300, low_runs=[(0, 40), (260, 299)])
    assert detect_pauses(energy=energy).events == []


def test_all_low_energy_gives_no_pause():
    energy = _energy(300, low_runs=[(0, 299)])
    assert detect_pauses(energy=energy).events == []


def test_multiple_vad_pauses_are_sorted():
    energy = _energy(600, low_runs=[(400, 440), (100, 130)])
    starts = [e.start_s for e in detect_pauses(energy=energy).events]
    assert starts == sorted(starts) and len(starts) == 2


# ------------------------------------------------------------ alignment only
def test_alignment_only_gap_and_boundary_types():
    words = _aligned([
        ("Welcome", 0.0, 0.5), ("everyone.", 0.6, 1.2),   # 0.1 s gap: below threshold
        ("Today", 1.9, 2.3),                               # 0.7 s gap after a full stop
        ("we", 2.4, 2.6), ("present", 3.0, 3.5),           # 0.4 s gap mid-sentence
    ])
    res = detect_pauses(aligned=words)
    assert res.signals_used == ("alignment",)
    assert [(e.start_s, e.end_s) for e in res.events] == [(1.2, 1.9), (2.6, 3.0)]
    assert res.events[0].detection_source == PauseDetectionSource.ALIGNMENT
    assert res.events[0].boundary_type == PauseBoundaryType.CROSS_SENTENCE
    assert res.events[1].boundary_type == PauseBoundaryType.WITHIN_PHRASE
    assert res.n_alignment_candidates == 2


@pytest.mark.parametrize(
    "prev_word,expected",
    [
        ("done.", PauseBoundaryType.CROSS_SENTENCE),
        ("really?", PauseBoundaryType.CROSS_SENTENCE),
        ("stop!", PauseBoundaryType.CROSS_SENTENCE),
        ('end."', PauseBoundaryType.CROSS_SENTENCE),
        ("wait...", PauseBoundaryType.CROSS_SENTENCE),
        ("however,", PauseBoundaryType.WITHIN_PHRASE),
        ("and", PauseBoundaryType.WITHIN_PHRASE),
    ],
)
def test_boundary_classification_by_preceding_punctuation(prev_word, expected):
    words = _aligned([(prev_word, 0.0, 0.5), ("next", 1.5, 2.0)])
    assert detect_pauses(aligned=words).events[0].boundary_type == expected


def test_gap_shorter_than_minimum_ignored_and_exact_minimum_kept():
    # 1.15 - 1.0 = 0.1499999999999999 in floating point: must still count as 0.15 s.
    just_below = detect_pauses(aligned=_aligned([("a", 0.0, 1.0), ("b", 1.14, 2.0)]))
    exact = detect_pauses(aligned=_aligned([("a", 0.0, 1.0), ("b", 1.15, 2.0)]))
    assert just_below.events == []
    assert len(exact.events) == 1


def test_overlapping_or_abutting_words_have_no_gap():
    words = _aligned([("a", 0.0, 1.0), ("b", 0.9, 1.5), ("c", 1.5, 2.0)])
    assert detect_pauses(aligned=words).events == []


def test_untimed_words_are_not_bridged_and_are_counted():
    words = _aligned([("a", 0.0, 0.5), ("mystery", None, None), ("b", 3.0, 3.5)])
    res = detect_pauses(aligned=words)
    assert res.events == []  # a 2.5 s hole around an unaligned word is NOT reported as a pause
    assert res.n_gap_pairs_skipped_unaligned == 2


# ----------------------------------------------------------------- combination
def test_vad_and_alignment_agreeing_make_one_both_event_with_union_interval():
    words = _aligned([("one", 0.0, 0.95), ("two", 1.5, 2.0)])      # gap [0.95, 1.5]
    energy = _energy(300, low_runs=[(100, 140)])                    # VAD [0.995, 1.405]
    res = detect_pauses(aligned=words, energy=energy)
    assert res.signals_used == ("vad", "alignment")
    assert len(res.events) == 1
    ev = res.events[0]
    assert ev.detection_source == PauseDetectionSource.BOTH
    assert ev.start_s == pytest.approx(0.95)
    assert ev.end_s == pytest.approx(1.5)
    assert ev.duration_s == pytest.approx(0.55)
    assert (res.n_vad_candidates, res.n_alignment_candidates) == (1, 1)


def test_low_overlap_candidates_stay_separate():
    words = _aligned([("one", 0.0, 1.30), ("two", 2.30, 3.0)])     # gap [1.30, 2.30]
    energy = _energy(400, low_runs=[(100, 134)])                    # VAD [0.995, 1.345]: overlap 0.045 of 0.35
    res = detect_pauses(aligned=words, energy=energy)
    assert sorted(e.detection_source.value for e in res.events) == ["alignment", "vad"]


def test_agreement_requires_more_than_half_of_the_shorter_interval():
    # VAD run [1.005, 1.395] (len 0.39) -> agreement needs overlap > 0.195 s with the gap.
    energy = _energy(300, low_runs=[(101, 139)])
    below = _aligned([("a", 0.0, 1.21), ("b", 2.0, 2.5)])   # gap [1.21, 2.0]: overlap 0.185 s
    above = _aligned([("a", 0.0, 1.19), ("b", 2.0, 2.5)])   # gap [1.19, 2.0]: overlap 0.205 s
    res_below = detect_pauses(aligned=below, energy=energy)
    res_above = detect_pauses(aligned=above, energy=energy)
    assert {e.detection_source for e in res_below.events} == {
        PauseDetectionSource.VAD, PauseDetectionSource.ALIGNMENT
    }
    assert [e.detection_source for e in res_above.events] == [PauseDetectionSource.BOTH]


def test_one_vad_run_covering_two_gaps_yields_one_both_event():
    words = _aligned([("a", 0.0, 1.0), ("b", 1.3, 1.4), ("c", 1.7, 2.5)])   # gaps [1.0,1.3] [1.4,1.7]
    energy = _energy(300, low_runs=[(100, 170)])                              # VAD [0.995, 1.705]
    res = detect_pauses(aligned=words, energy=energy)
    assert len(res.events) == 1
    assert res.events[0].detection_source == PauseDetectionSource.BOTH
    assert res.events[0].start_s == pytest.approx(0.995)
    assert res.events[0].end_s == pytest.approx(1.705)


def test_vad_pause_inside_a_word_is_within_phrase():
    words = _aligned([("end.", 0.0, 0.5), ("stretched", 0.6, 2.5), ("x", 2.6, 3.0)])
    energy = _energy(300, low_runs=[(100, 140)])  # silence at ~1.0-1.4 s, inside "stretched"
    ev = detect_pauses(aligned=words, energy=energy).events[0]
    assert ev.detection_source == PauseDetectionSource.VAD
    assert ev.boundary_type == PauseBoundaryType.WITHIN_PHRASE


def test_pause_before_first_or_after_last_word_is_unknown_boundary():
    words = _aligned([("only", 2.0, 2.5)])
    energy = _energy(400, low_runs=[(50, 100)])  # pause before the first word
    assert detect_pauses(aligned=words, energy=energy).events[0].boundary_type == PauseBoundaryType.UNKNOWN


# ---------------------------------------------------------------- inputs
def test_neither_signal_is_an_error():
    with pytest.raises(ValueError, match="at least one"):
        detect_pauses()


def test_wrong_input_types_rejected():
    with pytest.raises(TypeError):
        detect_pauses(aligned="text")
    with pytest.raises(TypeError):
        detect_pauses(energy=np.zeros(10))


def test_empty_energy_gives_no_events():
    empty = EnergyExtractionResult(
        times_s=np.empty(0), values_db=np.empty(0), config=EnergyConfig()
    )
    assert detect_pauses(energy=empty).events == []


def test_mismatched_energy_arrays_rejected():
    bad = EnergyExtractionResult(times_s=np.zeros(5), values_db=np.zeros(4), config=EnergyConfig())
    with pytest.raises(ValueError):
        detect_pauses(energy=bad)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"vad_energy_threshold_dbfs": float("nan")},
        {"vad_min_pause_s": 0.0},
        {"align_min_gap_s": -0.1},
        {"agreement_overlap_fraction": 1.0},
        {"agreement_overlap_fraction": -0.1},
    ],
)
def test_invalid_config_rejected(kwargs):
    with pytest.raises(ValueError):
        PauseConfig(**kwargs)


def test_custom_thresholds_change_detection():
    words = _aligned([("a", 0.0, 1.0), ("b", 1.3, 2.0)])  # 0.3 s gap
    assert len(detect_pauses(aligned=words).events) == 1
    strict = PauseConfig(align_min_gap_s=0.5)
    assert detect_pauses(aligned=words, config=strict).events == []


# -------------------------------------------------- determinism and schema
def test_deterministic_repeated_detection_and_input_unchanged():
    words = _aligned([("a.", 0.0, 0.9), ("b", 1.5, 2.0), ("c", 2.5, 3.0)])
    energy = _energy(300, low_runs=[(95, 140), (210, 240)])
    before_words, before_values = words.model_dump_json(), energy.values_db.copy()
    first = detect_pauses(aligned=words, energy=energy)
    second = detect_pauses(aligned=words, energy=energy)
    assert first.to_event_dicts() == second.to_event_dicts()
    assert words.model_dump_json() == before_words
    assert np.array_equal(energy.values_db, before_values)


def test_events_conform_to_response_schema():
    words = _aligned([("a.", 0.0, 0.9), ("b", 1.5, 2.0)])
    res = detect_pauses(aligned=words, energy=_energy(300, low_runs=[(95, 140)]))
    assert all(isinstance(e, PauseEvent) for e in res.events)
    dicts = res.to_event_dicts()
    assert dicts == [PauseEvent(**d).model_dump(mode="json") for d in dicts]
    assert dicts[0]["detection_source"] in {"vad", "alignment", "both"}
    assert dicts[0]["boundary_type"] in {"within_phrase", "cross_sentence", "unknown"}
    assert PauseDetector().config == PauseConfig()


# --------------------------------------------------------------- integration
def _tone(duration_s: float, amplitude: float = 0.5) -> np.ndarray:
    t = np.arange(int(duration_s * 16000), dtype=np.float64) / 16000
    return (amplitude * np.sin(2 * np.pi * 1000.0 * t)).astype(np.float32)


def test_integration_real_energy_on_tone_silence_tone():
    audio = np.concatenate([_tone(1.0), np.zeros(8000, dtype=np.float32), _tone(1.0)])  # silence 1.0-1.5 s
    energy = extract_energy(audio)

    vad_only = detect_pauses(energy=energy)
    assert len(vad_only.events) == 1
    ev = vad_only.events[0]
    assert ev.detection_source == PauseDetectionSource.VAD
    assert 1.0 <= ev.start_s <= 1.05 and 1.45 <= ev.end_s <= 1.5  # window-quantized edges

    words = _aligned([("Hello.", 0.0, 1.0), ("again", 1.5, 2.5)])
    both = detect_pauses(aligned=words, energy=energy)
    assert len(both.events) == 1
    ev = both.events[0]
    assert ev.detection_source == PauseDetectionSource.BOTH
    assert ev.start_s == pytest.approx(1.0) and ev.end_s == pytest.approx(1.5)
    assert ev.boundary_type == PauseBoundaryType.CROSS_SENTENCE
