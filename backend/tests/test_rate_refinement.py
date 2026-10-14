"""Tests for the narrowing of rate findings to the words that deviate and for the cap on long silences.

The speech here is hand-made so that every expected number can be worked out on paper: words of 0.25 s whose start-to-start "slot" is 0.6 s at the
baseline pace (100 words/min, std 10) and 0.3 s in a fast stretch (200 words/min), 1.2 s in a slow one. Covers a fast and a slow stretch located on
their own words, the evidence that describes the narrowed stretch, every case that must keep the window interval, the length-scaled z-score, the
maximum-subarray behaviour (a short hiccup inside a stretch, two separate stretches), the cap on long silences in the rate and its effect on
findings, the clipping of findings to the audio, configuration errors and determinism.
"""
from __future__ import annotations

import math
from typing import List, Sequence, Tuple

import numpy as np
import pytest
from app.schemas.common import AlignmentMethod, FlawType
from app.schemas.contracts import AlignedTranscript, AlignedWord, BaselineStatsRecord
from app.services.features.rate import RateConfig, extract_rate
from app.services.grounding import (
    DetectionConfig,
    EvidenceError,
    FlawCandidate,
    clip_to_audio,
    detect_candidates,
    ground_flaws,
    normalize_features,
    refine_rate_candidates,
)
from app.services.grounding.candidates import _best_run
from app.services.grounding.flaws import WARNING_RATE, WARNING_RATE_NARROWED

LENGTH = 0.25


def baseline(mean: float = 100.0, std: float = 10.0) -> BaselineStatsRecord:
    return BaselineStatsRecord(
        passage_id="p001", dataset_version="1.0.0", baseline_recording_ids=["rec_a"],
        f0_voiced_hz_mean=150.0, f0_voiced_hz_std=20.0, f0_voiced_hz_p05=120.0, f0_voiced_hz_p95=185.0,
        energy_db_mean=-25.0, energy_db_std=5.0, rate_wpm_mean=mean, rate_wpm_std=std,
        pause_within_phrase_mean_s=0.4, pause_within_phrase_std_s=0.1, pause_cross_sentence_mean_s=0.9, pause_cross_sentence_std_s=0.2,
        n_f0_voiced_frames=100, n_energy_frames=100, n_rate_windows=5, n_pauses_within_phrase=3, n_pauses_cross_sentence=2,
        n_pauses_unknown_boundary=0, config_snapshot={"energy_frame_selection": "active", "energy_active_threshold_dbfs": -50.0}, sha256="0" * 64,
    ).with_computed_sha256()


def speech(slots: Sequence[float], length: float = LENGTH) -> AlignedTranscript:
    """Words whose start-to-start slots are `slots` (word i begins slots[i-1] after word i-1). The first word starts at 0.05 s, so that no word
    starts exactly on the boundary of a rolling window, where a floating-point sum could tip it into the neighbouring window."""
    starts = 0.05 + np.concatenate(([0.0], np.cumsum(slots[:-1])))
    words = [AlignedWord(word=f"w{i}", start_s=float(s), end_s=float(s + length), confidence=0.9) for i, s in enumerate(starts)]
    return AlignedTranscript(text=" ".join(w.word for w in words), words=words, alignment_method=AlignmentMethod.WHISPERX, total_coverage_pct=0.9)


def with_stretch(n: int, first: int, last: int, slot: float, normal: float = 0.6) -> List[float]:
    return [slot if first <= i <= last else normal for i in range(n)]


def analyse(aligned: AlignedTranscript, base: BaselineStatsRecord = None, cfg: DetectionConfig = None, rate_cfg: RateConfig = None, refine: bool = True):
    base = base or baseline()
    rate = extract_rate(aligned, rate_cfg)
    nb = normalize_features(base, rate=rate)
    det = detect_candidates(nb, cfg, aligned=aligned if refine else None, baseline=base if refine else None)
    return rate, nb, det


def only(det, flaw_type):
    return [c for c in det.candidates if c.type == flaw_type]


# ---------------------------------------------------------------------------------------------------------------------------------
# A stretch is located on its own words
# ---------------------------------------------------------------------------------------------------------------------------------

