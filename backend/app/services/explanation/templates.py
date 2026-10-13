"""Evidence-backed template explanations and recommendations (TASK-070, TASK-071; DEC-018, DEC-021).

`explain_flaw(flaw)` turns ONE grounded flaw into readable text using only its fact sheet (`facts.py`): what
happened, where, which measurement supports it, how far it was from the baseline, and why the rule flagged it,
followed by a practical recommendation. The text is deterministic: the same flaw always yields the same words.

Boundaries (AGENTS.md §6.2, §6.3):
    * no number is ever typed into a template: every figure is inserted from the fact sheet;
    * after rendering, both texts are re-checked by the independent guard (`guard.assert_grounded`);
    * if a template is missing, a fact is missing, or the guard rejects the text, a minimal fallback that states
      only the finding type and interval is used and `used_fallback` is True;
    * the wording describes a difference from the BASELINE recording of the same passage. It does not judge
      content, and does not infer confidence, emotion or any other state of the speaker.

Times are those of the flaw passed in; the pipeline passes flaws already converted to source time (DEC-023).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Tuple

from app.schemas.common import ExplanationMethod, FlawType, PauseBoundaryType
from app.services.explanation.facts import TYPE_LABELS, build_fact_sheet
from app.services.explanation.guard import ExplanationGuardError, assert_grounded
from app.services.grounding.flaws import GroundedFlaw


class ExplanationError(RuntimeError):
    """Raised when not even the safe fallback text can be produced (a bug, not an input problem)."""


@dataclass(frozen=True)
class Explanation:
    """Explanation and recommendation texts for one flaw."""

    explanation: str
    recommendation: str
    method: ExplanationMethod
    used_fallback: bool


_QUOTES = str.maketrans({"“": "", "”": "", '"': ""})


def _clean(word: str) -> str:
    """A transcript word without quote characters, safe to place between typographic quotes."""
    return word.translate(_QUOTES).strip()


def _span(facts: Dict[str, str]) -> str:
    return f"{facts['start']}–{facts['end']} s"


def _words_clause(flaw: GroundedFlaw) -> str:
    """Where in the transcript: the words the flaw covers (for a pause: the words around it)."""
    words = [w for w in (_clean(x) for x in flaw.affected_words) if w]
    if not words:
        return ""
    if flaw.type == FlawType.EXCESSIVE_PAUSE:
        if len(words) == 1:
            return f" at \u201c{words[0]}\u201d"
        return f" after \u201c{words[0]}\u201d and before \u201c{words[-1]}\u201d"
    if len(words) == 1:
        return f", around \u201c{words[0]}\u201d"
    return f", covering \u201c{words[0]}\u201d to \u201c{words[-1]}\u201d"


def _by_words(flaw: GroundedFlaw) -> bool:
    """True for a finding of the word-by-word comparison with the baseline (DEC-040), whose 'baseline' is the baseline's reading of the same words."""
    return flaw.rule.feature.endswith("_run_z") or flaw.rule.feature.endswith("_overall_z")


def _rate(flaw: GroundedFlaw, f: Dict[str, str]) -> Tuple[str, str]:
    fast = flaw.type == FlawType.TOO_FAST
    side, adverb = ("above", "faster") if fast else ("below", "slower")
    if _by_words(flaw):
        verdict = f"which indicates {'accelerated' if fast else 'slower'} delivery compared with the baseline."
        if flaw.rule.feature == "rate_overall_z":
            text = (
                f"{_span(f)}: over the whole recording, speech rate averaged {f['wpm']} words/min, {f['delta_pct']}% {side} the "
                f"{f['baseline_wpm']} words/min the baseline readings had for the same words ({f['z']} standard deviations {side} it). "
                f"Flagged because the pace of the whole recording differed from the baseline's by more than {f['threshold']} standard "
                f"deviations of how much readings of this passage differ in pace, {verdict}"
            )
        else:
            text = (
                f"{_span(f)}: speech rate averaged {f['wpm']} words/min, {f['delta_pct']}% {side} the {f['baseline_wpm']} words/min the "
                f"baseline readings had for these same words ({f['z']} standard deviations {side} it){_words_clause(flaw)}. "
                f"Flagged because the pace of this run of words was more than {f['threshold']} standard deviations {side} the baseline's "
                f"pace for the same words over at least {f['min_duration']} s, {verdict}"
            )
        rec = (
            f"Slow down in this stretch: aim for about {f['baseline_wpm']} words/min, the pace the baseline readings had for these words, "
            f"and keep the pauses between phrases."
            if fast
            else f"Bring the pace up in this stretch towards about {f['baseline_wpm']} words/min, the pace the baseline readings had for "
            f"these words, and link phrases together without long gaps."
        )
        return text, rec
    text = (
        f"{_span(f)}: speech rate averaged {f['wpm']} words/min, {f['delta_pct']}% {side} the baseline mean of "
        f"{f['baseline_wpm']} words/min ({f['z']} standard deviations {side} it){_words_clause(flaw)}. "
        f"Flagged because the rate was more than {f['threshold']} standard deviations {side} the baseline mean "
        f"over at least {f['min_duration']} s, which indicates "
        f"{'accelerated' if fast else 'slower'} delivery compared with the baseline."
    )
    rec = (
        f"Slow down in this stretch: aim for about {f['baseline_wpm']} words/min, the baseline pace, and keep the "
        f"pauses between phrases."
        if fast
        else f"Bring the pace up in this stretch towards the baseline pace of about {f['baseline_wpm']} words/min "
        f"and link phrases together without long gaps."
    )
    return text, rec


