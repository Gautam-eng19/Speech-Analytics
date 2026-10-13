"""Synthetic recorded takes for the dataset-tool tests: tone bursts with known word times, and a stand-in forced aligner.

A take is a list of words, each a short harmonic tone burst of known length, pitch and loudness, separated by gaps of known length and
framed by low room noise. The true word times are known exactly, so a test can compare what the tools place on the timeline with what was
put there. The stand-in aligner answers like the real one: it receives the PREPROCESSED (trimmed, scaled) audio, so its times are in
processed-audio time. It finds the bursts from the signal itself (it is not told the times), which also makes it a check that the
trimming offset is handled.
"""
from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
import scipy.io.wavfile as wavfile

from app.schemas.common import AlignmentMethod
from app.schemas.contracts import AlignedTranscript, AlignedWord, PreprocessedAudio, Transcript
from app.services.features.energy import EnergyConfig, frame_energy_db

SR = 48_000
NOISE_DB = -70.0
NORMAL_AMPLITUDE = 0.2   # peak -14 dBFS: inside the quality gates of a normal take

#: six sentences, 33 words; commas make pauses inside a sentence (within phrase), full stops make pauses between sentences
PASSAGE_TEXT = (
    "Good morning, my dear friends. "
    "Today we begin our long journey together. "
    "First we study the signal, then we measure every word. "
    "A clear voice carries ideas across the room. "
    "Speak with steady pace, calm breath, and care. "
    "Thank you for listening to this talk."
)


def passage_entry(passage_id: str = "p001", text: str = PASSAGE_TEXT) -> dict:
    return {"passage_id": passage_id, "title": "Test passage", "text": text, "target_word_count": len(text.split()),
            "domain": "test", "dataset_version": "1.0.0", "created_at": "2026-10-11"}


@dataclass
class Layout:
    """How one take is spoken. Index i of every list belongs to word i."""

    words: List[str]
    durations: List[float]
    gaps: List[float]                 # gap AFTER word i (one fewer than words)
    amplitudes: List[float]
    lead_s: float = 0.8
    tail_s: float = 0.8
    pitches: List[float] = field(default_factory=list)

    def times(self) -> List[Tuple[float, float]]:
        """True (start, end) of every word on the timeline of the written file."""
        out, cursor = [], self.lead_s
        for i, d in enumerate(self.durations):
            out.append((cursor, cursor + d))
            cursor += d + (self.gaps[i] if i < len(self.gaps) else 0.0)
        return out


MIN_GAP_S = 0.05   # the shortest gap the stand-in aligner can still see between two bursts


def normal_layout(words: Sequence[str], pace: float = 1.0, lead_s: float = 0.8, tail_s: float = 0.8,
                  amplitude: float = NORMAL_AMPLITUDE, jitter: float = 0.0, seed: int = 0) -> Layout:
    """A natural-sounding reading: ~0.28 s per word, 0.08 s between words, 0.3 s after a comma, 0.65 s after a full stop.

    `pace` scales every duration and gap (2.0 = twice as fast). `jitter` > 0 makes the reading human: every word and gap is multiplied by a
    log-normal factor of that spread (0.3 is a lot), drawn from `seed`, so two takes with different seeds are two different readings.
    """
    rng = np.random.default_rng(seed)
    noise = (lambda n: np.exp(rng.normal(0.0, jitter, n))) if jitter > 0 else (lambda n: np.ones(n))
    durations = [d for d in ((0.26 + 0.015 * (i % 5)) / pace * noise(1)[0] for i in range(len(words)))]
    gaps = []
    for i, word in enumerate(words[:-1]):
        gap = (0.65 if word.endswith(".") else 0.30 if word.endswith(",") else 0.08) / pace * noise(1)[0]
        gaps.append(max(MIN_GAP_S, gap))
    amplitudes = [amplitude * (0.92 + 0.03 * (i % 4)) for i in range(len(words))]
    pitches = [118.0 + 9.0 * (i % 7) for i in range(len(words))]
    return Layout(list(words), durations, gaps, amplitudes, lead_s, tail_s, pitches)


