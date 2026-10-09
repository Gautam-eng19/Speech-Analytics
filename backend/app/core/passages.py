"""Passage catalog: the reference text of each passage (data/metadata/passages.json; dataset-schema.md §3.1).

Used only to check that the participant read the passage the baseline belongs to (delivery is compared with a baseline of the
SAME content). A missing file, unknown passage or malformed entry gives `None`, never an error: the check is then reported as
unavailable instead of blocking the analysis.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional, Union

from app.core.config import settings
from app.schemas.request import ID_PATTERN


class PassageCatalog:
    """Read-only lookup of passage texts."""

    def __init__(self, path: Optional[Union[str, Path]] = None) -> None:
        self.path = Path(path) if path is not None else Path(settings.DATA_DIR) / "metadata" / "passages.json"

    def get_text(self, passage_id: str) -> Optional[str]:
        if not isinstance(passage_id, str) or not re.match(ID_PATTERN, passage_id):
            return None
        try:
            entries = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(entries, list):
            return None
        for entry in entries:
            if isinstance(entry, dict) and entry.get("passage_id") == passage_id:
                text = entry.get("text")
                return text if isinstance(text, str) and text.strip() else None
        return None
