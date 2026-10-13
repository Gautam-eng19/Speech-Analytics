"""Register recorded takes in the dataset and get them ready for the site (TASK-126).

Run it on a folder of WAV files that follow the naming of the recording protocol (rec_<passage>_<speaker>_<kind>_<nn>.wav) after the
quality check passed (check_recordings.py):

    python scripts/dataset/prepare_recordings.py data/incoming
    python scripts/dataset/prepare_recordings.py data/incoming --build-baseline

For every take it
  1. checks the recording quality again (a take that fails is not registered),
  2. copies the file to data/raw/ and records its SHA-256,
  3. runs the project's own preprocessing and forced alignment (WhisperX) with the PASSAGE TEXT as the transcript, because the
     speaker read a known text (the manual-transcript option of ARCHITECTURE.md 7.2 / 11),
  4. checks that the alignment is plausible and writes data/processed/alignments/<take>.alignment.json (processed-audio time),
  5. for a flawed take, proposes the flaw annotation from the recording plan: the planned stretch is placed on the timeline by the
     alignment and written to data/annotations/<take>.flaws.json in the time of the ORIGINAL file, marked "proposed" until a person has
     confirmed it by ear; it also checks, against the speaker's own baseline takes, that the flaw was really performed,
  6. writes Audacity label files (data/processed/labels/) so the words and the proposed flaw can be checked by ear,
  7. merges the entries into data/metadata/{manifest,speakers,passages}.json,
and finally verifies the dataset (validate_dataset.py) and, with --build-baseline, builds the baseline statistics that the site compares
a participant with (build_baseline_stats.py, dev speakers only).

Nothing is invented: a number that cannot be measured is reported as missing, never guessed. Running it again with the same files changes
nothing (an unchanged take keeps its alignment and any annotation a person already confirmed). A re-recorded take needs --replace.
Warnings never stop a take from being registered; they travel with its annotation so a weak example is not mistaken for a clear one.

Exit code: 0 when every take was registered (or already was) and the dataset is valid, 1 otherwise, 2 when there was nothing to do.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import io
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import scipy.io.wavfile as wavfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import build_baseline_stats as bbs  # noqa: E402
import check_recordings as cr  # noqa: E402
import make_plan as mp  # noqa: E402
import passage_text as pt  # noqa: E402
import take_checks as tc  # noqa: E402
import validate_dataset as vd  # noqa: E402
from app.core.baseline import BASELINE_STATS_SUBDIR, pause_statistics_thin, rate_statistics_thin  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.schemas.common import TranscriptSource  # noqa: E402
from app.schemas.contracts import AlignedTranscript, PreprocessedAudio, Transcript  # noqa: E402
from app.services.alignment import AlignmentConfigError, AlignmentModelError  # noqa: E402
from app.services.alignment.validator import validate_alignment  # noqa: E402
from app.services.audio import AudioPreprocessor  # noqa: E402

DATASET_VERSION = "1.0.0"
DEFAULT_PASSAGES = Path("data/plan/passages_v1.json")
DEFAULT_PLAN = Path("data/plan/v1/plan.csv")
CATEGORY_OF_KIND = {"base": "baseline_effective", "clean": "clean_control"}
FLAW_OF_KIND = {kind: flaw for flaw, kind in mp.KIND.items()}
ALIGNMENT_DECIMALS = 3   # word times are stored to the millisecond, so the stored file does not depend on last-bit float noise
SCORE_DECIMALS = 4


class PrepareError(Exception):
    """The whole run cannot continue (unusable passage file, no alignment model, ...). The message says what to do."""


class TakeProblem(Exception):
    """One take cannot be registered. The message says why, in plain words."""


@dataclass
class Take:
    path: Path
    take_id: str
    passage_id: str
    speaker_id: str
    split: str
    category: str
    flaw_type: Optional[str]
    number: int
    sha256: str = ""
    sample_rate: int = 0
    channels: int = 0
    duration_s: float = 0.0
    audio: Optional[PreprocessedAudio] = None
    aligned: Optional[AlignedTranscript] = None
    alignment_json: Optional[str] = None     # the stored form of a NEW alignment (None when a stored one was kept)
    alignment_sha256: str = ""
    reused_alignment: bool = False
    findings: List[tc.Finding] = field(default_factory=list)
    annotation: Optional[Dict[str, Any]] = None
    existing: Optional[Dict[str, Any]] = None
    status: str = "pending"   # registered | updated | unchanged | failed
    problem: str = ""

    @property
    def is_baseline(self) -> bool:
        return self.category == "baseline_effective"

    @property
    def warned(self) -> bool:
        return any(f.level == tc.WARN for f in self.findings)


@dataclass
class Report:
    takes: List[Take] = field(default_factory=list)
    baselines: List[Tuple[str, Any, str]] = field(default_factory=list)   # (passage_id, BaselineStatsRecord | None, error text)
    dataset_ok: Optional[bool] = None
    dataset_errors: List[str] = field(default_factory=list)
    dataset_notes: int = 0


# ---------------------------------------------------------------------------------------------------------------------------------
# Small file helpers
# ---------------------------------------------------------------------------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PrepareError(f"Cannot read {path}: {exc}") from exc


def write_json(path: Path, data: Any) -> None:
    """Write `data` as JSON; a file that already holds exactly this content is left untouched (no needless change for version control)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if not path.is_file() or path.read_bytes() != payload:
        path.write_bytes(payload)