def test_a_fast_stretch_is_narrowed_to_its_own_words():
    aligned = speech(with_stretch(60, 20, 35, 0.3))
    _, _, det = analyse(aligned)
    (cand,) = only(det, FlawType.TOO_FAST)
    first, last = aligned.words[20], aligned.words[35]
    assert cand.start_s == pytest.approx(first.start_s) and cand.end_s == pytest.approx(last.end_s)        # 12.0 to 16.75
    expected_rate = 16 * 60.0 / (last.end_s - first.start_s)
    assert cand.stretch_rate_wpm == pytest.approx(expected_rate)
    assert cand.mean_z == pytest.approx((expected_rate - 100.0) / 10.0)                                      # 16 words >= the 13.3 words of a window
    assert cand.flagged_intervals == ((cand.start_s, cand.end_s),) and cand.flagged_duration_s == pytest.approx(cand.duration_s)
    assert cand.peak_z >= abs(cand.mean_z) - 1e-9 and cand.member_indices
    _, _, wide = analyse(aligned, refine=False)
    (window_cand,) = only(wide, FlawType.TOO_FAST)
    assert window_cand.stretch_rate_wpm is None and window_cand.duration_s > 2 * cand.duration_s            # the old, window-wide interval


def test_a_slow_stretch_is_narrowed_to_its_own_words():
    aligned = speech(with_stretch(60, 20, 31, 1.2))
    _, _, det = analyse(aligned)
    (cand,) = only(det, FlawType.TOO_SLOW)
    first, last = aligned.words[20], aligned.words[31]
    assert cand.start_s == pytest.approx(first.start_s) and cand.end_s == pytest.approx(last.end_s)
    assert cand.stretch_rate_wpm == pytest.approx(12 * 60.0 / (last.end_s - first.start_s)) and cand.mean_z < -2.0
    assert not only(det, FlawType.TOO_FAST)


def test_the_stretch_rate_follows_the_definition_of_the_window_rate():
    aligned = speech(with_stretch(60, 20, 35, 0.3))
    _, _, det = analyse(aligned)
    (cand,) = only(det, FlawType.TOO_FAST)
    words = [w for w in aligned.words if cand.start_s - 1e-9 <= w.start_s and w.end_s <= cand.end_s + 1e-9]
    assert len(words) == 16
    assert cand.stretch_rate_wpm == pytest.approx(len(words) / (words[-1].end_s - words[0].start_s) * 60.0)


def test_a_stretch_shorter_than_a_window_word_count_is_scored_against_a_scaled_spread():
    """With only 8 words the stretch has fewer words than the ~13.3 of a baseline window, so its spread is std * sqrt(13.3 / 8)."""
    aligned = speech(with_stretch(60, 20, 27, 0.2))                       # 8 words, 300 words/min over 8 * 0.2 + ... seconds
    _, _, det = analyse(aligned)
    (cand,) = only(det, FlawType.TOO_FAST)
    n = round(cand.stretch_rate_wpm * (cand.end_s - cand.start_s) / 60.0)
    assert n == 8
    window_words = 100.0 * 8.0 / 60.0
    assert cand.mean_z == pytest.approx((cand.stretch_rate_wpm - 100.0) / (10.0 * math.sqrt(window_words / n)))


def test_a_brief_hiccup_inside_a_fast_stretch_does_not_split_it():
    slots = with_stretch(80, 20, 45, 0.3)
    slots[30] = 0.6                                                       # one ordinary-length word in the middle
    aligned = speech(slots)
    _, _, det = analyse(aligned)
    (cand,) = only(det, FlawType.TOO_FAST)
    assert cand.start_s == pytest.approx(aligned.words[20].start_s) and cand.end_s == pytest.approx(aligned.words[45].end_s)


def test_two_stretches_far_apart_inside_one_flagged_region_stay_two_findings():
    slots = [0.3 if (10 <= i <= 25 or 70 <= i <= 85) else 0.6 for i in range(120)]
    aligned = speech(slots)
    base = baseline()
    rate = extract_rate(aligned)
    nb = normalize_features(base, rate=rate)
    cfg = DetectionConfig()
    whole = FlawCandidate(FlawType.TOO_FAST, aligned.words[10].start_s, aligned.words[85].end_s, 10.0, 10.0, "rate_z",
                          (0, 1), ((aligned.words[10].start_s, aligned.words[85].end_s),))
    refined = refine_rate_candidates([whole], nb, aligned, base, cfg)
    assert len(refined) == 2
    assert refined[0].start_s == pytest.approx(aligned.words[10].start_s) and refined[0].end_s == pytest.approx(aligned.words[25].end_s)
    assert refined[1].start_s == pytest.approx(aligned.words[70].start_s) and refined[1].end_s == pytest.approx(aligned.words[85].end_s)


