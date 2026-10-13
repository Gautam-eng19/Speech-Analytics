"""Tests for evidence-backed explanations, the fact sheet and the number-grounding guard (TASK-070/071/072).

Covers:
- Golden texts for every supported flaw type (wording is part of the specification)
- Fact-sheet formatting (signs, decimals) and the guard's behaviour on grounded / invented numbers
- Direction words, absence of judgement language, fallback behaviour and its triggers
- A fuzz property: for random evidence every rendered text passes the guard and is well formed
- The overall summary
"""
from __future__ import annotations

import random
import re

import pytest
from app.schemas.common import (
    ExplanationMethod,
    FeatureName,
    FlawType,
    PauseBoundaryType,
    PauseDetectionSource,
)
from app.schemas.response import (
    DetectionRule,
    EnergyEvidence,
    FlatPitchEvidence,
    Flaw,
    PauseEvidence,
    RateEvidence,
    ScoreSummary,
    FeatureScore,
)
from app.services.explanation import (
    Explanation,
    ExplanationGuardError,
    TYPE_LABELS,
    assert_grounded,
    build_fact_sheet,
    build_overall_summary,
    explain_flaw,
    find_ungrounded,
    fmt,
)
from app.services.explanation import templates as templates_module
from app.services.explanation.facts import fmt_level
from app.services.grounding import GroundedFlaw, to_api_flaw

W, C = PauseBoundaryType.WITHIN_PHRASE, PauseBoundaryType.CROSS_SENTENCE


def _flaw(ftype, start, end, evidence, rule, words=(), severity=0.78, number=1) -> GroundedFlaw:
    return GroundedFlaw(
        flaw_id=f"flaw_{number:03d}", type=ftype, start_s=start, end_s=end, severity=severity, reliability=1.0,
        low_confidence=False, evidence=evidence, rule=rule, affected_words=tuple(words), warnings=("limitation",),
    )


def _fast(words=("alpha", "beta", "gamma")):
    ev = RateEvidence(rate_participant_wpm=187.3, rate_baseline_mean_wpm=142.6, rate_baseline_std_wpm=18.4,
                      rate_delta_wpm=44.7, rate_delta_pct=31.4, rate_z_score=2.41, peak_z_score=3.12,
                      window_duration_s=3.4, word_count_in_window=11)
    return _flaw(FlawType.TOO_FAST, 12.4, 15.8, ev,
                 DetectionRule(feature="rate_z", direction="above", threshold_z=2.0, min_duration_s=0.5), words)


def _slow(words=("alpha", "gamma")):
    ev = RateEvidence(rate_participant_wpm=90.0, rate_baseline_mean_wpm=140.0, rate_baseline_std_wpm=15.0,
                      rate_delta_wpm=-50.0, rate_delta_pct=-35.7, rate_z_score=-3.33, peak_z_score=-3.5,
                      window_duration_s=6.0, word_count_in_window=9)
    return _flaw(FlawType.TOO_SLOW, 3.0, 9.0, ev,
                 DetectionRule(feature="rate_z", direction="below", threshold_z=-2.0, min_duration_s=0.5), words)


def _energy(ftype, mean_db, delta, z, words=("alpha", "gamma")):
    ev = EnergyEvidence(energy_mean_db=mean_db, energy_baseline_mean_db=-8.7, energy_baseline_std_db=2.2,
                        energy_delta_db=delta, energy_z_score=z, window_duration_s=3.9)
    below = ftype == FlawType.LOW_ENERGY
    rule = DetectionRule(feature="energy_z", direction="below" if below else "above",
                         threshold_z=-2.0 if below else 2.0, min_duration_s=0.5)
    return _flaw(ftype, 6.8, 10.7, ev, rule, words)