def clean_word(word: str) -> str:
    """A passage word without the punctuation around it ('analytics.' -> 'analytics')."""
    return re.sub(r"^[^\w']+|[^\w']+$", "", word)


def alignment_to_json(aligned: AlignedTranscript) -> Tuple[str, AlignedTranscript]:
    """The stored form of an alignment (times to the millisecond, sorted keys) and the alignment exactly as stored."""
    data = aligned.model_dump(mode="json")
    for word in data["words"]:
        for key in ("start_s", "end_s"):
            if word[key] is not None:
                word[key] = round(word[key], ALIGNMENT_DECIMALS)
        if word["confidence"] is not None:
            word["confidence"] = round(word["confidence"], SCORE_DECIMALS)
    data["total_coverage_pct"] = round(data["total_coverage_pct"], SCORE_DECIMALS)
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", AlignedTranscript.model_validate(data)


def read_plan(path: Optional[Path]) -> Dict[str, Dict[str, str]]:
    """The recording plan by take id (empty when there is no plan file)."""
    if path is None or not path.is_file():
        return {}
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:      # a spreadsheet program may add a byte-order mark
            return {row["take_id"]: row for row in csv.DictReader(handle)}
    except (OSError, KeyError, ValueError, csv.Error) as exc:
        raise PrepareError(f"Cannot read the plan {path}: {exc}") from exc


def audacity_labels(rows: Sequence[Tuple[float, float, str]]) -> str:
    """Audacity label-track text: start, end and label separated by tabs, times in seconds (File > Import > Labels)."""
    return "".join(f"{start:.3f}\t{end:.3f}\t{label}\n" for start, end, label in rows)


# ---------------------------------------------------------------------------------------------------------------------------------
# The preparer
# ---------------------------------------------------------------------------------------------------------------------------------