# ---------------------------------------------------------------------------------------------------------------------------------
# Evidence describes the narrowed stretch
# ---------------------------------------------------------------------------------------------------------------------------------

def test_the_evidence_of_a_narrowed_finding_describes_the_stretch_it_labels():
    aligned = speech(with_stretch(60, 20, 35, 0.3))
    base = baseline()
    rate, nb, det = analyse(aligned, base)
    (flaw,) = ground_flaws(det, nb, base, rate=rate, aligned=aligned)
    (cand,) = only(det, FlawType.TOO_FAST)
    ev = flaw.evidence
    assert ev.rate_participant_wpm == pytest.approx(cand.stretch_rate_wpm, abs=1e-3)
    assert ev.rate_delta_wpm == pytest.approx(cand.stretch_rate_wpm - 100.0, abs=1e-3)
    assert ev.rate_delta_pct == pytest.approx(cand.stretch_rate_wpm - 100.0, abs=1e-3)                      # baseline mean is 100
    assert ev.rate_z_score == pytest.approx(cand.mean_z, abs=1e-3) and ev.peak_z_score == pytest.approx(cand.peak_z, abs=1e-3)
    assert ev.window_duration_s == pytest.approx(flaw.end_s - flaw.start_s, abs=1e-3)
    assert ev.word_count_in_window == 16 and flaw.affected_words == tuple(f"w{i}" for i in range(20, 36))
    assert flaw.warnings == (WARNING_RATE_NARROWED,)
    assert flaw.severity > 0.0


def test_an_unnarrowed_finding_keeps_the_window_evidence_and_warning():
    aligned = speech(with_stretch(60, 20, 35, 0.3))
    base = baseline()
    rate, nb, det = analyse(aligned, base, refine=False)
    flaws = ground_flaws(det, nb, base, rate=rate, aligned=aligned)
    (flaw,) = [f for f in flaws if f.type == FlawType.TOO_FAST]
    (cand,) = only(det, FlawType.TOO_FAST)
    idx = list(cand.member_indices)
    assert flaw.evidence.rate_participant_wpm == pytest.approx(float(np.mean(rate.words_per_min[idx])), abs=1e-3)
    assert flaw.warnings == (WARNING_RATE,)


# ---------------------------------------------------------------------------------------------------------------------------------
# When the window interval is kept
# ---------------------------------------------------------------------------------------------------------------------------------

def test_without_the_words_or_the_baseline_nothing_is_narrowed():
    aligned = speech(with_stretch(60, 20, 35, 0.3))
    base = baseline()
    nb = normalize_features(base, rate=extract_rate(aligned))
    assert all(c.stretch_rate_wpm is None for c in detect_candidates(nb).candidates)
    assert all(c.stretch_rate_wpm is None for c in detect_candidates(nb, aligned=aligned).candidates)
    assert all(c.stretch_rate_wpm is None for c in detect_candidates(nb, baseline=base).candidates)


def test_narrowing_can_be_switched_off():
    aligned = speech(with_stretch(60, 20, 35, 0.3))
    _, _, det = analyse(aligned, cfg=DetectionConfig(refine_rate=False))
    assert all(c.stretch_rate_wpm is None for c in det.candidates) and det.candidates


def test_a_burst_shorter_than_the_minimum_word_count_keeps_the_window_interval():
    aligned = speech(with_stretch(60, 20, 25, 0.1))                          # 6 very fast words: flagged by the window, too short to locate
    _, _, det = analyse(aligned)
    fast = only(det, FlawType.TOO_FAST)
    if fast:                                                                  # the window may or may not clear the threshold; if it does, it stays wide
        assert all(c.stretch_rate_wpm is None for c in fast)
    _, _, loose = analyse(aligned, cfg=DetectionConfig(refine_min_words=5))
    narrowed = [c for c in only(loose, FlawType.TOO_FAST) if c.stretch_rate_wpm is not None]
    assert all(c.end_s - c.start_s < 3.0 for c in narrowed)


