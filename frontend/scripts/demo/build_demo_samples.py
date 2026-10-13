"""Build the dashboard's demo samples: synthetic-voice recordings analysed by the REAL pipeline.

The repository has no recordings yet (docs/methodology/recording-protocol.md), so the dashboard needs something to show. This script
produces it honestly:

    * A synthetic voice (the `flite` speech synthesiser inside ffmpeg) reads the demo passage word by word. Because every word is
      synthesised separately and placed by this script, the WORD TIMINGS ARE EXACT (they are not estimated by a model).
    * Several "effective" takes with small seeded natural variation define a baseline; the baseline statistics come from the same
      `build_baseline_stats` code that real recordings will use.
    * Four samples are then produced with the same voice: one clean take and three with deliberate flaws (faster/slower speech, long
      pauses, quieter speech). The flaw positions are written to the index as `injected` ground truth.
    * Each sample is analysed by the real `AnalysisPipeline` (preprocessing, features, normalization, detection, severity, scoring,
      explanations, assembly). Only Whisper and WhisperX are replaced, by stand-ins that return the transcript and the exact word
      timings. Every number in the stored results therefore comes from the real analytical code.

Output (frontend/public/samples/): `index.json`, and per sample `<id>.json` (the AnalysisResult) and `<id>.wav` (16 kHz mono, the exact
audio that was analysed). Everything is labelled synthetic; nothing here is a real person's voice or a real evaluation.

Requirements: ffmpeg with libflite (`ffmpeg -filters | grep flite`), numpy, scipy, librosa (all in the project environment).

Usage (repository root, environment active):
    python scripts/demo/build_demo_samples.py            # writes frontend/public/samples/
    python scripts/demo/build_demo_samples.py --report   # also prints injected flaws vs. detected flaws
"""
from __future__ import annotations

import argparse
import io
import warnings
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import librosa
import numpy as np
import scipy.io.wavfile as wavfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts" / "dataset"))

import build_baseline_stats as bbs  # noqa: E402
from app.core.baseline import BaselineProvider  # noqa: E402
from app.core.cache import ResultCache  # noqa: E402
from app.core.passages import PassageCatalog  # noqa: E402
from app.schemas.common import AlignmentMethod, TranscriptSource  # noqa: E402
from app.schemas.contracts import AlignedTranscript, AlignedWord, Transcript  # noqa: E402
from app.schemas.request import AnalyzeRequest  # noqa: E402
from app.services.audio import AudioPreprocessor  # noqa: E402
from app.services.features.energy import extract_energy  # noqa: E402
from app.services.features.f0 import extract_f0  # noqa: E402
from app.services.features.pause import detect_pauses  # noqa: E402
from app.services.features.rate import extract_rate  # noqa: E402
from app.services.pipeline import AnalysisPipeline  # noqa: E402

warnings.filterwarnings("ignore")  # librosa/scipy future-warnings clutter the report

SR = 16000
VOICE = "slt"
PASSAGE_ID = "demo_talk"
PASSAGE_TITLE = "Project talk (demo passage)"
PASSAGE_TEXT = (
    "Good morning, everyone, and thank you for joining us today. Over the past year our team has built a tool that helps people "
    "improve the way they speak. It listens to a recording, compares it with a clear example of the same message, and shows exactly "
    "where the delivery changed. For instance, you might speak too quickly during a key point, or pause for too long before an answer. "
    "The tool marks those moments on a timeline, explains what it measured, and suggests one simple change. We tested it with students, "
    "teachers, and engineers, and most of them improved within a single week. Today I will show you how it works, step by step. "
    "Please feel free to ask questions at any time."
)
BASE_TEMPO = 1.3          # isolated flite words are slow; this brings the baseline to a natural pace
LEAD_S, TAIL_S = 0.5, 0.6  # silence around the speech, so the trimming offset is non-zero like in a real file
NOISE_DBFS = -72.0         # room-noise floor added to every take
GAP_AFTER = {"sentence": 0.50, "comma": 0.22, "word": 0.06}
SIGMA_GAP = 0.30     # spread (log-normal sigma) of natural pause lengths
CAP_MULT = 2.0       # longest natural pause as a multiple of the typical one
TEMPO_JIT = 0.06     # per-word speed variation (+-)