def _pause(kind=W, words=("w19", "w20"), start=10.7, end=12.2, threshold=2.0):
    ev = PauseEvidence(pause_duration_s=1.5, pause_baseline_mean_s=0.35, pause_baseline_std_s=0.07,
                       pause_delta_s=1.15, pause_z_score=16.43, boundary_type=kind,
                       detection_source=PauseDetectionSource.BOTH)
    return _flaw(FlawType.EXCESSIVE_PAUSE, start, end, ev,
                 DetectionRule(feature="pause_z", direction="above", threshold_z=threshold, min_duration_s=0.0), words)


# ----------------------------------------------------------------- golden texts
def test_too_fast_golden_text():
    out = explain_flaw(_fast())
    assert out.explanation == (
        "12.4–15.8 s: speech rate averaged 187.3 words/min, 31.4% above the baseline mean of 142.6 words/min "
        "(2.41 standard deviations above it), covering “alpha” to “gamma”. Flagged because the rate was "
        "more than 2.0 standard deviations above the baseline mean over at least 0.5 s, which indicates accelerated "
        "delivery compared with the baseline."
    )
    assert out.recommendation == (
        "Slow down in this stretch: aim for about 142.6 words/min, the baseline pace, and keep the pauses between phrases."
    )
    assert out.method == ExplanationMethod.TEMPLATE and out.used_fallback is False


def test_too_slow_golden_text():
    out = explain_flaw(_slow())
    assert out.explanation == (
        "3.0–9.0 s: speech rate averaged 90.0 words/min, 35.7% below the baseline mean of 140.0 words/min "
        "(3.33 standard deviations below it), covering “alpha” to “gamma”. Flagged because the rate was "
        "more than 2.0 standard deviations below the baseline mean over at least 0.5 s, which indicates slower "
        "delivery compared with the baseline."
    )
    assert out.recommendation == (
        "Bring the pace up in this stretch towards the baseline pace of about 140.0 words/min and link phrases "
        "together without long gaps."
    )


def test_low_energy_golden_text_keeps_the_sign_of_the_levels():
    out = explain_flaw(_energy(FlawType.LOW_ENERGY, -28.2, -19.5, -8.77))
    assert out.explanation == (
        "6.8–10.7 s: relative loudness averaged −28.2 dBFS, 19.5 dB below the baseline mean of −8.7 dBFS "
        "(8.77 standard deviations below it), covering “alpha” to “gamma”. Flagged because the energy was "
        "more than 2.0 standard deviations below the baseline mean over at least 0.5 s, which indicates quieter "
        "delivery than the baseline."
    )
    assert out.recommendation == (
        "Project your voice more in this stretch: support it with steady breath and keep a consistent distance "
        "from the microphone."
    )


def test_high_energy_golden_text():
    out = explain_flaw(_energy(FlawType.HIGH_ENERGY, -3.2, 5.5, 2.5))
    assert out.explanation == (
        "6.8–10.7 s: relative loudness averaged −3.2 dBFS, 5.5 dB above the baseline mean of −8.7 dBFS "
        "(2.50 standard deviations above it), covering “alpha” to “gamma”. Flagged because the energy was "
        "more than 2.0 standard deviations above the baseline mean over at least 0.5 s, which indicates louder "
        "delivery than the baseline."
    )
    assert out.recommendation == (
        "Ease the volume back in this stretch and let emphasis come from pace and pitch variation rather than loudness."
    )


def test_excessive_pause_golden_texts_within_phrase_and_between_sentences():
    out = explain_flaw(_pause())
    assert out.explanation == (
        "10.7–12.2 s: a pause of 1.50 s inside a phrase after “w19” and before “w20”, 1.15 s longer than "
        "the baseline mean pause of 0.35 s (16.43 standard deviations above it). Flagged because the pause was more "
        "than 2.0 standard deviations longer than the baseline mean, which is a longer break than in the baseline delivery."
    )
    assert out.recommendation == "Keep these words connected: aim for a pause close to 0.35 s, as in the baseline delivery."

    cross = explain_flaw(_pause(kind=C, threshold=2.5))
    assert "a pause of 1.50 s between sentences after" in cross.explanation
    assert "more than 2.5 standard deviations longer" in cross.explanation
    assert cross.recommendation == "Keep the pause between these sentences close to 0.35 s, as in the baseline delivery."


