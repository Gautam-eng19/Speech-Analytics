"""Whisper transcription service (TASK-021, ARCHITECTURE.md §7.2, §11).

Responsibility:
    PreprocessedAudio  →  Transcript

This service answers "What was said?"  It does NOT perform forced alignment
(that belongs to TASK-022/services/alignment/) and does NOT extract acoustic
features (services/features/).

Design notes
------------
- Accepts only the canonical ``PreprocessedAudio`` contract (float32 PCM, mono,
  16 kHz) produced by services/audio/.
- Passes the numpy array directly to ``whisper.transcribe()`` — never uses
  ``whisper.load_audio()`` which requires system ffmpeg.
- Whisper model is loaded once per ``WhisperTranscriber`` instance (no reload
  per request).
- A module-level singleton (``_transcriber``) is created lazily on first use
  to avoid importing torch at import time.
- All configuration is explicit and deterministic (model name, language, task,
  word_timestamps, temperature).
- Word timestamps are enabled so TASK-022 has Whisper's approximate timings
  as a starting point for forced alignment.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from app.core.config import settings
from app.schemas.contracts import PreprocessedAudio, Transcript, TranscriptSegment, WordTiming
from app.schemas.common import TranscriptSource

logger = logging.getLogger(__name__)

# Target sample rate expected by the Whisper model (hardcoded in the Whisper
# library itself — not a project config option).
_WHISPER_EXPECTED_SR = 16_000


class TranscriptionError(Exception):
    """Raised when transcription cannot be completed for a recoverable reason."""


class TranscriptionConfigError(ValueError):
    """Raised when the transcription service is misconfigured."""


class WhisperTranscriber:
    """Deterministic Whisper-based transcription service.

    Parameters
    ----------
    model_name:
        Whisper model to load ("base", "small", "medium", …).
        Defaults to ``settings.WHISPER_MODEL``.
    language:
        ISO 639-1 language code to force (e.g. ``"en"``).
        ``None`` means auto-detect (non-deterministic across hardware).
        Defaults to ``settings.WHISPER_LANGUAGE``.
    task:
        ``"transcribe"`` (keep original language) or ``"translate"`` (to English).
    temperature:
        Decoding temperature.  0.0 = greedy / fully deterministic.
    word_timestamps:
        Enable Whisper's word-level timestamp output.  Must be ``True`` so
        TASK-022 receives approximate timings.
    """

    def __init__(
        self,
        model_name: str = settings.WHISPER_MODEL,
        language: Optional[str] = settings.WHISPER_LANGUAGE or None,
        task: str = "transcribe",
        temperature: float = 0.0,
        word_timestamps: bool = True,
    ) -> None:
        if not model_name:
            raise TranscriptionConfigError("model_name must not be empty")
        if task not in ("transcribe", "translate"):
            raise TranscriptionConfigError(f"Invalid task '{task}'; expected 'transcribe' or 'translate'")
        if not (0.0 <= temperature <= 1.0):
            raise TranscriptionConfigError(f"temperature must be in [0.0, 1.0], got {temperature}")

        self._model_name = model_name
        self._language = language
        self._task = task
        self._temperature = temperature
        self._word_timestamps = word_timestamps
        self._model: Any = None  # loaded lazily

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load_model(self) -> None:
        """Load the Whisper model into memory (idempotent)."""
        if self._model is not None:
            return
        try:
            import whisper as _whisper  # type: ignore[import]
        except ImportError as exc:
            raise TranscriptionError(
                "openai-whisper is not installed. "
                "Run: pip install openai-whisper"
            ) from exc

        logger.info("Loading Whisper model '%s'…", self._model_name)
        try:
            self._model = _whisper.load_model(self._model_name)
        except Exception as exc:
            raise TranscriptionError(
                f"Failed to load Whisper model '{self._model_name}': {exc}"
            ) from exc
        logger.info("Whisper model '%s' loaded successfully.", self._model_name)

    def transcribe(self, audio: PreprocessedAudio) -> Transcript:
        """Transcribe preprocessed audio and return a ``Transcript``.

        Parameters
        ----------
        audio:
            Canonical ``PreprocessedAudio`` from services/audio/.

        Returns
        -------
        Transcript
            Contains full text, segments, and word timings.

        Raises
        ------
        TranscriptionConfigError
            If the audio contract is incompatible (wrong sample rate or shape).
        TranscriptionError
            If Whisper transcription fails at runtime.
        """
        self._validate_audio(audio)
        self.load_model()

        try:
            raw = self._run_whisper(audio.audio_array)
        except TranscriptionError:
            raise
        except Exception as exc:
            raise TranscriptionError(f"Whisper transcription failed: {exc}") from exc

        return self._build_transcript(raw)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_audio(self, audio: PreprocessedAudio) -> None:
        """Raise TranscriptionConfigError if audio is incompatible."""
        if not isinstance(audio, PreprocessedAudio):
            raise TranscriptionConfigError(
                f"Expected PreprocessedAudio, got {type(audio).__name__}"
            )
        if audio.sample_rate_hz != _WHISPER_EXPECTED_SR:
            raise TranscriptionConfigError(
                f"Whisper requires {_WHISPER_EXPECTED_SR} Hz audio; "
                f"got {audio.sample_rate_hz} Hz. "
                "Ensure the audio preprocessing stage resamples to 16 kHz."
            )
        if audio.audio_array.ndim != 1 or audio.audio_array.dtype != np.float32:
            raise TranscriptionConfigError(
                "audio_array must be a 1D float32 numpy array (mono PCM)."
            )

    def _run_whisper(self, audio_array: np.ndarray) -> dict:
        """Call whisper.transcribe with pinned, deterministic options.

        Audio is passed as a numpy array — ffmpeg is not required.
        """
        return self._model.transcribe(
            audio_array,
            language=self._language,
            task=self._task,
            temperature=self._temperature,
            word_timestamps=self._word_timestamps,
            # Disable verbose console output from the Whisper library itself.
            verbose=False,
        )

    def _build_transcript(self, raw: dict) -> Transcript:
        """Convert Whisper's raw output dict into the canonical Transcript."""
        full_text: str = (raw.get("text") or "").strip()
        detected_language: Optional[str] = raw.get("language")

        segments: list[TranscriptSegment] = []
        flat_words: list[WordTiming] = []

        for seg_idx, seg in enumerate(raw.get("segments", [])):
            word_timings: list[WordTiming] = []
            for w in seg.get("words", []):
                wt = WordTiming(
                    word=w.get("word", "").strip(),
                    approx_start_s=_safe_float(w.get("start")),
                    approx_end_s=_safe_float(w.get("end")),
                    probability=_safe_float(w.get("probability")),
                )
                word_timings.append(wt)
                flat_words.append(wt)

            segment = TranscriptSegment(
                segment_id=seg_idx,
                text=(seg.get("text") or "").strip(),
                start_s=float(seg.get("start", 0.0)),
                end_s=float(seg.get("end", 0.0)),
                no_speech_prob=_safe_float(seg.get("no_speech_prob")),
                words=word_timings,
            )
            segments.append(segment)

        return Transcript(
            text=full_text,
            segments=segments,
            words=flat_words,
            model_name=f"whisper_{self._model_name}",
            source=TranscriptSource.ASR,
            language=detected_language,
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_transcriber: Optional[WhisperTranscriber] = None


def get_transcriber(
    model_name: Optional[str] = None,
    language: Optional[str] = None,
) -> WhisperTranscriber:
    """Return the module-level ``WhisperTranscriber`` singleton.

    The singleton is created once with the provided (or default) parameters.
    Subsequent calls ignore ``model_name`` / ``language`` so all callers share
    the same loaded model.  If you need a different configuration, instantiate
    ``WhisperTranscriber`` directly.
    """
    global _transcriber
    if _transcriber is None:
        _transcriber = WhisperTranscriber(
            model_name=model_name or settings.WHISPER_MODEL,
            language=language or settings.WHISPER_LANGUAGE or None,
        )
    return _transcriber


def transcribe(audio: PreprocessedAudio) -> Transcript:
    """Convenience function: transcribe using the module-level singleton."""
    return get_transcriber().transcribe(audio)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _safe_float(value: Any) -> Optional[float]:
    """Convert to float, returning None for None / non-numeric values."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
