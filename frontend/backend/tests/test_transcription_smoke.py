"""Smoke test for the real Whisper model (TASK-021).

This test actually loads and runs Whisper base. It requires:
  - openai-whisper installed
  - The ~140 MB model downloaded (cached at ~/.cache/whisper/base.pt)

It is intentionally EXCLUDED from the standard pytest run (via the marker)
to avoid slow CI. Run manually:

    pytest backend/tests/test_transcription_smoke.py -v -m smoke

Or directly:

    python -m pytest backend/tests/test_transcription_smoke.py -v
"""
from __future__ import annotations

import hashlib

import numpy as np
import pytest

pytestmark = pytest.mark.smoke  # skip in default suite; run with -m smoke


TARGET_SR = 16_000


def _make_speech_like_audio(duration_s: float = 2.0) -> "PreprocessedAudio":
    """Produce a non-silent sinusoidal audio array that Whisper can process."""
    from app.schemas.contracts import PreprocessedAudio

    n = int(TARGET_SR * duration_s)
    t = np.linspace(0.0, duration_s, n, dtype=np.float32)
    # 440 Hz sine — short enough that Whisper will probably output silence or a
    # short token but the pipeline run itself is what we are validating.
    arr = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    sha = hashlib.sha256(arr.tobytes()).hexdigest()
    return PreprocessedAudio(
        sample_rate_hz=TARGET_SR,
        channels=1,
        duration_s=round(duration_s, 4),
        audio_array=arr,
        sha256=sha,
        peak_dbfs=-6.0,
    )


@pytest.mark.smoke
def test_real_whisper_base_transcribes():
    """Load the real Whisper base model and run a transcription end-to-end."""
    from app.schemas.contracts import Transcript
    from app.services.transcription import WhisperTranscriber

    t = WhisperTranscriber(model_name="base", language="en")
    audio = _make_speech_like_audio()
    result = t.transcribe(audio)

    assert isinstance(result, Transcript)
    assert result.model_name == "whisper_base"
    assert result.source.value == "asr"
    # text may be empty for a pure tone, but the call must not raise
    assert isinstance(result.text, str)
    assert isinstance(result.segments, list)
    assert isinstance(result.words, list)
    print(f"\n  [smoke] Whisper base transcript: '{result.text}'")
    print(f"  [smoke] Segments: {len(result.segments)}, Words: {len(result.words)}")
