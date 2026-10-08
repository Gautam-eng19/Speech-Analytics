"""Forced Alignment Service using WhisperX (TASK-022, ARCHITECTURE.md §7.3, §9.3, §12).

Responsibility:
    (PreprocessedAudio, Transcript)  →  AlignedTranscript

This service aligns the already-transcribed text (from TASK-021) to the preprocessed
audio array using WhisperX forced alignment on CPU/GPU.

Design notes:
- Accepts only the canonical ``PreprocessedAudio`` (mono, 16 kHz, float32 PCM)
  and ``Transcript`` (produced by TASK-021).
- Does NOT transcribe audio (transcription belongs to TASK-021).
- Does NOT extract features (F0, MFCC, energy, rate, pause belong to services/features/).
- Uses WhisperX (`load_align_model` and `align`).
- Caches loaded alignment models by (language_code, device, model_name) to avoid
  reloading models on every request.
- Preserves the original transcript text exactly.
- Computes `total_coverage_pct` as the fraction of audio covered by aligned words.
- All errors are typed and explicit; exceptions are never swallowed silently.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np

from app.core.config import settings
from app.schemas.common import AlignmentMethod
from app.schemas.contracts import (
    AlignedTranscript,
    AlignedWord,
    PreprocessedAudio,
    Transcript,
)

logger = logging.getLogger(__name__)

_EXPECTED_SAMPLE_RATE = 16_000


# ---------------------------------------------------------------------------
# Exceptions (ARCHITECTURE.md §23, TASK-022 specification)
# ---------------------------------------------------------------------------

class AlignmentError(Exception):
    """Base exception for all alignment failures."""


class AlignmentConfigError(ValueError, AlignmentError):
    """Raised when alignment inputs or configurations are invalid."""


class AlignmentModelError(AlignmentError):
    """Raised when loading the alignment model fails."""


class AlignmentRuntimeError(AlignmentError):
    """Raised when WhisperX alignment execution fails at runtime."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AlignmentConfig:
    """Explicit configuration parameters for forced alignment.

    Attributes:
        device: Device to run alignment on ("cpu" or "cuda"). Default "cpu".
        language_code: ISO 639-1 code for alignment model (default "en").
        model_name: Optional override for wav2vec2 alignment model name.
        model_dir: Optional directory for cached alignment model weights.
        interpolate_method: Method to interpolate character timings ("nearest").
        return_char_alignments: Whether to include char alignments (default False).
    """

    device: str = settings.ALIGNMENT_DEVICE
    language_code: str = settings.ALIGNMENT_LANGUAGE
    model_name: Optional[str] = None
    model_dir: Optional[str] = settings.ALIGNMENT_MODEL_DIR
    interpolate_method: str = "nearest"
    return_char_alignments: bool = False

    def __post_init__(self) -> None:
        if not self.device or self.device.strip() == "":
            raise AlignmentConfigError("device must not be empty (e.g. 'cpu' or 'cuda')")
        if not self.language_code or self.language_code.strip() == "":
            raise AlignmentConfigError("language_code must not be empty (e.g. 'en')")


# ---------------------------------------------------------------------------
# Model Cache
# ---------------------------------------------------------------------------

# Global cache: (language_code, device, model_name, model_dir) -> (model, metadata)
_ALIGN_MODEL_CACHE: Dict[Tuple[str, str, Optional[str], Optional[str]], Tuple[Any, Any]] = {}


def clear_alignment_model_cache() -> None:
    """Clear all cached alignment models in memory (useful for testing)."""
    global _ALIGN_MODEL_CACHE
    _ALIGN_MODEL_CACHE.clear()


# ---------------------------------------------------------------------------
# WhisperX Align Service
# ---------------------------------------------------------------------------

