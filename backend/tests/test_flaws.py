"""Unit tests for evidence attachment and grounded flaws (TASK-053/054, ARCHITECTURE.md §9.9, §21).

Expected evidence values are recomputed here from the raw arrays and the baseline numbers
(NOT by calling the code under test). Covers rate / energy / pause evidence, internal consistency of
z with the reported measurements, detection rules, affected words, warnings, ids and ordering,
source-time shifting, mapping to the public Flaw contract, and every error path.
"""
from __future__ import annotations

import math
from typing import Sequence, Tuple

import numpy as np
import pytest
from app.schemas.common import (
    AlignmentMethod,
    ExplanationMethod,
    FlawType,
    PauseBoundaryType,
    PauseDetectionSource,
)
from app.schemas.contracts import AlignedTranscript, AlignedWord, BaselineStatsRecord
from app.schemas.response import (
    EnergyEvidence,
    Flaw,
    PauseEvidence,
    PauseEvent,
    RateEvidence,
)
from app.services.features.energy import EnergyConfig, EnergyExtractionResult
from app.services.features.rate import extract_rate
from app.services.grounding import (
    CandidateDetectionResult,
    DetectionConfig,
    EvidenceError,
    FlawCandidate,
    GroundedFlaw,
    SeverityConfig,
    compute_severity,
    detect_candidates,
    ground_flaws,
    normalize_features,
    to_api_flaw,
)
from app.services.grounding.flaws import WARNING_ENERGY, WARNING_PAUSE, WARNING_RATE
from pydantic import ValidationError

W, C = PauseBoundaryType.WITHIN_PHRASE, PauseBoundaryType.CROSS_SENTENCE


def _baseline(**overrides) -> BaselineStatsRecord:
    data = dict(
        passage_id="p001", dataset_version="1.0.0", baseline_recording_ids=["rec_a"],
        f0_voiced_hz_mean=150.0, f0_voiced_hz_std=20.0, f0_voiced_hz_p05=120.0, f0_voiced_hz_p95=185.0,
        energy_db_mean=-25.0, energy_db_std=5.0, rate_wpm_mean=100.0, rate_wpm_std=10.0,
        pause_within_phrase_mean_s=0.4, pause_within_phrase_std_s=0.1,
        pause_cross_sentence_mean_s=0.9, pause_cross_sentence_std_s=0.2,
        n_f0_voiced_frames=100, n_energy_frames=100, n_rate_windows=5,
        n_pauses_within_phrase=3, n_pauses_cross_sentence=2, n_pauses_unknown_boundary=0,
        config_snapshot={"energy_frame_selection": "active", "energy_active_threshold_dbfs": -50.0},
        sha256="0" * 64,
    )
    data.update(overrides)
    return BaselineStatsRecord(**data).with_computed_sha256()


def _aligned(specs: Sequence[Tuple[str, float, float]]) -> AlignedTranscript:
    return AlignedTranscript(
        text=" ".join(w for w, _, _ in specs),
        words=[AlignedWord(word=w, start_s=s, end_s=e, confidence=0.9) for w, s, e in specs],
        alignment_method=AlignmentMethod.WHISPERX, total_coverage_pct=0.9,
    )


def _uniform(n_words=40, period=0.4, length=0.3):
    return [(f"w{i}", i * period, i * period + length) for i in range(n_words)]


def _energy(values) -> EnergyExtractionResult:
    return EnergyExtractionResult(
        times_s=np.arange(len(values)) * 0.01, values_db=np.array(values, dtype=np.float64), config=EnergyConfig()
    )


def _pause(start, end, kind, source=PauseDetectionSource.BOTH) -> PauseEvent:
    return PauseEvent(start_s=start, end_s=end, duration_s=end - start, detection_source=source, boundary_type=kind)


def _run(baseline, *, aligned=None, rate=None, energy=None, pauses=None, severity=None, cfg=None):
    nb = normalize_features(baseline, rate=rate, energy=energy, pauses=pauses)
    det = detect_candidates(nb, cfg)
    flaws = ground_flaws(det, nb, baseline, rate=rate, energy=energy, aligned=aligned, severity=severity)
    return nb, det, flaws


