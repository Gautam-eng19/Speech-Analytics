"""Fact sheet: the only numbers an explanation may use (TASK-070; ARCHITECTURE.md §22).

`build_fact_sheet(flaw)` formats every number that can appear in a flaw's explanation or recommendation, ONCE,
from the grounded evidence, the detection rule and the flaw interval. Templates insert these strings verbatim;
a future LLM would receive exactly this sheet and be required to copy values from it; the guard
(`guard.find_ungrounded`) verifies that nothing else appears.

Formatting is fixed per quantity (so the same flaw always yields the same text): times of the interval with
1 decimal, rates / loudness with 1, z-scores with 2, pause lengths with 2, severity with 2, counts as integers.
Differences and z-scores carry no sign (direction is expressed in words, "above" / "below"); levels that are
inherently signed (dBFS) keep it. The guard ignores signs when comparing.
"""
from __future__ import annotations

from typing import Dict

from app.schemas.common import FlawType
from app.schemas.response import EnergyEvidence, PauseEvidence, RateEvidence
from app.services.grounding.flaws import GroundedFlaw

TYPE_LABELS: Dict[FlawType, str] = {
    FlawType.TOO_FAST: "Too fast",
    FlawType.TOO_SLOW: "Too slow",
    FlawType.EXCESSIVE_PAUSE: "Excessive pause",
    FlawType.FLAT_PITCH: "Flat pitch",
    FlawType.PITCH_INSTABILITY: "Pitch instability",
    FlawType.LOW_ENERGY: "Low energy",
    FlawType.HIGH_ENERGY: "High energy",
    FlawType.REDUCED_CLARITY: "Reduced clarity",
}


def fmt(value: float, decimals: int) -> str:
    """Absolute value with a fixed number of decimals (direction is written in words, never as a sign)."""
    return f"{abs(float(value)):.{decimals}f}"


def fmt_level(value: float, decimals: int) -> str:
    """A level that is inherently signed (dBFS), keeping its sign: negative values use the true minus sign.

    "-28.2 dBFS" and "28.2 dBFS" are opposite statements, so unlike differences, levels must not lose their sign.
    """
    text = f"{abs(float(value)):.{decimals}f}"
    return f"\u2212{text}" if float(value) < 0 and float(text) != 0.0 else text


def build_fact_sheet(flaw: GroundedFlaw) -> Dict[str, str]:
    """All formatted numbers usable in the text of `flaw` (times are in the flaw's own timeline)."""
    facts: Dict[str, str] = {
        "start": fmt(flaw.start_s, 1),
        "end": fmt(flaw.end_s, 1),
        "duration": fmt(flaw.duration_s, 1),
        "severity": fmt(flaw.severity, 2),
        "threshold": fmt(flaw.rule.threshold_z, 1),
        "min_duration": fmt(flaw.rule.min_duration_s, 1),
    }
    ev = flaw.evidence
    if isinstance(ev, RateEvidence):
        facts.update(
            wpm=fmt(ev.rate_participant_wpm, 1),
            baseline_wpm=fmt(ev.rate_baseline_mean_wpm, 1),
            baseline_wpm_std=fmt(ev.rate_baseline_std_wpm, 1),
            delta_wpm=fmt(ev.rate_delta_wpm, 1),
            delta_pct=fmt(ev.rate_delta_pct, 1),
            z=fmt(ev.rate_z_score, 2),
            peak_z=fmt(ev.peak_z_score, 2),
            window_s=fmt(ev.window_duration_s, 1),
            words=str(int(ev.word_count_in_window)),
        )
    elif isinstance(ev, EnergyEvidence):
        facts.update(
            db=fmt_level(ev.energy_mean_db, 1),
            baseline_db=fmt_level(ev.energy_baseline_mean_db, 1),
            baseline_db_std=fmt(ev.energy_baseline_std_db, 1),
            delta_db=fmt(ev.energy_delta_db, 1),
            z=fmt(ev.energy_z_score, 2),
            window_s=fmt(ev.window_duration_s, 1),
        )
    elif isinstance(ev, PauseEvidence):
        facts.update(
            pause_s=fmt(ev.pause_duration_s, 2),
            baseline_pause_s=fmt(ev.pause_baseline_mean_s, 2),
            baseline_pause_std_s=fmt(ev.pause_baseline_std_s, 2),
            delta_pause_s=fmt(ev.pause_delta_s, 2),
            z=fmt(ev.pause_z_score, 2),
        )
    return facts