def test_a_region_with_no_qualifying_run_keeps_the_window_candidate():
    aligned = speech([0.6] * 60)
    base = baseline()
    nb = normalize_features(base, rate=extract_rate(aligned))
    window = FlawCandidate(FlawType.TOO_FAST, 8.0, 16.0, 3.0, 3.0, "rate_z", (0,), ((8.0, 16.0),))
    assert refine_rate_candidates([window], nb, aligned, base, DetectionConfig()) == [window]


def test_other_candidates_pass_through_untouched():
    aligned = speech([0.6] * 60)
    base = baseline()
    nb = normalize_features(base, rate=extract_rate(aligned))
    energy = FlawCandidate(FlawType.LOW_ENERGY, 1.0, 2.0, 3.0, -3.0, "energy_z", (1, 2), ((1.0, 2.0),))
    assert refine_rate_candidates([energy], nb, aligned, base, DetectionConfig()) == [energy]


def test_too_few_aligned_words_or_an_unusable_spread_leave_candidates_alone():
    base = baseline()
    short = speech([0.6] * 5)
    nb = normalize_features(base, rate=extract_rate(speech([0.6] * 60)))
    window = FlawCandidate(FlawType.TOO_FAST, 0.0, 3.0, 3.0, 3.0, "rate_z", (0,), ((0.0, 3.0),))
    assert refine_rate_candidates([window], nb, short, base, DetectionConfig()) == [window]
    broken = base.model_copy(update={"rate_wpm_std": 0.0})
    assert refine_rate_candidates([window], nb, speech([0.6] * 60), broken, DetectionConfig()) == [window]


def test_the_baseline_must_be_the_one_the_features_were_normalized_with():
    aligned = speech(with_stretch(60, 20, 35, 0.3))
    nb = normalize_features(baseline(), rate=extract_rate(aligned))
    other = baseline(mean=120.0)
    with pytest.raises(ValueError, match="not the one"):
        detect_candidates(nb, aligned=aligned, baseline=other)


def test_configuration_errors():
    with pytest.raises(ValueError, match="refine_min_words"):
        DetectionConfig(refine_min_words=1)
    with pytest.raises(ValueError, match="max_gap_s"):
        RateConfig(max_gap_s=0.0)
    with pytest.raises(ValueError, match="max_gap_s"):
        RateConfig(max_gap_s=float("nan"))


def test_narrowing_is_deterministic():
    aligned = speech(with_stretch(60, 20, 35, 0.3))
    first = analyse(aligned)[2].candidates
    assert first == analyse(aligned)[2].candidates


# ---------------------------------------------------------------------------------------------------------------------------------
# Long silences are not slow speech
# ---------------------------------------------------------------------------------------------------------------------------------

def silent_gap_speech(gap_after: int, gap_s: float) -> AlignedTranscript:
    slots = [0.6] * 60
    slots[gap_after] = 0.6 + gap_s
    return speech(slots)


def test_a_long_silence_counts_as_at_most_the_cap_in_the_rate():
    aligned = silent_gap_speech(30, 3.5)                                   # a 3.85 s silence after word 30
    capped = extract_rate(aligned)
    uncapped = extract_rate(aligned, RateConfig(max_gap_s=100.0))
    k = int(np.argmin(np.abs(capped.times_s - aligned.words[30].end_s)))
    gap = aligned.words[31].start_s - aligned.words[30].end_s                    # 0.6 + 3.5 - 0.25 = 3.85 s of silence
    assert gap == pytest.approx(3.85)
    assert capped.speaking_duration_s[k] == pytest.approx(capped.effective_duration_s[k] - (gap - 1.0))
    assert capped.words_per_min[k] == pytest.approx(capped.word_count[k] / capped.speaking_duration_s[k] * 60.0)
    assert uncapped.speaking_duration_s[k] == pytest.approx(uncapped.effective_duration_s[k])
    assert capped.words_per_min[k] > uncapped.words_per_min[k]
    assert np.array_equal(capped.effective_duration_s, uncapped.effective_duration_s)                    # the span used to place findings is unchanged


def test_gaps_up_to_the_cap_count_in_full():
    aligned = silent_gap_speech(30, 0.5)                                   # a 0.75 s silence: natural, kept
    r = extract_rate(aligned)
    assert np.allclose(r.speaking_duration_s, r.effective_duration_s)


