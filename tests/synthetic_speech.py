"""Synthetic 'speech' used by integration tests: tone words with known timings.

A recording is a list of items:
    ("word", text, freq_hz, amplitude, duration_s)  -> a tone burst, aligned as one word
    ("gap", duration_s)                               -> digital silence
Word and gap times are integer sample counts at 16 kHz, so the returned alignment is exact in
processed-audio time provided the recording starts and ends with a word (no trimming).
"""
from __future__ import annotations

import io
from typing import List, Sequence, Tuple

import numpy as np
import scipy.io.wavfile as wavfile

from app.schemas.common import AlignmentMethod
from app.schemas.contracts import AlignedTranscript, AlignedWord

SR = 16000


def build_speech(items: Sequence[tuple]) -> Tuple[bytes, AlignedTranscript]:
    chunks: List[np.ndarray] = []
    words: List[AlignedWord] = []
    cursor = 0
    for item in items:
        if item[0] == "word":
            _, text, freq, amp, dur = item
            n = int(round(dur * SR))
            t = np.arange(n) / SR
            chunks.append(amp * np.sin(2 * np.pi * freq * t))
            words.append(AlignedWord(word=text, start_s=cursor / SR, end_s=(cursor + n) / SR, confidence=0.9))
        else:
            n = int(round(item[1] * SR))
            chunks.append(np.zeros(n))
        cursor += n
    buf = io.BytesIO()
    wavfile.write(buf, SR, (np.concatenate(chunks) * 32767).astype(np.int16))
    transcript = AlignedTranscript(
        text=" ".join(w.word for w in words), words=words,
        alignment_method=AlignmentMethod.WHISPERX, total_coverage_pct=0.8,
    )
    return buf.getvalue(), transcript


def normal_delivery(n_words: int = 24, special_gaps=None, amp_scale: float = 1.0,
                    word_dur: float = 0.4, gap: float = 0.1, start_index: int = 0) -> list:
    """Words with varying pitch/loudness; `special_gaps` maps word index -> longer gap (s)."""
    special_gaps = special_gaps or {}
    items: list = []
    for k in range(n_words):
        i = start_index + k
        text = f"w{i}."  if i in special_gaps and special_gaps[i] >= 0.6 else f"w{i}"
        items.append(("word", text, 110.0 + 12.0 * (i % 6), amp_scale * (0.3 + 0.05 * (i % 5)), word_dur))
        if k < n_words - 1:
            items.append(("gap", special_gaps.get(i, gap)))
    return items
