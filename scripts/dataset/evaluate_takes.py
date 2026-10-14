"""Replay registered takes through the analysis and compare the findings with the annotations.

    python scripts/dataset/evaluate_takes.py                       # every dev take that is not a baseline take
    python scripts/dataset/evaluate_takes.py --only flaw_fast      # takes whose id contains this text
    python scripts/dataset/evaluate_takes.py --json report.json    # also write everything to a file

It answers, with numbers instead of an impression: was each planned flaw found, how far off are the start and the end, how much of the detected
range was really the flaw, and what else was flagged (on a clean take, anything flagged is a false alarm).

Try a different setting without touching any file, for example the pause threshold or the old, window-wide rate intervals:

    python scripts/dataset/evaluate_takes.py --detect z_pause_within=3 min_pause_s=0.8
    python scripts/dataset/evaluate_takes.py --detect refine_rate=false

Compare several values of a setting in one table (every row changes ONE setting; the others keep their normal value), to choose a setting
from numbers: how many planned flaws are found, how many extra flags, how many clean takes are flagged:

    python scripts/dataset/evaluate_takes.py --sweep "z_run_rate=3,3.5,4,4.5" "run_min_words=8,10,12" "min_pause_s=1,1.2,1.5"

(Quote each list: PowerShell cuts an unquoted list at its commas. The tool puts such pieces back together, so a forgotten quote still works.)

The replay needs no speech model and no internet: the audio is the registered recording, the word times are the alignment stored by
prepare_recordings.py, the transcript is the passage text, and the baseline is the stored one. Everything else is the real analysis, so the same
files and the same code give the same table every time. (With --live the real Whisper and WhisperX run instead, as on the site; slower.)

Rules that protect the dataset:
  * Only the dev split is evaluated unless --allow-test is given: the test speakers stay sealed until the settings are frozen (protocol 7.5).
  * Baseline takes are left out unless --include-baseline: they are part of the baseline, so a good score on them proves nothing.
  * Annotations that are only "proposed" count, but the report says how many; --confirmed-only keeps the confirmed ones.

A planned flaw counts as FOUND when a detection of the same type covers at least half of the annotated interval.
Times are in the time of the original file, the same as the annotations and the site.

Exit code: 0 when the replay ran, 1 when a take could not be replayed or nothing was selected.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import re
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.core.baseline import BASELINE_STATS_SUBDIR, BaselineProvider  # noqa: E402
from app.core.cache import ResultCache  # noqa: E402
from app.core.passages import PassageCatalog  # noqa: E402
from app.schemas.common import FlawType  # noqa: E402
from app.schemas.contracts import AlignedTranscript  # noqa: E402
from app.schemas.request import AnalyzeRequest  # noqa: E402
from app.services import pipeline as pipeline_module  # noqa: E402
from app.services.grounding import DetectionConfig  # noqa: E402
from app.services.grounding.profile_detection import StretchReading, measure_stretch  # noqa: E402
from app.services.pipeline import AnalysisPipeline, PipelineConfig, PipelineError  # noqa: E402

MIN_COVER = 0.5   # a detection must cover at least this share of the annotated interval


class EvaluationError(Exception):
    """The evaluation cannot run as asked. The message says what to change."""


@dataclass
class Annotated:
    flaw_type: str
    start_s: float
    end_s: float
    status: str      # "proposed", "confirmed" or "unknown" (written by hand)
    notes: str = ""  # the annotator notes: at registration, where the flaw was placed and what the take check said about how well it was performed


@dataclass
class Detected:
    flaw_type: str
    start_s: float
    end_s: float
    severity: float
    note: str        # the evidence in one phrase, as the analysis reports it
    where: str = ""       # an extra on a take that has planned flaws: "on" a planned stretch, "next" to one or "away" from all (see relate_extras)
    where_note: str = ""  # the same in words


@dataclass
class Match:
    planned: Annotated
    found: Optional[Detected]
    overlap_s: float = 0.0
    start_error_s: Optional[float] = None    # detected start minus planned start (positive: detected too late)
    end_error_s: Optional[float] = None      # detected end minus planned end (positive: detected too late)
    iou: float = 0.0                         # overlap / union of the two intervals
    range_ratio: Optional[float] = None      # detected length / planned length (2.0: twice as long as it should be)
    why: List[str] = field(default_factory=list)          # a miss: what the registration check said, what the analysis measures there, what was found instead
    measured: Optional[Dict[str, Any]] = None             # the numbers behind `why` (written with --json)


@dataclass
class TakeResult:
    recording_id: str
    category: str
    speaker_id: str
    duration_s: float
    composite_score: Optional[float] = None
    matches: List[Match] = field(default_factory=list)
    extras: List[Detected] = field(default_factory=list)
    error: str = ""


def overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def match_flaws(planned: Sequence[Annotated], detected: Sequence[Detected], min_cover: float = MIN_COVER) -> Tuple[List[Match], List[Detected]]:
    """Pair each planned flaw with the detection of the same type that overlaps it most; the unpaired detections are the extras.

    A pairing counts only if the detection covers at least `min_cover` of the planned interval; every detection is used at most once.
    """
    used: set = set()
    matches: List[Match] = []
    for plan in planned:
        length = plan.end_s - plan.start_s
        best, best_overlap = None, 0.0
        for i, det in enumerate(detected):
            if i in used or det.flaw_type != plan.flaw_type:
                continue
            o = overlap(plan.start_s, plan.end_s, det.start_s, det.end_s)
            if o > best_overlap:
                best, best_overlap = i, o
        if best is None or length <= 0 or best_overlap + 1e-9 < min_cover * length:
            matches.append(Match(plan, None))
            continue
        used.add(best)
        det = detected[best]
        union = (plan.end_s - plan.start_s) + (det.end_s - det.start_s) - best_overlap
        matches.append(Match(plan, det, best_overlap, det.start_s - plan.start_s, det.end_s - plan.end_s,
                             best_overlap / union if union > 0 else 0.0, (det.end_s - det.start_s) / length))
    return matches, [d for i, d in enumerate(detected) if i not in used]


NEAR_S = 3.0   # an extra flag this close (seconds) to a planned flaw counts as right next to it


def relate_extras(planned: Sequence[Annotated], extras: Sequence[Detected], near_s: float = NEAR_S) -> None:
    """Say for each extra on a take that has planned flaws how it relates to them: ON a planned stretch (overlaps it), NEXT to one (at most `near_s`
    seconds away) or AWAY from all of them.

    People do not change one thing at a time: someone asked to speak quietly often slows down too, and after a loud, slow or paused stretch they
    often catch up. Such a flag is real (its evidence is measured) but not what was planned, so it is told apart from a flag far from anything
    planned, which is the kind worth listening to.
    """
    if not planned:
        return
    for d in extras:
        nearest: List[Tuple[float, str, Annotated]] = []
        for p in planned:
            if overlap(p.start_s, p.end_s, d.start_s, d.end_s) > 0.0:
                nearest.append((0.0, "on", p))
            elif d.start_s >= p.end_s:
                nearest.append((d.start_s - p.end_s, "after", p))
            else:
                nearest.append((p.start_s - d.end_s, "before", p))
        gap, side, plan = min(nearest, key=lambda candidate: (candidate[0], candidate[1] != "on"))      # overlapping beats touching; then the earlier flaw
        if side == "on":
            d.where, d.where_note = "on", f"on the planned {plan.flaw_type} stretch"
        elif gap <= near_s + 1e-9:
            d.where, d.where_note = "next", f"{gap:.1f} s {side} the planned {plan.flaw_type} stretch"
        else:
            d.where, d.where_note = "away", "away from every planned flaw"


_TAKE_CHECK = re.compile(r"Take check: (.+?)\.?\s*$", re.S)


def take_check_note(notes: str) -> str:
    """What the registration check said about how well the flaw was performed: the last sentence of the notes prepare_recordings.py wrote ('' if none)."""
    found = _TAKE_CHECK.search(notes or "")
    return found.group(1).strip() if found else ""


MEASURED_TYPES = ("too_fast", "too_slow", "high_energy", "low_energy", "flat_pitch")


def describe_stretch(flaw_type: str, reading: StretchReading, rules: DetectionConfig) -> str:
    """The measurement of a planned stretch in one sentence, set against what a finding needs (nothing is computed here; '' for a flaw type that
    is not judged word by word)."""
    if flaw_type not in MEASURED_TYPES:
        return ""
    if reading.reason == "transcript_mismatch":
        return "the words of this take do not match the passage well enough to be compared word by word"
    pace = flaw_type in ("too_fast", "too_slow")
    pitch = flaw_type == "flat_pitch"
    signal = reading.rate if pace else reading.pitch if pitch else reading.level
    if signal is None:
        return "too few words could be compared word by word in this take"
    if signal.n_words == 0 or signal.change is None or signal.z is None:
        return "no word that the baseline knows lies in that stretch"
    if pace:
        size, direction = f"{abs(signal.change):.0f}%", "faster" if signal.change > 0 else "slower"
        min_size, z_needed = f"{rules.min_rate_change_pct:g}%", rules.z_run_rate
        enough = abs(signal.change) >= rules.min_rate_change_pct
        subject = "the baseline readers spoke the same words"
    elif pitch:
        size, direction = f"{abs(signal.change):.0f}%", "more" if signal.change > 0 else "less"
        min_size, z_needed = f"{rules.min_flat_pitch_change_pct:g}%", rules.z_run_pitch
        enough = -signal.change >= rules.min_flat_pitch_change_pct
        subject = "the baseline readers moved it on the same words"
    else:
        size, direction = f"{abs(signal.change):.1f} dB", "louder" if signal.change > 0 else "quieter"
        min_size, z_needed = f"{rules.min_energy_change_db:g} dB", rules.z_run_energy
        enough = abs(signal.change) >= rules.min_energy_change_db
        subject = "the baseline readers spoke the same words"
    planned_up = flaw_type in ("too_fast", "high_energy")
    right_way = (signal.change > 0) == planned_up
    verb = "moved the pitch" if pitch else "were"
    text = (f"those {signal.n_words} words {verb} {size} {direction} than {subject} (z {abs(signal.z):.1f}); a finding needs a change of at least "
            f"{min_size} with z above {z_needed:g} over at least {rules.run_min_words} words")
    if signal.n_words < rules.run_min_words:
        text += f" (this stretch has only {signal.n_words})"
    if not right_way:
        return text + ". That is the opposite of what was planned"
    if enough and abs(signal.z) > z_needed and signal.n_words >= rules.run_min_words:
        return text + ". This stretch passes all three, so something else held the finding back (for example a longer finding that took its words); send this line to the developer"
    return text


#: settings of the detection that --detect may change: name -> how to read the value
DETECT_SETTINGS = {"z_rate_fast": float, "z_rate_slow": float, "z_energy": float, "z_pause_within": float, "z_pause_cross": float,
                   "merge_gap_s": float, "refine_rate": "bool", "refine_min_words": int, "min_pause_s": float, "min_flaw_s": float,
                   # word-by-word comparison with the baseline
                   "use_profile": "bool", "z_run_rate": float, "z_run_energy": float, "run_min_words": int, "min_rate_change_pct": float,
                   "min_energy_change_db": float, "global_tempo_change_pct": float,
                   # flat pitch
                   "z_run_pitch": float, "min_flat_pitch_change_pct": float, "global_pitch_change_pct": float}


def detection_config(pairs: Sequence[str]) -> Optional[DetectionConfig]:
    """The detection settings given as NAME=VALUE (None when there are none). `min_pause_s` / `min_flaw_s` are the shortest pause / rate or energy finding."""
    if not pairs:
        return None
    values: Dict[str, Any] = {}
    durations: Dict[FlawType, float] = {}
    for pair in pairs:
        name, sep, text = pair.partition("=")
        if not sep or name not in DETECT_SETTINGS:
            raise EvaluationError(f"Unknown setting '{pair}'. Use NAME=VALUE with NAME one of: {', '.join(sorted(DETECT_SETTINGS))}.")
        kind = DETECT_SETTINGS[name]
        try:
            value = (text.strip().lower() in ("1", "true", "yes", "on")) if kind == "bool" else kind(text)
            if kind == "bool" and text.strip().lower() not in ("1", "true", "yes", "on", "0", "false", "no", "off"):
                raise ValueError(text)
        except ValueError as exc:
            raise EvaluationError(f"'{text}' is not a valid value for {name}.") from exc
        if name == "min_pause_s":
            durations[FlawType.EXCESSIVE_PAUSE] = value
        elif name == "min_flaw_s":
            durations.update({t: value for t in (FlawType.TOO_FAST, FlawType.TOO_SLOW, FlawType.LOW_ENERGY, FlawType.HIGH_ENERGY)})
        else:
            values[name] = value
    try:
        return DetectionConfig(min_duration_s=durations or None, **values)
    except ValueError as exc:
        raise EvaluationError(str(exc)) from exc


class ReplayAligner:
    """Answers with the alignment stored at registration (processed-audio time), so no alignment model is needed."""

    def __init__(self, aligned: AlignedTranscript) -> None:
        self.aligned = aligned

    def align(self, _audio: Any, _transcript: Any) -> AlignedTranscript:
        return self.aligned


class NoTranscriber:
    def transcribe(self, _audio: Any) -> Any:
        raise RuntimeError("the replay supplies the transcript; speech recognition must not run")


def read_json(path: Path, what: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EvaluationError(f"Cannot read {what} ({path}): {exc}") from exc


def load_annotations(data_dir: Path, recording_id: str) -> List[Annotated]:
    path = data_dir / "annotations" / f"{recording_id}.flaws.json"
    if not path.is_file():
        return []
    data = read_json(path, "an annotation file")
    status = str(data.get("annotation_status", "unknown"))
    return [Annotated(str(f["flaw_type"]), float(f["start_s"]), float(f["end_s"]), status, str(f.get("annotator_notes") or "")) for f in data.get("flaws", [])]


def evidence_note(flaw: Any) -> str:
    """The evidence of a finding in one short phrase (taken from the analysis, nothing computed here)."""
    ev = flaw.evidence
    if hasattr(ev, "rate_participant_wpm"):
        return f"rate {ev.rate_participant_wpm:.0f} words/min against {ev.rate_baseline_mean_wpm:.0f} expected, z {ev.rate_z_score:.1f}"
    if hasattr(ev, "f0_std_hz_in_window"):
        return f"pitch movement {ev.f0_std_hz_in_window:.1f} Hz against {ev.f0_std_baseline_hz:.1f} expected, z {ev.f0_std_z:.1f}"
    if hasattr(ev, "energy_mean_db"):
        return f"level {ev.energy_mean_db:.1f} dBFS against {ev.energy_baseline_mean_db:.1f} expected, z {ev.energy_z_score:.1f}"
    if hasattr(ev, "pause_duration_s"):
        return f"pause {ev.pause_duration_s:.2f} s against {ev.pause_baseline_mean_s:.2f} s usual, z {ev.pause_z_score:.1f}"
    return ""


@contextlib.contextmanager
def captured_word_measurements() -> Iterator[List[Any]]:
    """Keep the word measurements the analysis judges (the very objects it uses), so a planned flaw that was missed can be measured with the same numbers."""
    kept: List[Any] = []
    measure = pipeline_module.measure_words

    def capture(*args: Any, **kwargs: Any) -> Any:
        observations = measure(*args, **kwargs)
        kept.append(observations)
        return observations

    with mock.patch.object(pipeline_module, "measure_words", capture):
        yield kept


class Evaluator:
    def __init__(self, data_dir: Path, *, live: bool = False, detection: Optional[DetectionConfig] = None) -> None:
        self.data_dir = Path(data_dir)
        self.live = live
        self.config = PipelineConfig(detection=detection) if detection is not None else None

    def select(self, splits: Sequence[str], include_baseline: bool, only: Optional[str]) -> List[Dict[str, Any]]:
        manifest = read_json(self.data_dir / "metadata" / "manifest.json", "the manifest")
        chosen = [e for e in manifest if isinstance(e, dict) and e.get("split") in splits
                  and (include_baseline or e.get("category") != "baseline_effective")
                  and (not only or only in str(e.get("recording_id")))]
        return sorted(chosen, key=lambda e: str(e["recording_id"]))

    def pipeline_for(self, entry: Dict[str, Any], cache_dir: Path) -> AnalysisPipeline:
        common = dict(baseline_provider=BaselineProvider(self.data_dir / BASELINE_STATS_SUBDIR), cache=ResultCache(cache_dir),
                      passages=PassageCatalog(self.data_dir / "metadata" / "passages.json"), config=self.config)
        if self.live:
            return AnalysisPipeline(**common)
        rec_id = str(entry["recording_id"])
        path = self.data_dir / "processed" / "alignments" / f"{rec_id}.alignment.json"
        if not path.is_file():
            raise EvaluationError("its stored alignment is missing (run prepare_recordings.py)")
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry.get("sha256_alignment"):
            raise EvaluationError("its stored alignment no longer matches the manifest (run prepare_recordings.py --realign)")
        aligned = AlignedTranscript.model_validate_json(path.read_text(encoding="utf-8"))
        return AnalysisPipeline(transcriber=NoTranscriber(), aligner=ReplayAligner(aligned), **common)

    def evaluate_take(self, entry: Dict[str, Any], confirmed_only: bool = False) -> TakeResult:
        rec_id = str(entry["recording_id"])
        result = TakeResult(rec_id, str(entry.get("category")), str(entry.get("speaker_id")), float(entry.get("duration_s") or 0.0))
        planned = load_annotations(self.data_dir, rec_id)
        if confirmed_only:
            planned = [p for p in planned if p.status == "confirmed"]
        passage_id = str(entry["passage_id"])
        wav = self.data_dir.parent / str(entry["audio_file"])
        if not wav.is_file():
            wav = self.data_dir / "raw" / f"{rec_id}.wav"
        try:
            with captured_word_measurements() as words, tempfile.TemporaryDirectory() as tmp:
                pipeline = self.pipeline_for(entry, Path(tmp))
                text = PassageCatalog(self.data_dir / "metadata" / "passages.json").get_text(passage_id)
                request = AnalyzeRequest(baseline_id=passage_id, passage_id=passage_id, manual_transcript=None if self.live else text)
                analysis = pipeline.analyze(wav.read_bytes(), request)
                profile = pipeline.baseline_provider.get(passage_id, passage_id=passage_id).word_profile
        except (EvaluationError, PipelineError, OSError) as exc:
            result.error = getattr(exc, "detail", None) or str(exc)
            return result
        detected = [Detected(f.type.value, f.start_s, f.end_s, f.severity, evidence_note(f)) for f in analysis.flaws]
        result.composite_score = analysis.scores.composite_score
        result.matches, result.extras = match_flaws(planned, detected)
        relate_extras(planned, result.extras)
        for match in result.matches:
            if match.found is None:
                self.explain_miss(match, result.extras, words[-1] if words else None, profile, analysis.audio.trim_start_s)
        return result

    @property
    def rules(self) -> DetectionConfig:
        return (self.config or PipelineConfig()).detection

    def explain_miss(self, match: Match, extras: Sequence[Detected], observed: Any, profile: Any, trim_start_s: float) -> None:
        """Fill in why a planned flaw was not found: what the registration check said, how big the change really was over the planned words (judged
        with the analysis' own measurements and yardstick), and whether the same kind of flaw turned up somewhere else in the take."""
        plan = match.planned
        check = take_check_note(plan.notes)
        if check:
            match.why.append(f"registration check: {check}")
        if plan.flaw_type in MEASURED_TYPES:
            if not self.rules.use_profile:
                match.why.append("measured by the analysis: the word-by-word comparison is switched off in this run")
            elif profile is None:
                match.why.append("measured by the analysis: this baseline has no word profile (rebuild it with --build-baseline), so only the overall statistics judged the take")
            elif observed is not None:
                reading = measure_stretch(observed, profile, self.rules, plan.start_s - trim_start_s, plan.end_s - trim_start_s)
                match.measured = asdict(reading)
                match.why.append(f"measured by the analysis: {describe_stretch(plan.flaw_type, reading, self.rules)}")
        elsewhere = [d for d in extras if d.flaw_type == plan.flaw_type]
        if elsewhere:
            places = ", ".join(_fmt_interval(d.start_s, d.end_s) for d in elsewhere)
            match.why.append(f"a {plan.flaw_type} was found elsewhere in this take ({places}): the flaw may have been performed in another place than planned")

    def run(self, splits: Sequence[str], include_baseline: bool = False, only: Optional[str] = None, confirmed_only: bool = False) -> List[TakeResult]:
        entries = self.select(splits, include_baseline, only)
        return [self.evaluate_take(e, confirmed_only) for e in entries]


# ---------------------------------------------------------------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------------------------------------------------------------

def parse_sweep(pairs: Sequence[str]) -> List[Tuple[str, str]]:
    """``NAME=v1,v2,v3`` -> [(NAME, "v1"), (NAME, "v2"), ...]; every name must be a setting `--detect` knows.

    PowerShell cuts an unquoted ``NAME=1,2,3`` into ``NAME=1``, ``2`` and ``3``; a piece that is only values (no NAME=) therefore continues the
    setting before it.
    """
    out: List[Tuple[str, str]] = []
    current: Optional[str] = None
    for pair in pairs:
        name, sep, values = pair.partition("=")
        if not sep and current is not None and name.strip() and name.strip().replace(",", "").replace(".", "").replace("-", "").isdigit():
            name, values = current, pair                                    # the rest of a list that was cut at its commas
        elif not sep:
            name = ""
        listed = [v.strip() for v in values.split(",") if v.strip()]
        if name not in DETECT_SETTINGS or not listed:
            raise EvaluationError(f"Unknown or empty sweep '{pair}'. Use NAME=VALUE1,VALUE2,... with NAME one of: {', '.join(sorted(DETECT_SETTINGS))}.")
        current = name
        out += [(name, v) for v in listed]
    return out


@contextlib.contextmanager
def remembered_pitch_and_mfcc() -> Iterator[None]:
    """Compute the pitch and MFCC of each recording once while a sweep replays it many times: the detection rules do not use them."""
    def remembering(extractor: Any) -> Any:
        memo: Dict[Tuple[str, str], Any] = {}

        class Remembered:
            def __init__(self, config: Any) -> None:
                self._inner, self._config = extractor(config), repr(config)

            def extract(self, audio: Any) -> Any:
                key = (self._config, audio.sha256)
                if key not in memo:
                    memo[key] = self._inner.extract(audio)
                return memo[key]

        return Remembered

    with mock.patch.object(pipeline_module, "F0Extractor", remembering(pipeline_module.F0Extractor)), \
            mock.patch.object(pipeline_module, "MFCCExtractor", remembering(pipeline_module.MFCCExtractor)):
        yield


def sweep(data_dir: Path, pairs: Sequence[str], splits: Sequence[str], include_baseline: bool, only: Optional[str], confirmed_only: bool,
          live: bool) -> Tuple[List[Tuple[str, Dict[str, Any]]], int]:
    """Replay the selected takes once with the normal settings and once for each (NAME, value) of `pairs`; return the summaries and the take count."""
    runs: List[Tuple[str, Optional[DetectionConfig]]] = [("normal settings", None)]
    for name, value in parse_sweep(pairs):
        runs.append((f"{name}={value}", detection_config([f"{name}={value}"])))
    rows: List[Tuple[str, Dict[str, Any]]] = []
    count = 0
    with remembered_pitch_and_mfcc():
        for label, detection in runs:
            results = Evaluator(data_dir, live=live, detection=detection).run(splits, include_baseline, only, confirmed_only)
            count = len(results)
            if any(r.error for r in results):
                first = next(r for r in results if r.error)
                raise EvaluationError(f"{first.recording_id} could not be replayed: {first.error}")
            rows.append((label, summarise(results)))
    return rows, count


SHORT_TYPES = {"too_fast": "fast", "too_slow": "slow", "excessive_pause": "pause", "low_energy": "quiet", "high_energy": "loud", "flat_pitch": "flat"}


def render_sweep(rows: Sequence[Tuple[str, Dict[str, Any]]], take_count: int) -> str:
    """One line per setting: planned flaws found (per type and in total), extra flags on flawed takes, clean takes flagged, false alarms a minute."""
    types = sorted({t for _, s in rows for t in s["types"]}, key=lambda t: list(SHORT_TYPES).index(t) if t in SHORT_TYPES else 99)
    head = ["setting".ljust(26)] + [SHORT_TYPES.get(t, t).rjust(6) for t in types] + ["found".rjust(7), "extras".rjust(7), "away".rjust(6), "clean flagged".rjust(14), "false/min".rjust(10)]
    lines = [f"Sweep over {take_count} take(s). Each row changes ONE setting; everything else keeps its normal value.", "", "  ".join(head)]
    for label, s in rows:
        found = sum(v["found"] for v in s["types"].values())
        planned = sum(v["planned"] for v in s["types"].values())
        cells = [label.ljust(26)]
        for t in types:
            v = s["types"].get(t)
            cells.append((f"{v['found']}/{v['planned']}" if v else "-").rjust(6))
        per_minute = s["false_alarms_on_clean_takes"] / s["clean_minutes"] if s["clean_minutes"] else 0.0
        cells += [f"{found}/{planned}".rjust(7), str(s["extras_on_flawed_takes"]).rjust(7), str(s["extras_away_from_planned_flaws"]).rjust(6),
                  f"{s['clean_takes_with_a_flag']}/{s['clean_takes']}".rjust(14), f"{per_minute:.2f}".rjust(10)]
        lines.append("  ".join(cells))
    lines += ["", "found = planned flaws found / planned; extras = other flags on takes that have a planned flaw; away = those extras that are not on or right next to a",
              "planned flaw; clean flagged = clean takes with at least one flag; false/min = flags on clean takes per minute of clean speech.",
              "A good setting finds more and flags less."]
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------------------------------------------------------------

def _fmt_interval(start: float, end: float) -> str:
    return f"{start:.1f}-{end:.1f} s"


def summarise(results: Sequence[TakeResult]) -> Dict[str, Any]:
    by_type: Dict[str, Dict[str, Any]] = {}
    for r in results:
        for m in r.matches:
            t = by_type.setdefault(m.planned.flaw_type, {"planned": 0, "found": 0, "start_errors": [], "end_errors": [], "iou": [], "range_ratio": []})
            t["planned"] += 1
            if m.found is not None:
                t["found"] += 1
                t["start_errors"].append(abs(m.start_error_s))
                t["end_errors"].append(abs(m.end_error_s))
                t["iou"].append(m.iou)
                t["range_ratio"].append(m.range_ratio)

    def mean(values: List[float]) -> Optional[float]:
        return sum(values) / len(values) if values else None

    flawed_extras = sum(len(r.extras) for r in results if r.matches)
    unplanned: Dict[str, int] = {}
    for r in results:
        for d in r.extras:
            unplanned[d.flaw_type] = unplanned.get(d.flaw_type, 0) + 1
    where = [d.where for r in results if r.matches for d in r.extras]
    clean = [r for r in results if not r.matches and not r.error]
    return {
        "types": {t: {"planned": v["planned"], "found": v["found"], "mean_abs_start_error_s": mean(v["start_errors"]),
                      "mean_abs_end_error_s": mean(v["end_errors"]), "mean_iou": mean(v["iou"]), "mean_range_ratio": mean(v["range_ratio"]),
                      "unplanned_flags": unplanned.get(t, 0),
                      "precision": v["found"] / (v["found"] + unplanned.get(t, 0)) if v["found"] + unplanned.get(t, 0) else None,
                      "f1": 2 * v["found"] / (2 * v["found"] + unplanned.get(t, 0) + v["planned"] - v["found"])}
                  for t, v in sorted(by_type.items())},
        "extras_on_flawed_takes": flawed_extras,
        "extras_on_planned_flaws": where.count("on"),
        "extras_next_to_planned_flaws": where.count("next"),
        "extras_away_from_planned_flaws": where.count("away"),
        "clean_takes": len(clean),
        "clean_takes_with_a_flag": sum(1 for r in clean if r.extras),
        "false_alarms_on_clean_takes": sum(len(r.extras) for r in clean),
        "clean_minutes": sum(r.duration_s for r in clean) / 60.0,
        "annotations_proposed": sum(1 for r in results for m in r.matches if m.planned.status != "confirmed"),
        "annotations_total": sum(len(r.matches) for r in results),
        "failed_takes": sum(1 for r in results if r.error),
    }


def render(results: Sequence[TakeResult]) -> str:
    lines: List[str] = []
    for r in results:
        score = "" if r.composite_score is None else f"  score {r.composite_score:g}"
        lines.append(f"{r.recording_id}  ({r.category}){score}")
        if r.error:
            lines.append(f"    could not be replayed: {r.error}")
            continue
        for m in r.matches:
            p = m.planned
            if m.found is None:
                lines.append(f"    MISSED  {p.flaw_type:<16} planned {_fmt_interval(p.start_s, p.end_s)}")
                lines += [f"              - {reason}" for reason in m.why]
                continue
            d = m.found
            lines.append(f"    FOUND   {p.flaw_type:<16} planned {_fmt_interval(p.start_s, p.end_s)}, detected {_fmt_interval(d.start_s, d.end_s)}: "
                         f"start {m.start_error_s:+.1f} s, end {m.end_error_s:+.1f} s, overlap {m.iou:.0%}, detected range {m.range_ratio:.1f}x the plan"
                         + (f" ({d.note})" if d.note else ""))
        for d in r.extras:
            lines.append(f"    EXTRA   {d.flaw_type:<16} detected {_fmt_interval(d.start_s, d.end_s)}, severity {d.severity:.2f}" + (f" ({d.note})" if d.note else "")
                         + (f" - {d.where_note}" if d.where_note else ""))
        if not r.matches and not r.extras:
            lines.append("    nothing flagged")
    s = summarise(results)
    lines += ["", "Summary"]
    for t, v in s["types"].items():
        if v["found"]:
            lines.append(f"  {t:<16} found {v['found']} of {v['planned']}; start off by {v['mean_abs_start_error_s']:.1f} s and end by {v['mean_abs_end_error_s']:.1f} s on average; "
                         f"overlap {v['mean_iou']:.0%}; detected range {v['mean_range_ratio']:.1f}x the plan; {v['unplanned_flags']} flag(s) of this kind nobody planned, "
                         f"precision {v['precision']:.0%}, F1 {v['f1']:.2f}")
        else:
            lines.append(f"  {t:<16} found 0 of {v['planned']}; {v['unplanned_flags']} flag(s) of this kind nobody planned, F1 0.00")
    lines.append(f"  extra detections on flawed takes: {s['extras_on_flawed_takes']}" + (
        f" ({s['extras_on_planned_flaws']} on a planned stretch, {s['extras_next_to_planned_flaws']} right next to one, "
        f"{s['extras_away_from_planned_flaws']} away from every planned flaw)" if s["extras_on_flawed_takes"] else ""))
    if s["clean_takes"]:
        lines.append(f"  clean takes: {s['clean_takes_with_a_flag']} of {s['clean_takes']} had at least one flag; {s['false_alarms_on_clean_takes']} false alarms in "
                     f"{s['clean_minutes']:.1f} minutes")
    if s["annotations_total"]:
        lines.append(f"  {s['annotations_proposed']} of {s['annotations_total']} planned flaws are annotations that no person has confirmed by ear yet")
    if s["failed_takes"]:
        lines.append(f"  {s['failed_takes']} take(s) could not be replayed (see above)")
    rows = listen_first(results)
    if rows:
        lines += ["", "Listen to these first: here the plan and the analysis disagree. Open the take (data\\raw\\<take>.wav) in Audacity and play the stretch."]
        lines += [f"  {take:<36} {_fmt_interval(start, end):<14} {what}" for take, start, end, what in rows]
    return "\n".join(lines)


def listen_first(results: Sequence[TakeResult]) -> List[Tuple[str, float, float, str]]:
    """The places where a person's ear settles the question: a planned flaw nothing was found for, a flag on a clean take, and a flag on a flawed
    take that is away from every planned flaw. (A flag on or next to a planned flaw is usually a side effect of how it was performed.)"""
    rows: List[Tuple[str, float, float, str]] = []
    for r in results:
        if r.error:
            continue
        found = [(m.planned.start_s, m.planned.end_s, f"planned {m.planned.flaw_type}, not found") for m in r.matches if m.found is None]
        found += [(d.start_s, d.end_s, f"{d.flaw_type} flagged on a clean take" if not r.matches else f"{d.flaw_type} flagged away from the planned flaw")
                  for d in r.extras if not r.matches or d.where == "away"]
        rows += [(r.recording_id, start, end, what) for start, end, what in sorted(found)]
    return rows


def write_detected_labels(data_dir: Path, results: Sequence[TakeResult]) -> int:
    """Write what was detected as Audacity label files (data/processed/labels/<take>.detected.txt), next to the word and planned-flaw labels that
    prepare_recordings.py wrote, so the findings can be checked by ear on the take itself. Returns the number of files written (an empty file means nothing was flagged)."""
    from prepare_recordings import audacity_labels            # the one place that knows the label format

    folder = Path(data_dir) / "processed" / "labels"
    folder.mkdir(parents=True, exist_ok=True)
    written = 0
    for r in results:
        if r.error:
            continue
        detections = [("FOUND", m.found) for m in r.matches if m.found is not None] + [("EXTRA", d) for d in r.extras]
        rows = [(d.start_s, d.end_s, f"{kind} {d.flaw_type} severity {d.severity:.2f}" + (f" ({d.note})" if d.note else "") + (f" - {d.where_note}" if d.where_note else ""))
                for kind, d in sorted(detections, key=lambda item: (item[1].start_s, item[1].end_s))]
        (folder / f"{r.recording_id}.detected.txt").write_text(audacity_labels(rows), encoding="utf-8")
        written += 1
    return written


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Replay registered takes through the analysis and compare the findings with the annotations.")
    parser.add_argument("--data-dir", type=Path, default=Path("data"), help="the data/ folder (default: data)")
    parser.add_argument("--splits", nargs="+", default=["dev"], choices=["dev", "test"], help="splits to evaluate (default: dev)")
    parser.add_argument("--allow-test", action="store_true", help="evaluate the sealed test split (only after the settings are frozen)")
    parser.add_argument("--include-baseline", action="store_true", help="also replay the baseline takes (they are part of the baseline)")
    parser.add_argument("--only", default=None, help="only takes whose id contains this text, for example flaw_fast or p001")
    parser.add_argument("--confirmed-only", action="store_true", help="count only annotations a person has confirmed")
    parser.add_argument("--detect", nargs="+", default=[], metavar="NAME=VALUE",
                        help="try other detection settings for this run only, for example z_pause_within=3 min_pause_s=0.8 refine_rate=false")
    parser.add_argument("--sweep", nargs="+", default=[], metavar="NAME=V1,V2,...",
                        help="compare several values of a setting in one table, for example z_run_rate=3,3.5,4 run_min_words=8,10,12")
    parser.add_argument("--labels", action="store_true",
                        help="also write what was detected as Audacity labels (data/processed/labels/<take>.detected.txt) to check the findings by ear")
    parser.add_argument("--live", action="store_true", help="run the real Whisper and WhisperX as on the site (slower, needs the models)")
    parser.add_argument("--json", type=Path, default=None, dest="json_out", help="also write the full results to this file")
    args = parser.parse_args(argv)
    try:
        if "test" in args.splits and not args.allow_test:
            raise EvaluationError("The test split is sealed until the settings are frozen. Add --allow-test only for the final, single run.")
        if args.sweep:
            if args.detect:
                raise EvaluationError("Use either --detect (one run with changed settings) or --sweep (a table), not both.")
            if args.labels:
                raise EvaluationError("--labels belongs to a normal run: a sweep replays the takes with many settings, so there is no single set of findings to label.")
            rows, count = sweep(args.data_dir, args.sweep, args.splits, args.include_baseline, args.only, args.confirmed_only, args.live)
            if not count:
                print("No takes matched. Register recordings first (prepare_recordings.py) or change --splits / --only.", file=sys.stderr)
                return 1
            print(render_sweep(rows, count))
            return 0
        results = Evaluator(args.data_dir, live=args.live, detection=detection_config(args.detect)).run(
            args.splits, args.include_baseline, args.only, args.confirmed_only)
    except EvaluationError as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 1
    if not results:
        print("No takes matched. Register recordings first (prepare_recordings.py) or change --splits / --only.", file=sys.stderr)
        return 1
    if args.detect:
        print(f"Detection settings changed for this run: {' '.join(args.detect)}\n")
    print(render(results))
    if args.labels:
        print(f"\nAudacity labels of the detections: {write_detected_labels(args.data_dir, results)} file(s) written to "
              f"{args.data_dir / 'processed' / 'labels'} (<take>.detected.txt; import them like the other labels).")
    if args.json_out:
        args.json_out.write_text(json.dumps({"summary": summarise(results), "takes": [asdict(r) for r in results]}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 1 if any(r.error for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
