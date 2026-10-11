"""Passage text helpers shared by the dataset tools (plan generator, recording checker).

One implementation of "what is a sentence / a word of a passage" so that the recording plan, the on-screen prompter, the quality check
and (later) the annotation tool all count the same way. A passage is plain prose: every sentence ends with . ? or ! and the text has no
digits, symbols, acronyms or abbreviations, because the forced aligner cannot place those reliably and the pause classifier treats a
word ending in a full stop as the end of a sentence (docs/methodology/recording-protocol.md section 4.1).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

#: Reading speed used only to ESTIMATE how long a stretch takes before a speaker's own baseline takes exist (words per second).
ESTIMATE_WORDS_PER_SECOND = 2.5  # 150 words per minute, the middle of the 130 to 160 range asked for in the protocol

#: Recommended passage size (protocol 4.1). Outside it the passage is accepted with a warning.
RECOMMENDED_WORDS = (100, 130)
#: Flaws are placed in sentences 3 to 6, so a passage needs at least six sentences.
MIN_SENTENCES = 6

_SENTENCE_BREAK = re.compile(r"(?<=[.?!])\s+")
_ALLOWED_CHAR = re.compile(r"[A-Za-z' ,.;:?!]")
_ABBREVIATIONS = {"dr.", "mr.", "mrs.", "ms.", "st.", "vs.", "etc.", "e.g.", "i.e.", "prof.", "jr.", "sr."}


def split_sentences(text: str) -> List[str]:
    """The sentences of a passage, in order, each as written (punctuation kept)."""
    return [s for s in _SENTENCE_BREAK.split(text.strip()) if s]


def words_of(sentence: str) -> List[str]:
    """The words of a sentence as the speaker reads them: whitespace-separated tokens, punctuation attached."""
    return sentence.split()


def passage_words(text: str) -> List[List[str]]:
    """The passage as a list of sentences, each a list of words."""
    return [words_of(s) for s in split_sentences(text)]


def word_count(text: str) -> int:
    return sum(len(s) for s in passage_words(text))


def estimated_duration_s(words: int) -> float:
    """A guide to how long `words` words take at a natural pace. NOT a measurement: a speaker's own baseline takes replace it."""
    return words / ESTIMATE_WORDS_PER_SECOND


def validate_passage(entry: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """(errors, warnings) for one passage entry. Errors make the passage unusable for recording; warnings are advice."""
    errors: List[str] = []
    warnings: List[str] = []
    pid = entry.get("passage_id", "?")
    text = entry.get("text")
    if not isinstance(text, str) or not text.strip():
        return [f"{pid}: the passage has no text."], warnings
    if re.search(r"\d", text):
        errors.append(f"{pid}: the text contains digits. Spell numbers out (for example 'seven o'clock').")
    other = sorted({c for c in text if not c.isdigit() and not _ALLOWED_CHAR.match(c)})
    if other:
        errors.append(f"{pid}: the text contains characters the aligner cannot place: {' '.join(repr(c) for c in other)}. Use plain letters and . , ; : ? ! only.")
    sentences = split_sentences(text)
    if len(sentences) < MIN_SENTENCES:
        errors.append(f"{pid}: only {len(sentences)} sentences; at least {MIN_SENTENCES} are needed so flaws can sit in sentences 3 to 6.")
    for i, sentence in enumerate(sentences, start=1):
        if sentence[-1] not in ".?!":
            errors.append(f"{pid}: sentence {i} does not end with . ? or !")
    for token in text.split():
        if token.lower() in _ABBREVIATIONS:
            errors.append(f"{pid}: the abbreviation '{token}' is not allowed (write the full word).")
        letters = [c for c in token if c.isalpha()]
        if len(letters) >= 2 and all(c.isupper() for c in letters):
            errors.append(f"{pid}: '{token}' looks like an acronym; write it out in words.")
    count = word_count(text)
    low, high = RECOMMENDED_WORDS
    if not low <= count <= high:
        warnings.append(f"{pid}: {count} words; {low} to {high} is recommended (about 45 to 55 seconds at a natural pace).")
    declared = entry.get("target_word_count")
    if isinstance(declared, int) and declared != count:
        warnings.append(f"{pid}: target_word_count says {declared} but the text has {count} words.")
    return errors, warnings
