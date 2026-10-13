"""Explanation service package (ARCHITECTURE.md §7.7, §22): evidence in, readable text out, numbers guarded."""
from .facts import TYPE_LABELS, build_fact_sheet, fmt
from .guard import ExplanationGuardError, assert_grounded, find_ungrounded
from .summary import FEATURE_LABELS, build_overall_summary
from .templates import Explanation, ExplanationError, explain_flaw

__all__ = [
    "TYPE_LABELS",
    "FEATURE_LABELS",
    "build_fact_sheet",
    "fmt",
    "ExplanationGuardError",
    "assert_grounded",
    "find_ungrounded",
    "Explanation",
    "ExplanationError",
    "explain_flaw",
    "build_overall_summary",
]