class Preparer:
    """Registers takes in one data directory. `aligner` is anything with `.align(audio, transcript)`; the WhisperX service by default."""

    def __init__(
        self,
        data_dir: Path,
        passages_file: Path = DEFAULT_PASSAGES,
        plan_file: Optional[Path] = DEFAULT_PLAN,
        *,
        aligner: Any = None,
        microphone: str = "headset_usb",
        conditions: str = "quiet_room",
        replace: bool = False,
        realign: bool = False,
        today: Optional[str] = None,
        out: Callable[[str], None] = print,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.passages_file = Path(passages_file)
        self.plan_file = Path(plan_file) if plan_file else None
        self._aligner = aligner
        self.microphone = microphone
        self.conditions = conditions
        self.replace = replace
        self.realign = realign
        self.today = today or date.today().isoformat()
        self.say = out
        self.preprocessor = AudioPreprocessor()
        self._reference_cache: Dict[str, Tuple[PreprocessedAudio, AlignedTranscript]] = {}

    # -- locations ----------------------------------------------------------------------------------------------------------------
    def rel(self, *parts: str) -> str:
        """A path as the manifest stores it: relative to the folder that contains the data directory."""
        return "/".join((self.data_dir.name,) + parts)

    # -- inputs -------------------------------------------------------------------------------------------------------------------
    def load_reference_passages(self) -> Dict[str, Dict[str, Any]]:
        entries = read_json(self.passages_file, None)
        if not isinstance(entries, list) or not entries:
            raise PrepareError(f"Cannot find the passages in {self.passages_file}. Use --passages to point at the passages file.")
        return {e["passage_id"]: e for e in entries if isinstance(e, dict) and isinstance(e.get("passage_id"), str)}

    def aligner(self) -> Any:
        if self._aligner is None:
            from app.services.alignment import get_aligner

            self._aligner = get_aligner()
        return self._aligner

    # -- one take: describe, load, align ------------------------------------------------------------------------------------------
    def describe(self, path: Path) -> Take:
        name = cr.parse_name(path)
        if not name:
            raise TakeProblem("The file name does not follow the protocol (rec_p001_spk_dev_01_base_01.wav). Rename the file; do not change the audio.")
        kind = name["kind"]
        flaw = FLAW_OF_KIND.get(kind)
        if kind.startswith("flaw_") and flaw is None:
            raise TakeProblem(f"'{kind}' is not a flaw of the plan ({', '.join(sorted(FLAW_OF_KIND))}).")
        category = CATEGORY_OF_KIND.get(kind, "flawed_human_controlled")
        split = "dev" if name["speaker"].startswith("spk_dev_") else "test"
        return Take(path, path.stem, name["passage"], name["speaker"], split, category, flaw, int(name["number"]))

    def load(self, take: Take, passage: Dict[str, Any], existing: Optional[Dict[str, Any]]) -> None:
        """Read, preprocess and align one take; fills in the take or raises TakeProblem."""
        data = take.path.read_bytes()
        take.sha256 = sha256_bytes(data)
        take.existing = existing
        if existing is not None and existing.get("sha256_audio") != take.sha256 and not self.replace:
            raise TakeProblem("It is already registered with different audio. If you recorded this take again, add --replace.")
        try:
            rate, raw = wavfile.read(str(take.path))
        except Exception as exc:  # the reader raises many types for damaged files; all mean the same here
            raise TakeProblem(f"Not a readable WAV file ({type(exc).__name__}).") from exc
        take.sample_rate, take.channels = int(rate), (1 if raw.ndim == 1 else int(raw.shape[1]))
        take.duration_s = len(raw) / rate
        try:
            take.audio = self.preprocessor.process(data)
        except Exception as exc:  # AudioPreprocessingError, AudioTooLongError, decoder errors: all unusable for the dataset
            raise TakeProblem(f"The audio could not be prepared: {str(exc)[:120]}") from exc
        if len(take.audio.audio_array) == 0:
            raise TakeProblem("The audio is silent after preprocessing.")

        text = " ".join(str(passage["text"]).split())   # single spaces: the aligner splits the text into words on spaces
        stored = None
        if existing is not None and existing.get("sha256_audio") == take.sha256 and not self.realign:
            stored = self._stored_alignment(take.take_id, existing)
        if stored is not None:
            take.aligned, take.reused_alignment = stored, True
        else:
            take.aligned = self._align(take, text)
        # Coverage is judged by assess_alignment: the pipeline's own 0.80 warning would fire on every take with a deliberate long pause.
        validation = validate_alignment(take.aligned, audio_duration_s=take.audio.duration_s, min_coverage_pct=None)
        if not validation.is_valid:
            raise TakeProblem("The word alignment is not valid: " + "; ".join(validation.errors))
        take.findings += [tc.Finding(tc.WARN, w) for w in validation.warnings]
        words = [w for sentence in pt.passage_words(passage["text"]) for w in sentence]
        assessment = tc.assess_alignment(take.aligned, words, take.audio.duration_s, take.is_baseline)
        failures = [f.message for f in assessment if f.level == tc.FAIL]
        if failures:
            raise TakeProblem("The word alignment cannot be used: " + "; ".join(failures) + ".")
        take.findings += assessment

    def _stored_alignment(self, rec_id: str, entry: Dict[str, Any]) -> Optional[AlignedTranscript]:
        """The alignment stored for a registered recording, or None when it is missing or no longer matches its manifest hash."""
        path = self.data_dir / "processed" / "alignments" / f"{rec_id}.alignment.json"
        if not path.is_file() or sha256_bytes(path.read_bytes()) != entry.get("sha256_alignment"):
            return None
        try:
            return AlignedTranscript.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError:
            return None

    def _align(self, take: Take, text: str) -> AlignedTranscript:
        transcript = Transcript(text=text, segments=[], words=[], model_name="manual", source=TranscriptSource.MANUAL,
                                language=settings.ALIGNMENT_LANGUAGE or None)
        try:
            aligned = self.aligner().align(take.audio, transcript)
        except (AlignmentModelError, AlignmentConfigError, ImportError) as exc:
            raise PrepareError(
                f"The alignment model could not be loaded: {exc}\nRun  python scripts/check_environment.py --download-models  and fix what it reports."
            ) from exc
        except Exception as exc:  # AlignmentRuntimeError and anything the model raises on one take
            raise TakeProblem(f"The alignment failed: {str(exc)[:160]}") from exc
        take.alignment_json, aligned = alignment_to_json(aligned)
        return aligned

    # -- references for the flaw checks ---------------------------------------------------------------------------------------------
    def references(self, take: Take, batch: Sequence[Take], manifest: Dict[str, Dict[str, Any]]) -> List[Tuple[PreprocessedAudio, AlignedTranscript]]:
        """The speaker's baseline takes of this passage: the ones of this run first, then those registered earlier."""
        found: Dict[str, Tuple[PreprocessedAudio, AlignedTranscript]] = {}
        for other in batch:
            if other.is_baseline and other.status != "failed" and other.speaker_id == take.speaker_id and other.passage_id == take.passage_id:
                found[other.take_id] = (other.audio, other.aligned)
        for rec_id, entry in manifest.items():
            if (rec_id in found or entry.get("category") != "baseline_effective" or entry.get("speaker_id") != take.speaker_id
                    or entry.get("passage_id") != take.passage_id):
                continue
            if rec_id not in self._reference_cache:
                aligned = self._stored_alignment(rec_id, entry)
                audio_path = self.data_dir / "raw" / f"{rec_id}.wav"
                if aligned is None or not audio_path.is_file():
                    continue
                self._reference_cache[rec_id] = (self.preprocessor.process(audio_path.read_bytes()), aligned)
            found[rec_id] = self._reference_cache[rec_id]
        return [found[k] for k in sorted(found)]

    # -- the proposed annotation ---------------------------------------------------------------------------------------------------
    def propose(self, take: Take, row: Dict[str, str], words: Sequence[str], refs: Sequence[Tuple[PreprocessedAudio, AlignedTranscript]]) -> None:
        """Place the planned flaw on the timeline and check that it was performed; fills in take.annotation and take.findings."""
        if row.get("flaw_type") != take.flaw_type:
            raise TakeProblem(f"The plan says {row.get('flaw_type')!r} for this take, the file name says {take.flaw_type!r}.")
        try:
            first, last = int(row["stretch_first_word"]), int(row["stretch_last_word"])
            pause_after = int(row["pause_after_word"]) if row.get("pause_after_word") else None
        except (KeyError, ValueError) as exc:
            raise TakeProblem("The plan has no usable word numbers for this take.") from exc
        if not (1 <= first <= last <= len(words)):
            raise TakeProblem(f"The plan's words {first} to {last} are outside the passage ({len(words)} words).")
        aligned, audio = take.aligned, take.audio
        if take.flaw_type == "excessive_pause":
            if pause_after is None or pause_after != first or last != first + 1:
                raise TakeProblem("The plan does not say after which word the silence falls.")
            span = tc.gap_after_word(aligned, pause_after)
            note = tc.check_pause(take.number, span[1] - span[0]) if span else None
        else:
            span = tc.word_span(aligned, first, last)
            note = self._performed(take, first, last, span, refs) if span else None
        if span is None:
            raise TakeProblem("The words around the planned flaw have no time, so the flaw cannot be placed.")
        take.findings.append(note or tc.Finding(tc.INFO, "no baseline take of this speaker was available to check that the flaw was performed"))
        start, end = audio.to_source_time(span[0]), min(audio.to_source_time(span[1]), take.duration_s)
        stretch = [words[first - 1], words[last - 1]] if take.flaw_type == "excessive_pause" else list(words[first - 1:last])
        where = f"words {first} to {last}" if take.flaw_type != "excessive_pause" else f"the silence after word {pause_after}"
        notes = f"Proposed from the recording plan ({row.get('stretch', '')}; {where}), placed by forced alignment. Not yet confirmed by ear."
        if note is not None:
            notes += f" Take check: {note.message}."
        take.annotation = {
            "recording_id": take.take_id,
            "passage_id": take.passage_id,
            "dataset_version": DATASET_VERSION,
            "annotation_status": "proposed",
            "flaws": [{
                "flaw_id": f"ann_{take.take_id}_01",
                "flaw_type": take.flaw_type,
                "start_s": round(start, ALIGNMENT_DECIMALS),
                "end_s": round(end, ALIGNMENT_DECIMALS),
                "severity_label": row.get("severity_label") or "medium",
                "target_words": [clean_word(w) for w in stretch],
                "annotator_notes": notes,
            }],
        }

    def _performed(self, take: Take, first: int, last: int, span: Tuple[float, float], refs: Sequence[Tuple[PreprocessedAudio, AlignedTranscript]]) -> Optional[tc.Finding]:
        """Did the speaker really go faster / slower / louder / quieter in the stretch? None when there is nothing to compare with."""
        spans = [s for _audio, ref in refs if (s := tc.word_span(ref, first, last)) is not None]
        if take.flaw_type in ("too_fast", "too_slow"):
            if not spans:
                return None
            reference = sum(end - start for start, end in spans) / len(spans)
            return tc.check_speed(take.flaw_type, take.number, span[1] - span[0], reference) if reference > 0 else None
        window = settings.SPEECH_LEVEL_WINDOW_DB
        mine = tc.level_offset_db(take.audio.audio_array, take.audio.sample_rate_hz, span, window)
        theirs = [o for (audio, ref) in refs
                  if (s := tc.word_span(ref, first, last)) is not None
                  and (o := tc.level_offset_db(audio.audio_array, audio.sample_rate_hz, s, window)) is not None]
        if mine is None or not theirs:
            return None
        return tc.check_level(take.flaw_type, take.number, mine, sum(theirs) / len(theirs))

    # -- the run ------------------------------------------------------------------------------------------------------------------
    def run(self, inputs: Sequence[Path], build_baseline: bool = False) -> Report:
        files = cr.collect(inputs)
        report = Report()
        if not files:
            return report
        reference = self.load_reference_passages()
        plan = read_plan(self.plan_file)
        for folder in ("metadata", "annotations", "raw", "processed"):
            (self.data_dir / folder).mkdir(parents=True, exist_ok=True)
        manifest_path = self.data_dir / "metadata" / "manifest.json"
        passages_path, speakers_path = self.data_dir / "metadata" / "passages.json", self.data_dir / "metadata" / "speakers.json"
        manifest = {e["recording_id"]: e for e in read_json(manifest_path, []) if isinstance(e, dict) and "recording_id" in e}
        passages = read_json(passages_path, [])
        speakers = read_json(speakers_path, [])
        speaker_split = {s["speaker_id"]: s.get("split") for s in speakers if isinstance(s, dict) and "speaker_id" in s}
        sizes = {pid: pt.word_count(e["text"]) for pid, e in reference.items() if isinstance(e.get("text"), str)}
        quality = {r.file: r for r in cr.check_files(files, sizes)}

        # 1. read, check and align every take (nothing is written yet)
        self.say(f"Preparing {len(files)} recording(s). The first alignment loads the model and can take a minute.")
        seen: set = set()
        for index, path in enumerate(files, start=1):
            try:
                if path.suffix.lower() != ".wav":
                    raise TakeProblem(f"This is a {path.suffix.lower()} file, not a WAV file. Export the take from Audacity as WAV (Signed 16-bit PCM).")
                take = self.describe(path)
            except TakeProblem as exc:
                report.takes.append(Take(path, path.stem, "", "", "", "", None, 0, status="failed", problem=str(exc)))
                self.say(f"  [{index}/{len(files)}] {path.name}: not registered")
                continue
            report.takes.append(take)
            self.say(f"  [{index}/{len(files)}] {take.take_id}: working ...")
            try:
                if take.take_id in seen:
                    raise TakeProblem("Another file with the same name was given; only the first one is used.")
                seen.add(take.take_id)
                self._prepare_take(take, reference, quality.get(path.name), manifest, speaker_split, passages)
            except TakeProblem as exc:
                take.status, take.problem = "failed", str(exc)
            self.say(f"  [{index}/{len(files)}] {take.take_id}: {'not registered' if take.status == 'failed' else 'aligned' if not take.reused_alignment else 'alignment kept'}")

        # 2. flaw annotations and the check that each flaw was performed (needs the baseline takes of the same speaker)
        usable = [t for t in report.takes if t.status != "failed"]
        for take in usable:
            if take.category != "flawed_human_controlled":
                continue
            try:
                self._annotate(take, plan, reference, usable, manifest)
            except TakeProblem as exc:
                take.status, take.problem = "failed", str(exc)

        # 3. write files, then the metadata
        usable = [t for t in report.takes if t.status != "failed"]
        for take in usable:
            self._write_take(take)
        self._merge_metadata(usable, manifest, passages, speakers, reference)
        write_json(manifest_path, [manifest[k] for k in sorted(manifest)])
        write_json(passages_path, passages)
        write_json(speakers_path, speakers)

        # 4. baselines, then the dataset check
        if build_baseline:
            self._build_baselines(report, manifest)
        self._validate(report)
        return report

    def _prepare_take(self, take: Take, reference: Dict[str, Dict[str, Any]], quality: Optional[Any], manifest: Dict[str, Dict[str, Any]],
                      speaker_split: Dict[str, Optional[str]], passages: List[Dict[str, Any]]) -> None:
        if quality is not None and quality.status == cr.FAIL:
            reasons = "; ".join(c.message for c in quality.checks if c.status == cr.FAIL)
            raise TakeProblem(f"It failed the recording check, so it is not registered: {reasons}")
        if take.passage_id not in reference:
            raise TakeProblem(f"Passage {take.passage_id} is not in {self.passages_file}.")
        registered = next((p for p in passages if isinstance(p, dict) and p.get("passage_id") == take.passage_id), None)
        if registered is not None and " ".join(str(registered.get("text", "")).split()) != " ".join(str(reference[take.passage_id]["text"]).split()):
            raise TakeProblem(f"The text of passage {take.passage_id} in the dataset differs from {self.passages_file}. Recordings belong to one exact text.")
        if take.speaker_id in speaker_split and speaker_split[take.speaker_id] not in (None, take.split):
            raise TakeProblem(f"Speaker {take.speaker_id} is registered in the {speaker_split[take.speaker_id]} split, but the file name says {take.split}.")
        self.load(take, reference[take.passage_id], manifest.get(take.take_id))

    def _annotate(self, take: Take, plan: Dict[str, Dict[str, str]], reference: Dict[str, Dict[str, Any]], batch: Sequence[Take],
                  manifest: Dict[str, Dict[str, Any]]) -> None:
        row = plan.get(take.take_id)
        if row is None:
            raise TakeProblem(f"It is not in the recording plan ({self.plan_file}), so the flaw cannot be placed. Use --plan to point at the plan sheet.")
        existing = self._existing_annotation(take)
        if existing is not None and existing.get("annotation_status") != "proposed" and take.existing is not None \
                and take.existing.get("sha256_audio") == take.sha256:
            take.annotation = None    # a person confirmed or edited it: keep it
            take.findings.append(tc.Finding(tc.INFO, "the annotation was confirmed by a person and was kept"))
            return
        words = [w for sentence in pt.passage_words(reference[take.passage_id]["text"]) for w in sentence]
        self.propose(take, row, words, self.references(take, batch, manifest))

    def _existing_annotation(self, take: Take) -> Optional[Dict[str, Any]]:
        path = self.data_dir / "annotations" / f"{take.take_id}.flaws.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    # -- writing ---------------------------------------------------------------------------------------------------------------------
    def _write_take(self, take: Take) -> None:
        raw = self.data_dir / "raw" / f"{take.take_id}.wav"
        raw.parent.mkdir(parents=True, exist_ok=True)
        if not (raw.is_file() and sha256_bytes(raw.read_bytes()) == take.sha256):
            shutil.copyfile(take.path, raw)
        align_path = self.data_dir / "processed" / "alignments" / f"{take.take_id}.alignment.json"
        if take.alignment_json is not None:
            align_path.parent.mkdir(parents=True, exist_ok=True)
            align_path.write_text(take.alignment_json, encoding="utf-8")
        take.alignment_sha256 = sha256_bytes(align_path.read_bytes())
        if take.annotation is not None:
            write_json(self.data_dir / "annotations" / f"{take.take_id}.flaws.json", take.annotation)
        labels = self.data_dir / "processed" / "labels"
        labels.mkdir(parents=True, exist_ok=True)
        audio = take.audio
        word_rows = [(audio.to_source_time(w.start_s), audio.to_source_time(w.end_s), w.word) for w in take.aligned.words
                     if w.start_s is not None and w.end_s is not None]
        (labels / f"{take.take_id}.words.txt").write_text(audacity_labels(word_rows), encoding="utf-8")
        if take.annotation is not None:
            flaw = take.annotation["flaws"][0]
            (labels / f"{take.take_id}.flaw.txt").write_text(
                audacity_labels([(flaw["start_s"], flaw["end_s"], f"PLANNED {flaw['flaw_type']} (check by ear)")]), encoding="utf-8")

    def _merge_metadata(self, takes: Sequence[Take], manifest: Dict[str, Dict[str, Any]], passages: List[Dict[str, Any]],
                        speakers: List[Dict[str, Any]], reference: Dict[str, Dict[str, Any]]) -> None:
        for take in takes:
            if not any(isinstance(p, dict) and p.get("passage_id") == take.passage_id for p in passages):
                passages.append(dict(reference[take.passage_id]))
            if not any(isinstance(s, dict) and s.get("speaker_id") == take.speaker_id for s in speakers):
                speakers.append({"speaker_id": take.speaker_id, "split": take.split, "gender": "unspecified",
                                 "native_language": "unspecified", "notes": "Added by prepare_recordings.py; fill in the details."})
            old = take.existing
            unchanged = old is not None and old.get("sha256_audio") == take.sha256
            entry = {
                "recording_id": take.take_id,
                "passage_id": take.passage_id,
                "speaker_id": take.speaker_id,
                "category": take.category,
                "split": take.split,
                "audio_file": self.rel("raw", f"{take.take_id}.wav"),
                "duration_s": round(take.duration_s, ALIGNMENT_DECIMALS),
                "sample_rate_hz": take.sample_rate,
                "channels": take.channels,
                "sha256_audio": take.sha256,
                "alignment_file": self.rel("processed", "alignments", f"{take.take_id}.alignment.json"),
                "sha256_alignment": take.alignment_sha256,
                "annotation_file": self.rel("annotations", f"{take.take_id}.flaws.json") if take.category == "flawed_human_controlled" else None,
                "recording_conditions": (old or {}).get("recording_conditions", self.conditions) if unchanged else self.conditions,
                "microphone": (old or {}).get("microphone", self.microphone) if unchanged else self.microphone,
                "is_synthetic": False,
                "synthesis_technique": None,
                "dataset_version": DATASET_VERSION,
                "created_at": (old or {}).get("created_at", self.today) if unchanged else self.today,
            }
            if unchanged:
                entry = {**old, **entry}
            take.status = "unchanged" if unchanged and old == entry else "updated" if old is not None else "registered"
            manifest[take.take_id] = entry

    # -- baselines and the dataset check ---------------------------------------------------------------------------------------------
    def _build_baselines(self, report: Report, manifest: Dict[str, Dict[str, Any]]) -> None:
        wanted = sorted({e["passage_id"] for e in manifest.values() if e.get("category") == "baseline_effective" and e.get("split") == "dev"})
        for passage_id in wanted:
            try:
                record = bbs.build_for_passage(self.data_dir, passage_id, ["dev"])
                bbs.write_stats(record, self.data_dir / BASELINE_STATS_SUBDIR, overwrite=True)
                report.baselines.append((passage_id, record, ""))
            except bbs.BaselineBuildError as exc:
                report.baselines.append((passage_id, None, str(exc)))

    def _validate(self, report: Report) -> None:
        validator = vd.DatasetValidator(self.data_dir, check_files_exist=True)
        with contextlib.redirect_stdout(io.StringIO()):
            report.dataset_ok = validator.validate_all()
        report.dataset_errors = list(validator.errors)
        report.dataset_notes = len(validator.warnings)


# ---------------------------------------------------------------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------------------------------------------------------------

def render(report: Report, data_dir: Path) -> str:
    lines: List[str] = [""]
    for take in report.takes:
        if take.status == "failed":
            lines += [f"FAILED  {take.take_id}", f"        {take.problem}"]
            continue
        pace = tc.pace_wpm(take.aligned)
        facts = f"{take.duration_s:.1f} s file, {len(take.aligned.words)} words placed" + (f", {pace:.0f} words per minute" if pace else "")
        label = "CHECK " if take.warned else "OK    "
        lines.append(f"{label}  {take.take_id}  ({take.status}; {facts})")
        for finding in take.findings:
            mark = {tc.FAIL: "x", tc.WARN: "!", tc.INFO: "-", tc.OK: "+"}[finding.level]
            lines.append(f"        {mark} {finding.message}")
    counts = {s: sum(1 for t in report.takes if t.status == s) for s in ("registered", "updated", "unchanged", "failed")}
    lines += ["", f"{len(report.takes)} file(s): {counts['registered']} registered, {counts['updated']} updated, "
                  f"{counts['unchanged']} unchanged, {counts['failed']} not registered."]
    for passage_id, record, error in report.baselines:
        if record is None:
            lines += ["", f"Baseline for {passage_id}: NOT built.", f"  {error}",
                      "  A baseline needs the baseline takes to contain enough natural speech and pauses to measure. Send this message to the team lead."]
            continue
        thin = [name for name, flag in (("speech rate", rate_statistics_thin(record)), ("pauses", pause_statistics_thin(record))) if flag]
        lines += ["", f"Baseline for {passage_id}: built from {len(record.baseline_recording_ids)} take(s) -> "
                      f"{data_dir / BASELINE_STATS_SUBDIR / (passage_id + '.json')}",
                  f"  pitch {record.f0_voiced_hz_mean:.0f} Hz on average, speech rate {record.rate_wpm_mean:.0f} +/- {record.rate_wpm_std:.0f} words per minute, "
                  f"{record.n_pauses_within_phrase} short and {record.n_pauses_cross_sentence} sentence pauses measured."]
        if thin:
            lines.append(f"  Note: few observations for {' and '.join(thin)}; scores for them will be noisier. More baseline takes make them steadier.")
    if report.dataset_ok is not None:
        verdict = "valid" if report.dataset_ok else "NOT valid"
        lines += ["", f"Dataset check: {verdict} ({report.dataset_notes} note(s); run  python scripts/dataset/validate_dataset.py --check-files  for details)."]
        lines += [f"  x {e}" for e in report.dataset_errors]
    if any(record is not None for _pid, record, _err in report.baselines):
        lines += ["", "Next: start the site with   python -m uvicorn app.main:app --app-dir backend   and open http://127.0.0.1:8000 (the dashboard must be built once:",
                  "cd frontend, npm ci, npm run build). Choose the baseline 'Project talk' and upload a flawed take."]
    if any(t.annotation for t in report.takes):
        lines += ["", "The flaw annotations are PROPOSED from the plan. Open a take in Audacity and import data/processed/labels/<take>.words.txt and",
                  "<take>.flaw.txt (File > Import > Labels) to check by ear that the marked stretch is where the flaw is."]
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None, aligner: Any = None) -> int:
    """Command line. `aligner` replaces the WhisperX service (for tests only)."""
    parser = argparse.ArgumentParser(description="Register recorded takes in the dataset and prepare them for analysis.")
    parser.add_argument("inputs", nargs="+", type=Path, help="folder(s) or WAV file(s) named by the protocol, for example data/incoming")
    parser.add_argument("--data-dir", type=Path, default=Path("data"), help="the data/ folder (default: data)")
    parser.add_argument("--passages", type=Path, default=DEFAULT_PASSAGES, help=f"the passages file (default: {DEFAULT_PASSAGES})")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN, help=f"the recording plan sheet (default: {DEFAULT_PLAN})")
    parser.add_argument("--build-baseline", action="store_true", help="also build the baseline statistics from the dev speakers' baseline takes")
    parser.add_argument("--microphone", default="headset_usb", help="microphone name stored for NEW takes (default: headset_usb)")
    parser.add_argument("--conditions", default="quiet_room", help="room description stored for NEW takes (default: quiet_room)")
    parser.add_argument("--replace", action="store_true", help="accept a take whose audio changed because it was recorded again")
    parser.add_argument("--realign", action="store_true", help="align again even when a stored alignment exists")
    args = parser.parse_args(argv)
    try:
        preparer = Preparer(args.data_dir, args.passages, args.plan, aligner=aligner, microphone=args.microphone,
                            conditions=args.conditions, replace=args.replace, realign=args.realign)
        report = preparer.run(args.inputs, build_baseline=args.build_baseline)
    except PrepareError as exc:
        print(f"\nStopped: {exc}", file=sys.stderr)
        return 1
    if not report.takes:
        print("No WAV files found in the given paths.", file=sys.stderr)
        return 2
    print(render(report, args.data_dir))
    failed = any(t.status == "failed" for t in report.takes) or report.dataset_ok is False \
        or any(record is None for _pid, record, _err in report.baselines)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