def _energy(flaw: GroundedFlaw, f: Dict[str, str]) -> Tuple[str, str]:
    low = flaw.type == FlawType.LOW_ENERGY
    side, word = ("below", "quieter") if low else ("above", "louder")
    if _by_words(flaw):
        text = (
            f"{_span(f)}: relative loudness averaged {f['db']} dBFS, {f['delta_db']} dB {side} the {f['baseline_db']} dBFS the baseline readings "
            f"had for these same words, after allowing for the recording's overall level ({f['z']} standard deviations {side} it){_words_clause(flaw)}. "
            f"Flagged because the level of this run of words was more than {f['threshold']} standard deviations {side} the baseline's level for "
            f"the same words over at least {f['min_duration']} s, which indicates {word} delivery than the baseline."
        )
    else:
        text = (
            f"{_span(f)}: relative loudness averaged {f['db']} dBFS, {f['delta_db']} dB {side} the baseline mean of "
            f"{f['baseline_db']} dBFS ({f['z']} standard deviations {side} it){_words_clause(flaw)}. "
            f"Flagged because the energy was more than {f['threshold']} standard deviations {side} the baseline mean "
            f"over at least {f['min_duration']} s, which indicates {word} delivery than the baseline."
        )
    rec = (
        "Project your voice more in this stretch: support it with steady breath and keep a consistent distance "
        "from the microphone."
        if low
        else "Ease the volume back in this stretch and let emphasis come from pace and pitch variation rather "
        "than loudness."
    )
    return text, rec


def _pause(flaw: GroundedFlaw, f: Dict[str, str]) -> Tuple[str, str]:
    cross = getattr(flaw.evidence, "boundary_type", None) == PauseBoundaryType.CROSS_SENTENCE
    where = "between sentences" if cross else "inside a phrase"
    text = (
        f"{_span(f)}: a pause of {f['pause_s']} s {where}{_words_clause(flaw)}, {f['delta_pause_s']} s longer than "
        f"the baseline mean pause of {f['baseline_pause_s']} s ({f['z']} standard deviations above it). "
        f"Flagged because the pause was more than {f['threshold']} standard deviations longer than the baseline "
        f"mean, which is a longer break than in the baseline delivery."
    )
    rec = (
        f"Keep the pause between these sentences close to {f['baseline_pause_s']} s, as in the baseline delivery."
        if cross
        else f"Keep these words connected: aim for a pause close to {f['baseline_pause_s']} s, as in the "
        f"baseline delivery."
    )
    return text, rec


_TEMPLATES: Dict[FlawType, Callable[[GroundedFlaw, Dict[str, str]], Tuple[str, str]]] = {
    FlawType.TOO_FAST: _rate,
    FlawType.TOO_SLOW: _rate,
    FlawType.LOW_ENERGY: _energy,
    FlawType.HIGH_ENERGY: _energy,
    FlawType.EXCESSIVE_PAUSE: _pause,
}


def _fallback(flaw: GroundedFlaw, facts: Dict[str, str], covered: list) -> Explanation:
    label = TYPE_LABELS[flaw.type].lower()
    text = f"Delivery was flagged as “{label}” relative to the baseline from {facts['start']} s to {facts['end']} s."
    rec = "Compare this section with the baseline recording."
    try:
        assert_grounded(text, facts, covered)
        assert_grounded(rec, facts, covered)
    except ExplanationGuardError as exc:  # pragma: no cover - the fallback only uses fact-sheet numbers
        raise ExplanationError(f"fallback explanation failed the guard: {exc}") from exc
    return Explanation(text, rec, ExplanationMethod.TEMPLATE, True)


def explain_flaw(flaw: GroundedFlaw) -> Explanation:
    """Explanation + recommendation for `flaw`, from its evidence only (see module docstring)."""
    facts = build_fact_sheet(flaw)
    covered = [w for w in (_clean(x) for x in flaw.affected_words) if w]
    template = _TEMPLATES.get(flaw.type)
    if template is not None:
        try:
            explanation, recommendation = template(flaw, facts)
            assert_grounded(explanation, facts, covered)
            assert_grounded(recommendation, facts, covered)
            return Explanation(explanation, recommendation, ExplanationMethod.TEMPLATE, False)
        except (ExplanationGuardError, KeyError):
            pass  # a missing fact or an ungrounded number: use the safe fallback
    return _fallback(flaw, facts, covered)