def human_layout(words: Sequence[str], seed: int, *, passage_seed: int = 7, tempo: float = 1.0, word_sd: float = 0.20, gap_sd: float = 0.30,
                 take_sd: float = 0.04, drift_sd: float = 0.05, level_pos_sd_db: float = 3.0, level_take_sd_db: float = 1.5,
                 level_drift_sd_db: float = 1.0, level_word_sd_db: float = 2.0, amplitude: float = NORMAL_AMPLITUDE,
                 lead_s: float = 0.8, tail_s: float = 0.8) -> Layout:
    """A reading by a person, for tests of the word-by-word comparison: what a word is decides how long it takes and how loud it is.

    Word length (letters) sets the duration, punctuation sets the pause after the word (0.59 s after a full stop, 0.36 s after a comma, 0.04 s
    otherwise), and a loudness pattern that belongs to the PASSAGE (`passage_seed`: stress) is shared by every reading of it. Each reading then
    differs by chance: its own overall pace (`tempo` for the speaker, `take_sd` for the take), a slowly wandering pace (`drift_sd`), word-to-word
    jitter (`word_sd`, `gap_sd`), and for the loudness an overall gain, a slow drift and word jitter. All of it is drawn from `seed`.
    """
    n = len(words)
    passage_rng = np.random.default_rng(passage_seed)
    stress_db = passage_rng.normal(0.0, level_pos_sd_db, n)
    rng = np.random.default_rng(seed)

    def wander(sd: float, phi: float = 0.92) -> np.ndarray:
        steps = rng.normal(0.0, sd * math.sqrt(1.0 - phi ** 2), n)
        out = np.zeros(n)
        for i in range(n):
            out[i] = (phi * out[i - 1] if i else 0.0) + steps[i]
        return out

    letters = np.array([len(re.sub(r"[^A-Za-z]", "", w)) for w in words], dtype=float)
    base_duration = 0.10 + 0.032 * letters
    base_gap = np.array([0.59 if w.endswith((".", "?", "!")) else 0.36 if w.endswith(",") else 0.04 for w in words[:-1]])
    log_pace = math.log(tempo) + rng.normal(0.0, take_sd) + wander(drift_sd)
    durations = base_duration * np.exp(log_pace + rng.normal(0.0, word_sd, n))
    gaps = np.maximum(MIN_GAP_S + 0.02, base_gap * np.exp(0.7 * log_pace[:-1] + rng.normal(0.0, gap_sd, n - 1)))
    level_db = stress_db + rng.normal(0.0, level_take_sd_db) + wander(level_drift_sd_db, 0.9) + rng.normal(0.0, level_word_sd_db, n)
    amplitudes = amplitude * 10 ** (level_db / 20)
    pitches = [118.0 + 9.0 * (i % 7) for i in range(n)]
    return Layout(list(words), [float(d) for d in durations], [float(g) for g in gaps], [float(a) for a in amplitudes], lead_s, tail_s, pitches)


def speed_stretch(layout: Layout, first: int, last: int, factor: float) -> Layout:
    """Words first..last (1-based, as in the plan) take `factor` times as long (0.5 = twice as fast), gaps inside the stretch too."""
    for i in range(first - 1, last):
        layout.durations[i] *= factor
        if i < last - 1:
            layout.gaps[i] = max(MIN_GAP_S, layout.gaps[i] * factor)
    return layout


def level_stretch(layout: Layout, first: int, last: int, db: float) -> Layout:
    """Words first..last are `db` louder (negative: quieter)."""
    for i in range(first - 1, last):
        layout.amplitudes[i] *= 10 ** (db / 20)
    return layout


def pause_after(layout: Layout, word: int, seconds: float) -> Layout:
    """A silence of `seconds` between word `word` and the next one."""
    layout.gaps[word - 1] = seconds
    return layout