def test_a_deliberate_long_pause_no_longer_makes_the_speech_look_slow():
    aligned = silent_gap_speech(30, 3.5)
    _, _, det = analyse(aligned)
    assert not only(det, FlawType.TOO_SLOW)
    _, _, old = analyse(aligned, rate_cfg=RateConfig(max_gap_s=100.0))
    assert only(old, FlawType.TOO_SLOW)                                    # without the cap the pause was reported as slow speech as well


def test_the_cap_reaches_the_detector_through_the_normalized_bundle():
    aligned = speech([0.6] * 60)
    nb = normalize_features(baseline(), rate=extract_rate(aligned, RateConfig(max_gap_s=2.0)))
    assert nb.rate_max_gap_s == 2.0
    assert normalize_features(baseline()).rate_max_gap_s is None


def test_the_narrowing_counts_a_long_silence_inside_a_slow_stretch_the_way_the_rate_does():
    slots = with_stretch(80, 20, 35, 1.2)
    slots[28] = 4.0                                                        # a long silence inside the slow stretch
    aligned = speech(slots)
    base = baseline()
    nb = normalize_features(base, rate=extract_rate(aligned))
    first, last = aligned.words[20], aligned.words[35]
    region = FlawCandidate(FlawType.TOO_SLOW, first.start_s, last.end_s, 4.0, -4.0, "rate_z", (3, 4), ((first.start_s, last.end_s),))
    (cand,) = refine_rate_candidates([region], nb, aligned, base, DetectionConfig())
    gap = aligned.words[29].start_s - aligned.words[28].end_s                 # 4.0 - 0.25 = 3.75 s, of which only 1.0 s counts
    assert gap == pytest.approx(3.75)
    assert cand.start_s == pytest.approx(first.start_s) and cand.end_s == pytest.approx(last.end_s)         # the silence did not split the stretch
    assert cand.stretch_rate_wpm == pytest.approx(60.0 * 16 / ((last.end_s - first.start_s) - (gap - 1.0)), rel=1e-9)


# ---------------------------------------------------------------------------------------------------------------------------------
# The search itself
# ---------------------------------------------------------------------------------------------------------------------------------

def test_best_run_is_the_contiguous_run_with_the_largest_positive_sum():
    assert _best_run(np.array([-1.0, 2.0, 3.0, -1.0, -5.0])) == (1, 2)
    assert _best_run(np.array([1.0, -0.5, 1.0])) == (0, 2)                      # a small dip is bridged
    assert _best_run(np.array([1.0, -5.0, 1.0])) == (0, 0)                      # a tie goes to the earliest run
    assert _best_run(np.array([-1.0, -2.0])) is None and _best_run(np.array([0.0, 0.0])) is None and _best_run(np.array([])) is None


def region(aligned, first, last, members=(3,)):
    return FlawCandidate(FlawType.TOO_FAST, aligned.words[first].start_s, aligned.words[last].end_s, 5.0, 5.0, "rate_z", members,
                         ((aligned.words[first].start_s, aligned.words[last].end_s),))


def refine(aligned, parent, base=None):
    base = base or baseline()
    nb = normalize_features(base, rate=extract_rate(aligned))
    return refine_rate_candidates([parent], nb, aligned, base, DetectionConfig())


def test_the_search_stays_inside_the_flagged_region():
    aligned = speech(with_stretch(80, 10, 60, 0.3))                         # the fast stretch is much longer than the region that was flagged
    (inner,) = refine(aligned, region(aligned, 25, 40))
    assert inner.start_s == pytest.approx(aligned.words[25].start_s) and inner.end_s == pytest.approx(aligned.words[40].end_s)
    (right,) = refine(aligned, region(aligned, 5, 30))
    assert right.start_s == pytest.approx(aligned.words[10].start_s) and right.end_s == pytest.approx(aligned.words[30].end_s)