# --------------------------------------------------------------------------------------------- passage structure
TOKENS: List[str] = PASSAGE_TEXT.split()


def _sentence_ranges() -> List[range]:
    ranges, start = [], 0
    for i, token in enumerate(TOKENS):
        if re.search(r"[.?!]$", token):
            ranges.append(range(start, i + 1))
            start = i + 1
    return ranges


SENTENCES = _sentence_ranges()  # S1..S8 as word-index ranges


def sentence(n: int) -> range:
    """1-based sentence number -> word indices."""
    return SENTENCES[n - 1]


def word_in(sentence_no: int, word: str) -> int:
    """Index of `word` (punctuation ignored) inside the given sentence."""
    for i in sentence(sentence_no):
        if re.sub(r"[^A-Za-z']", "", TOKENS[i]).lower() == word.lower():
            return i
    raise ValueError(f"{word!r} is not in sentence {sentence_no}")


def end_of(sentence_no: int) -> int:
    """Index of the last word of the given sentence."""
    return sentence(sentence_no)[-1]


# ----------------------------------------------------------------------------------------------- speech synthesis
_word_cache: Dict[str, np.ndarray] = {}


def synth_word(token: str) -> np.ndarray:
    """The synthetic voice saying one word, trimmed of its leading/trailing silence (float32, 16 kHz)."""
    word = re.sub(r"[^A-Za-z']", "", token).lower()
    if word not in _word_cache:
        result = subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"flite=text='{word}':voice={VOICE}",
             "-ar", str(SR), "-ac", "1", "-f", "s16le", "pipe:1"],
            capture_output=True,
        )
        if result.returncode != 0 or not result.stdout:
            raise RuntimeError(f"ffmpeg/flite could not synthesise {word!r}: {result.stderr.decode(errors='replace')[:200]}")
        x = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32) / 32768.0
        active = np.flatnonzero(np.abs(x) > 10 ** (-45 / 20))
        pad = int(0.004 * SR)
        _word_cache[word] = x[max(0, active[0] - pad): active[-1] + pad + 1].copy()
    return _word_cache[word]


def stretch(x: np.ndarray, rate: float) -> np.ndarray:
    """Time-stretch without changing pitch (rate > 1 = faster)."""
    if abs(rate - 1.0) < 1e-3:
        return x
    return librosa.effects.time_stretch(x, rate=rate).astype(np.float32)


# ---------------------------------------------------------------------------------------------------- edits / flaws
@dataclass(frozen=True)
class Fast:
    sentence_no: int
    factor: float = 1.7
    label: str = "too_fast"


@dataclass(frozen=True)
class Slow:
    sentence_no: int
    factor: float = 0.6
    label: str = "too_slow"


@dataclass(frozen=True)
class Pause:
    after_word: int          # index of the word after which the silence is inserted
    seconds: float
    label: str = "excessive_pause"


@dataclass(frozen=True)
class Quiet:
    sentence_no: int
    db: float = -14.0
    label: str = "low_energy"


Edit = object


@dataclass
class Take:
    audio: np.ndarray                          # float32, 16 kHz, what is written to the WAV file
    words: List[AlignedWord]                   # exact word timings in FILE time
    injected: List[dict] = field(default_factory=list)  # ground truth of the deliberate flaws, in file time