# ------------------------------------------------------------- word clauses
def test_word_clause_variants():
    assert explain_flaw(_fast(words=())).explanation.count("covering") == 0
    assert ", around “delta”." in explain_flaw(_fast(words=("delta",))).explanation
    assert " at “only”," in explain_flaw(_pause(words=("only",))).explanation
    assert "after" not in explain_flaw(_pause(words=())).explanation.split("Flagged")[0]


def test_transcript_words_with_digits_or_quotes_are_safe():
    out = explain_flaw(_fast(words=('"2026"', "w19")))
    assert "covering “2026” to “w19”" in out.explanation
    assert out.used_fallback is False                                    # digits inside covered quoted words are fine
    assert explain_flaw(_pause(words=("“w5”", "w6"))).used_fallback is False


# -------------------------------------------------------------- direction/tone
@pytest.mark.parametrize(
    "flaw,must,must_not",
    [
        (_fast(), "above", "below"), (_slow(), "below", "above"),
        (_energy(FlawType.LOW_ENERGY, -28.2, -19.5, -8.77), "below", "above"),
        (_energy(FlawType.HIGH_ENERGY, -3.2, 5.5, 2.5), "above", "below"),
        (_pause(), "above", "below"),
    ],
)
def test_direction_words_match_the_flaw(flaw, must, must_not):
    text = explain_flaw(flaw).explanation
    assert must in text and must_not not in text


BANNED = ["confiden", "nervous", "anxious", "emotion", "intelligib", "personality", "honest", "lying", "stress",
          "insecure", "mistake", " poor", " bad ", "fail", "correct answer"]


def test_no_judgement_or_state_inference_language():
    flaws = [_fast(), _slow(), _energy(FlawType.LOW_ENERGY, -28.2, -19.5, -8.77),
             _energy(FlawType.HIGH_ENERGY, -3.2, 5.5, 2.5), _pause(), _pause(kind=C)]
    for flaw in flaws:
        out = explain_flaw(flaw)
        for text in (out.explanation, out.recommendation):
            for word in BANNED:
                assert word not in text.lower(), (flaw.type, word)


def test_explanations_are_deterministic():
    assert explain_flaw(_fast()) == explain_flaw(_fast())


# ------------------------------------------------------------------ fact sheet
def test_fact_sheet_formatting_and_signs():
    facts = build_fact_sheet(_slow())
    assert facts["wpm"] == "90.0" and facts["baseline_wpm"] == "140.0" and facts["delta_wpm"] == "50.0"
    assert facts["delta_pct"] == "35.7" and facts["z"] == "3.33" and facts["peak_z"] == "3.50"
    assert facts["threshold"] == "2.0" and facts["min_duration"] == "0.5" and facts["words"] == "9"
    assert facts["start"] == "3.0" and facts["end"] == "9.0" and facts["severity"] == "0.78"
    energy = build_fact_sheet(_energy(FlawType.LOW_ENERGY, -28.2, -19.5, -8.77))
    assert energy["db"] == "−28.2" and energy["baseline_db"] == "−8.7" and energy["delta_db"] == "19.5"
    pause = build_fact_sheet(_pause())
    assert pause["pause_s"] == "1.50" and pause["baseline_pause_s"] == "0.35" and pause["delta_pause_s"] == "1.15"


def test_fmt_helpers():
    assert fmt(-3.456, 2) == "3.46" and fmt(2, 1) == "2.0"
    assert fmt_level(-28.19, 1) == "−28.2" and fmt_level(3.21, 1) == "3.2"
    assert fmt_level(-0.04, 1) == "0.0" and fmt_level(0.0, 1) == "0.0"           # no "-0.0"