@pytest.mark.parametrize("left_words,right_words", [(12, 20), (20, 12)])
def test_a_second_stretch_is_found_whichever_side_the_stronger_one_is_on(left_words, right_words):
    slots = [0.3 if (10 <= i < 10 + left_words or 70 <= i < 70 + right_words) else 0.6 for i in range(120)]
    aligned = speech(slots)
    strongest = int(np.argmax(normalize_features(baseline(), rate=extract_rate(aligned)).rate_z))      # the window the halfway slot is derived from
    refined = refine(aligned, region(aligned, 5, 100, members=(strongest,)))
    assert len(refined) == 2
    found = [t for c in refined for t in (c.start_s, c.end_s)]
    expected = [aligned.words[10].start_s, aligned.words[10 + left_words - 1].end_s, aligned.words[70].start_s, aligned.words[70 + right_words - 1].end_s]
    assert found == pytest.approx(expected)


def test_a_stretch_that_is_not_clearly_beyond_the_threshold_is_not_reported_as_narrowed():
    aligned = speech(with_stretch(80, 20, 40, 0.52))                         # about 118 words/min against 100 +/- 10: z of 1.8
    parent = region(aligned, 20, 40)
    assert refine(aligned, parent) == [parent]


def test_a_burst_of_words_squeezed_into_a_fraction_of_a_second_is_not_a_finding():
    slots = [0.6] * 60
    for i in range(20, 30):
        slots[i] = 0.04                                                      # ten words in 0.4 s: an aligner glitch, not speech
    aligned = speech(slots, length=0.03)
    parent = region(aligned, 20, 29)
    assert refine(aligned, parent) == [parent]


def test_a_long_silence_after_normal_words_does_not_stretch_a_slow_finding_up_to_it():
    slots = with_stretch(80, 20, 35, 1.2)
    slots[40] = 0.6 + 3.5                                                     # four normal words, then a long silence after word 40
    aligned = speech(slots)
    base = baseline()
    nb = normalize_features(base, rate=extract_rate(aligned))
    parent = FlawCandidate(FlawType.TOO_SLOW, aligned.words[20].start_s, aligned.words[41].end_s, 4.0, -4.0, "rate_z", (3, 4),
                           ((aligned.words[20].start_s, aligned.words[41].end_s),))
    (cand,) = refine_rate_candidates([parent], nb, aligned, base, DetectionConfig())
    assert cand.end_s == pytest.approx(aligned.words[35].end_s)


def test_a_candidate_that_names_no_window_is_left_alone():
    aligned = speech(with_stretch(80, 20, 40, 0.3))
    parent = FlawCandidate(FlawType.TOO_FAST, aligned.words[20].start_s, aligned.words[40].end_s, 5.0, 5.0, "rate_z", (),
                           ((aligned.words[20].start_s, aligned.words[40].end_s),))
    assert refine(aligned, parent) == [parent]


def test_a_narrowed_slow_finding_reports_a_negative_peak():
    aligned = speech(with_stretch(60, 20, 31, 1.2))
    base = baseline()
    rate, nb, det = analyse(aligned, base)
    (flaw,) = ground_flaws(det, nb, base, rate=rate, aligned=aligned)
    assert flaw.type == FlawType.TOO_SLOW and flaw.evidence.rate_z_score < 0 and flaw.evidence.peak_z_score < 0
    assert flaw.evidence.peak_z_score == pytest.approx(flaw.evidence.rate_z_score, abs=1e-3)


# ---------------------------------------------------------------------------------------------------------------------------------
# Clipping to the audio
# ---------------------------------------------------------------------------------------------------------------------------------

def test_findings_are_clipped_to_the_audio_and_empty_ones_dropped():
    aligned = speech(with_stretch(60, 20, 35, 0.3))
    base = baseline()
    rate, nb, det = analyse(aligned, base)
    (flaw,) = ground_flaws(det, nb, base, rate=rate, aligned=aligned)
    assert clip_to_audio([flaw], 100.0) == [flaw]
    (clipped,) = clip_to_audio([flaw], flaw.end_s - 1.0)
    assert clipped.end_s == pytest.approx(flaw.end_s - 1.0, abs=1e-4) and clipped.start_s == flaw.start_s and clipped.evidence == flaw.evidence
    assert clip_to_audio([flaw], flaw.start_s) == [] and clip_to_audio([flaw], flaw.start_s - 1.0) == []
    shifted = flaw.shifted(0.0)
    negative = type(flaw)(**{**shifted.__dict__, "start_s": -0.5})
    (fixed,) = clip_to_audio([negative], 100.0)
    assert fixed.start_s == 0.0
