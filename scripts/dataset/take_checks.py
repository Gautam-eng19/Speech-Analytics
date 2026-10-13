"""Checks on aligned takes (TASK-126): is the word alignment plausible, and did the speaker really perform the planned flaw?

Pure and deterministic: the same alignment and audio give the same findings. Nothing here changes a file or a number of the analysis. The
findings are ADVICE for the people who record and annotate (docs/methodology/dataset-guide.md): a take that earns a warning is still
registered, but the warning travels with its annotation so nobody mistakes a weak example for a clear one. Every threshold sits in one
frozen dataclass (AGENTS.md section 20) and is a PROPOSED starting value, not a calibrated one.

Time bases: alignments are in PROCESSED-audio time (0 = first retained sample), the same time the analysis uses. Word numbers are the
1-based global positions that the recording plan uses (make_plan.py), so the plan's stretch maps straight onto the aligned words.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import make_plan as mp  # noqa: E402  (the plan's own planned speed factors, level offsets and pause lengths)
from app.schemas.contracts import AlignedTranscript  # noqa: E402
from app.services.audio.preprocessor import speech_level_dbfs  # noqa: E402

OK, INFO, WARN, FAIL = "ok", "info", "warn", "fail"


@dataclass(frozen=True)
class Finding:
    level: str  # OK, INFO, WARN or FAIL
    message: str


@dataclass(frozen=True)
class AlignmentGates:
    """When is an alignment too doubtful to use? PROPOSED, uncalibrated: they send a take to a human, they never change the analysis."""

    max_untimed_share: float = 0.05     # more words than this share without a time: fail (ANY untimed word fails a baseline take)
    low_confidence: float = 0.30        # a word with a lower alignment score counts as doubtful
    max_doubtful_share: float = 0.20    # more doubtful words than this share: warn
    min_mean_confidence: float = 0.50   # a lower average alignment score: warn
    max_edge_gap_s: float = 1.5         # first word starts / last word ends further than this from the ends of the trimmed audio: warn
    min_coverage: float = 0.50          # the words cover less than this share of the audio: warn (the analysis itself warns below 0.80)


@dataclass(frozen=True)
class PerformedGates:
    """When does a take count as a CLEAR example of its planned flaw? Measured against the same speaker's own baseline takes."""

    change_share: float = 0.5   # speed and loudness: at least this share of the planned change must be there (half way)
    pause_share: float = 0.7    # a pause: at least this share of the planned minimum length
    min_stretch_s: float = 0.5  # a stretch shorter than this is too short to measure a loudness change in


ALIGNMENT_GATES = AlignmentGates()
PERFORMED_GATES = PerformedGates()


def normalise_word(word: str) -> str:
    """A word without punctuation or case, for comparing the aligner's word with the passage's word."""
    return re.sub(r"[^a-z0-9']", "", word.lower())


# ---------------------------------------------------------------------------------------------------------------------------------
# Is the alignment plausible?
# ---------------------------------------------------------------------------------------------------------------------------------

def assess_alignment(
    aligned: AlignedTranscript,
    passage_words: Sequence[str],
    audio_duration_s: float,
    is_baseline: bool,
    gates: AlignmentGates = ALIGNMENT_GATES,
) -> List[Finding]:
    """Warnings and failures about one alignment of a take against its passage (an empty list means nothing doubtful).

    A FAIL means the take cannot be tied to the passage words (no use as a baseline or as a flaw example); a WARN means a person should
    look at the word labels before trusting it.
    """
    words = aligned.words
    if len(words) != len(passage_words):
        return [Finding(FAIL, f"the aligner returned {len(words)} words but the passage has {len(passage_words)} words, so the words of the take "
                              "cannot be matched to the words of the passage")]
    findings: List[Finding] = []

    different = [i for i, (got, want) in enumerate(zip(words, passage_words)) if normalise_word(got.word) != normalise_word(want)]
    if different:
        i = different[0]
        findings.append(Finding(WARN, f"{len(different)} aligned word(s) differ from the passage text, the first at word {i + 1} "
                                      f"('{words[i].word}' instead of '{passage_words[i]}')"))

    untimed = [i for i, w in enumerate(words) if w.start_s is None or w.end_s is None]
    if untimed:
        share = len(untimed) / len(words)
        text = f"{len(untimed)} of {len(words)} words got no time, the first is word {untimed[0] + 1} ('{words[untimed[0]].word}')"
        if is_baseline or share > gates.max_untimed_share:
            findings.append(Finding(FAIL, text + (": a baseline needs every word placed" if is_baseline else "")))
        else:
            findings.append(Finding(WARN, text))

    if aligned.total_coverage_pct < gates.min_coverage:
        findings.append(Finding(WARN, f"the words cover only {aligned.total_coverage_pct:.0%} of the audio; the alignment is probably wrong"))

    timed = [w for w in words if w.start_s is not None and w.end_s is not None]
    if timed:
        lead = min(w.start_s for w in timed)
        tail = audio_duration_s - max(w.end_s for w in timed)
        if lead > gates.max_edge_gap_s:
            findings.append(Finding(WARN, f"the first word starts {lead:.1f} s into the trimmed audio; the aligner may have drifted"))
        if tail > gates.max_edge_gap_s:
            findings.append(Finding(WARN, f"the last word ends {tail:.1f} s before the end of the trimmed audio; the aligner may have drifted"))

    scores = [w.confidence for w in words if w.confidence is not None]
    if scores:
        mean = sum(scores) / len(scores)
        doubtful = sum(1 for s in scores if s < gates.low_confidence)
        if mean < gates.min_mean_confidence:
            findings.append(Finding(WARN, f"the aligner is unsure about this take (average score {mean:.2f}); check the words by ear"))
        elif doubtful / len(scores) > gates.max_doubtful_share:
            findings.append(Finding(WARN, f"{doubtful} of {len(scores)} words have a low alignment score; check the words by ear"))
    return findings


