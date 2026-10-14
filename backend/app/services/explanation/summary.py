"""Overall summary text (`overall_summary`).

A short, deterministic paragraph for the top of the results page, built only from already-computed values: the
number and kinds of flaws, the analysed duration, the composite score and which features were NOT evaluated. Like
every explanation it is checked by the number-grounding guard before it is returned.
"""
from __future__ import annotations

from collections import Counter
from typing import Dict, Sequence

from app.schemas.common import FeatureName, FlawType
from app.schemas.response import ScoreSummary
from app.services.explanation.facts import TYPE_LABELS, fmt
from app.services.explanation.guard import ExplanationGuardError, assert_grounded
from app.services.explanation.templates import ExplanationError
from app.services.grounding.flaws import GroundedFlaw

FEATURE_LABELS: Dict[FeatureName, str] = {
    FeatureName.SPEECH_RATE: "speech rate",
    FeatureName.PITCH: "pitch",
    FeatureName.PAUSES: "pauses",
    FeatureName.ENERGY: "energy",
    FeatureName.MFCC: "spectral shape",
    FeatureName.CLARITY: "clarity",
}


def _join(items: Sequence[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def build_overall_summary(
    flaws: Sequence[GroundedFlaw],
    scores: ScoreSummary,
    unevaluated: Sequence[FeatureName],
    analysed_duration_s: float,
    thresholds_calibrated: bool = False,
) -> str:
    """Deterministic summary of one analysis (see module docstring).

    Raises:
        ExplanationError: the produced text failed the number-grounding guard (a bug).
    """
    evaluated = [FEATURE_LABELS[f] for f in scores.feature_scores]
    facts: Dict[str, str] = {
        "n": str(len(flaws)),
        "duration": fmt(analysed_duration_s, 1),
        "composite": fmt(scores.composite_score, 1),
        "scale": "100",
    }

    if flaws:
        counts = Counter(f.type for f in flaws)
        parts = []
        for ftype in FlawType:
            if counts[ftype]:
                facts[f"count_{ftype.value}"] = str(counts[ftype])
                parts.append(f"{TYPE_LABELS[ftype].lower()}: {counts[ftype]}")
        plural = len(flaws) != 1
        first = (
            f"{len(flaws)} delivery deviation{'s' if plural else ''} from the baseline "
            f"{'were' if plural else 'was'} detected in {facts['duration']} s of analysed speech ({', '.join(parts)})."
        )
    else:
        first = f"No deviations from the baseline were detected in {facts['duration']} s of analysed speech."

    sentences = [
        first,
        f"Deviation score: {facts['composite']} out of {facts['scale']} across {_join(evaluated)} "
        f"({facts['scale']} means no deviation was detected).",
    ]
    if unevaluated:
        sentences.append(f"Not evaluated: {_join([FEATURE_LABELS[f] for f in unevaluated])}.")
    sentences.append("These results compare delivery with the baseline recording; they are not a measure of speech quality or content.")
    if not thresholds_calibrated:
        sentences.append(
            "Detection thresholds and score weights are initial values that have not yet been calibrated on recorded data."
        )
    text = " ".join(sentences)
    try:
        assert_grounded(text, facts)
    except ExplanationGuardError as exc:  # pragma: no cover - the summary only uses fact-sheet numbers
        raise ExplanationError(f"summary failed the guard: {exc}") from exc
    return text
