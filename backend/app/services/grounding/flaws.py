"""Evidence attachment and the final grounded flaw (§17 step 7).

Turns detector candidates into `GroundedFlaw`s: a stable id, a time interval, a severity, and a FULLY
populated evidence object built from the measured features and the baseline statistics. Nothing here
is estimated by a model, and no downstream stage may add evidence (§17: "evidence must be fully
populated before the flaw is returned").

Evidence (the typed models of `schemas/response.py`; all values rounded to `EVIDENCE_DECIMALS` places so
serialized results do not depend on last-bit floating-point differences):

    too_fast / too_slow -> RateEvidence    rate (words per minute) of the interval, baseline mean/std, delta,
                                           delta in percent of the baseline mean, mean and peak z, span,
                                           words that start inside the interval. For an interval narrowed to the
                                           words that deviate the rate is that of the narrowed stretch
                                           (words / span) and z compares it with the baseline's window spread scaled
                                           for the shorter stretch (candidates.refine_rate_candidates);
                                           otherwise it is the mean of the flagged windows
    low / high_energy   -> EnergyEvidence  mean dBFS of the flagged frames, baseline mean/std, delta, mean z, span
    excessive_pause     -> PauseEvidence   pause duration, the type-specific baseline mean/std, delta, z,
                                           boundary type and detection source
    flat_pitch          -> FlatPitchEvidence  the pitch movement of the run in Hz (root-mean-square distance from the reading's median pitch) against what the baseline readings had for the same words, the z-score (negative: the voice
                                           moved less), the share of the run's frames that were voiced, span

Because z is linear in the measurement, the reported mean z equals (reported mean - baseline mean) /
baseline std: the evidence is internally consistent and re-derivable by a reader.

For a run of words judged against the baseline's reading of the same words the "baseline mean" is what the baseline readings did with
those words (for the pace, allowing for the speaker's overall pace; for the loudness, plus the recording's overall level offset), and the
"baseline std" is the spread that makes the reported z-score true: |participant - baseline| / |z|, so the same identity holds.

Each flaw also records the rule that flagged it (`DetectionRule`: signal, direction, threshold, minimum
duration, taken from the `DetectionConfig` that PRODUCED the candidates), the aligned words it covers, and
plain-language limitations (`warnings`). For rate and energy findings the covered words are those whose
midpoint lies inside the interval; for a pause they are the word(s) the pause follows and precedes.

Reliability is the constant 1.0 at P0 and `low_confidence` is False; neither is a measured confidence.

Times are processed-audio time. Conversion to source time happens once, at response assembly, with
`GroundedFlaw.shifted(trim_start_s)`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, List, Optional, Sequence, Tuple

import numpy as np

from app.schemas.common import ExplanationMethod, FlawType, PauseBoundaryType
from app.schemas.contracts import AlignedTranscript, BaselineStatsRecord
from app.schemas.response import (
    DetectionRule,
    EnergyEvidence,
    Evidence,
    FlatPitchEvidence,
    Flaw,
    PauseEvidence,
    RateEvidence,
)
from app.services.features.pause import _timed_words
from app.services.grounding.candidates import CandidateDetectionResult, DetectionConfig, FlawCandidate
from app.services.grounding.normalizer import NormalizedFeatureBundle
from app.services.grounding.severity import SeverityConfig, compute_severity

EVIDENCE_DECIMALS = 4
RELIABILITY_P0 = 1.0
_EPS_S = 1e-9

WARNING_RATE = (
    "Speech rate is measured over rolling windows, so the start and end of this finding are approximate "
    "(window-level)."
)
WARNING_RATE_NARROWED = (
    "Speech rate is detected over rolling windows and the finding is then narrowed to the words that were faster or slower, so its start and "
    "end can still be off by a word or two. Its standard-deviation figure compares this short stretch with the spread of the baseline's "
    "windows, scaled for the stretch having fewer words to average over."
)
WARNING_RATE_RUN = (
    "Speech rate is compared word by word with the baseline's reading of the same words, after allowing for the speaker's overall pace. The "
    "finding is the run of words that differs most, so its start and end are word boundaries, as accurate as the forced alignment is."
)
WARNING_RATE_OVERALL = (
    "The pace of the whole reading differs from the baseline's by more than readers of the same passage differ among themselves; this one "
    "finding covers all the words that could be compared. Speakers differ in natural pace, so a moderate difference alone is not a flaw."
)
WARNING_ENERGY_RUN = (
    "Loudness is compared word by word with the baseline's level for the same words, after removing the recording's overall level (recordings "
    "are scaled to a common speech level), so it shows louder or quieter stretches within the recording, not how loud the speaker was overall, "
    "and it depends on microphone distance."
)
WARNING_PITCH_RUN = (
    "Pitch is compared word by word: how far the pitch of the words moves around the recording's own median pitch, against how far the baseline's "
    "readings moved on the same words, after allowing for the speaker's overall range. Only voiced speech has a pitch, so words with little of it "
    "are left out, and a pitch tracker can make mistakes. The Hz figures are that movement expressed above the median pitch of the recording."
)
WARNING_PITCH_OVERALL = (
    "The pitch of the whole recording moves less than the baseline's by more than readers of the same passage differ among themselves; this one "
    "finding covers all the words that could be compared. Speakers differ in how expressive they naturally are, so a moderate difference alone is "
    "not a flaw."
)
WARNING_ENERGY = (
    "Energy is relative loudness: the recording is scaled so that its typical speech level is the same as the baseline's, "
    "so it shows louder or quieter stretches within the recording, not how loud the speaker was overall, and it depends on "
    "microphone distance."
)
WARNING_PAUSE = "The pause type (within a phrase or between sentences) is inferred from the transcript's punctuation."


class EvidenceError(ValueError):
    """Raised when evidence cannot be built faithfully from the inputs."""


@dataclass(frozen=True)
class GroundedFlaw:
    """A detected flaw with its interval, severity and complete evidence.

    `evidence` is one of the typed evidence models; `rule` states why it was flagged; `affected_words`
    and `warnings` are described in the module docstring. Times are in the timeline of whoever built it
    (processed-audio time until `shifted`).
    """

    flaw_id: str
    type: FlawType
    start_s: float
    end_s: float
    severity: float
    reliability: float
    low_confidence: bool
    evidence: Evidence
    rule: DetectionRule
    affected_words: Tuple[str, ...]
    warnings: Tuple[str, ...]

    @property
    def duration_s(self) -> float:
        return round(self.end_s - self.start_s, EVIDENCE_DECIMALS)

    def shifted(self, offset_s: float) -> "GroundedFlaw":
        """Copy with start/end moved by `offset_s` seconds (evidence holds no absolute times)."""
        if not math.isfinite(offset_s):
            raise ValueError(f"offset_s must be finite, got {offset_s}")
        return replace(
            self,
            start_s=round(self.start_s + offset_s, EVIDENCE_DECIMALS),
            end_s=round(self.end_s + offset_s, EVIDENCE_DECIMALS),
        )


def _r(x: float) -> float:
    return round(float(x), EVIDENCE_DECIMALS)


def _require_aligned(arr_len: int, expected: int, what: str) -> None:
    if arr_len != expected:
        raise EvidenceError(f"{what}: raw feature has {arr_len} entries but the normalized signal has {expected}")


def _indices(c: FlawCandidate, length: int, what: str) -> List[int]:
    idx = list(c.member_indices)
    if not idx or min(idx) < 0 or max(idx) >= length:
        raise EvidenceError(f"{what}: candidate member indices {idx[:3]}... are outside the signal (length {length})")
    return idx


def _rate_evidence(
    c: FlawCandidate, nb: NormalizedFeatureBundle, baseline: BaselineStatsRecord, rate: Any, aligned: Any
) -> RateEvidence:
    if c.run is not None:      # a run of words against the baseline's reading of the same words
        run = c.run
        if not (run.expected > 0.0 and math.isfinite(run.expected) and math.isfinite(run.observed)):
            raise EvidenceError("rate evidence needs finite observed and expected rates")
        delta = run.observed - run.expected
        timed = _timed_words(aligned)[0] if aligned is not None else []
        words_in_span = sum(1 for _, s, _e in timed if c.start_s - _EPS_S <= s <= c.end_s + _EPS_S) if aligned is not None else run.n_words
        return RateEvidence(
            rate_participant_wpm=_r(run.observed),
            rate_baseline_mean_wpm=_r(run.expected),
            rate_baseline_std_wpm=_r(run.sigma_equiv),
            rate_delta_wpm=_r(delta),
            rate_delta_pct=_r(100.0 * delta / run.expected),
            rate_z_score=_r(c.mean_z),
            peak_z_score=_r(c.mean_z),
            window_duration_s=_r(c.end_s - c.start_s),
            word_count_in_window=int(words_in_span),
        )
    if rate is None or aligned is None:
        raise EvidenceError("rate evidence needs the rate extraction result and the aligned transcript")
    wpm = np.asarray(rate.words_per_min, dtype=np.float64)
    _require_aligned(len(wpm), len(nb.rate_z), "rate")
    idx = _indices(c, len(wpm), "rate")
    if not baseline.rate_wpm_mean > 0.0:
        raise EvidenceError("baseline rate_wpm_mean must be > 0 to express the difference in percent")

    if c.stretch_rate_wpm is not None:        # narrowed to the words that deviate: the evidence describes that stretch
        mean_wpm = float(c.stretch_rate_wpm)
        peak_signed = math.copysign(c.peak_z, c.mean_z)
    else:
        mean_wpm = float(np.mean(wpm[idx]))
        z = nb.rate_z[idx]
        peak_signed = float(z[int(np.argmax(np.abs(z)))])
    delta = mean_wpm - baseline.rate_wpm_mean
    timed, _ = _timed_words(aligned)
    words_in_span = sum(1 for _, s, _e in timed if c.start_s - _EPS_S <= s <= c.end_s + _EPS_S)
    return RateEvidence(
        rate_participant_wpm=_r(mean_wpm),
        rate_baseline_mean_wpm=_r(baseline.rate_wpm_mean),
        rate_baseline_std_wpm=_r(baseline.rate_wpm_std),
        rate_delta_wpm=_r(delta),
        rate_delta_pct=_r(100.0 * delta / baseline.rate_wpm_mean),
        rate_z_score=_r(c.mean_z),
        peak_z_score=_r(peak_signed),
        window_duration_s=_r(c.end_s - c.start_s),
        word_count_in_window=int(words_in_span),
    )


def _energy_evidence(
    c: FlawCandidate, nb: NormalizedFeatureBundle, baseline: BaselineStatsRecord, energy: Any
) -> EnergyEvidence:
    if c.run is not None:      # a run of words against the baseline's level for the same words
        run = c.run
        if not (math.isfinite(run.expected) and math.isfinite(run.observed)):
            raise EvidenceError("energy evidence needs finite observed and expected levels")
        return EnergyEvidence(
            energy_mean_db=_r(run.observed),
            energy_baseline_mean_db=_r(run.expected),
            energy_baseline_std_db=_r(run.sigma_equiv),
            energy_delta_db=_r(run.observed - run.expected),
            energy_z_score=_r(c.mean_z),
            window_duration_s=_r(c.end_s - c.start_s),
        )
    if energy is None:
        raise EvidenceError("energy evidence needs the energy extraction result")
    values = np.asarray(energy.values_db, dtype=np.float64)
    _require_aligned(len(values), len(nb.energy_z), "energy")
    idx = _indices(c, len(values), "energy")
    mean_db = float(np.mean(values[idx]))
    return EnergyEvidence(
        energy_mean_db=_r(mean_db),
        energy_baseline_mean_db=_r(baseline.energy_db_mean),
        energy_baseline_std_db=_r(baseline.energy_db_std),
        energy_delta_db=_r(mean_db - baseline.energy_db_mean),
        energy_z_score=_r(c.mean_z),
        window_duration_s=_r(c.end_s - c.start_s),
    )


def _pitch_evidence(c: FlawCandidate) -> FlatPitchEvidence:
    run = c.run
    if run is None:
        raise EvidenceError("flat pitch evidence needs the run of words that was found")
    if not (math.isfinite(run.observed) and math.isfinite(run.expected) and run.voiced_fraction is not None and math.isfinite(run.voiced_fraction)):
        raise EvidenceError("flat pitch evidence needs finite pitch movements and the voiced fraction of the run")
    return FlatPitchEvidence(
        f0_std_hz_in_window=_r(run.observed),
        f0_std_baseline_hz=_r(run.expected),
        f0_std_z=_r(c.mean_z),
        f0_voiced_fraction=_r(min(1.0, max(0.0, run.voiced_fraction))),
        window_duration_s=_r(c.end_s - c.start_s),
    )


def _pause_evidence(c: FlawCandidate, nb: NormalizedFeatureBundle) -> PauseEvidence:
    idx = _indices(c, len(nb.pauses), "pause")
    if len(idx) != 1:
        raise EvidenceError("a pause candidate must reference exactly one pause event")
    p = nb.pauses[idx[0]]
    if not (math.isfinite(p.z_score) and math.isfinite(p.baseline_mean_s) and math.isfinite(p.baseline_std_s)):
        raise EvidenceError("pause evidence needs a finite z-score and baseline statistics")
    return PauseEvidence(
        pause_duration_s=_r(p.event.duration_s),
        pause_baseline_mean_s=_r(p.baseline_mean_s),
        pause_baseline_std_s=_r(p.baseline_std_s),
        pause_delta_s=_r(p.event.duration_s - p.baseline_mean_s),
        pause_z_score=_r(p.z_score),
        boundary_type=p.event.boundary_type,
        detection_source=p.event.detection_source,
    )


def _rule(c: FlawCandidate, evidence: Evidence, cfg: DetectionConfig) -> DetectionRule:
    minimum = float(cfg.min_duration_s[c.type])
    if c.run is not None:
        above = c.type in (FlawType.TOO_FAST, FlawType.HIGH_ENERGY)
        threshold = cfg.z_run_rate if c.run.kind.startswith("rate") else cfg.z_run_pitch if c.run.kind.startswith("pitch") else cfg.z_run_energy
        return DetectionRule(
            feature=c.detection_feature, direction="above" if above else "below", threshold_z=threshold if above else -threshold,
            min_duration_s=minimum,
        )
    if c.type == FlawType.TOO_FAST:
        return DetectionRule(feature="rate_z", direction="above", threshold_z=cfg.z_rate_fast, min_duration_s=minimum)
    if c.type == FlawType.TOO_SLOW:
        return DetectionRule(feature="rate_z", direction="below", threshold_z=-cfg.z_rate_slow, min_duration_s=minimum)
    if c.type == FlawType.HIGH_ENERGY:
        return DetectionRule(feature="energy_z", direction="above", threshold_z=cfg.z_energy, min_duration_s=minimum)
    if c.type == FlawType.LOW_ENERGY:
        return DetectionRule(feature="energy_z", direction="below", threshold_z=-cfg.z_energy, min_duration_s=minimum)
    if c.type == FlawType.EXCESSIVE_PAUSE:
        # The threshold depends on the pause's boundary type.
        cross = evidence.boundary_type == PauseBoundaryType.CROSS_SENTENCE
        threshold = cfg.z_pause_cross if cross else cfg.z_pause_within
        return DetectionRule(feature="pause_z", direction="above", threshold_z=threshold, min_duration_s=minimum)
    raise EvidenceError(f"no detection rule for flaw type '{c.type.value}'")


def _words_in_interval(timed: Sequence[Tuple[str, float, float]], start_s: float, end_s: float) -> Tuple[str, ...]:
    return tuple(t for t, s, e in timed if start_s - _EPS_S <= (s + e) / 2.0 <= end_s + _EPS_S)


def _words_around_pause(timed: Sequence[Tuple[str, float, float]], start_s: float, end_s: float) -> Tuple[str, ...]:
    prev_idx: Optional[int] = None
    next_idx: Optional[int] = None
    for i, (_, s, _e) in enumerate(timed):
        if s < start_s - _EPS_S:
            prev_idx = i                      # last word that began before the pause began
    for i, (_, _s, e) in enumerate(timed):
        if e > end_s + _EPS_S:
            next_idx = i                      # first word that ends after the pause ended
            break
    chosen = sorted({i for i in (prev_idx, next_idx) if i is not None})
    return tuple(timed[i][0] for i in chosen)


def ground_flaws(
    detection: CandidateDetectionResult,
    normalized: NormalizedFeatureBundle,
    baseline: BaselineStatsRecord,
    *,
    rate: Any = None,
    energy: Any = None,
    aligned: Optional[AlignedTranscript] = None,
    severity: Optional[SeverityConfig] = None,
) -> List[GroundedFlaw]:
    """Build the `GroundedFlaw`s for every candidate of `detection`.

    Args:
        detection: output of `detect_candidates` (carries the config that was applied).
        normalized: the `NormalizedFeatureBundle` the candidates were detected on.
        baseline: the baseline statistics the bundle was normalized with.
        rate / energy: the raw `RateExtractionResult` / `EnergyExtractionResult` behind the bundle
            (needed for rate / energy evidence).
        aligned: the aligned transcript (word counts and affected words).
        severity: severity constants (defaults to the proposed ones).

    Flaws are ordered by (start, end, type) and numbered `flaw_001`, `flaw_002`, ...

    Raises:
        EvidenceError: a needed raw input is missing, arrays do not line up, or a candidate has a
            flaw type with no evidence builder (e.g. pitch_instability).
    """
    if not isinstance(detection, CandidateDetectionResult) or detection.config is None:
        raise TypeError("detection must be a CandidateDetectionResult produced by detect_candidates")
    if baseline.passage_id != normalized.baseline_passage_id or baseline.sha256 != normalized.baseline_sha256:
        raise EvidenceError("the baseline does not match the one the features were normalized with")
    cfg = detection.config
    sev_cfg = severity or SeverityConfig()
    timed = _timed_words(aligned)[0] if aligned is not None else []

    ordered = sorted(detection.candidates, key=lambda c: (c.start_s, c.end_s, c.type.value))
    flaws: List[GroundedFlaw] = []
    for number, c in enumerate(ordered, start=1):
        if c.type in (FlawType.TOO_FAST, FlawType.TOO_SLOW):
            evidence: Evidence = _rate_evidence(c, normalized, baseline, rate, aligned)
            if c.run is not None:
                warnings = (WARNING_RATE_OVERALL if c.run.kind == "rate_overall" else WARNING_RATE_RUN,)
            else:
                warnings = (WARNING_RATE if c.stretch_rate_wpm is None else WARNING_RATE_NARROWED,)
            words = _words_in_interval(timed, c.start_s, c.end_s)
        elif c.type in (FlawType.LOW_ENERGY, FlawType.HIGH_ENERGY):
            evidence = _energy_evidence(c, normalized, baseline, energy)
            warnings = (WARNING_ENERGY if c.run is None else WARNING_ENERGY_RUN,)
            words = _words_in_interval(timed, c.start_s, c.end_s)
        elif c.type == FlawType.FLAT_PITCH:
            evidence = _pitch_evidence(c)
            warnings = (WARNING_PITCH_OVERALL if c.run is not None and c.run.kind == "pitch_overall" else WARNING_PITCH_RUN,)
            words = _words_in_interval(timed, c.start_s, c.end_s)
        elif c.type == FlawType.EXCESSIVE_PAUSE:
            evidence = _pause_evidence(c, normalized)
            warnings = (WARNING_PAUSE,)
            words = _words_around_pause(timed, c.start_s, c.end_s)
        else:
            raise EvidenceError(f"no evidence builder for flaw type '{c.type.value}'")

        flaws.append(
            GroundedFlaw(
                flaw_id=f"flaw_{number:03d}",
                type=c.type,
                start_s=_r(c.start_s),
                end_s=_r(c.end_s),
                severity=compute_severity(c, sev_cfg),
                reliability=RELIABILITY_P0,
                low_confidence=False,
                evidence=evidence,
                rule=_rule(c, evidence, cfg),
                affected_words=words,
                warnings=warnings,
            )
        )
    return flaws


def clip_to_audio(flaws: Sequence[GroundedFlaw], duration_s: float) -> List[GroundedFlaw]:
    """Keep every flaw inside the analysed audio [0, duration_s] (processed time); a flaw that would be left empty is dropped.

    An aligner may place a word end a few milliseconds beyond the audio; the result contract requires every flaw to lie within the audio, so the
    interval is clipped here instead of failing the whole analysis.
    """
    out: List[GroundedFlaw] = []
    for f in flaws:
        start, end = max(0.0, f.start_s), min(float(duration_s), f.end_s)
        if end > start:
            out.append(f if (start, end) == (f.start_s, f.end_s) else replace(f, start_s=_r(start), end_s=_r(end)))
    return out


def to_api_flaw(
    flaw: GroundedFlaw,
    explanation: str,
    recommendation: str,
    method: ExplanationMethod = ExplanationMethod.TEMPLATE,
) -> Flaw:
    """Map a grounded flaw plus its explanation texts onto the public `Flaw` contract (validated)."""
    return Flaw(
        flaw_id=flaw.flaw_id,
        type=flaw.type,
        start_s=flaw.start_s,
        end_s=flaw.end_s,
        duration_s=flaw.duration_s,
        severity=flaw.severity,
        reliability=flaw.reliability,
        low_confidence=flaw.low_confidence,
        evidence=flaw.evidence,
        explanation=explanation,
        recommendation=recommendation,
        explanation_method=method,
        rule=flaw.rule,
        affected_words=list(flaw.affected_words),
        warnings=list(flaw.warnings),
    )