# ---------------------------------------------------------------------- rate
def test_too_fast_evidence_matches_independent_recomputation():
    aligned = _aligned(_uniform())
    rate = extract_rate(aligned)
    baseline = _baseline()                                   # rate mean 100, std 10
    nb, det, flaws = _run(baseline, aligned=aligned, rate=rate)

    (flaw,) = flaws
    assert flaw.type == FlawType.TOO_FAST and flaw.flaw_id == "flaw_001"
    ev = flaw.evidence
    assert isinstance(ev, RateEvidence)

    wpm = rate.words_per_min                                  # four windows, all flagged
    mean_wpm = float(np.mean(wpm))
    z = (wpm - 100.0) / 10.0
    assert ev.rate_participant_wpm == pytest.approx(mean_wpm, abs=1e-4)
    assert ev.rate_baseline_mean_wpm == 100.0 and ev.rate_baseline_std_wpm == 10.0
    assert ev.rate_delta_wpm == pytest.approx(mean_wpm - 100.0, abs=1e-4)
    assert ev.rate_delta_pct == pytest.approx(mean_wpm - 100.0, abs=1e-3)          # baseline mean is 100
    assert ev.rate_z_score == pytest.approx(float(np.mean(z)), abs=1e-4)
    assert ev.peak_z_score == pytest.approx(float(z[np.argmax(np.abs(z))]), abs=1e-4)
    assert ev.word_count_in_window == 40
    assert ev.window_duration_s == pytest.approx(15.9)
    assert (flaw.start_s, flaw.end_s) == (0.0, 15.9) and flaw.duration_s == 15.9
    assert len(flaw.affected_words) == 40 and flaw.affected_words[0] == "w0"
    assert flaw.warnings == (WARNING_RATE,)
    assert flaw.rule.feature == "rate_z" and flaw.rule.direction == "above"
    assert flaw.rule.threshold_z == 2.0 and flaw.rule.min_duration_s == 0.5
    assert flaw.severity == 1.0                                # |z| >> 4 and 15.9 s flagged
    assert flaw.reliability == 1.0 and flaw.low_confidence is False


def test_too_slow_has_negative_deltas_and_a_below_rule():
    aligned = _aligned(_uniform())
    rate = extract_rate(aligned)
    _, _, (flaw,) = _run(_baseline(rate_wpm_mean=300.0), aligned=aligned, rate=rate)
    ev = flaw.evidence
    assert flaw.type == FlawType.TOO_SLOW
    assert ev.rate_delta_wpm < 0 and ev.rate_delta_pct == pytest.approx(100 * ev.rate_delta_wpm / 300.0, abs=1e-3)
    assert ev.rate_z_score < -2 and ev.peak_z_score <= ev.rate_z_score + 1e-6        # peak is the most negative
    assert flaw.rule.direction == "below" and flaw.rule.threshold_z == -2.0


def test_reported_z_is_consistent_with_reported_measurements():
    aligned = _aligned(_uniform())
    rate = extract_rate(aligned)
    _, _, (flaw,) = _run(_baseline(rate_wpm_mean=90.0, rate_wpm_std=7.5), aligned=aligned, rate=rate)
    ev = flaw.evidence
    assert (ev.rate_participant_wpm - ev.rate_baseline_mean_wpm) / ev.rate_baseline_std_wpm == pytest.approx(
        ev.rate_z_score, abs=1e-3
    )


def test_rate_evidence_needs_rate_and_alignment():
    aligned = _aligned(_uniform())
    rate = extract_rate(aligned)
    baseline = _baseline()
    nb = normalize_features(baseline, rate=rate)
    det = detect_candidates(nb)
    with pytest.raises(EvidenceError, match="rate"):
        ground_flaws(det, nb, baseline, aligned=aligned)                                # no raw rate result
    with pytest.raises(EvidenceError, match="aligned"):
        ground_flaws(det, nb, baseline, rate=rate)                                      # no alignment


# -------------------------------------------------------------------- energy
def test_low_energy_evidence_and_severity():
    values = [-25.0] * 50 + [-45.0] * 120 + [-25.0] * 30
    energy = _energy(values)
    nb, det, flaws = _run(_baseline(), energy=energy)
    (flaw,) = flaws
    ev = flaw.evidence
    assert isinstance(ev, EnergyEvidence) and flaw.type == FlawType.LOW_ENERGY
    assert ev.energy_mean_db == -45.0 and ev.energy_baseline_mean_db == -25.0 and ev.energy_baseline_std_db == 5.0
    assert ev.energy_delta_db == -20.0 and ev.energy_z_score == -4.0
    assert ev.window_duration_s == pytest.approx(1.2)
    assert (flaw.start_s, flaw.end_s) == (0.495, 1.695)
    assert flaw.severity == pytest.approx(0.24)                  # magnitude 1.0 x (1.2 s / 5 s)
    assert flaw.rule.feature == "energy_z" and flaw.rule.direction == "below" and flaw.rule.threshold_z == -2.0
    assert flaw.warnings == (WARNING_ENERGY,) and flaw.affected_words == ()