class WhisperXAligner:
    """Forced alignment service using WhisperX wav2vec2 CTC aligner."""

    def __init__(
        self,
        config: Optional[AlignmentConfig] = None,
        load_align_model_fn: Optional[Callable[..., Tuple[Any, Any]]] = None,
        align_fn: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.config = config or AlignmentConfig()
        self._load_align_model_fn = load_align_model_fn
        self._align_fn = align_fn
        self._model: Any = None
        self._metadata: Any = None

    @property
    def is_loaded(self) -> bool:
        """Whether the alignment model is currently loaded in this aligner instance."""
        return self._model is not None and self._metadata is not None

    def load_model(self) -> Tuple[Any, Any]:
        """Load or retrieve from cache the WhisperX alignment model and metadata."""
        if self.is_loaded:
            return self._model, self._metadata

        cache_key = (
            self.config.language_code,
            self.config.device,
            self.config.model_name,
            self.config.model_dir,
        )

        if cache_key in _ALIGN_MODEL_CACHE:
            self._model, self._metadata = _ALIGN_MODEL_CACHE[cache_key]
            logger.debug("Reusing cached WhisperX alignment model for key %s", cache_key)
            return self._model, self._metadata

        loader = self._load_align_model_fn
        if loader is None:
            try:
                import whisperx  # type: ignore[import]
                loader = whisperx.load_align_model
            except ImportError as exc:
                raise AlignmentModelError(
                    "WhisperX is not installed. Install whisperx (pip install whisperx) "
                    "or verify your environment."
                ) from exc

        logger.info(
            "Loading WhisperX alignment model (lang=%s, device=%s, model=%s)...",
            self.config.language_code,
            self.config.device,
            self.config.model_name,
        )

        try:
            model, metadata = loader(
                language_code=self.config.language_code,
                device=self.config.device,
                model_name=self.config.model_name,
                model_dir=self.config.model_dir,
            )
        except ValueError as exc:
            # WhisperX raises ValueError for unsupported languages
            raise AlignmentConfigError(
                f"Unsupported language code '{self.config.language_code}': {exc}"
            ) from exc
        except Exception as exc:
            raise AlignmentModelError(
                f"Failed to load WhisperX alignment model for '{self.config.language_code}': {exc}"
            ) from exc

        self._model = model
        self._metadata = metadata
        _ALIGN_MODEL_CACHE[cache_key] = (model, metadata)
        logger.info("WhisperX alignment model loaded successfully.")
        return self._model, self._metadata

    def align(
        self,
        audio: PreprocessedAudio,
        transcript: Transcript,
    ) -> AlignedTranscript:
        """Align a preprocessed audio signal to an existing Transcript.

        Parameters
        ----------
        audio:
            Canonical PreprocessedAudio from services/audio/.
        transcript:
            Canonical Transcript produced by TASK-021 (services/transcription/).

        Returns
        -------
        AlignedTranscript:
            Contract containing aligned words with start/end/confidence and coverage.
        """
        self._validate_inputs(audio, transcript)

        # Handle empty transcript: return empty AlignedTranscript immediately
        if not transcript.text or transcript.text.strip() == "":
            return AlignedTranscript(
                text=transcript.text,
                words=[],
                alignment_method=AlignmentMethod.WHISPERX,
                total_coverage_pct=0.0,
            )

        model, metadata = self.load_model()

        # Build segments payload expected by whisperx.align
        segments = self._build_segments_payload(audio, transcript)

        align_runner = self._align_fn
        if align_runner is None:
            try:
                import whisperx  # type: ignore[import]
                align_runner = whisperx.align
            except ImportError as exc:
                raise AlignmentModelError("WhisperX is not installed.") from exc

        try:
            raw_aligned = align_runner(
                transcript=segments,
                model=model,
                align_model_metadata=metadata,
                audio=audio.audio_array,
                device=self.config.device,
                interpolate_method=self.config.interpolate_method,
                return_char_alignments=self.config.return_char_alignments,
                print_progress=False,
            )
        except Exception as exc:
            raise AlignmentRuntimeError(f"WhisperX alignment execution failed: {exc}") from exc

        aligned_words = self._extract_aligned_words(raw_aligned)
        coverage_pct = self._compute_coverage_pct(aligned_words, audio.duration_s)

        return AlignedTranscript(
            text=transcript.text,
            words=aligned_words,
            alignment_method=AlignmentMethod.WHISPERX,
            total_coverage_pct=coverage_pct,
        )

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _validate_inputs(
        self,
        audio: PreprocessedAudio,
        transcript: Transcript,
    ) -> None:
        """Validate input contracts and ensure conformity."""
        if not hasattr(audio, "audio_array") or not hasattr(audio, "sample_rate_hz"):
            raise AlignmentConfigError(
                f"Expected PreprocessedAudio contract, got {type(audio).__name__}"
            )
        if audio.sample_rate_hz != _EXPECTED_SAMPLE_RATE:
            raise AlignmentConfigError(
                f"Audio sample rate must be {_EXPECTED_SAMPLE_RATE} Hz; got {audio.sample_rate_hz} Hz"
            )
        if audio.channels != 1:
            raise AlignmentConfigError(
                f"Audio must be mono (channels=1); got {audio.channels} channels"
            )
        if audio.audio_array.ndim != 1 or audio.audio_array.dtype != np.float32:
            raise AlignmentConfigError(
                "audio_array must be a 1D float32 numpy array"
            )
        if not np.all(np.isfinite(audio.audio_array)):
            raise AlignmentConfigError(
                "audio_array contains non-finite samples (NaN or Inf)"
            )
        if not hasattr(transcript, "text") or not hasattr(transcript, "words"):
            raise AlignmentConfigError(
                f"Expected Transcript contract, got {type(transcript).__name__}"
            )

        # Check for empty audio with non-empty transcript
        if audio.audio_array.size == 0 and transcript.text.strip() != "":
            raise AlignmentConfigError(
                "Cannot align non-empty transcript against empty audio (0 samples)"
            )

        # Language consistency check if transcript explicitly specifies a language
        if (
            transcript.language is not None
            and transcript.language.strip() != ""
            and transcript.language.lower() != self.config.language_code.lower()
        ):
            logger.warning(
                "Transcript language ('%s') differs from alignment config language ('%s')",
                transcript.language,
                self.config.language_code,
            )

    def _build_segments_payload(
        self,
        audio: PreprocessedAudio,
        transcript: Transcript,
    ) -> List[Dict[str, Any]]:
        """Construct segment dictionaries required by whisperx.align."""
        if transcript.segments:
            return [
                {
                    "text": seg.text,
                    "start": float(seg.start_s),
                    "end": float(seg.end_s),
                }
                for seg in transcript.segments
            ]

        # If transcript has no segments (e.g. manual text or raw string), wrap full text in single segment
        return [
            {
                "text": transcript.text,
                "start": 0.0,
                "end": float(audio.duration_s),
            }
        ]

    def _extract_aligned_words(
        self,
        raw_aligned: Dict[str, Any],
    ) -> List[AlignedWord]:
        """Convert WhisperX alignment output dictionary into canonical AlignedWord list."""
        aligned_words: List[AlignedWord] = []

        segments = raw_aligned.get("segments", [])
        for seg in segments:
            words = seg.get("words", [])
            for w in words:
                word_text = (w.get("word") or "").strip()
                if not word_text:
                    continue

                start_s = _safe_float(w.get("start"))
                end_s = _safe_float(w.get("end"))
                raw_score = _safe_float(w.get("score"))
                confidence = None
                if raw_score is not None:
                    # Clip confidence strictly to [0.0, 1.0]
                    confidence = float(min(1.0, max(0.0, raw_score)))

                # Enforce chronological ordering if both timestamps exist
                if start_s is not None and end_s is not None:
                    if end_s < start_s:
                        # Swap if inverted or adjust
                        logger.warning(
                            "Inverted timing for word '%s': start=%s, end=%s. Normalizing.",
                            word_text,
                            start_s,
                            end_s,
                        )
                        start_s, end_s = end_s, start_s

                aligned_words.append(
                    AlignedWord(
                        word=word_text,
                        start_s=start_s,
                        end_s=end_s,
                        confidence=confidence,
                    )
                )

        return aligned_words

    @staticmethod
    def _compute_coverage_pct(
        words: List[AlignedWord],
        total_duration_s: float,
    ) -> float:
        """Compute the fraction [0.0, 1.0] of audio covered by aligned words."""
        if total_duration_s <= 0.0 or not words:
            return 0.0

        intervals: List[Tuple[float, float]] = []
        for w in words:
            if (
                w.start_s is not None
                and w.end_s is not None
                and w.end_s > w.start_s
            ):
                intervals.append((w.start_s, w.end_s))

        if not intervals:
            return 0.0

        # Merge overlapping or contiguous intervals
        intervals.sort(key=lambda x: x[0])
        merged: List[Tuple[float, float]] = [intervals[0]]
        for cur_start, cur_end in intervals[1:]:
            prev_start, prev_end = merged[-1]
            if cur_start <= prev_end:
                merged[-1] = (prev_start, max(prev_end, cur_end))
            else:
                merged.append((cur_start, cur_end))

        covered_s = sum(end - start for start, end in merged)
        fraction = min(1.0, max(0.0, covered_s / total_duration_s))
        return round(fraction, 4)


# ---------------------------------------------------------------------------
# Module-level Singleton & Convenience Function
# ---------------------------------------------------------------------------

_aligner_instance: Optional[WhisperXAligner] = None


def get_aligner(
    config: Optional[AlignmentConfig] = None,
) -> WhisperXAligner:
    """Retrieve or initialize the shared WhisperXAligner instance."""
    global _aligner_instance
    if _aligner_instance is None or config is not None:
        _aligner_instance = WhisperXAligner(config=config)
    return _aligner_instance


def align(
    audio: PreprocessedAudio,
    transcript: Transcript,
    config: Optional[AlignmentConfig] = None,
) -> AlignedTranscript:
    """Convenience functional interface for forced alignment.

    Parameters
    ----------
    audio:
        PreprocessedAudio object from services/audio/.
    transcript:
        Transcript object from services/transcription/.
    config:
        Optional alignment configuration override.

    Returns
    -------
    AlignedTranscript
    """
    aligner = get_aligner(config)
    return aligner.align(audio=audio, transcript=transcript)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _safe_float(val: Any) -> Optional[float]:
    """Safely convert value to float, returning None on missing or invalid types."""
    if val is None:
        return None
    try:
        f = float(val)
        return f if np.isfinite(f) else None
    except (TypeError, ValueError):
        return None