# ------------------------------------------------------------------------ guard
FACTS = {"start": "12.4", "end": "15.8", "pct": "31.4", "z": "2.41", "db": "−28.2", "words": "11", "label": "text"}


@pytest.mark.parametrize("text", [
    "12.4–15.8 s: 31.4% above the baseline (2.41 standard deviations).",
    "Averaged −28.2 dBFS over 11 words.",
    "The value 31.40 is the same as 31.4.",
    "Signs are ignored: -2.41 and +2.41 and 28.2.",
    "",
    "No digits at all here.",
])
def test_guard_accepts_grounded_text(text):
    assert find_ungrounded(text, FACTS) == []
    assert_grounded(text, FACTS)


@pytest.mark.parametrize("text,expected", [
    ("Speech was 37% faster.", ["37"]),
    ("12.4–15.9 s.", ["15.9"]),
    ("31.5% above.", ["31.5"]),
    ("Took 99s.", ["99"]),                                    # number glued to a unit is still found
    ("About 2.411 deviations.", ["2.411"]),
    ("Value 1.2.3 here.", ["1.2", "3"]),
])
def test_guard_rejects_invented_numbers(text, expected):
    assert find_ungrounded(text, FACTS) == expected
    with pytest.raises(ExplanationGuardError):
        assert_grounded(text, FACTS)


@pytest.mark.parametrize("word", ["twice", "Half", "THREE", "double", "percent", "dozen", "ten"])
def test_guard_rejects_spelled_out_quantities(word):
    assert find_ungrounded(f"It was {word} as fast.", FACTS) == [f"word:{word.lower()}"]


def test_guard_ignores_number_words_inside_longer_words():
    assert find_ungrounded("This often happens at the Stone Tower.", FACTS) == []


def test_guard_masks_digits_only_in_quoted_covered_words():
    assert find_ungrounded("Around “w19” and “2026”.", FACTS, ["w19", "2026"]) == []
    assert find_ungrounded('Around "w19".', FACTS, ["w19"]) == []                                  # straight quotes too
    assert find_ungrounded("Around “187 wpm”.", FACTS, ["w19"]) == ["187"]                # not a covered word
    assert find_ungrounded("Around w19 unquoted.", FACTS, ["w19"]) == ["19"]                        # quoting is required
    assert find_ungrounded("Around “one”.", FACTS, ["one"]) == []                         # quoted number word


def test_guard_ignores_non_numeric_fact_values_and_signs_in_facts():
    assert find_ungrounded("Label text 28.2 only.", {"label": "text", "x": "−28.2"}) == []


# ----------------------------------------------------------- fallback behaviour
def test_unsupported_flaw_types_use_the_safe_fallback():
    ev = FlatPitchEvidence(f0_std_hz_in_window=1.0, f0_std_baseline_hz=20.0, f0_std_z=-3.0,
                           f0_voiced_fraction=0.8, window_duration_s=2.0)
    flaw = _flaw(FlawType.FLAT_PITCH, 4.0, 6.0, ev,
                 DetectionRule(feature="f0_std_z", direction="below", threshold_z=-2.0, min_duration_s=0.5))
    out = explain_flaw(flaw)
    assert out.used_fallback is True and out.method == ExplanationMethod.TEMPLATE
    assert out.explanation == (
        "Delivery was flagged as “flat pitch” relative to the baseline from 4.0 s to 6.0 s."
    )
    assert out.recommendation == "Compare this section with the baseline recording."


def test_a_template_that_invents_a_number_is_replaced_by_the_fallback(monkeypatch):
    def bad(flaw, facts):
        return "Speech was 37% faster than the baseline.", "Slow down."

    monkeypatch.setitem(templates_module._TEMPLATES, FlawType.TOO_FAST, bad)
    out = explain_flaw(_fast())
    assert out.used_fallback is True and "37" not in out.explanation + out.recommendation


