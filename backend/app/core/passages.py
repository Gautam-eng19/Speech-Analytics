"""Passage catalog: the reference text of each passage (data/metadata/passages.json; dataset-schema.md §3.1).

Used only to check that the participant read the passage the baseline belongs to (delivery is compared with a baseline of the
SAME content). A missing file, unknown passage or malformed entry gives `None`, never an error: the check is then reported as
unavailable instead of blocking the analysis.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from app.core.baseline import CUSTOM_PASSAGES_FILE, is_custom_id
from app.core.config import settings
from app.schemas.request import ID_PATTERN


@dataclass(frozen=True)
class PassageInfo:
    """A passage as listed in the catalog: its id, optional title and reference text."""

    passage_id: str
    title: Optional[str]
    text: str


class PassageCatalog:
    """Read-only lookup of passage texts."""

    def __init__(self, path: Optional[Union[str, Path]] = None, custom_path: Optional[Union[str, Path]] = None) -> None:
        """`path` is the project catalog, `custom_path` the user's own passages. Naming `path` alone means no custom passages."""
        self.path = Path(path) if path is not None else Path(settings.DATA_DIR) / "metadata" / "passages.json"
        if custom_path is not None:
            self.custom_path: Optional[Path] = Path(custom_path)
        else:
            self.custom_path = Path(settings.DATA_DIR) / CUSTOM_PASSAGES_FILE if path is None else None

    def get(self, passage_id: str) -> Optional[PassageInfo]:
        """The catalog entry for `passage_id`, or None if the id, the file or the entry is missing or malformed."""
        if not isinstance(passage_id, str) or not re.match(ID_PATTERN, passage_id):
            return None
        source = self.custom_path if is_custom_id(passage_id) else self.path
        if source is None:
            return None
        try:
            entries = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(entries, list):
            return None
        for entry in entries:
            if isinstance(entry, dict) and entry.get("passage_id") == passage_id:
                text = entry.get("text")
                if not (isinstance(text, str) and text.strip()):
                    return None
                title = entry.get("title")
                return PassageInfo(passage_id, title if isinstance(title, str) and title.strip() else None, text)
        return None

    def get_text(self, passage_id: str) -> Optional[str]:
        info = self.get(passage_id)
        return info.text if info is not None else None
