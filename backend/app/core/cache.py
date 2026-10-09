"""Deterministic file-based analysis cache (ARCHITECTURE.md §7.10, §26.4; DEC-019, DEC-023, DEC-032).

Two parts:

* `make_cache_key(parts)` / `analysis_id_for_key(key)`: the key is the SHA-256 of the canonical JSON (sorted keys, compact,
  no NaN) of everything the result depends on; the `analysis_id` is the RFC 4122 version-5 UUID of that key. The same
  input therefore always has the same id, and a stored result can be found by id alone (GET /result/{id}). The caller must
  put into the parts at least: the preprocessed-audio hash AND its trim offset (the hash covers only the trimmed samples,
  DEC-023), the baseline identity and hash, the passage, the manual transcript (if any), the config / pipeline / API
  contract versions, a fingerprint of every analytical constant in effect, and the library versions.
* `ResultCache`: stores each `AnalysisResult` as `<analysis_id>.json` in one directory, written atomically (temp file +
  rename) so a crash cannot leave a half-written result. A missing, unreadable or schema-invalid file is a cache miss,
  never an error, and is overwritten by the next `put`. Identifiers are validated, so an id can never address a file
  outside the cache directory.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Mapping, Optional, Union

from pydantic import ValidationError

from app.core.config import settings
from app.schemas.response import AnalysisResult

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_NAMESPACE = "speech-analytics:analysis:"


def make_cache_key(parts: Mapping[str, Any]) -> str:
    """SHA-256 hex digest of the canonical JSON of `parts` (raises on NaN / non-serialisable values)."""
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def analysis_id_for_key(key: str) -> str:
    """Deterministic UUID (version 5) string for a cache key."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, _NAMESPACE + key))


def is_valid_analysis_id(analysis_id: Any) -> bool:
    return isinstance(analysis_id, str) and bool(_ID_RE.match(analysis_id))


class ResultCache:
    """Atomic, directory-per-cache store of `AnalysisResult` JSON files keyed by `analysis_id`."""

    def __init__(self, directory: Optional[Union[str, Path]] = None) -> None:
        self.directory = Path(directory) if directory is not None else Path(settings.CACHE_DIR)

    def path_for(self, analysis_id: str) -> Path:
        if not is_valid_analysis_id(analysis_id):
            raise ValueError(f"invalid analysis_id {analysis_id!r}")
        return self.directory / f"{analysis_id}.json"

    def exists(self, analysis_id: str) -> bool:
        return is_valid_analysis_id(analysis_id) and self.path_for(analysis_id).is_file()

    def get(self, analysis_id: str) -> Optional[AnalysisResult]:
        """The stored result, or None on a miss (unknown id, missing / unreadable / invalid file)."""
        if not is_valid_analysis_id(analysis_id):
            return None
        path = self.path_for(analysis_id)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("cache file %s unreadable (%s); treating as a miss", path, exc)
            return None
        try:
            result = AnalysisResult.model_validate_json(text)
        except ValidationError as exc:
            logger.warning("cache file %s is not a valid AnalysisResult (%s); treating as a miss", path, exc.error_count())
            return None
        if result.analysis_id != analysis_id:
            logger.warning("cache file %s holds analysis_id %s; treating as a miss", path, result.analysis_id)
            return None
        return result

    def put(self, result: AnalysisResult) -> Path:
        """Store `result` under its own `analysis_id` (atomic replace). Returns the file path."""
        path = self.path_for(result.analysis_id)
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
        try:
            tmp.write_text(result.model_dump_json(), encoding="utf-8")
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()
        return path