def test_high_energy_uses_the_above_rule_and_partial_magnitude():
    energy = _energy([-25.0] * 50 + [-10.0] * 120 + [-25.0] * 30)               # z = +3
    _, _, (flaw,) = _run(_baseline(), energy=energy)
    assert flaw.type == FlawType.HIGH_ENERGY
    assert flaw.evidence.energy_delta_db == 15.0 and flaw.evidence.energy_z_score == 3.0
    assert flaw.rule.direction == "above" and flaw.rule.threshold_z == 2.0
    assert flaw.severity == pytest.approx((3.0 - 1.0) / 3.0 * 0.24, abs=1e-4)


def test_energy_evidence_averages_only_the_flagged_frames_across_gaps():
    # Two quiet stretches bridged by uncovered frames: the mean covers the flagged frames only.
    values = [-25.0] * 20 + [-40.0] * 30 + [-90.0] * 10 + [-50.0] * 30 + [-25.0] * 20
    _, _, (flaw,) = _run(_baseline(), energy=_energy(values))
    expected = (30 * -40.0 + 30 * -50.0) / 60.0
    assert flaw.evidence.energy_mean_db == pytest.approx(expected)
    assert flaw.evidence.energy_z_score == pytest.approx((expected + 25.0) / 5.0, abs=1e-4)


def test_energy_evidence_needs_the_raw_energy_result():
    energy = _energy([-25.0] * 50 + [-45.0] * 120 + [-25.0] * 30)
    baseline = _baseline()
    nb = normalize_features(baseline, energy=energy)
    with pytest.raises(EvidenceError, match="energy"):
        ground_flaws(detect_candidates(nb), nb, baseline)


# --------------------------------------------------------------------- pauses
def test_within_phrase_pause_evidence_and_words():
    aligned = _aligned([("a", 0.0, 1.0), ("b", 2.0, 3.0)])
    _, _, (flaw,) = _run(_baseline(), aligned=aligned, pauses=[_pause(1.0, 2.0, W)])
    ev = flaw.evidence
    assert isinstance(ev, PauseEvidence) and flaw.type == FlawType.EXCESSIVE_PAUSE
    assert ev.pause_duration_s == 1.0 and ev.pause_baseline_mean_s == 0.4 and ev.pause_baseline_std_s == 0.1
    assert ev.pause_delta_s == 0.6 and ev.pause_z_score == pytest.approx(6.0)
    assert ev.boundary_type == W and ev.detection_source == PauseDetectionSource.BOTH
    assert flaw.affected_words == ("a", "b")
    assert flaw.severity == 1.0                                  # |z| >= 4 and no duration component
    assert flaw.rule.threshold_z == 2.0 and flaw.rule.feature == "pause_z" and flaw.rule.min_duration_s == 0.0
    assert flaw.warnings == (WARNING_PAUSE,)


def test_cross_sentence_pause_uses_its_own_threshold_and_baseline():
    aligned = _aligned([("end.", 0.0, 1.0), ("Next", 2.6, 3.0)])
    _, _, (flaw,) = _run(_baseline(), aligned=aligned, pauses=[_pause(1.0, 2.6, C)])
    assert flaw.evidence.pause_baseline_mean_s == 0.9 and flaw.evidence.pause_baseline_std_s == 0.2
    assert flaw.evidence.pause_z_score == pytest.approx(3.5)
    assert flaw.rule.threshold_z == 2.5


def test_pause_inside_a_word_reports_that_word_once_and_edge_pauses_one_word():
    inside = _aligned([("x", 0.0, 0.5), ("stretched", 0.6, 3.0), ("y", 3.1, 3.5)])
    _, _, (flaw,) = _run(_baseline(), aligned=inside, pauses=[_pause(1.0, 2.0, W, PauseDetectionSource.VAD)])
    assert flaw.affected_words == ("stretched",)

    before_first = _aligned([("only", 2.0, 2.5)])
    _, _, (flaw,) = _run(_baseline(), aligned=before_first, pauses=[_pause(0.5, 1.5, W)])
    assert flaw.affected_words == ("only",)


