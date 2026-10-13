"""Request contract for POST /api/v1/analyze (multipart/form-data).

The audio file itself is a multipart file part (`participant_audio`) and is not
a Pydantic field. `AudioUploadMeta` describes it for validation purposes; size
and duration limits are config-driven (core/config.py) and are passed in, never
hard-coded here.
"""
from __future__ import annotations

import os
from typing import Optional

from pydantic import Field, field_validator, model_validator

from .common import ContractModel, SpeakerGender

# Allowed upload formats (ARCHITECTURE.md §10, §23): WAV or MP3.
ALLOWED_AUDIO_EXTENSIONS = frozenset({".wav", ".mp3"})
ALLOWED_AUDIO_CONTENT_TYPES = frozenset(
    {
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
        "audio/vnd.wave",
        "audio/mpeg",
        "audio/mp3",
    }
)

# Identifiers are used to locate baseline files; restrict to a safe charset
# (path-traversal protection, ARCHITECTURE.md §27).
ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$"


class AnalyzeRequest(ContractModel):
    """Non-file form fields of POST /api/v1/analyze."""

    baseline_id: str = Field(pattern=ID_PATTERN)
    passage_id: str = Field(pattern=ID_PATTERN)
    speaker_gender: Optional[SpeakerGender] = None
    # ARCHITECTURE.md §23: optional at P0. If supplied it must equal the server
    # CONFIG_VERSION, otherwise the API returns CONFIG_VERSION_MISMATCH.
    config_version: Optional[str] = Field(default=None, min_length=1)
    # ARCHITECTURE.md §7.2/§11: optional manual transcript bypasses ASR.
    manual_transcript: Optional[str] = Field(default=None, min_length=1)

    @field_validator("manual_transcript")
    @classmethod
    def _transcript_not_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("manual_transcript must not be blank")
        return v


class AudioUploadMeta(ContractModel):
    """Metadata of the uploaded `participant_audio` part, for validation."""

    filename: str = Field(min_length=1)
    content_type: str
    size_bytes: int

    @field_validator("filename")
    @classmethod
    def _sanitize_and_check_extension(cls, v: str) -> str:
        # Never trust client filenames (ARCHITECTURE.md §27).
        name = os.path.basename(v.replace("\\", "/"))
        if not name:
            raise ValueError("filename is empty")
        ext = os.path.splitext(name)[1].lower()
        if ext not in ALLOWED_AUDIO_EXTENSIONS:
            raise ValueError(f"unsupported audio extension '{ext}'; expected WAV or MP3")
        return name

    @field_validator("content_type")
    @classmethod
    def _check_content_type(cls, v: str) -> str:
        base = v.split(";", 1)[0].strip().lower()
        if base not in ALLOWED_AUDIO_CONTENT_TYPES:
            raise ValueError(f"unsupported content type '{base}'; expected WAV or MP3")
        return base

    @field_validator("size_bytes")
    @classmethod
    def _non_empty(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("uploaded audio is empty")
        return v

    @model_validator(mode="after")
    def _extension_matches_content_type(self) -> "AudioUploadMeta":
        ext = os.path.splitext(self.filename)[1].lower()
        is_wav_type = self.content_type in {
            "audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"
        }
        if (ext == ".wav") != is_wav_type:
            raise ValueError("file extension does not match content type")
        return self

    def ensure_within_limit(self, max_bytes: int) -> None:
        """Raise ValueError if the upload exceeds the config-supplied limit."""
        if self.size_bytes > max_bytes:
            raise ValueError(
                f"upload of {self.size_bytes} bytes exceeds limit of {max_bytes} bytes"
            )