def test_a_template_that_needs_a_missing_fact_is_replaced_by_the_fallback(monkeypatch):
    def broken(flaw, facts):
        return f"Value {facts['does_not_exist']}.", "Rec."

    monkeypatch.setitem(templates_module._TEMPLATES, FlawType.TOO_FAST, broken)
    assert explain_flaw(_fast()).used_fallback is True


def test_a_recommendation_with_an_invented_number_also_triggers_the_fallback(monkeypatch):
    monkeypatch.setitem(templates_module._TEMPLATES, FlawType.TOO_FAST,
                        lambda flaw, facts: ("Fine text.", "Aim for 120 words/min."))
    assert explain_flaw(_fast()).used_fallback is True


# ---------------------------------------------------------------------- fuzz
def _random_flaw(rng: random.Random, number: int) -> GroundedFlaw:
    words = tuple(rng.choice(["alpha", "w12", "2026", "don’t", "x-ray", "7", "ok"]) for _ in range(rng.randint(0, 4)))
    start = round(rng.uniform(0, 50), 4)
    end = round(start + rng.uniform(0.5, 12), 4)
    kind = rng.choice(["fast", "slow", "low", "high", "pause_w", "pause_c"])
    z = round(rng.uniform(2.0, 40.0), 4)
    if kind in ("fast", "slow"):
        sign = 1 if kind == "fast" else -1
        base = round(rng.uniform(80, 200), 4)
        wpm = round(base + sign * rng.uniform(5, 120) if sign > 0 else max(5.0, base - rng.uniform(5, 70)), 4)
        ev = RateEvidence(rate_participant_wpm=wpm, rate_baseline_mean_wpm=base, rate_baseline_std_wpm=round(rng.uniform(1, 30), 4),
                          rate_delta_wpm=round(wpm - base, 4), rate_delta_pct=round(100 * (wpm - base) / base, 4),
                          rate_z_score=sign * z, peak_z_score=sign * round(z + rng.random(), 4),
                          window_duration_s=round(end - start, 4), word_count_in_window=rng.randint(0, 80))
        rule = DetectionRule(feature="rate_z", direction="above" if sign > 0 else "below",
                             threshold_z=2.0 * sign, min_duration_s=0.5)
        ftype = FlawType.TOO_FAST if sign > 0 else FlawType.TOO_SLOW
    elif kind in ("low", "high"):
        sign = -1 if kind == "low" else 1
        base = round(rng.uniform(-30, -5), 4)
        mean = round(base + sign * rng.uniform(3, 30), 4)
        ev = EnergyEvidence(energy_mean_db=mean, energy_baseline_mean_db=base, energy_baseline_std_db=round(rng.uniform(0.5, 8), 4),
                            energy_delta_db=round(mean - base, 4), energy_z_score=sign * z, window_duration_s=round(end - start, 4))
        rule = DetectionRule(feature="energy_z", direction="above" if sign > 0 else "below",
                             threshold_z=2.0 * sign, min_duration_s=0.5)
        ftype = FlawType.HIGH_ENERGY if sign > 0 else FlawType.LOW_ENERGY
    else:
        dur = round(end - start, 4)
        bmean = round(rng.uniform(0.1, 0.8), 4)
        ev = PauseEvidence(pause_duration_s=dur, pause_baseline_mean_s=bmean, pause_baseline_std_s=round(rng.uniform(0.02, 0.3), 4),
                           pause_delta_s=round(dur - bmean, 4), pause_z_score=z,
                           boundary_type=W if kind == "pause_w" else C, detection_source=PauseDetectionSource.VAD)
        rule = DetectionRule(feature="pause_z", direction="above", threshold_z=2.0 if kind == "pause_w" else 2.5, min_duration_s=0.0)
        ftype = FlawType.EXCESSIVE_PAUSE
    return _flaw(ftype, start, end, ev, rule, words, severity=round(rng.random(), 4), number=number)


