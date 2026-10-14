"""Number-grounding guard for explanation text.

Rule: every number a user reads must originate from the analytical pipeline. An explanation (written by a
template today, possibly by an LLM later) may only repeat numbers that appear in its FACT SHEET, the
pre-formatted strings produced from the evidence (see `facts.py`). This module checks that, independently of
whoever wrote the text:

    * every numeric token must equal (numerically, ignoring sign and trailing zeros) a fact-sheet value;
    * spelled-out quantities that could smuggle in an invented ratio ("twice", "half", "three", ...) are
      rejected unless they are quoted transcript words;
    * digits inside a quoted transcript word are ignored, but ONLY when the quoted text is exactly one of the
      words the flaw really covers (so "187 wpm" in quotes is still flagged).

The guard cannot judge whether a sentence is TRUE (e.g. "above" vs "below"); it only guarantees that no
number or quantity is invented. Direction and meaning are fixed by the template wording and covered by tests.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Iterable, List, Mapping, Sequence

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_QUOTED_RE = re.compile(r"[“\"]([^”\"]+)[”\"]")

# Quantity words an LLM could use to state a number without digits. Matched as whole words, case-insensitive.
NUMBER_WORDS = frozenset(
    {
        "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
        "twelve", "twenty", "thirty", "forty", "fifty", "sixty", "hundred", "thousand", "twice", "thrice",
        "double", "doubled", "triple", "tripled", "quadruple", "half", "quarter", "dozen", "percent",
        "percentage",
    }
)
_WORD_RE = re.compile(r"[A-Za-z]+")


class ExplanationGuardError(ValueError):
    """Raised when an explanation text contains a number or quantity that is not in its fact sheet."""


def _decimal(token: str) -> Decimal:
    try:
        return Decimal(token)
    except InvalidOperation as exc:  # pragma: no cover - tokens come from _NUMBER_RE
        raise ValueError(f"not a number: {token!r}") from exc


def mask_quoted_words(text: str, covered_words: Iterable[str]) -> str:
    """Blank out quoted spans whose content is exactly one of `covered_words` (transcript words may contain digits)."""
    allowed = set(covered_words)

    def repl(match: "re.Match[str]") -> str:
        return " " if match.group(1).strip() in allowed else match.group(0)

    return _QUOTED_RE.sub(repl, text)


def find_ungrounded(text: str, facts: Mapping[str, str], covered_words: Sequence[str] = ()) -> List[str]:
    """Return the numbers / quantity words in `text` that are not backed by `facts` (empty list = grounded).

    Args:
        text: the explanation or recommendation text.
        facts: the fact sheet (name -> formatted number string). Non-numeric values are ignored.
        covered_words: transcript words the text may quote (their digits are ignored when quoted exactly).
    """
    allowed = set()
    for value in facts.values():
        try:
            allowed.add(_decimal(str(value).lstrip("+-−")))
        except (InvalidOperation, ValueError):
            continue

    scanned = mask_quoted_words(text, covered_words)
    problems: List[str] = []
    for token in _NUMBER_RE.findall(scanned):
        if _decimal(token) not in allowed:
            problems.append(token)
    for word in _WORD_RE.findall(scanned):
        if word.lower() in NUMBER_WORDS:
            problems.append(f"word:{word.lower()}")
    return problems


def assert_grounded(text: str, facts: Mapping[str, str], covered_words: Sequence[str] = ()) -> None:
    """Raise `ExplanationGuardError` if `text` contains an ungrounded number or quantity word."""
    problems = find_ungrounded(text, facts, covered_words)
    if problems:
        raise ExplanationGuardError(f"explanation contains numbers/quantities not in the fact sheet: {problems}")