def pace_wpm(aligned: AlignedTranscript) -> Optional[float]:
    """Words per minute from the first timed word to the last (None when fewer than two words have times)."""
    timed = [w for w in aligned.words if w.start_s is not None and w.end_s is not None]
    if len(timed) < 2:
        return None
    span = max(w.end_s for w in timed) - min(w.start_s for w in timed)
    return None if span <= 0 else len(timed) * 60.0 / span


# ---------------------------------------------------------------------------------------------------------------------------------
# Where is the planned flaw?
# ---------------------------------------------------------------------------------------------------------------------------------

def word_span(aligned: AlignedTranscript, first_word: int, last_word: int) -> Optional[Tuple[float, float]]:
    """(start, end) in seconds of words first_word..last_word (1-based, inclusive), or None when a boundary word has no time."""
    words = aligned.words
    if not (1 <= first_word <= last_word <= len(words)):
        raise ValueError(f"words {first_word}..{last_word} are outside the {len(words)} aligned words")
    first, last = words[first_word - 1], words[last_word - 1]
    if first.start_s is None or last.end_s is None or last.end_s < first.start_s:
        return None
    return float(first.start_s), float(last.end_s)


def gap_after_word(aligned: AlignedTranscript, word: int) -> Optional[Tuple[float, float]]:
    """(start, end) of the silence between word `word` and the next one (1-based), or None when either has no time."""
    words = aligned.words
    if not (1 <= word < len(words)):
        raise ValueError(f"there is no word after word {word} ({len(words)} aligned words)")
    before, after = words[word - 1], words[word]
    if before.end_s is None or after.start_s is None or after.start_s < before.end_s:
        return None
    return float(before.end_s), float(after.start_s)


# ---------------------------------------------------------------------------------------------------------------------------------
# Did the speaker perform it?
# ---------------------------------------------------------------------------------------------------------------------------------

def level_offset_db(audio: np.ndarray, sample_rate: int, span: Tuple[float, float], window_db: float,
                    gates: PerformedGates = PERFORMED_GATES) -> Optional[float]:
    """Speech level inside `span` minus the speech level of the rest of the take, in dB (None when it cannot be measured).

    Both levels are the typical (median) loudness of the speaking frames, measured the way the loudness scaling measures it
    (`speech_level_dbfs`), so one global gain does not change the result.
    """
    start, end = int(round(span[0] * sample_rate)), int(round(span[1] * sample_rate))
    if end - start < gates.min_stretch_s * sample_rate:
        return None
    inside = speech_level_dbfs(audio[start:end], sample_rate, window_db)
    outside = speech_level_dbfs(np.concatenate([audio[:start], audio[end:]]), sample_rate, window_db)
    if inside is None or outside is None:
        return None
    return inside - outside


def check_speed(flaw_type: str, take_number: int, flawed_s: float, reference_s: float, gates: PerformedGates = PERFORMED_GATES) -> Finding:
    """Did the stretch really go faster / slower than the speaker's own baseline takes?"""
    planned = mp.SPEED_FACTOR[(flaw_type, take_number)]
    ratio = flawed_s / reference_s
    halfway = 1.0 + gates.change_share * (planned - 1.0)
    clear = ratio <= halfway if planned < 1.0 else ratio >= halfway
    text = f"the stretch took {ratio:.2f} times as long as in the speaker's baseline takes (the plan asked for about {planned:.2f})"
    return Finding(OK if clear else WARN, text if clear else text + "; this take is a weak example of the flaw")


def check_level(flaw_type: str, take_number: int, offset_db: float, reference_offset_db: float, gates: PerformedGates = PERFORMED_GATES) -> Finding:
    """Did the stretch really get louder / quieter than the rest, compared with how the speaker's baseline takes vary?"""
    planned = mp.LEVEL_DB[take_number]
    change = offset_db - reference_offset_db
    clear = change >= gates.change_share * planned if flaw_type == "high_energy" else change <= -gates.change_share * planned
    sign = "+" if flaw_type == "high_energy" else "-"
    text = f"the stretch was {change:+.1f} dB against the rest of the take, compared with the baseline takes (the plan asked for about {sign}{planned} dB)"
    return Finding(OK if clear else WARN, text if clear else text + "; this take is a weak example of the flaw")


def check_pause(take_number: int, gap_s: float, gates: PerformedGates = PERFORMED_GATES) -> Finding:
    """Is the silence the plan asked for really there?"""
    low, high = mp.PAUSE_SECONDS[take_number]
    clear = gap_s >= gates.pause_share * low
    text = f"the silence after the word lasts {gap_s:.1f} s (the plan asked for {low:g} to {high:g} s)"
    return Finding(OK if clear else WARN, text if clear else text + "; this take is a weak example of the flaw")
