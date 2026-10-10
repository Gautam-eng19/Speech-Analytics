"""Baseline statistics serving (ARCHITECTURE.md §14.5, DEC-015; TASK-040).

`BaselineProvider.get(passage_id)` is the single entry point through which pipeline stages
obtain baseline statistics. Callers never learn how many baseline recordings contributed.

Statistics are PRECOMPUTED offline by `scripts/dataset/build_baseline_stats.py` and stored as
JSON (one file per passage) under ``<DATA_DIR>/processed/baseline_stats/``. They are never
recomputed per request. The provider only reads and verifies:

    * the identifier is safe (no path traversal) and the file exists;
    * the JSON parses into a valid `BaselineStatsRecord` (finite numbers, required fields);
    * the file describes the requested passage;
    * the stored `sha256` matches the content (detects hand-edited or corrupted files).

Missing or invalid baselines raise explicit errors; no default or "average speaker"
statistics are ever substituted (the baseline is the effective delivery of the SAME content,
not a universal human average).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Union

from pydantic import ValidationError

from app.core.config import settings
from app.schemas.contracts import BaselineStatsRecord
from app.schemas.request import ID_PATTERN

BASELINE_STATS_SUBDIR = Path("processed") / "baseline_stats"


class BaselineError(Exception):
    """Base class for baseline lookup failures."""


class BaselineNotFoundError(BaselineError, LookupError):
    """No baseline statistics exist for the requested passage (maps to BASELINE_NOT_FOUND)."""


class BaselineIntegrityError(BaselineError, ValueError):
    """A baseline statistics file exists but is unreadable, invalid, or fails verification.

    `code` is a short machine-readable reason that is safe to show to clients (the message itself names server paths):
    ``unreadable``, ``invalid_file``, ``integrity_check_failed`` or ``passage_mismatch``.
    """

    code = "integrity_error"

    def __init__(self, message: str, code: Optional[str] = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class BaselinePassageMismatchError(BaselineIntegrityError):
    """The requested baseline exists but describes a different passage than the one requested."""

    code = "passage_mismatch"


class BaselineProvider:
    """Read-only provider of per-passage `BaselineStatsRecord` objects."""

    def __init__(self, directory: Optional[Union[str, Path]] = None) -> None:
        self.directory = (
            Path(directory) if directory is not None else Path(settings.DATA_DIR) / BASELINE_STATS_SUBDIR
        )

    def path_for(self, passage_id: str) -> Path:
        """Location of the stats file for `passage_id` (identifier validated first)."""
        if not isinstance(passage_id, str) or not re.match(ID_PATTERN, passage_id):
            raise BaselineNotFoundError(f"invalid passage_id {passage_id!r}")
        return self.directory / f"{passage_id}.json"

    def exists(self, passage_id: str) -> bool:
        try:
            return self.path_for(passage_id).is_file()
        except BaselineNotFoundError:
            return False

    def list_passages(self) -> List[str]:
        """Passage ids that have a stats file, sorted (deterministic)."""
        if not self.directory.is_dir():
            return []
        return sorted(
            p.stem for p in self.directory.glob("*.json") if re.match(ID_PATTERN, p.stem)
        )

    def list_baselines(self) -> List[str]:
        """Baseline ids (file stems) that have a stats file, sorted; the same list as `list_passages` (kept for DEC-015)."""
        return self.list_passages()

    def load(self, baseline_id: str) -> BaselineStatsRecord:
        """Return the verified record stored under `baseline_id`, WITHOUT requiring it to describe a particular passage.

        Raises:
            BaselineNotFoundError: invalid identifier or no stats file for it.
            BaselineIntegrityError: file unreadable, schema-invalid, or with a `sha256` that does not match its content.
        """
        path = self.path_for(baseline_id)
        if not path.is_file():
            raise BaselineNotFoundError(f"no baseline statistics '{baseline_id}' in {self.directory}")

        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise BaselineIntegrityError(f"cannot read baseline file {path}: {exc}", code="unreadable") from exc

        try:
            record = BaselineStatsRecord.model_validate_json(text)
        except ValidationError as exc:
            raise BaselineIntegrityError(f"invalid baseline file {path}: {exc}", code="invalid_file") from exc

        if not record.verify_sha256():
            raise BaselineIntegrityError(
                f"baseline file {path} fails sha256 verification (content changed since it was built)",
                code="integrity_check_failed",
            )
        return record

    def get(self, baseline_id: str, *, passage_id: Optional[str] = None) -> BaselineStatsRecord:
        """Return verified baseline statistics.

        `baseline_id` selects the statistics file (``<baseline_id>.json``). The builder names its output after the
        passage, so by default ``baseline_id`` IS the passage id (DEC-015: ``get(passage_id)``). When the caller also
        names the passage it is analysing, the file must describe exactly that passage: several baselines (e.g.
        different baseline speakers) can then exist for one passage, but a baseline can never be applied to another one.

        Raises:
            BaselineNotFoundError: invalid identifier or no stats file for it.
            BaselinePassageMismatchError: the file describes a different passage than expected.
            BaselineIntegrityError: file unreadable, schema-invalid, or with a `sha256` that does not match its content.
        """
        if passage_id is not None and (not isinstance(passage_id, str) or not re.match(ID_PATTERN, passage_id)):
            raise BaselineNotFoundError(f"invalid passage_id {passage_id!r}")
        record = self.load(baseline_id)
        expected = passage_id if passage_id is not None else baseline_id
        if record.passage_id != expected:
            raise BaselinePassageMismatchError(
                f"baseline file {self.path_for(baseline_id)} describes passage '{record.passage_id}', expected '{expected}'"
            )
        return record


def rate_statistics_thin(record: BaselineStatsRecord) -> bool:
    """True if the baseline's speech-rate statistics rest on very few rolling windows (rate z-scores can be over-sensitive)."""
    return record.n_rate_windows < settings.BASELINE_THIN_RATE_WINDOWS


def pause_statistics_thin(record: BaselineStatsRecord) -> bool:
    """True if the baseline's pause statistics rest on very few within-phrase pauses (pause z-scores can be over-sensitive)."""
    return record.n_pauses_within_phrase < settings.BASELINE_THIN_PAUSES
