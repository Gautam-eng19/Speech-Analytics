"""Recording plan generator (TASK-122, docs/methodology/recording-protocol.md sections 5 and 7).

Turns "who records which passage" into the exact list of takes to record, in the order to record them, with the instruction for each
flawed take and a ready-to-use on-screen prompter per speaker. Everything is deterministic: the same arguments (and seed) always give
byte-identical files, so every team member who runs it gets the same plan.

    python scripts/dataset/make_plan.py --dev 2 --test 2 --tier recommended --out data/plan/v1

Writes into --out:
    plan.csv                 one row per take (the plan sheet, protocol Appendix A)
    prompter_<speaker>.html  open in a browser on the recording computer: shows the passage, the instruction and the file name
    session_log.csv          empty session log (protocol 7.6)

Tiers are nested: every take of a smaller tier is also in the larger one, with the same take id, so a pilot is never wasted.
To continue after a pilot, point --done at the folder with the files already recorded: their takes are marked accepted in the new
plan and the prompter starts at the first take that is still open.
    pilot        1 passage, the first dev speaker only: 3 baseline + 1 clean + 5 flawed (strong)            =  9 takes
    minimum      1 passage; dev 3 baseline + 2 clean + 5 flawed (strong); test 3 clean + 5 flawed (strong)
    recommended  every passage; as minimum, plus the moderate version of each flawed take and a clean take
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import passage_text as pt

TIERS = ("pilot", "minimum", "recommended")
FLAW_TYPES = ("too_fast", "too_slow", "excessive_pause", "low_energy", "high_energy")
#: Take-id part of each flaw type (protocol 7.3).
KIND = {"too_fast": "flaw_fast", "too_slow": "flaw_slow", "excessive_pause": "flaw_pause", "low_energy": "flaw_quiet", "high_energy": "flaw_loud"}
#: take number -> (intensity, severity_label of the annotation schema). Take 01 is the moderate one, take 02 the strong one.
INTENSITY = {1: ("moderate", "medium"), 2: ("strong", "high")}

#: Sentence in which each flawed take is performed (protocol 5.5). For excessive_pause take 2 it is the sentence AFTER which the
#: silence falls. Replaced by the next suitable sentence when the passage's sentence is too short for the flaw.
DEFAULT_SENTENCE = {
    ("too_fast", 1): 3, ("too_fast", 2): 5,
    ("too_slow", 1): 4, ("too_slow", 2): 6,
    ("excessive_pause", 1): 4, ("excessive_pause", 2): 5,
    ("low_energy", 1): 5, ("low_energy", 2): 3,
    ("high_energy", 1): 4, ("high_energy", 2): 6,
}
CANDIDATE_SENTENCES = (3, 4, 5, 6)  # flaws never go into sentences 1, 2, 7 or later, so normal speech surrounds them
#: Shortest sentence (in words) that can carry each flaw: speed is measured in 8 s windows, energy needs a few seconds, a pause inside a
#: phrase needs a position with three words on each side.
MIN_WORDS = {"too_fast": 14, "too_slow": 14, "low_energy": 10, "high_energy": 10, "excessive_pause": 12}
MIN_WORDS_EACH_SIDE_OF_PAUSE = 3
FUNCTION_WORDS = frozenset(
    "a an the to of in on at for or and but by with as so that is are was were be i we it you he she they my our your his her its their "
    "this these those if than then when while from into about how".split()
)

#: target duration of a speed-flaw stretch as a multiple of its normal duration (protocol 5.4)
SPEED_FACTOR = {("too_fast", 1): 0.75, ("too_fast", 2): 0.55, ("too_slow", 1): 1.35, ("too_slow", 2): 1.8}
SPEED_LABEL = {("too_fast", 1): "about 1.3 times faster", ("too_fast", 2): "about 1.8 times faster",
               ("too_slow", 1): "about 0.75 times the speed (slower)", ("too_slow", 2): "about 0.55 times the speed (much slower)"}
LEVEL_DB = {1: 8, 2: 14}
PAUSE_SECONDS = {1: (1.5, 2.0), 2: (3.0, 4.0)}

CSV_COLUMNS = [
    "order", "take_id", "speaker_id", "split", "passage_id", "category", "flaw_type", "intensity", "severity_label", "stretch",
    "stretch_first_word", "stretch_last_word", "pause_after_word", "instruction", "normal_duration_s_est", "target_duration_s_est",
    "status", "attempts", "accepted_by", "notes", "recorded_at",
]
SESSION_LOG_COLUMNS = ["date", "speaker_id", "microphone", "room", "input_volume_setting", "noise_floor_db", "normal_peak_db", "problems"]

CHECKLIST = [
    "Close the door and the windows, put phones on silent, switch off fans and air conditioning, close chat and meeting programs.",
    "Put the microphone beside the corner of your mouth, 3 to 4 cm away, not in the stream of your breath. Mark the position with tape.",
    "In the computer's sound settings switch OFF audio enhancements, noise suppression, automatic gain and voice isolation, and keep mic boost at its minimum.",
    "In Audacity: Recording channels = 1 (Mono); Project rate = 48000 Hz (the same for every recording); default sample format = 16-bit; software playthrough OFF.",
    "Noise check: record 10 seconds of silence. The meter should show about -60 dB or lower. -50 dB or higher: move somewhere quieter or lower the input volume.",
    "Normal level: read one sentence in your normal voice. The loudest syllables should reach about -16 dB (between -18 and -14).",
    "Loud and quiet tests: read one sentence in a strong loud voice (peaks must stay at or below -2 dB, never red) and in a strong quiet voice (at least 25 dB above the silence).",
    "Write down the input volume setting, delete the test recordings, and do not touch the settings again during the session.",
    "Read the whole passage aloud once without recording (warm-up).",
]


class PlanError(ValueError):
    """The plan cannot be made from the given inputs. The message says why in plain words."""


@dataclass(frozen=True)
class Passage:
    passage_id: str
    title: str
    sentences: Tuple[Tuple[str, ...], ...]  # words of each sentence

    @property
    def sentence_starts(self) -> List[int]:
        """Global 1-based index of the first word of each sentence."""
        starts, at = [], 1
        for words in self.sentences:
            starts.append(at)
            at += len(words)
        return starts

    @property
    def all_words(self) -> List[str]:
        return [w for words in self.sentences for w in words]


def load_passages(path: Path, wanted: Optional[Sequence[str]] = None) -> List[Passage]:
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PlanError(f"Cannot read the passages file {path}: {exc}") from exc
    if not isinstance(entries, list) or not entries:
        raise PlanError(f"{path} must contain a list of passages.")
    passages: List[Passage] = []
    problems: List[str] = []
    for entry in entries:
        errors, _warnings = pt.validate_passage(entry)
        problems += errors
        if not errors:
            passages.append(Passage(entry["passage_id"], str(entry.get("title") or entry["passage_id"]),
                                    tuple(tuple(s) for s in pt.passage_words(entry["text"]))))
    if problems:
        raise PlanError("The passages cannot be used for recording:\n  " + "\n  ".join(problems))
    ids = [p.passage_id for p in passages]
    if len(set(ids)) != len(ids):
        raise PlanError("Two passages have the same passage_id.")
    if wanted:
        missing = [w for w in wanted if w not in ids]
        if missing:
            raise PlanError(f"Unknown passage id(s): {', '.join(missing)}. Available: {', '.join(ids)}.")
        passages = [p for w in wanted for p in passages if p.passage_id == w]
    return passages


def phrase_pause_position(words: Sequence[str]) -> Optional[int]:
    """1-based index of the word AFTER which a silence 'inside a phrase' is placed, or None if the sentence has no such place.

    The silence goes where a speaker would not normally stop: after a content word that carries no punctuation, with at least three
    words on each side, as close to the middle of the sentence as possible (ties: the earlier word).
    """
    n = len(words)
    best: Optional[int] = None
    for i in range(MIN_WORDS_EACH_SIDE_OF_PAUSE, n - MIN_WORDS_EACH_SIDE_OF_PAUSE + 1):
        word = words[i - 1]
        if re.search(r"[,.;:?!]$", word) or word.strip(",.;:?!").lower() in FUNCTION_WORDS:
            continue
        if best is None or abs(i - n / 2) < abs(best - n / 2):
            best = i
    return best


def _valid_sentence(passage: Passage, flaw: str, take_no: int, sentence_no: int) -> bool:
    if sentence_no > len(passage.sentences):
        return False
    words = passage.sentences[sentence_no - 1]
    if flaw == "excessive_pause" and take_no == 2:
        return sentence_no in CANDIDATE_SENTENCES[:-1] and sentence_no + 1 <= len(passage.sentences)
    if len(words) < MIN_WORDS[flaw]:
        return False
    if flaw == "excessive_pause" and take_no == 1:
        return phrase_pause_position(words) is not None
    return True


def choose_sentences(passage: Passage, flaw: str, usage: Optional[Dict[int, int]] = None) -> Dict[int, int]:
    """{take number: sentence number} for one flaw type: the default table, adjusted when a sentence is too short; the two takes of a
    flaw type never use the same sentence. `usage` counts how often each sentence already carries a flaw; when a default has to be
    replaced, the least used suitable sentence is taken so the flaws are spread over sentences 3 to 6."""
    usage = usage if usage is not None else {}
    chosen: Dict[int, int] = {}
    for take_no in (1, 2):
        default = DEFAULT_SENTENCE[(flaw, take_no)]
        valid = [s for s in CANDIDATE_SENTENCES if s not in chosen.values() and _valid_sentence(passage, flaw, take_no, s)]
        if not valid:
            raise PlanError(f"Passage {passage.passage_id} has no sentence among 3 to 6 that can carry '{flaw}' "
                            f"(needs {MIN_WORDS[flaw]} or more words). Use a passage with longer sentences.")
        if default in valid:
            pick = default
        else:
            start = CANDIDATE_SENTENCES.index(default)
            cycle = CANDIDATE_SENTENCES[start:] + CANDIDATE_SENTENCES[:start]
            pick = min(valid, key=lambda s: (usage.get(s, 0), cycle.index(s)))
        chosen[take_no] = pick
    for sentence_no in chosen.values():
        usage[sentence_no] = usage.get(sentence_no, 0) + 1
    return chosen


def _quote(word: str) -> str:
    """The word in plain ASCII quotes: plan.csv is opened in spreadsheet programs that garble typographic quotes."""
    return "'" + word.strip(",.;:?!") + "'"


def build_flawed(passage: Passage, speaker_id: str, split: str, flaw: str, take_no: int, sentence_no: int, order: int) -> Dict[str, Any]:
    intensity, severity = INTENSITY[take_no]
    starts = passage.sentence_starts
    first = starts[sentence_no - 1]
    words = passage.sentences[sentence_no - 1]
    last = first + len(words) - 1
    row: Dict[str, Any] = {
        "order": order, "take_id": f"rec_{passage.passage_id}_{speaker_id}_{KIND[flaw]}_{take_no:02d}", "speaker_id": speaker_id, "split": split,
        "passage_id": passage.passage_id, "category": "flawed_human_controlled", "flaw_type": flaw, "intensity": intensity,
        "severity_label": severity, "stretch": f"S{sentence_no}", "stretch_first_word": first, "stretch_last_word": last,
        "pause_after_word": "",
    }
    normal = pt.estimated_duration_s(len(words))
    if flaw in ("too_fast", "too_slow"):
        factor = SPEED_FACTOR[(flaw, take_no)]
        row["normal_duration_s_est"] = round(normal, 1)
        row["target_duration_s_est"] = round(normal * factor, 1)
        row["instruction"] = (
            f"Read sentence {sentence_no} (the highlighted words) {SPEED_LABEL[(flaw, take_no)]} than your normal pace; it should take about "
            f"{row['target_duration_s_est']} s instead of about {row['normal_duration_s_est']} s. Say every word. "
            + ("Do not get louder. " if flaw == "too_fast" else "Stretch the words but do NOT add silent pauses. ")
            + "Read everything outside the highlighted sentence normally."
        )
    elif flaw in ("low_energy", "high_energy"):
        db = LEVEL_DB[take_no]
        row["normal_duration_s_est"] = round(normal, 1)
        row["target_duration_s_est"] = ""
        if flaw == "low_energy":
            row["instruction"] = (f"Read sentence {sentence_no} (highlighted) in a clearly softer voice, about {db} dB lower on the meter than your normal reading. "
                                  "Keep the same distance from the microphone. Do not whisper and do not lean away. Everything else is normal.")
        else:
            row["instruction"] = (f"Read sentence {sentence_no} (highlighted) louder, projecting, about {db} dB higher on the meter than your normal reading. "
                                  "Keep the same distance from the microphone and make sure the meter never goes red (no clipping). Everything else is normal.")
    else:  # excessive_pause
        low, high = PAUSE_SECONDS[take_no]
        row["normal_duration_s_est"] = ""
        row["target_duration_s_est"] = f"{low:g}-{high:g}"
        if take_no == 1:
            position = phrase_pause_position(words)
            after = first + position - 1
            row["pause_after_word"] = after
            row["stretch"] = f"S{sentence_no}, silence after {_quote(words[position - 1])}"
            row["stretch_first_word"] = after
            row["stretch_last_word"] = after + 1
            row["instruction"] = (f"In sentence {sentence_no}, stop right after the word {_quote(words[position - 1])} and stay completely SILENT for {low:g} to {high:g} seconds "
                                  "(count in your head), then continue. No 'um', no loud breathing. Everything else is normal.")
        else:
            nxt = starts[sentence_no]
            row["pause_after_word"] = last
            row["stretch"] = f"between S{sentence_no} and S{sentence_no + 1}"
            row["stretch_first_word"] = last
            row["stretch_last_word"] = nxt
            row["instruction"] = (f"After the last word of sentence {sentence_no} ({_quote(words[-1])}) stay completely SILENT for {low:g} to {high:g} seconds "
                                  f"(count in your head), then start sentence {sentence_no + 1}. No 'um', no loud breathing. Everything else is normal.")
    return row


def build_plain(passage: Passage, speaker_id: str, split: str, category: str, kind: str, number: int, order: int) -> Dict[str, Any]:
    if category == "baseline_effective":
        instruction = ("Read the whole passage clearly at a natural, steady pace (about 130 to 160 words a minute), with short natural pauses at commas and "
                       "sentence ends and natural intonation. This take defines what good delivery looks like.")
    else:
        instruction = ("Read the whole passage normally again. Do not try to copy your earlier takes and do not try to be perfect: natural variation is the point.")
    return {
        "order": order, "take_id": f"rec_{passage.passage_id}_{speaker_id}_{kind}_{number:02d}", "speaker_id": speaker_id, "split": split,
        "passage_id": passage.passage_id, "category": category, "flaw_type": "", "intensity": "", "severity_label": "", "stretch": "",
        "stretch_first_word": "", "stretch_last_word": "", "pause_after_word": "", "instruction": instruction,
        "normal_duration_s_est": "", "target_duration_s_est": "",
    }


def block_for(split: str, tier: str) -> Tuple[int, int, Tuple[int, ...]]:
    """(baseline takes, clean takes, flawed take numbers) one speaker records per passage."""
    if split == "dev":
        return {"pilot": (3, 1, (2,)), "minimum": (3, 2, (2,)), "recommended": (3, 2, (1, 2))}[tier]
    return {"pilot": (0, 0, ()), "minimum": (0, 3, (2,)), "recommended": (0, 3, (1, 2))}[tier]


def shuffle_without_repeats(items: List[Dict[str, Any]], rng: random.Random) -> List[Dict[str, Any]]:
    """Order the flawed takes randomly (seeded) so that the same flaw type is never recorded twice in a row (protocol 5.5) whenever that
    is possible: always continue with a type different from the last one, preferring the type with the most takes left."""
    pools: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        pools.setdefault(item["flaw_type"], []).append(item)
    for pool in pools.values():
        rng.shuffle(pool)
    ordered: List[Dict[str, Any]] = []
    last = None
    while any(pools.values()):
        options = [t for t, pool in pools.items() if pool and t != last] or [t for t, pool in pools.items() if pool]
        most = max(len(pools[t]) for t in options)
        pick = rng.choice(sorted(t for t in options if len(pools[t]) == most))
        ordered.append(pools[pick].pop())
        last = pick
    return ordered


def make_plan(passages: Sequence[Passage], dev: int, test: int, tier: str, seed: int) -> List[Dict[str, Any]]:
    if tier not in TIERS:
        raise PlanError(f"Unknown tier '{tier}'. Choose one of: {', '.join(TIERS)}.")
    if dev < 1:
        raise PlanError("At least one dev speaker is needed: the baseline is built from dev speakers' baseline takes.")
    if test < 0 or dev + test > 20:
        raise PlanError("The number of speakers must be between 1 and 20.")
    use = list(passages) if tier == "recommended" else list(passages[:1])
    speakers = [("dev", f"spk_dev_{i:02d}") for i in range(1, dev + 1)] + [("test", f"spk_test_{i:02d}") for i in range(1, test + 1)]
    if tier == "pilot":
        speakers = speakers[:1]
    rows: List[Dict[str, Any]] = []
    for split, speaker in speakers:
        order = 0
        for passage in use:
            n_base, n_clean, flaw_numbers = block_for(split, tier)
            rng = random.Random(f"{seed}:{speaker}:{passage.passage_id}")
            block: List[Dict[str, Any]] = []
            for n in range(1, n_base + 1):
                block.append(build_plain(passage, speaker, split, "baseline_effective", "base", n, 0))
            for n in range(1, n_clean + 1):
                block.append(build_plain(passage, speaker, split, "clean_control", "clean", n, 0))
            flawed = []
            usage: Dict[int, int] = {}
            for flaw in FLAW_TYPES:
                sentences = choose_sentences(passage, flaw, usage)
                for take_no in flaw_numbers:
                    flawed.append(build_flawed(passage, speaker, split, flaw, take_no, sentences[take_no], 0))
            block += shuffle_without_repeats(flawed, rng)
            for row in block:
                order += 1
                row["order"] = order
                row.update({"status": "todo", "attempts": 0, "accepted_by": "", "notes": "", "recorded_at": ""})
                rows.append(row)
    return rows


# ---------------------------------------------------------------------------------------------------------------------------------
# Output files
# ---------------------------------------------------------------------------------------------------------------------------------

def recorded_take_ids(paths: Sequence[Path]) -> List[str]:
    """Take ids of the WAV files in the given files and folders (file name without extension), sorted."""
    found = set()
    for path in paths:
        files = path.iterdir() if path.is_dir() else [path]
        found.update(f.stem for f in files if f.is_file() and f.suffix.lower() == ".wav")
    return sorted(found)


def mark_done(rows: Sequence[Dict[str, Any]], recorded: Sequence[str]) -> Tuple[int, List[str]]:
    """Mark the planned takes that already have a recording as accepted. Returns (how many were marked, recordings that match no take)."""
    planned = {r["take_id"]: r for r in rows}
    for take_id in recorded:
        if take_id in planned:
            planned[take_id]["status"] = "accepted"
    return sum(1 for t in recorded if t in planned), [t for t in recorded if t not in planned]


def write_csv(path: Path, columns: Sequence[str], rows: Sequence[Dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})


def prompter_html(speaker: str, rows: Sequence[Dict[str, Any]], passages: Sequence[Passage], tier: str) -> str:
    template = (Path(__file__).parent / "templates" / "prompter.html").read_text(encoding="utf-8")
    used = [p for p in passages if any(r["passage_id"] == p.passage_id for r in rows)]
    data = {
        "speaker_id": speaker, "split": rows[0]["split"], "tier": tier, "checklist": CHECKLIST,
        "passages": [{"passage_id": p.passage_id, "title": p.title, "sentences": [list(s) for s in p.sentences]} for p in used],
        "takes": [{k: r[k] for k in ("order", "take_id", "passage_id", "category", "flaw_type", "intensity", "stretch", "stretch_first_word",
                                      "stretch_last_word", "pause_after_word", "instruction", "target_duration_s_est", "status")} for r in rows],
    }
    blob = json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c")
    return template.replace("__SPEAKER__", speaker).replace("__DATA__", blob)


def write_plan(out: Path, rows: Sequence[Dict[str, Any]], passages: Sequence[Passage], tier: str, overwrite: bool) -> List[Path]:
    out.mkdir(parents=True, exist_ok=True)
    target = out / "plan.csv"
    if target.exists() and not overwrite:
        raise PlanError(f"{target} already exists. It may hold your progress; choose another --out folder or add --overwrite.")
    written = [target]
    write_csv(target, CSV_COLUMNS, rows)
    log = out / "session_log.csv"
    if overwrite or not log.exists():
        write_csv(log, SESSION_LOG_COLUMNS, [])
        written.append(log)
    speakers = sorted({r["speaker_id"] for r in rows}, key=lambda s: ([r["order"] for r in rows if r["speaker_id"] == s][0], s))
    for speaker in speakers:
        mine = [r for r in rows if r["speaker_id"] == speaker]
        page = out / f"prompter_{speaker}.html"
        page.write_text(prompter_html(speaker, mine, passages, tier), encoding="utf-8")
        written.append(page)
    return written


def summary(rows: Sequence[Dict[str, Any]]) -> str:
    lines = []
    speakers = sorted({r["speaker_id"] for r in rows})
    for s in speakers:
        mine = [r for r in rows if r["speaker_id"] == s]
        by: Dict[str, int] = {}
        for r in mine:
            by[r["category"]] = by.get(r["category"], 0) + 1
        lines.append(f"  {s:<13} {len(mine):>3} takes  (baseline {by.get('baseline_effective', 0)}, clean {by.get('clean_control', 0)}, flawed {by.get('flawed_human_controlled', 0)})")
    lines.append(f"  total         {len(rows):>3} takes")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Make the recording plan sheet and on-screen prompters.")
    parser.add_argument("--dev", type=int, required=True, help="number of dev speakers (they record the baseline)")
    parser.add_argument("--test", type=int, required=True, help="number of test speakers (held-out voices)")
    parser.add_argument("--tier", choices=TIERS, default="recommended")
    parser.add_argument("--passages", type=Path, default=Path("data/plan/passages_v1.json"))
    parser.add_argument("--passage-ids", nargs="+", default=None, help="use only these passages, in this order")
    parser.add_argument("--seed", type=int, default=20261011, help="changes the shuffled order of the flawed takes")
    parser.add_argument("--out", type=Path, default=Path("data/plan/v1"))
    parser.add_argument("--overwrite", action="store_true", help="replace an existing plan.csv (it may contain recording progress)")
    parser.add_argument("--done", nargs="+", type=Path, default=None, metavar="PATH",
                        help="folder(s) or WAV file(s) already recorded: those takes are marked accepted (continue after the pilot)")
    args = parser.parse_args(argv)
    try:
        passages = load_passages(args.passages, args.passage_ids)
        rows = make_plan(passages, args.dev, args.test, args.tier, args.seed)
        marked, unmatched = (mark_done(rows, recorded_take_ids(args.done)) if args.done else (0, []))
        written = write_plan(args.out, rows, passages, args.tier, args.overwrite)
    except PlanError as exc:
        print(f"Cannot make the plan: {exc}", file=sys.stderr)
        return 2
    if args.test == 0 and args.tier != "pilot":
        print("Note: no test speakers. Nothing can then be reported as measured on unseen voices.")
    print(f"Recording plan ({args.tier}):\n{summary(rows)}")
    if args.done:
        print(f"{marked} take(s) already recorded are marked accepted.")
        if unmatched:
            print(f"Note: {len(unmatched)} recording(s) match no take of this plan and were ignored: {', '.join(unmatched[:5])}{' ...' if len(unmatched) > 5 else ''}")
    print("Wrote:")
    for path in written:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