def burst(duration_s: float, pitch_hz: float, amplitude: float, sr: int = SR) -> np.ndarray:
    n = int(round(duration_s * sr))
    t = np.arange(n) / sr
    tone = sum(np.sin(2 * np.pi * pitch_hz * k * t) / k for k in range(1, 6))
    fade = min(int(0.015 * sr), n // 2)
    envelope = np.ones(n)
    envelope[:fade] = 0.5 - 0.5 * np.cos(np.pi * np.arange(fade) / max(fade, 1))
    envelope[n - fade:] = envelope[:fade][::-1]
    tone = tone * envelope
    return amplitude * tone / np.max(np.abs(tone))


def synth_take(layout: Layout, seed: int = 0, sr: int = SR) -> np.ndarray:
    """The take as floating-point samples (-1..1): room noise, then the words with their gaps, then room noise."""
    rng = np.random.default_rng(seed)
    noise = 10 ** (NOISE_DB / 20)
    pieces = [np.zeros(int(round(layout.lead_s * sr)))]
    for i, word in enumerate(layout.words):
        pitch = layout.pitches[i] if layout.pitches else 120.0
        pieces.append(burst(layout.durations[i], pitch, layout.amplitudes[i], sr))
        if i < len(layout.gaps):
            pieces.append(np.zeros(int(round(layout.gaps[i] * sr))))
    pieces.append(np.zeros(int(round(layout.tail_s * sr))))
    x = np.concatenate(pieces)
    return x + rng.normal(0.0, noise, len(x))


def write_wav(path: Path, x: np.ndarray, sr: int = SR) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(str(path), sr, np.round(np.clip(x, -1.0, 1.0) * 32767).astype(np.int16))
    return path


def write_take(folder: Path, take_id: str, layout: Layout, seed: int = 0) -> Path:
    return write_wav(folder / f"{take_id}.wav", synth_take(layout, seed))


class BurstAligner:
    """Stand-in for the WhisperX service: finds the word bursts in the audio it is given and names them in order.

    Options let a test make the aligner misbehave: `drop` leaves those word numbers (1-based) without a time, `confidence` sets every
    word's score, `extra_words` appends words that the passage does not have, `fail_with` raises that error instead of aligning.
    """

    def __init__(self, drop: Optional[Set[int]] = None, confidence: float = 0.9, extra_words: int = 0,
                 fail_with: Optional[Exception] = None) -> None:
        self.drop = drop or set()
        self.confidence = confidence
        self.extra_words = extra_words
        self.fail_with = fail_with
        self.calls = 0
        self.texts: List[str] = []

    def align(self, audio: PreprocessedAudio, transcript: Transcript) -> AlignedTranscript:
        self.calls += 1
        self.texts.append(transcript.text)
        if self.fail_with is not None:
            raise self.fail_with
        config = EnergyConfig(sample_rate=audio.sample_rate_hz)
        levels = frame_energy_db(audio.audio_array, config)
        loud = levels > float(np.max(levels)) - 25.0
        edges = np.diff(np.concatenate(([0], loud.astype(np.int8), [0])))
        starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
        words = transcript.text.split()
        if len(starts) != len(words):
            raise RuntimeError(f"the stand-in aligner found {len(starts)} bursts for {len(words)} words")
        hop = config.hop_length / audio.sample_rate_hz
        aligned: List[AlignedWord] = []
        for i, (a, b) in enumerate(zip(starts, ends), start=1):
            if i in self.drop:
                aligned.append(AlignedWord(word=words[i - 1], start_s=None, end_s=None, confidence=None))
            else:
                aligned.append(AlignedWord(word=words[i - 1], start_s=float(a * hop), end_s=float(b * hop), confidence=self.confidence))
        aligned += [AlignedWord(word=f"extra{k}", start_s=None, end_s=None) for k in range(self.extra_words)]
        covered = sum(w.end_s - w.start_s for w in aligned if w.start_s is not None)
        return AlignedTranscript(text=transcript.text, words=aligned, alignment_method=AlignmentMethod.WHISPERX,
                                 total_coverage_pct=min(1.0, covered / max(audio.duration_s, 1e-9)))


def plan_row(take_id: str, flaw_type: str, first: int, last: int, pause_after: Optional[int] = None,
             severity: str = "medium", stretch: str = "S3") -> Dict[str, str]:
    return {"take_id": take_id, "flaw_type": flaw_type, "severity_label": severity, "stretch": stretch,
            "stretch_first_word": str(first), "stretch_last_word": str(last),
            "pause_after_word": "" if pause_after is None else str(pause_after)}


def write_plan(path: Path, rows: Sequence[Dict[str, str]]) -> Path:
    columns = ["take_id", "flaw_type", "severity_label", "stretch", "stretch_first_word", "stretch_last_word", "pause_after_word"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path