def test_pause_that_overlaps_the_next_word_onset_still_reports_both_neighbours():
    # A VAD-based pause can extend slightly into the following word: [1.0, 2.1] vs "b" starting at 2.0.
    aligned = _aligned([("a", 0.0, 1.0), ("b", 2.0, 3.0), ("c", 3.1, 3.5)])
    _, _, (flaw,) = _run(_baseline(), aligned=aligned, pauses=[_pause(1.0, 2.1, W)])
    assert flaw.affected_words == ("a", "b")
    # ...and one that overlaps the previous word's tail: [0.9, 2.0] with "a" ending at 1.0.
    _, _, (flaw,) = _run(_baseline(), aligned=aligned, pauses=[_pause(0.9, 2.0, W)])
    assert flaw.affected_words == ("a", "b")


def test_pause_flaw_without_alignment_has_no_words_but_full_evidence():
    _, _, (flaw,) = _run(_baseline(), pauses=[_pause(1.0, 2.0, W)])
    assert flaw.affected_words == () and flaw.evidence.pause_z_score == pytest.approx(6.0)


# ---------------------------------------------------------- ordering and ids
def test_flaws_are_ordered_by_time_and_numbered_stably():
    aligned = _aligned([("a", 0.0, 1.0), ("b", 4.0, 5.0)] + [(f"c{i}", 6 + i * 0.4, 6.3 + i * 0.4) for i in range(30)])
    pause_flaw_start = 1.0
    energy = _energy([-25.0] * 600 + [-45.0] * 120 + [-25.0] * 30)               # low energy at 6.0 s
    baseline = _baseline()
    _, det, flaws = _run(baseline, aligned=aligned, energy=energy, pauses=[_pause(pause_flaw_start, 4.0, W)])
    assert [f.flaw_id for f in flaws] == [f"flaw_{i:03d}" for i in range(1, len(flaws) + 1)]
    assert [f.start_s for f in flaws] == sorted(f.start_s for f in flaws)
    assert flaws[0].type == FlawType.EXCESSIVE_PAUSE and flaws[0].flaw_id == "flaw_001"
    assert {f.type for f in flaws} >= {FlawType.EXCESSIVE_PAUSE, FlawType.LOW_ENERGY}


def test_unsorted_candidates_are_ordered_before_numbering():
    baseline = _baseline()
    energy = _energy([-25.0] * 50 + [-45.0] * 120 + [-25.0] * 400 + [-45.0] * 120 + [-25.0] * 30)
    nb = normalize_features(baseline, energy=energy)
    det = detect_candidates(nb)
    assert len(det.candidates) == 2
    reversed_det = CandidateDetectionResult(list(reversed(det.candidates)), det.skipped, det.config)
    flaws = ground_flaws(reversed_det, nb, baseline, energy=energy)
    assert [f.flaw_id for f in flaws] == ["flaw_001", "flaw_002"]
    assert flaws[0].start_s < flaws[1].start_s


def test_affected_words_are_chosen_by_midpoint_not_by_start_time():
    # Low-energy interval is [0.495, 1.695]. Midpoints: wa 0.5 (inside), wc 1.0 (inside), wb 1.9 (outside).
    aligned = _aligned([("wa", 0.3, 0.7), ("wc", 0.8, 1.2), ("wb", 1.6, 2.2)])
    energy = _energy([-25.0] * 50 + [-45.0] * 120 + [-25.0] * 30)
    _, _, (flaw,) = _run(_baseline(), aligned=aligned, energy=energy)
    assert (flaw.start_s, flaw.end_s) == (0.495, 1.695)
    assert flaw.affected_words == ("wa", "wc")


def test_determinism_and_inputs_untouched():
    aligned = _aligned(_uniform())
    rate = extract_rate(aligned)
    before = rate.words_per_min.copy()
    a = _run(_baseline(), aligned=aligned, rate=rate)[2]
    b = _run(_baseline(), aligned=aligned, rate=rate)[2]
    assert a == b
    assert np.array_equal(rate.words_per_min, before)


def test_severity_config_is_passed_through():
    energy = _energy([-25.0] * 50 + [-45.0] * 120 + [-25.0] * 30)
    cfg = SeverityConfig(duration_severe_s={FlawType.LOW_ENERGY: 1.2})
    _, det, (flaw,) = _run(_baseline(), energy=energy, severity=cfg)
    assert flaw.severity == pytest.approx(1.0)
    assert flaw.severity == compute_severity(det.candidates[0], cfg)