def build_take(seed: int, edits: Sequence[Edit] = (), variation: float = 1.0) -> Take:
    """One reading of the passage. `variation` scales the seeded natural take-to-take variation (0 = none)."""
    rng = np.random.default_rng(seed)
    n = len(TOKENS)
    drift = 1.0 + variation * rng.uniform(-0.03, 0.03)           # this reading is slightly faster or slower overall
    tempo = np.full(n, BASE_TEMPO * drift)
    gain_db = np.zeros(n)
    gap = np.zeros(n)
    for i, token in enumerate(TOKENS):
        kind = "sentence" if re.search(r"[.?!]$", token) else "comma" if token.endswith(",") else "word"
        # Pause lengths in real speech are heavy-tailed: log-normal around the typical length (median = typical).
        gap[i] = GAP_AFTER[kind] * float(np.exp(variation * rng.normal(0.0, SIGMA_GAP)))
        gap[i] = min(max(gap[i], 0.02), CAP_MULT * GAP_AFTER[kind])
        tempo[i] *= 1.0 + variation * rng.uniform(-TEMPO_JIT, TEMPO_JIT)
        gain_db[i] = variation * rng.normal(0.0, 1.0)
    gap[-1] = 0.0

    flawed: List[tuple] = []  # (label, first_word, last_word) or pause (label, i, i, seconds)
    for edit in edits:
        if isinstance(edit, Fast):
            for i in sentence(edit.sentence_no):
                tempo[i] *= edit.factor
                gap[i] /= edit.factor
            r = sentence(edit.sentence_no)
            flawed.append((edit.label, r[0], r[-1], None))
        elif isinstance(edit, Slow):
            for i in sentence(edit.sentence_no):
                tempo[i] *= edit.factor
                gap[i] /= edit.factor
            r = sentence(edit.sentence_no)
            flawed.append((edit.label, r[0], r[-1], None))
        elif isinstance(edit, Quiet):
            for i in sentence(edit.sentence_no):
                gain_db[i] += edit.db
            r = sentence(edit.sentence_no)
            flawed.append((edit.label, r[0], r[-1], None))
        elif isinstance(edit, Pause):
            gap[edit.after_word] = edit.seconds
            flawed.append((edit.label, edit.after_word, edit.after_word + 1, edit.seconds))
        else:  # pragma: no cover
            raise TypeError(edit)

    chunks: List[np.ndarray] = [np.zeros(int(LEAD_S * SR), dtype=np.float32)]
    words: List[AlignedWord] = []
    cursor = len(chunks[0])
    for i, token in enumerate(TOKENS):
        clip = stretch(synth_word(token), float(tempo[i])) * float(10 ** (gain_db[i] / 20))
        chunks.append(clip)
        words.append(AlignedWord(word=token, start_s=cursor / SR, end_s=(cursor + len(clip)) / SR, confidence=0.99))
        cursor += len(clip)
        silence = np.zeros(int(round(gap[i] * SR)), dtype=np.float32)
        chunks.append(silence)
        cursor += len(silence)
    chunks.append(np.zeros(int(TAIL_S * SR), dtype=np.float32))
    audio = np.concatenate(chunks)
    audio += rng.normal(0.0, 10 ** (NOISE_DBFS / 20), len(audio)).astype(np.float32)
    audio = audio / max(1.0, float(np.max(np.abs(audio))) / 0.9)  # never clip, otherwise leave the level alone

    injected = []
    for label, first, last, seconds in flawed:
        if seconds is not None:       # a pause: the silence between the two words
            start, end = words[first].end_s, words[last].start_s
        else:
            start, end = words[first].start_s, words[last].end_s
        injected.append({"type": label, "start_s": round(start, 3), "end_s": round(end, 3)})
    return Take(audio, words, sorted(injected, key=lambda d: d["start_s"]))


def to_wav_bytes(audio: np.ndarray) -> bytes:
    buf = io.BytesIO()
    wavfile.write(buf, SR, (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16))
    return buf.getvalue()


# ------------------------------------------------------------------------- stand-ins for Whisper and WhisperX
class ExactTranscriber:
    """Returns the passage text. Marks itself clearly so the result never claims a real Whisper model produced it."""

    def transcribe(self, audio) -> Transcript:
        return Transcript(text=PASSAGE_TEXT, segments=[], words=[], model_name="whisper_demo-exact-timings",
                          source=TranscriptSource.ASR, language="en")


class ExactAligner:
    """Returns the generator's exact word timings, converted to the trimmed-audio time the real aligner works in."""

    def __init__(self, words: List[AlignedWord]) -> None:
        self.words = words

    def align(self, audio, transcript) -> AlignedTranscript:
        off = audio.trim_start_s
        shifted = [AlignedWord(word=w.word, start_s=max(0.0, w.start_s - off), end_s=w.end_s - off, confidence=w.confidence)
                   for w in self.words]
        return AlignedTranscript(text=transcript.text, words=shifted, alignment_method=AlignmentMethod.WHISPERX,
                                 total_coverage_pct=0.97)


# ---------------------------------------------------------------------------------------------------- the samples
BASELINE_SEEDS = (11, 12, 13, 14, 15)
FIRST_CANDIDATE_SEED = 200
MAX_CANDIDATES = 40
CLEAN_PROBE_SEEDS = tuple(range(100, 110))   # clean takes used only to report how often the current thresholds flag clean speech
MAX_EXTRA_FLAWS = 2                          # a flawed sample may contain at most this many detections beyond the injected ones

