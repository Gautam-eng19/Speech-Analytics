"""Unit tests for TASK-021: Whisper transcription service.

These tests do NOT download or load the real Whisper model (~140 MB).
They mock the model entirely and validate:
  - service contract and output structure
  - input validation (sample rate, dtype, shape, type)
  - error handling
  - config validation
  - deterministic model_name propagation
  - singleton behaviour

A separate smoke test (test_transcription_smoke.py) validates real Whisper.
"""
from __future__ import annotations

import hashlib
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.schemas.contracts import PreprocessedAudio, Transcript, TranscriptSegment, WordTiming
from app.schemas.common import TranscriptSource
from app.services.transcription.transcriber import (
    TranscriptionConfigError,
    TranscriptionError,
    WhisperTranscriber,
    _safe_float,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TARGET_SR = 16_000


def _make_audio(duration_s: float = 3.0, sr: int = TARGET_SR) -> PreprocessedAudio:
    """Build a canonical PreprocessedAudio for testing (silent audio)."""
    n = int(sr * duration_s)
    arr = np.zeros(n, dtype=np.float32)
    sha = hashlib.sha256(arr.tobytes()).hexdigest()
    return PreprocessedAudio(
        sample_rate_hz=sr,
        channels=1,
        duration_s=round(duration_s, 4),
        audio_array=arr,
        sha256=sha,
        peak_dbfs=-100.0,
    )


def _fake_whisper_output(text: str = "hello world") -> dict:
    """Minimal Whisper raw output mimicking model.transcribe() result."""
    return {
        "text": f" {text}",
        "language": "en",
        "segments": [
            {
                "id": 0,
                "text": f" {text}",
                "start": 0.0,
                "end": 1.5,
                "no_speech_prob": 0.01,
                "words": [
                    {"word": " hello", "start": 0.0, "end": 0.6, "probability": 0.98},
                    {"word": " world", "start": 0.7, "end": 1.5, "probability": 0.95},
                ],
            }
        ],
    }


def _make_transcriber_with_mock_model(raw_output: dict | None = None) -> tuple[WhisperTranscriber, MagicMock]:
    """Return a WhisperTranscriber whose internal Whisper model is mocked."""
    raw = raw_output if raw_output is not None else _fake_whisper_output()
    transcriber = WhisperTranscriber(model_name="base", language="en")
    mock_model = MagicMock()
    mock_model.transcribe.return_value = raw
    transcriber._model = mock_model  # inject mock — skips real model load
    return transcriber, mock_model


# ---------------------------------------------------------------------------
# Config / construction tests
# ---------------------------------------------------------------------------

class TestWhisperTranscriberConfig:
    def test_default_construction(self):
        t = WhisperTranscriber()
        assert t.model_name  # nonempty
        assert not t.is_loaded

    def test_custom_model_name(self):
        t = WhisperTranscriber(model_name="small")
        assert t.model_name == "small"

    def test_empty_model_name_raises(self):
        with pytest.raises(TranscriptionConfigError, match="model_name"):
            WhisperTranscriber(model_name="")

    def test_invalid_task_raises(self):
        with pytest.raises(TranscriptionConfigError, match="task"):
            WhisperTranscriber(task="summarize")

    def test_invalid_temperature_raises(self):
        with pytest.raises(TranscriptionConfigError, match="temperature"):
            WhisperTranscriber(temperature=1.5)

    def test_negative_temperature_raises(self):
        with pytest.raises(TranscriptionConfigError, match="temperature"):
            WhisperTranscriber(temperature=-0.1)

    def test_valid_translate_task(self):
        t = WhisperTranscriber(task="translate")
        assert t._task == "translate"

    def test_zero_temperature_valid(self):
        t = WhisperTranscriber(temperature=0.0)
        assert t._temperature == 0.0

    def test_one_temperature_valid(self):
        t = WhisperTranscriber(temperature=1.0)
        assert t._temperature == 1.0


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

class TestModelLoading:
    def test_load_model_idempotent(self):
        t, mock = _make_transcriber_with_mock_model()
        assert t.is_loaded
        t.load_model()  # second call: should not re-load
        assert t.is_loaded

    def test_load_model_not_loaded_initially(self):
        t = WhisperTranscriber(model_name="base")
        assert not t.is_loaded

    def test_missing_whisper_raises_transcription_error(self):
        t = WhisperTranscriber(model_name="base")
        with patch.dict("sys.modules", {"whisper": None}):
            with pytest.raises(TranscriptionError, match="not installed"):
                t.load_model()


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestInputValidation:
    def test_wrong_sample_rate_raises(self):
        t, _ = _make_transcriber_with_mock_model()
        audio = _make_audio(sr=8000)
        audio_wrong_sr = PreprocessedAudio(
            sample_rate_hz=8000,
            channels=1,
            duration_s=audio.duration_s,
            audio_array=audio.audio_array,
            sha256=audio.sha256,
            peak_dbfs=audio.peak_dbfs,
        )
        with pytest.raises(TranscriptionConfigError, match="16000 Hz"):
            t.transcribe(audio_wrong_sr)

    def test_non_preprocessed_audio_raises(self):
        t, _ = _make_transcriber_with_mock_model()
        with pytest.raises(TranscriptionConfigError, match="PreprocessedAudio"):
            t.transcribe({"audio": "fake"})  # type: ignore[arg-type]

    def test_2d_array_rejected_by_pydantic(self):
        """Pydantic validates the audio_array shape — 2D is forbidden."""
        arr2d = np.zeros((2, 16000), dtype=np.float32)
        with pytest.raises(Exception):  # Pydantic ValidationError
            PreprocessedAudio(
                sample_rate_hz=16000, channels=1, duration_s=1.0,
                audio_array=arr2d,
                sha256="a" * 64, peak_dbfs=-3.0,
            )

    def test_int16_array_rejected_by_pydantic(self):
        arr_i16 = np.zeros(16000, dtype=np.int16)
        with pytest.raises(Exception):
            PreprocessedAudio(
                sample_rate_hz=16000, channels=1, duration_s=1.0,
                audio_array=arr_i16,
                sha256="a" * 64, peak_dbfs=-3.0,
            )


# ---------------------------------------------------------------------------
# Transcription output structure
# ---------------------------------------------------------------------------

class TestTranscriptionOutput:
    def test_returns_transcript_type(self):
        t, _ = _make_transcriber_with_mock_model()
        result = t.transcribe(_make_audio())
        assert isinstance(result, Transcript)

    def test_text_is_stripped(self):
        t, _ = _make_transcriber_with_mock_model(_fake_whisper_output("  hello world  "))
        result = t.transcribe(_make_audio())
        assert result.text == "hello world"

    def test_source_is_asr(self):
        t, _ = _make_transcriber_with_mock_model()
        result = t.transcribe(_make_audio())
        assert result.source is TranscriptSource.ASR

    def test_model_name_format(self):
        t, _ = _make_transcriber_with_mock_model()
        result = t.transcribe(_make_audio())
        assert result.model_name == "whisper_base"

    def test_language_propagated(self):
        t, _ = _make_transcriber_with_mock_model()
        result = t.transcribe(_make_audio())
        assert result.language == "en"

    def test_segment_structure(self):
        t, _ = _make_transcriber_with_mock_model()
        result = t.transcribe(_make_audio())
        assert len(result.segments) == 1
        seg = result.segments[0]
        assert isinstance(seg, TranscriptSegment)
        assert seg.segment_id == 0
        assert seg.start_s == 0.0
        assert seg.end_s == 1.5
        assert seg.no_speech_prob == pytest.approx(0.01)

    def test_word_timing_structure(self):
        t, _ = _make_transcriber_with_mock_model()
        result = t.transcribe(_make_audio())
        assert len(result.words) == 2
        w = result.words[0]
        assert isinstance(w, WordTiming)
        assert w.word == "hello"
        assert w.approx_start_s == pytest.approx(0.0)
        assert w.approx_end_s == pytest.approx(0.6)
        assert w.probability == pytest.approx(0.98)

    def test_flat_words_match_segment_words(self):
        t, _ = _make_transcriber_with_mock_model()
        result = t.transcribe(_make_audio())
        seg_words = [w for seg in result.segments for w in seg.words]
        assert [w.word for w in result.words] == [w.word for w in seg_words]

    def test_word_stripping(self):
        """Whisper returns words with leading spaces — we strip them."""
        t, _ = _make_transcriber_with_mock_model()
        result = t.transcribe(_make_audio())
        for w in result.words:
            assert not w.word.startswith(" "), f"Word '{w.word}' has leading space"


# ---------------------------------------------------------------------------
# Empty / edge-case audio
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_audio_produces_empty_transcript(self):
        raw_empty = {"text": "", "language": "en", "segments": []}
        t, _ = _make_transcriber_with_mock_model(raw_empty)
        # Build a valid PreprocessedAudio with 0-sample array
        arr = np.empty(0, dtype=np.float32)
        sha = hashlib.sha256(arr.tobytes()).hexdigest()
        audio = PreprocessedAudio(
            sample_rate_hz=16000, channels=1, duration_s=0.0,
            audio_array=arr, sha256=sha, peak_dbfs=-100.0,
        )
        result = t.transcribe(audio)
        assert result.text == ""
        assert result.segments == []
        assert result.words == []

    def test_no_speech_prob_none_when_missing(self):
        raw = {
            "text": "hi",
            "language": "en",
            "segments": [
                {"id": 0, "text": "hi", "start": 0.0, "end": 0.5, "words": []}
                # no_speech_prob intentionally absent
            ],
        }
        t, _ = _make_transcriber_with_mock_model(raw)
        result = t.transcribe(_make_audio())
        assert result.segments[0].no_speech_prob is None

    def test_word_timestamps_none_when_missing(self):
        raw = {
            "text": "hi",
            "language": "en",
            "segments": [
                {"id": 0, "text": "hi", "start": 0.0, "end": 0.5,
                 "words": [{"word": "hi"}]}  # no start/end
            ],
        }
        t, _ = _make_transcriber_with_mock_model(raw)
        result = t.transcribe(_make_audio())
        w = result.words[0]
        assert w.approx_start_s is None
        assert w.approx_end_s is None

    def test_multi_segment_output(self):
        raw = {
            "text": "hello world",
            "language": "en",
            "segments": [
                {"id": 0, "text": "hello", "start": 0.0, "end": 0.5,
                 "words": [{"word": " hello", "start": 0.0, "end": 0.5, "probability": 0.9}]},
                {"id": 1, "text": "world", "start": 0.6, "end": 1.1,
                 "words": [{"word": " world", "start": 0.6, "end": 1.1, "probability": 0.95}]},
            ],
        }
        t, _ = _make_transcriber_with_mock_model(raw)
        result = t.transcribe(_make_audio())
        assert len(result.segments) == 2
        assert result.segments[0].segment_id == 0
        assert result.segments[1].segment_id == 1
        assert len(result.words) == 2


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_model_transcribe_runtime_error_wrapped(self):
        t, mock = _make_transcriber_with_mock_model()
        mock.transcribe.side_effect = RuntimeError("CUDA OOM")
        with pytest.raises(TranscriptionError, match="Whisper transcription failed"):
            t.transcribe(_make_audio())

    def test_model_load_error_wrapped(self):
        t = WhisperTranscriber(model_name="nonexistent_model")
        import whisper as _w
        with patch.object(_w, "load_model", side_effect=RuntimeError("unknown model")):
            with pytest.raises(TranscriptionError, match="Failed to load"):
                t.load_model()


# ---------------------------------------------------------------------------
# Determinism / configuration
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_audio_calls_whisper_once_per_request(self):
        t, mock = _make_transcriber_with_mock_model()
        audio = _make_audio()
        t.transcribe(audio)
        t.transcribe(audio)
        # Model should be called once per transcribe call
        assert mock.transcribe.call_count == 2

    def test_word_timestamps_always_enabled(self):
        t, mock = _make_transcriber_with_mock_model()
        t.transcribe(_make_audio())
        _, kwargs = mock.transcribe.call_args
        assert kwargs.get("word_timestamps") is True

    def test_temperature_zero_passed_to_model(self):
        t = WhisperTranscriber(model_name="base", temperature=0.0)
        mock = MagicMock()
        mock.transcribe.return_value = _fake_whisper_output()
        t._model = mock
        t.transcribe(_make_audio())
        _, kwargs = mock.transcribe.call_args
        assert kwargs.get("temperature") == 0.0

    def test_language_passed_to_model(self):
        t = WhisperTranscriber(model_name="base", language="en")
        mock = MagicMock()
        mock.transcribe.return_value = _fake_whisper_output()
        t._model = mock
        t.transcribe(_make_audio())
        _, kwargs = mock.transcribe.call_args
        assert kwargs.get("language") == "en"

    def test_numpy_array_passed_not_filepath(self):
        """Confirm Whisper is called with a numpy array, never a file path."""
        t, mock = _make_transcriber_with_mock_model()
        audio = _make_audio()
        t.transcribe(audio)
        args, _ = mock.transcribe.call_args
        assert isinstance(args[0], np.ndarray)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_get_transcriber_returns_same_instance(self):
        import app.services.transcription.transcriber as _mod
        _mod._transcriber = None  # reset
        t1 = _mod.get_transcriber()
        t2 = _mod.get_transcriber()
        assert t1 is t2

    def test_convenience_transcribe_uses_singleton(self):
        import app.services.transcription.transcriber as _mod
        mock_model = MagicMock()
        mock_model.transcribe.return_value = _fake_whisper_output()
        _mod._transcriber = WhisperTranscriber(model_name="base")
        _mod._transcriber._model = mock_model
        result = _mod.transcribe(_make_audio())
        assert isinstance(result, Transcript)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

class TestSafeFloat:
    def test_none_returns_none(self):
        assert _safe_float(None) is None

    def test_int_converts(self):
        assert _safe_float(5) == 5.0

    def test_float_returns_float(self):
        assert _safe_float(3.14) == pytest.approx(3.14)

    def test_invalid_returns_none(self):
        assert _safe_float("not-a-number") is None

    def test_numpy_scalar_converts(self):
        assert _safe_float(np.float64(2.5)) == pytest.approx(2.5)