def test_rule_reflects_the_detection_config_that_produced_the_candidates():
    energy = _energy([-25.0] * 50 + [-45.0] * 120 + [-25.0] * 30)
    cfg = DetectionConfig(z_energy=3.0, min_duration_s={FlawType.LOW_ENERGY: 0.8})
    _, _, (flaw,) = _run(_baseline(), energy=energy, cfg=cfg)
    assert flaw.rule.threshold_z == -3.0 and flaw.rule.min_duration_s == 0.8


# ----------------------------------------------------------- shift / API map
def test_shifted_moves_only_the_times_and_does_not_mutate():
    energy = _energy([-25.0] * 50 + [-45.0] * 120 + [-25.0] * 30)
    _, _, (flaw,) = _run(_baseline(), energy=energy)
    moved = flaw.shifted(2.5)
    assert (moved.start_s, moved.end_s) == (2.995, 4.195)
    assert (flaw.start_s, flaw.end_s) == (0.495, 1.695)
    assert moved.duration_s == flaw.duration_s and moved.evidence == flaw.evidence
    assert moved.flaw_id == flaw.flaw_id and moved.severity == flaw.severity
    assert flaw.shifted(0.0) == flaw
    with pytest.raises(ValueError):
        flaw.shifted(float("nan"))
    with pytest.raises(Exception):
        flaw.start_s = 9.9                                          # frozen


def test_to_api_flaw_builds_a_valid_public_flaw():
    aligned = _aligned(_uniform())
    rate = extract_rate(aligned)
    _, _, (flaw,) = _run(_baseline(), aligned=aligned, rate=rate)
    api = to_api_flaw(flaw, "Explanation text.", "Recommendation text.")
    assert isinstance(api, Flaw)
    assert api.explanation_method == ExplanationMethod.TEMPLATE
    assert (api.flaw_id, api.type, api.start_s, api.end_s, api.duration_s) == (
        flaw.flaw_id, flaw.type, flaw.start_s, flaw.end_s, flaw.duration_s)
    assert api.evidence == flaw.evidence and api.rule == flaw.rule
    assert api.affected_words == list(flaw.affected_words) and api.warnings == list(flaw.warnings)
    assert Flaw.model_validate_json(api.model_dump_json()) == api
    with pytest.raises(ValidationError):
        to_api_flaw(flaw, "", "Recommendation text.")


# ------------------------------------------------------------------- errors
def test_unsupported_flaw_type_has_no_evidence_builder():
    baseline = _baseline()
    nb = normalize_features(baseline)
    cand = FlawCandidate(FlawType.FLAT_PITCH, 0.0, 1.0, 3.0, -3.0, "f0_std_z", (0,), ((0.0, 1.0),))
    det = CandidateDetectionResult(candidates=[cand], skipped={}, config=DetectionConfig())
    with pytest.raises(EvidenceError, match="flat_pitch"):
        ground_flaws(det, nb, baseline)


def test_mismatched_baseline_is_rejected():
    energy = _energy([-25.0] * 50 + [-45.0] * 120 + [-25.0] * 30)
    baseline = _baseline()
    nb = normalize_features(baseline, energy=energy)
    det = detect_candidates(nb)
    with pytest.raises(EvidenceError, match="baseline"):
        ground_flaws(det, nb, _baseline(rate_wpm_mean=111.0), energy=energy)


def test_raw_and_normalized_arrays_must_line_up_and_indices_must_exist():
    energy = _energy([-25.0] * 50 + [-45.0] * 120 + [-25.0] * 30)
    baseline = _baseline()
    nb = normalize_features(baseline, energy=energy)
    det = detect_candidates(nb)
    with pytest.raises(EvidenceError, match="entries"):
        ground_flaws(det, nb, baseline, energy=_energy([-25.0] * 10))
    bad = FlawCandidate(FlawType.LOW_ENERGY, 0.0, 1.0, 3.0, -3.0, "energy_z", (999,), ((0.0, 1.0),))
    with pytest.raises(EvidenceError, match="outside"):
        ground_flaws(CandidateDetectionResult([bad], {}, DetectionConfig()), nb, baseline, energy=energy)


def test_detection_result_without_config_is_rejected():
    baseline = _baseline()
    nb = normalize_features(baseline)
    with pytest.raises(TypeError):
        ground_flaws(CandidateDetectionResult(candidates=[], skipped={}), nb, baseline)
    with pytest.raises(TypeError):
        ground_flaws([], nb, baseline)


def test_no_candidates_gives_no_flaws():
    baseline = _baseline()
    nb = normalize_features(baseline)
    assert ground_flaws(detect_candidates(nb), nb, baseline) == []