# `edits` are factories so every candidate seed gets a fresh, identical flaw plan.
SAMPLES = [
    dict(id="clean-delivery", title="Clean delivery", edits=lambda: (),
         description="A control take: the same voice reading the passage at its normal pace, with no deliberate flaw. "
                     "It shows what the dashboard looks like when nothing is flagged."),
    dict(id="rushed-explanation", title="Rushed explanation", edits=lambda: (Fast(3, 1.8),),
         description="The third sentence is read about 1.8 times faster than the baseline pace; everything else is normal."),
    dict(id="hesitant-delivery", title="Hesitant delivery",
         edits=lambda: (Pause(word_in(4, "quickly"), 1.9), Slow(6, 0.6)),
         description="A 1.9 s silence inside a phrase in the fourth sentence, and the sixth sentence read at about 0.6 times the normal speed."),
    # The quiet sentence is allowed to go undetected: in every candidate tried, the current frame-level energy rule missed a
    # sentence 20 dB quieter. The miss is real, so the sample keeps it and the dashboard shows it against the injected truth.
    dict(id="mixed-flaws", title="Mixed flaws", edits=lambda: (Fast(2, 1.7), Pause(end_of(5), 3.2), Quiet(7, -20.0)),
         may_miss=("low_energy",),
         description="Three deliberate flaws in one take: a fast second sentence, a 3.2 s silence between two sentences, and a seventh "
                     "sentence 20 dB quieter. The current energy rule does not detect the quiet sentence; the timeline shows that miss."),
]


def baseline_record(workdir: Path):
    recordings = []
    for k, seed in enumerate(BASELINE_SEEDS, start=1):
        take = build_take(seed)
        audio = AudioPreprocessor().process(to_wav_bytes(take.audio))
        off = audio.trim_start_s
        aligned = AlignedTranscript(
            text=PASSAGE_TEXT,
            words=[AlignedWord(word=w.word, start_s=max(0.0, w.start_s - off), end_s=w.end_s - off, confidence=0.99) for w in take.words],
            alignment_method=AlignmentMethod.WHISPERX, total_coverage_pct=0.97)
        f0, energy, rate = extract_f0(audio), extract_energy(audio), extract_rate(aligned)
        pauses = detect_pauses(aligned=aligned, energy=energy).events
        recordings.append(bbs.RecordingFeatures(f"demo_base_{k:02d}", f0.voiced_values_hz, energy.values_db, rate.words_per_min, pauses))
    record = bbs.aggregate_baseline_stats(PASSAGE_ID, "demo", recordings)
    bbs.write_stats(record, workdir / "baselines")
    return record


def analyze(take: Take, work: Path, tag: str):
    pipeline = AnalysisPipeline(
        transcriber=ExactTranscriber(), aligner=ExactAligner(take.words),
        baseline_provider=BaselineProvider(work / "baselines"), cache=ResultCache(work / f"cache_{tag}"),
        passages=PassageCatalog(work / "passages.json"),
    )
    wav = to_wav_bytes(take.audio)
    return wav, pipeline.analyze(wav, AnalyzeRequest(baseline_id=PASSAGE_ID, passage_id=PASSAGE_ID))


def overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def match_injected(injected: List[dict], flaws) -> tuple:
    """For each injected flaw, whether it was found, and how many detections remain unexplained.

    A flaw is found when a detection of the same type overlaps at least 50 % of the injected window (ARCHITECTURE.md §25.3).
    This is evaluation done at build time by the generator; the dashboard only displays the stored outcome.
    """
    used = set()
    found = []
    for truth in injected:
        length = truth["end_s"] - truth["start_s"]
        hit = next((i for i, f in enumerate(flaws) if i not in used and f.type.value == truth["type"]
                    and overlap(truth["start_s"], truth["end_s"], f.start_s, f.end_s) >= 0.5 * length), None)
        found.append(hit is not None)
        if hit is not None:
            used.add(hit)
    return found, len(flaws) - len(used)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "frontend" / "public" / "samples")
    parser.add_argument("--report", action="store_true", help="print injected flaws next to the detected ones")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "passages.json").write_text(
            json.dumps([{"passage_id": PASSAGE_ID, "title": PASSAGE_TITLE, "text": PASSAGE_TEXT}]), encoding="utf-8")
        baseline = baseline_record(work)

        # How often do the current (uncalibrated) thresholds flag clean synthetic speech? Reported, never hidden.
        flagged_clean = sum(1 for seed in CLEAN_PROBE_SEEDS if analyze(build_take(seed), work, f"probe{seed}")[1].flaws)
        print(f"clean probe: {flagged_clean} of {len(CLEAN_PROBE_SEEDS)} clean takes were flagged by the current thresholds")

        index = []
        for spec in SAMPLES:
            chosen = None
            for attempt in range(MAX_CANDIDATES):
                seed = FIRST_CANDIDATE_SEED + attempt
                take = build_take(seed, spec["edits"]())
                wav, result = analyze(take, work, f"{spec['id']}_{seed}")
                found, extras = match_injected(take.injected, result.flaws)
                allowed_misses = spec.get("may_miss", ())
                if take.injected:
                    ok = all(f or t["type"] in allowed_misses for f, t in zip(found, take.injected)) and extras <= MAX_EXTRA_FLAWS
                else:
                    ok = not result.flaws
                if args.report:
                    print(f"   {spec['id']} seed {seed}: {'accepted' if ok else 'rejected'} "
                          f"(detected {[(f.type.value, round(f.start_s, 1), round(f.end_s, 1)) for f in result.flaws]})")
                if ok:
                    chosen = (seed, attempt + 1, take, wav, result)
                    break
            if chosen is None:
                raise SystemExit(f"no acceptable take for {spec['id']} within {MAX_CANDIDATES} seeds")
            seed, attempts, take, wav, result = chosen
            found, extras = match_injected(take.injected, result.flaws)
            for truth, was_found in zip(take.injected, found):
                truth["detected"] = was_found
            (args.out / f"{spec['id']}.wav").write_bytes(wav)
            (args.out / f"{spec['id']}.json").write_text(result.model_dump_json(), encoding="utf-8")
            index.append({
                "id": spec["id"], "title": spec["title"], "description": spec["description"],
                "analysis_id": result.analysis_id, "audio": f"{spec['id']}.wav", "result": f"{spec['id']}.json",
                "duration_s": round(len(take.audio) / SR, 3), "injected": take.injected,
                "extra_detections": extras, "seed": seed, "candidates_tried": attempts,
            })
            print(f"{spec['id']}: seed {seed} after {attempts} candidate(s); composite {result.scores.composite_score}; "
                  f"injected {[(d['type'], d['start_s'], d['end_s']) for d in take.injected]}; "
                  f"detected {[(f.type.value, round(f.start_s, 1), round(f.end_s, 1)) for f in result.flaws]}")
        (args.out / "index.json").write_text(json.dumps({
            "synthetic": True,
            "generator": "scripts/demo/build_demo_samples.py",
            "voice": f"flite/{VOICE} (synthetic speech synthesiser)",
            "note": "Synthetic voice reading one passage with deliberate, known flaws. Word timings are exact by construction; "
                    "Whisper and WhisperX were replaced by stand-ins. Every other number comes from the real analysis code.",
            "selection_note": "Each sample is the first generated take (seeds from %d upward) that fits its description: the clean take "
                              "has no flag; each flawed take has its injected flaws detected (a documented exception: the quiet sentence of the mixed "
                              "sample, which the current energy rule misses) with at most %d additional detections. "
                              "The samples illustrate the interface; they are not a measurement of detection accuracy."
                              % (FIRST_CANDIDATE_SEED, MAX_EXTRA_FLAWS),
            "diagnostics": {
                "clean_takes_flagged": flagged_clean, "clean_takes_probed": len(CLEAN_PROBE_SEEDS),
                "comment": "How many clean synthetic takes (same generator, no flaw) the current, uncalibrated thresholds flagged. "
                           "Calibration on real recordings has to bring this down.",
            },
            "passage": {"passage_id": PASSAGE_ID, "title": PASSAGE_TITLE, "text": PASSAGE_TEXT, "word_count": len(TOKENS)},
            "baseline": {"baseline_id": PASSAGE_ID, "takes": len(BASELINE_SEEDS), "sha256": baseline.sha256},
            "samples": index,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(index)} samples to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