def test_fuzz_every_rendered_text_passes_the_guard_and_is_well_formed():
    rng = random.Random(2026)
    for i in range(400):
        flaw = _random_flaw(rng, i + 1)
        out = explain_flaw(flaw)
        assert out.used_fallback is False, (flaw.type, flaw.affected_words)
        facts = build_fact_sheet(flaw)
        covered = [w.replace('"', "") for w in flaw.affected_words]
        for text in (out.explanation, out.recommendation):
            assert text and text == text.strip()
            assert not re.search(r"[{}]|None|nan|inf\b", text), text
            assert find_ungrounded(text, facts, covered) == [], (text, facts)
        assert explain_flaw(flaw) == out


# ------------------------------------------------------------ API integration
def test_explanations_fit_the_public_flaw_contract():
    for flaw in (_fast(), _slow(), _energy(FlawType.LOW_ENERGY, -28.2, -19.5, -8.77), _pause()):
        out = explain_flaw(flaw)
        api = to_api_flaw(flaw, out.explanation, out.recommendation, out.method)
        assert isinstance(api, Flaw) and api.explanation == out.explanation


# ---------------------------------------------------------------------- summary
def _scores(composite=72.5, features=(FeatureName.SPEECH_RATE, FeatureName.PAUSES, FeatureName.ENERGY)):
    return ScoreSummary(
        feature_scores={f: FeatureScore(score=80.0, weight=round(1 / len(features), 6), flaw_count=0, penalty_total=20.0)
                        for f in features},
        composite_score=composite, scoring_version="1.0.0",
    )


def test_summary_golden_text_with_flaws():
    flaws = [_energy(FlawType.LOW_ENERGY, -28.2, -19.5, -8.77), _fast(), _pause()]
    text = build_overall_summary(flaws, _scores(), [FeatureName.PITCH], 19.04)
    assert text == (
        "3 delivery deviations from the baseline were detected in 19.0 s of analysed speech (too fast: 1, excessive "
        "pause: 1, low energy: 1). Deviation score: 72.5 out of 100 across speech rate, pauses and energy (100 means "
        "no deviation was detected). Not evaluated: pitch. These results compare delivery with the baseline recording; "
        "they are not a measure of speech quality or content. Detection thresholds and score weights are initial "
        "values that have not yet been calibrated on recorded data."
    )


def test_summary_without_flaws_singular_and_calibrated_variants():
    none = build_overall_summary([], _scores(100.0), [], 18.0, thresholds_calibrated=True)
    assert none.startswith("No deviations from the baseline were detected in 18.0 s of analysed speech.")
    assert "Not evaluated" not in none and "calibrated" not in none
    assert "Deviation score: 100.0 out of 100" in none

    one = build_overall_summary([_fast()], _scores(), [], 18.0, thresholds_calibrated=True)
    assert one.startswith("1 delivery deviation from the baseline was detected")
    two = build_overall_summary([_fast(), _slow()], _scores(), [], 18.0, thresholds_calibrated=True)
    assert two.startswith("2 delivery deviations from the baseline were detected")

    several = build_overall_summary([], _scores(features=(FeatureName.ENERGY,)), [FeatureName.PITCH, FeatureName.SPEECH_RATE], 5.0)
    assert "across energy (100" in several and "Not evaluated: pitch and speech rate." in several


def test_summary_is_deterministic_and_uses_only_grounded_numbers():
    flaws = [_fast(), _pause()]
    a = build_overall_summary(flaws, _scores(), [FeatureName.PITCH], 12.34)
    assert a == build_overall_summary(list(reversed(flaws)), _scores(), [FeatureName.PITCH], 12.34)
    facts = {"n": "2", "duration": "12.3", "composite": "72.5", "scale": "100", "a": "1", "b": "1"}
    assert find_ungrounded(a, facts) == []
