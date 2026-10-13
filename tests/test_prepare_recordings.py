"""Tests for scripts/dataset/prepare_recordings.py (TASK-126).

Synthetic takes with known word times (tests/dataset_takes.py) are registered with a stand-in aligner that finds the word bursts in the
audio it receives. That exercises the real preprocessing (decode, resample, trim, loudness scaling), the real quality check, the real
plan sheet, the real dataset validator and the real baseline builder; only the WhisperX model is replaced, because it cannot be
downloaded in CI. The real model is run by the team on their own machine (docs/methodology/dataset-guide.md).

Covers: what is written for every kind of take, the manifest/speaker/passage entries, time bases (processed vs original file), flaw
annotations placed on the true word times for every flaw type, the "was the flaw performed" verdicts, idempotent re-runs, re-recorded
takes, annotations a person confirmed, isolated failures (bad name, damaged file, clipping, unknown passage, wrong split, passage text
mismatch, wrong word count, untimed words, aligner errors), the baseline build, the CLI, determinism, and the committed plan with the
committed passages end to end.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "dataset"))
sys.path.insert(0, str(Path(__file__).parent))

import dataset_takes as dt  # noqa: E402
import make_plan as mp  # noqa: E402
import passage_text as pt  # noqa: E402
import prepare_recordings as pr  # noqa: E402
import take_checks as tc  # noqa: E402
from app.core.baseline import BaselineProvider  # noqa: E402
from app.services.alignment import AlignmentModelError  # noqa: E402

REPO = Path(__file__).parent.parent
WORDS = [w for sentence in pt.passage_words(dt.PASSAGE_TEXT) for w in sentence]     # 45 words, six sentences
S2, S3, S4, S5 = (6, 12), (13, 22), (23, 30), (31, 38)                              # word numbers of sentences 2 to 5 (1-based)
SPEAKER = "spk_dev_01"


def take_id(kind: str, number: int = 1, speaker: str = SPEAKER, passage: str = "p001") -> str:
    return f"rec_{passage}_{speaker}_{kind}_{number:02d}"


class World:
    """A temporary project: an incoming folder of takes, a passages file, a plan sheet and an empty data directory."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.data = root / "data"
        self.incoming = root / "incoming"
        self.passages = root / "passages.json"
        self.plan = root / "plan.csv"
        self.layouts: Dict[str, dt.Layout] = {}
        self.plan_rows: List[Dict[str, str]] = []
        self.reset_data()

    def reset_data(self) -> None:
        shutil.rmtree(self.data, ignore_errors=True)
        (self.data / "metadata").mkdir(parents=True)
        for name in ("passages", "speakers", "manifest"):
            (self.data / "metadata" / f"{name}.json").write_text("[]\n", encoding="utf-8")
        self.passages.write_text(json.dumps([dt.passage_entry()]), encoding="utf-8")

    def add(self, name: str, layout: dt.Layout, seed: int = 0) -> Path:
        self.layouts[name] = layout
        return dt.write_take(self.incoming, name, layout, seed)

    def write_plan(self) -> None:
        dt.write_plan(self.plan, self.plan_rows)

    def prepare(self, aligner: Optional[dt.BurstAligner] = None, build_baseline: bool = False, inputs: Optional[List[Path]] = None, **kw):
        aligner = aligner or dt.BurstAligner()
        kw.setdefault("today", "2026-10-13")
        preparer = pr.Preparer(self.data, self.passages, self.plan, aligner=aligner, out=lambda _line: None, **kw)
        return preparer.run(inputs or [self.incoming], build_baseline=build_baseline), aligner

    def files(self) -> Dict[str, str]:
        return {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(self.data.rglob("*")) if p.is_file()}

    def manifest(self) -> Dict[str, dict]:
        return {e["recording_id"]: e for e in json.loads((self.data / "metadata" / "manifest.json").read_text(encoding="utf-8"))}

    def annotation(self, name: str) -> dict:
        return json.loads((self.data / "annotations" / f"{name}.flaws.json").read_text(encoding="utf-8"))


def build_world(root: Path) -> World:
    world = World(root)
    for n in (1, 2, 3):
        world.add(take_id("base", n), dt.normal_layout(WORDS), seed=n)
    world.add(take_id("clean"), dt.normal_layout(WORDS), seed=4)
    world.add(take_id("flaw_fast"), dt.speed_stretch(dt.normal_layout(WORDS), *S3, 0.55), seed=5)
    world.add(take_id("flaw_slow"), dt.speed_stretch(dt.normal_layout(WORDS), *S4, 1.6), seed=6)
    world.add(take_id("flaw_loud"), dt.level_stretch(dt.normal_layout(WORDS), *S2, 8.0), seed=7)
    world.add(take_id("flaw_quiet"), dt.level_stretch(dt.normal_layout(WORDS), *S5, -8.0), seed=8)
    world.add(take_id("flaw_pause"), dt.pause_after(dt.normal_layout(WORDS), S3[1], 1.8), seed=9)
    world.plan_rows = [
        dt.plan_row(take_id("flaw_fast"), "too_fast", *S3, stretch="S3"),
        dt.plan_row(take_id("flaw_slow"), "too_slow", *S4, stretch="S4"),
        dt.plan_row(take_id("flaw_loud"), "high_energy", *S2, stretch="S2"),
        dt.plan_row(take_id("flaw_quiet"), "low_energy", *S5, stretch="S5", severity="high"),
        dt.plan_row(take_id("flaw_pause"), "excessive_pause", S3[1], S3[1] + 1, pause_after=S3[1], stretch="between S3 and S4"),
    ]
    world.write_plan()
    return world


@pytest.fixture(scope="module")
def source(tmp_path_factory) -> World:
    """The synthetic takes, written once; every test works on its own copy."""
    return build_world(tmp_path_factory.mktemp("source"))


@pytest.fixture()
def world(source: World, tmp_path: Path) -> World:
    copy = World(tmp_path)
    shutil.copytree(source.incoming, copy.incoming)
    shutil.copyfile(source.plan, copy.plan)
    copy.layouts = dict(source.layouts)
    copy.plan_rows = [dict(r) for r in source.plan_rows]
    return copy


def by_id(report: pr.Report) -> Dict[str, pr.Take]:
    return {t.take_id: t for t in report.takes}


def messages(take: pr.Take, level: Optional[str] = None) -> List[str]:
    return [f.message for f in take.findings if level is None or f.level == level]


# ---------------------------------------------------------------------------------------------------------------------------------
# What is written
# ---------------------------------------------------------------------------------------------------------------------------------

def test_every_kind_of_take_is_registered_and_the_dataset_validates(world: World):
    report, _ = world.prepare()
    assert [t.status for t in report.takes] == ["registered"] * 9
    assert report.dataset_ok is True and report.dataset_errors == []
    manifest = world.manifest()
    assert sorted(manifest) == sorted(world.layouts)
    stored = json.loads((world.data / "metadata" / "manifest.json").read_text(encoding="utf-8"))
    assert [e["recording_id"] for e in stored] == sorted(manifest)                  # stable order, so version-control diffs stay small
    kinds = {"base": "baseline_effective", "clean": "clean_control", "flaw": "flawed_human_controlled"}
    for rec_id, entry in manifest.items():
        kind = rec_id.split("_")[5]
        assert entry["category"] == kinds[kind]
        assert (entry["split"], entry["passage_id"], entry["speaker_id"]) == ("dev", "p001", SPEAKER)
        assert entry["audio_file"] == f"data/raw/{rec_id}.wav" and entry["alignment_file"] == f"data/processed/alignments/{rec_id}.alignment.json"
        raw, aligned = world.data / "raw" / f"{rec_id}.wav", world.data / "processed" / "alignments" / f"{rec_id}.alignment.json"
        assert hashlib.sha256(raw.read_bytes()).hexdigest() == entry["sha256_audio"]
        assert hashlib.sha256(aligned.read_bytes()).hexdigest() == entry["sha256_alignment"]
        assert raw.read_bytes() == (world.incoming / f"{rec_id}.wav").read_bytes()
        assert entry["duration_s"] == pytest.approx(sum(world.layouts[rec_id].durations) + sum(world.layouts[rec_id].gaps) + 1.6, abs=0.01)
        assert (entry["sample_rate_hz"], entry["channels"], entry["is_synthetic"], entry["synthesis_technique"]) == (48000, 1, False, None)
        assert (entry["dataset_version"], entry["created_at"], entry["microphone"], entry["recording_conditions"]) == (
            "1.0.0", "2026-10-13", "headset_usb", "quiet_room")
        assert (world.data / "processed" / "labels" / f"{rec_id}.words.txt").is_file()
        flawed = kind == "flaw"
        assert (entry["annotation_file"] == f"data/annotations/{rec_id}.flaws.json") is flawed
        assert (world.data / "annotations" / f"{rec_id}.flaws.json").is_file() is flawed
        assert (world.data / "processed" / "labels" / f"{rec_id}.flaw.txt").is_file() is flawed


def test_speakers_and_passages_are_added_once_with_the_reference_text(world: World):
    world.prepare()
    speakers = json.loads((world.data / "metadata" / "speakers.json").read_text(encoding="utf-8"))
    assert [(s["speaker_id"], s["split"], s["gender"]) for s in speakers] == [(SPEAKER, "dev", "unspecified")]
    passages = json.loads((world.data / "metadata" / "passages.json").read_text(encoding="utf-8"))
    assert [(p["passage_id"], p["text"]) for p in passages] == [("p001", dt.PASSAGE_TEXT)]
    world.prepare()
    assert len(json.loads((world.data / "metadata" / "speakers.json").read_text(encoding="utf-8"))) == 1


def test_existing_speaker_entries_are_kept_as_they_are(world: World):
    existing = [{"speaker_id": SPEAKER, "split": "dev", "gender": "female", "native_language": "en", "notes": "kept"}]
    (world.data / "metadata" / "speakers.json").write_text(json.dumps(existing), encoding="utf-8")
    world.prepare()
    assert json.loads((world.data / "metadata" / "speakers.json").read_text(encoding="utf-8")) == existing


def test_the_aligner_gets_the_passage_text_with_single_spaces_as_the_transcript(world: World):
    entry = dt.passage_entry(text=dt.PASSAGE_TEXT.replace(" ", "  ", 3))
    world.passages.write_text(json.dumps([entry]), encoding="utf-8")
    (world.data / "metadata" / "passages.json").write_text(json.dumps([entry]), encoding="utf-8")
    _, aligner = world.prepare()
    assert set(aligner.texts) == {dt.PASSAGE_TEXT}


def test_alignment_is_stored_in_processed_time_to_the_millisecond_and_labels_in_file_time(world: World):
    world.prepare()
    name = take_id("base", 1)
    stored = json.loads((world.data / "processed" / "alignments" / f"{name}.alignment.json").read_text(encoding="utf-8"))
    truth = world.layouts[name].times()
    assert len(stored["words"]) == len(WORDS) == 45
    assert stored["words"][0]["start_s"] < 0.3                          # processed time: the lead-in is trimmed away
    for word in stored["words"]:
        for key in ("start_s", "end_s"):
            assert round(word[key], 3) == word[key]
    label_rows = [line.split("\t") for line in (world.data / "processed" / "labels" / f"{name}.words.txt").read_text(encoding="utf-8").splitlines()]
    assert len(label_rows) == 45 and label_rows[0][2] == "Good" and label_rows[-1][2] == "talk."
    for (start, end, word), (true_start, true_end) in zip(label_rows, truth):
        assert float(start) == pytest.approx(true_start, abs=0.04) and float(end) == pytest.approx(true_end, abs=0.04)
        assert start == f"{float(start):.3f}"


def test_labels_are_audacity_label_tracks():
    text = pr.audacity_labels([(1.5, 2.25, "word"), (3.0, 3.0004, "next")])
    assert text == "1.500\t2.250\tword\n3.000\t3.000\tnext\n"
    assert pr.audacity_labels([]) == ""


# ---------------------------------------------------------------------------------------------------------------------------------
# Flaw annotations
# ---------------------------------------------------------------------------------------------------------------------------------

def stretch_truth(world: World, name: str, first: int, last: int) -> Tuple[float, float]:
    times = world.layouts[name].times()
    return times[first - 1][0], times[last - 1][1]


@pytest.mark.parametrize("kind,flaw,words", [
    ("flaw_fast", "too_fast", S3), ("flaw_slow", "too_slow", S4), ("flaw_loud", "high_energy", S2), ("flaw_quiet", "low_energy", S5),
])
def test_the_planned_stretch_is_placed_on_the_true_word_times_of_the_original_file(world: World, kind, flaw, words):
    world.prepare()
    name = take_id(kind)
    start, end = stretch_truth(world, name, *words)
    annotation = world.annotation(name)
    assert annotation["annotation_status"] == "proposed" and annotation["recording_id"] == name and annotation["passage_id"] == "p001"
    (flaw_entry,) = annotation["flaws"]
    assert flaw_entry["flaw_type"] == flaw
    assert flaw_entry["start_s"] == pytest.approx(start, abs=0.04) and flaw_entry["end_s"] == pytest.approx(end, abs=0.04)
    assert flaw_entry["target_words"] == [pr.clean_word(w) for w in WORDS[words[0] - 1:words[1]]]
    assert "Not yet confirmed by ear" in flaw_entry["annotator_notes"] and "Take check:" in flaw_entry["annotator_notes"]
    assert flaw_entry["flaw_id"] == f"ann_{name}_01"
    label = (world.data / "processed" / "labels" / f"{name}.flaw.txt").read_text(encoding="utf-8").split("\t")
    assert float(label[0]) == flaw_entry["start_s"] and float(label[1]) == flaw_entry["end_s"] and "PLANNED" in label[2]


def test_a_pause_is_placed_between_the_word_before_and_the_word_after_the_silence(world: World):
    world.prepare()
    name = take_id("flaw_pause")
    times = world.layouts[name].times()
    (flaw,) = world.annotation(name)["flaws"]
    assert flaw["flaw_type"] == "excessive_pause"
    assert flaw["start_s"] == pytest.approx(times[S3[1] - 1][1], abs=0.04) and flaw["end_s"] == pytest.approx(times[S3[1]][0], abs=0.04)
    assert flaw["end_s"] - flaw["start_s"] == pytest.approx(1.8, abs=0.06)
    assert flaw["target_words"] == ["word", "A"]
    assert flaw["severity_label"] == "medium"


def test_severity_comes_from_the_plan(world: World):
    world.prepare()
    assert world.annotation(take_id("flaw_quiet"))["flaws"][0]["severity_label"] == "high"
    assert world.annotation(take_id("flaw_fast"))["flaws"][0]["severity_label"] == "medium"


def test_annotation_times_stay_inside_the_file(world: World):
    world.prepare()
    for name in world.layouts:
        if "flaw" in name:
            duration = world.manifest()[name]["duration_s"]
            for flaw in world.annotation(name)["flaws"]:
                assert 0 <= flaw["start_s"] < flaw["end_s"] <= duration


# ---------------------------------------------------------------------------------------------------------------------------------
# Was the flaw performed?
# ---------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["flaw_fast", "flaw_slow", "flaw_loud", "flaw_quiet", "flaw_pause"])
def test_a_clear_flaw_is_confirmed_against_the_speakers_own_baseline_takes(world: World, kind):
    report, _ = world.prepare()
    take = by_id(report)[take_id(kind)]
    checks = [f for f in take.findings if f.level in (tc.OK, tc.WARN)]
    assert [f.level for f in checks] == [tc.OK], messages(take)
    assert not take.warned


def test_weak_flaws_are_warned_and_the_warning_travels_with_the_annotation(world: World):
    weak = {
        "flaw_fast": dt.speed_stretch(dt.normal_layout(WORDS), *S3, 0.97),
        "flaw_slow": dt.speed_stretch(dt.normal_layout(WORDS), *S4, 1.03),
        "flaw_loud": dt.level_stretch(dt.normal_layout(WORDS), *S2, 1.5),
        "flaw_quiet": dt.level_stretch(dt.normal_layout(WORDS), *S5, -1.5),
        "flaw_pause": dt.pause_after(dt.normal_layout(WORDS), S3[1], 0.5),
    }
    for kind, layout in weak.items():
        world.add(take_id(kind), layout, seed=11)
    report, _ = world.prepare()
    for kind in weak:
        take = by_id(report)[take_id(kind)]
        assert take.status == "registered" and take.warned, kind
        assert any("weak example" in m for m in messages(take, tc.WARN)), kind
        assert "weak example" in world.annotation(take.take_id)["flaws"][0]["annotator_notes"]


def test_a_loudness_the_speaker_shows_naturally_does_not_count_as_a_flaw(world: World):
    """If the speaker reads sentence 2 about 6 dB louder than the rest in every baseline take, +8 dB there is only +2 dB of flaw."""
    for n in (1, 2, 3):
        world.add(take_id("base", n), dt.level_stretch(dt.normal_layout(WORDS), *S2, 6.0), seed=n)
    report, _ = world.prepare()
    take = by_id(report)[take_id("flaw_loud")]
    assert take.warned and any("weak example" in m and "+2" in m for m in messages(take, tc.WARN)), messages(take)


def test_without_a_baseline_take_of_the_speaker_the_speed_check_is_skipped_with_a_note(world: World):
    for n in (1, 2, 3):
        (world.incoming / f"{take_id('base', n)}.wav").unlink()
    report, _ = world.prepare()
    take = by_id(report)[take_id("flaw_fast")]
    assert take.status == "registered" and not take.warned
    assert any("no baseline take" in m for m in messages(take, tc.INFO))
    assert "Take check" not in world.annotation(take.take_id)["flaws"][0]["annotator_notes"]
    # the pause needs no baseline, so it is still checked
    assert any("silence after the word" in m for m in messages(by_id(report)[take_id("flaw_pause")], tc.OK))


def test_baseline_takes_registered_earlier_are_used_as_the_reference(world: World):
    flawed = [p for p in world.incoming.glob("*flaw*")]
    held_back = {p.name: p.read_bytes() for p in flawed}
    for p in flawed:
        p.unlink()
    world.prepare()                                                  # first only the baseline and clean takes
    for name, data in held_back.items():
        (world.incoming / name).write_bytes(data)
    for p in world.incoming.glob("*base*"):
        p.unlink()
    for p in world.incoming.glob("*clean*"):
        p.unlink()
    report, aligner = world.prepare()                                # now only the flawed ones
    assert aligner.calls == 5
    take = by_id(report)[take_id("flaw_fast")]
    assert any("baseline takes" in m for m in messages(take, tc.OK)) and not take.warned


# ---------------------------------------------------------------------------------------------------------------------------------
# Re-runs, re-recorded takes, confirmed annotations
# ---------------------------------------------------------------------------------------------------------------------------------

def test_the_manifest_stays_sorted_when_takes_are_added_in_a_later_run(world: World):
    held_back = {p.name: p.read_bytes() for p in world.incoming.glob("*base*")}
    for p in world.incoming.glob("*base*"):
        p.unlink()
    world.prepare()
    for name, data in held_back.items():
        (world.incoming / name).write_bytes(data)
    world.prepare()
    ids = [e["recording_id"] for e in json.loads((world.data / "metadata" / "manifest.json").read_text(encoding="utf-8"))]
    assert ids == sorted(ids) and len(ids) == 9


def test_running_again_changes_nothing_and_does_not_align_again(world: World):
    world.prepare()
    before = world.files()
    raw_times = {p.name: p.stat().st_mtime_ns for p in (world.data / "raw").glob("*.wav")}
    report, aligner = world.prepare(today="2027-01-01")
    assert {p.name: p.stat().st_mtime_ns for p in (world.data / "raw").glob("*.wav")} == raw_times      # recordings are not copied twice
    assert [t.status for t in report.takes] == ["unchanged"] * 9
    assert aligner.calls == 0 and all(t.reused_alignment for t in report.takes)
    assert world.files() == before
    assert all(e["created_at"] == "2026-10-13" for e in world.manifest().values())


def test_realign_aligns_again_but_keeps_the_same_result(world: World):
    world.prepare()
    before = world.files()
    report, aligner = world.prepare(realign=True)
    assert aligner.calls == 9 and not any(t.reused_alignment for t in report.takes)
    assert world.files() == before
    assert [t.status for t in report.takes] == ["unchanged"] * 9


def test_a_take_recorded_again_needs_replace(world: World):
    world.prepare()
    before = world.files()
    name = take_id("base", 2)
    world.add(name, dt.normal_layout(WORDS, pace=1.1), seed=99)
    report, aligner = world.prepare()
    take = by_id(report)[name]
    assert take.status == "failed" and "--replace" in take.problem
    assert aligner.calls == 0
    assert world.files() == before                                   # nothing was touched
    assert [t.status for t in report.takes if t.take_id != name] == ["unchanged"] * 8


def test_replace_registers_the_new_audio_and_aligns_it_again(world: World):
    world.prepare()
    name = take_id("base", 2)
    old_sha = world.manifest()[name]["sha256_audio"]
    world.add(name, dt.normal_layout(WORDS, pace=1.1), seed=99)
    report, aligner = world.prepare(replace=True)
    assert by_id(report)[name].status == "updated" and aligner.calls == 1
    entry = world.manifest()[name]
    assert entry["sha256_audio"] != old_sha
    assert entry["sha256_audio"] == hashlib.sha256((world.data / "raw" / f"{name}.wav").read_bytes()).hexdigest()
    assert entry["created_at"] == "2026-10-13"


def test_a_confirmed_annotation_is_never_overwritten(world: World):
    world.prepare()
    name = take_id("flaw_fast")
    path = world.data / "annotations" / f"{name}.flaws.json"
    annotation = world.annotation(name)
    annotation["annotation_status"] = "confirmed"
    annotation["flaws"][0]["start_s"] = 1.234
    path.write_text(json.dumps(annotation, indent=2) + "\n", encoding="utf-8")
    before = path.read_bytes()
    report, _ = world.prepare()
    assert path.read_bytes() == before
    assert any("confirmed by a person" in m for m in messages(by_id(report)[name], tc.INFO))


def test_an_annotation_written_by_hand_without_a_status_is_kept_too(world: World):
    world.prepare()
    name = take_id("flaw_slow")
    path = world.data / "annotations" / f"{name}.flaws.json"
    path.write_text(json.dumps({"recording_id": name, "passage_id": "p001", "dataset_version": "1.0.0",
                                "flaws": [{"flaw_id": "x", "flaw_type": "too_slow", "start_s": 2.0, "end_s": 3.0, "severity_label": "high"}]}), encoding="utf-8")
    before = path.read_bytes()
    world.prepare()
    assert path.read_bytes() == before


def test_a_proposed_annotation_follows_a_changed_plan(world: World):
    world.prepare()
    name = take_id("flaw_fast")
    before = world.annotation(name)["flaws"][0]["start_s"]
    world.plan_rows[0] = dt.plan_row(name, "too_fast", 6, 12, stretch="S2")
    world.write_plan()
    world.prepare()
    flaws = world.annotation(name)["flaws"][0]
    assert flaws["start_s"] != before and flaws["start_s"] == pytest.approx(world.layouts[name].times()[5][0], abs=0.04)


def test_a_replaced_take_gets_a_new_proposal_even_if_the_old_one_was_confirmed(world: World):
    world.prepare()
    name = take_id("flaw_fast")
    path = world.data / "annotations" / f"{name}.flaws.json"
    annotation = world.annotation(name)
    annotation["annotation_status"] = "confirmed"
    path.write_text(json.dumps(annotation), encoding="utf-8")
    world.add(name, dt.speed_stretch(dt.normal_layout(WORDS), *S3, 0.5), seed=77)
    world.prepare(replace=True)
    assert world.annotation(name)["annotation_status"] == "proposed"


# ---------------------------------------------------------------------------------------------------------------------------------
# Failures stay isolated
# ---------------------------------------------------------------------------------------------------------------------------------

def test_a_flawed_take_that_is_not_in_the_plan_is_not_registered(world: World):
    world.plan_rows = [r for r in world.plan_rows if r["take_id"] != take_id("flaw_slow")]
    world.write_plan()
    report, _ = world.prepare()
    take = by_id(report)[take_id("flaw_slow")]
    assert take.status == "failed" and "not in the recording plan" in take.problem
    assert take_id("flaw_slow") not in world.manifest()
    assert not (world.data / "annotations" / f"{take.take_id}.flaws.json").exists()
    assert not (world.data / "raw" / f"{take.take_id}.wav").exists()
    assert sum(t.status == "registered" for t in report.takes) == 8 and report.dataset_ok is True


def test_a_missing_plan_file_fails_only_the_flawed_takes(world: World):
    world.plan.unlink()
    report, _ = world.prepare()
    assert sorted(t.take_id for t in report.takes if t.status == "failed") == sorted(n for n in world.layouts if "flaw" in n)
    assert sum(t.status == "registered" for t in report.takes) == 4


@pytest.mark.parametrize("row,message", [
    (dt.plan_row("X", "too_slow", *S3), "plan says 'too_slow'"),
    (dt.plan_row("X", "too_fast", 40, 99), "outside the passage"),
    (dt.plan_row("X", "too_fast", 0, 5), "outside the passage"),
    (dt.plan_row("X", "too_fast", 9, 3), "outside the passage"),
])
def test_an_unusable_plan_row_fails_that_take_with_a_reason(world: World, row, message):
    name = take_id("flaw_fast")
    world.plan_rows[0] = {**row, "take_id": name}
    world.write_plan()
    report, _ = world.prepare()
    take = by_id(report)[name]
    assert take.status == "failed" and message in take.problem


def test_a_pause_row_must_say_after_which_word_the_silence_falls(world: World):
    name = take_id("flaw_pause")
    world.plan_rows[4] = {**dt.plan_row(name, "excessive_pause", 22, 23, pause_after=None)}
    world.write_plan()
    report, _ = world.prepare()
    assert by_id(report)[name].status == "failed" and "after which word" in by_id(report)[name].problem


def test_one_bad_file_never_stops_the_good_ones(world: World):
    (world.incoming / "notes.wav").write_bytes(b"not a recording")
    (world.incoming / "rec_p001_spk_dev_01_base_09.wav").write_bytes(b"RIFF....garbage")
    clipped = dt.synth_take(dt.normal_layout(WORDS), seed=21) * 8.0
    dt.write_wav(world.incoming / "rec_p001_spk_dev_01_base_08.wav", clipped)
    dt.write_take(world.incoming, "rec_p009_spk_dev_01_base_01", dt.normal_layout(WORDS))
    report, _ = world.prepare()
    tk = by_id(report)
    assert tk["notes"].status == "failed" and "does not follow the protocol" in tk["notes"].problem
    assert tk["rec_p001_spk_dev_01_base_09"].status == "failed" and "recording check" in tk["rec_p001_spk_dev_01_base_09"].problem
    assert tk["rec_p001_spk_dev_01_base_08"].status == "failed" and "recording check" in tk["rec_p001_spk_dev_01_base_08"].problem
    assert tk["rec_p009_spk_dev_01_base_01"].status == "failed" and "p009" in tk["rec_p009_spk_dev_01_base_01"].problem
    assert sum(t.status == "registered" for t in report.takes) == 9 and report.dataset_ok is True
    assert sorted(world.manifest()) == sorted(world.layouts)


def test_an_audio_file_that_is_not_wav_is_reported_with_the_fix(world: World):
    (world.incoming / "rec_p001_spk_dev_01_clean_09.m4a").write_bytes(b"not wav")
    report, _ = world.prepare()
    take = by_id(report)["rec_p001_spk_dev_01_clean_09"]
    assert take.status == "failed" and ".m4a file, not a WAV file" in take.problem and "Audacity" in take.problem
    assert sum(t.status == "registered" for t in report.takes) == 9


def test_progress_is_reported_before_and_after_each_take(world: World):
    lines: List[str] = []
    pr.Preparer(world.data, world.passages, world.plan, aligner=dt.BurstAligner(), out=lines.append, today="2026-10-13").run([world.incoming])
    assert lines[0].startswith("Preparing 9 recording(s)")
    assert f"  [1/9] {take_id('base', 1)}: working ..." in lines and f"  [1/9] {take_id('base', 1)}: aligned" in lines
    assert f"  [9/9] {take_id('flaw_slow')}: aligned" in lines
    lines.clear()
    pr.Preparer(world.data, world.passages, world.plan, aligner=dt.BurstAligner(), out=lines.append, today="2026-10-13").run([world.incoming])
    assert f"  [1/9] {take_id('base', 1)}: alignment kept" in lines


def test_a_flaw_kind_the_plan_does_not_know_is_refused(world: World):
    dt.write_take(world.incoming, "rec_p001_spk_dev_01_flaw_mumble_01", dt.normal_layout(WORDS))
    report, _ = world.prepare()
    assert by_id(report)["rec_p001_spk_dev_01_flaw_mumble_01"].status == "failed"
    assert "not a flaw of the plan" in by_id(report)["rec_p001_spk_dev_01_flaw_mumble_01"].problem


def test_a_speaker_cannot_change_split(world: World):
    (world.data / "metadata" / "speakers.json").write_text(json.dumps([{"speaker_id": SPEAKER, "split": "test"}]), encoding="utf-8")
    report, _ = world.prepare()
    assert all(t.status == "failed" and "test split" in t.problem for t in report.takes)
    assert world.manifest() == {}


def test_a_different_passage_text_in_the_dataset_refuses_the_takes(world: World):
    other = dt.passage_entry(text=dt.PASSAGE_TEXT.replace("Good morning", "Good evening"))
    (world.data / "metadata" / "passages.json").write_text(json.dumps([other]), encoding="utf-8")
    report, _ = world.prepare()
    assert all(t.status == "failed" and "differs" in t.problem for t in report.takes)
    assert world.manifest() == {}


def test_two_files_with_the_same_name_are_not_both_registered(world: World, tmp_path: Path):
    second = tmp_path / "second"
    second.mkdir()
    shutil.copyfile(world.incoming / f"{take_id('clean')}.wav", second / f"{take_id('clean')}.wav")
    report, _ = world.prepare(inputs=[world.incoming, second])
    assert sorted(t.status for t in report.takes).count("failed") == 1
    assert [t.problem for t in report.takes if t.status == "failed"][0].startswith("Another file with the same name")


def test_a_missing_passage_file_stops_the_run_with_a_message(world: World):
    world.passages.unlink()
    with pytest.raises(pr.PrepareError, match="passages"):
        world.prepare()


# ---------------------------------------------------------------------------------------------------------------------------------
# Alignment problems
# ---------------------------------------------------------------------------------------------------------------------------------

def test_a_wrong_number_of_words_fails_every_take_and_registers_nothing(world: World):
    report, _ = world.prepare(aligner=dt.BurstAligner(extra_words=1))
    assert all(t.status == "failed" for t in report.takes)
    assert all("returned 46 words but the passage has 45 words" in t.problem for t in report.takes)
    assert world.manifest() == {}


def test_a_word_without_a_time_fails_a_baseline_take_but_only_warns_for_the_others(world: World):
    report, _ = world.prepare(aligner=dt.BurstAligner(drop={5}))
    tk = by_id(report)
    assert all(tk[take_id("base", n)].status == "failed" and "baseline needs every word" in tk[take_id("base", n)].problem for n in (1, 2, 3))
    assert tk[take_id("clean")].status == "registered" and tk[take_id("clean")].warned
    assert any("got no time" in m for m in messages(tk[take_id("clean")], tc.WARN))


def test_an_unsure_aligner_is_a_warning(world: World):
    report, _ = world.prepare(aligner=dt.BurstAligner(confidence=0.1))
    assert all(t.status == "registered" and t.warned for t in report.takes)
    assert any("unsure" in m for m in messages(report.takes[0], tc.WARN))


def test_an_error_on_one_take_is_reported_for_that_take(world: World):
    report, _ = world.prepare(aligner=dt.BurstAligner(fail_with=RuntimeError("boom")))
    assert all(t.status == "failed" and "The alignment failed: boom" in t.problem for t in report.takes)


def test_a_missing_alignment_model_stops_the_run_and_says_what_to_do(world: World):
    with pytest.raises(pr.PrepareError, match="check_environment.py --download-models"):
        world.prepare(aligner=dt.BurstAligner(fail_with=AlignmentModelError("no weights")))
    assert world.manifest() == {}


def test_a_stored_alignment_that_no_longer_matches_its_hash_is_made_again(world: World):
    world.prepare()
    name = take_id("base", 1)
    path = world.data / "processed" / "alignments" / f"{name}.alignment.json"
    original = path.read_text(encoding="utf-8")
    altered = json.loads(original)
    for word in altered["words"]:
        word["start_s"] += 0.2                                          # still a valid alignment, but not the one that was registered
        word["end_s"] += 0.2
    path.write_text(json.dumps(altered, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report, aligner = world.prepare()
    assert aligner.calls == 1 and by_id(report)[name].status == "unchanged" and not by_id(report)[name].reused_alignment
    assert path.read_text(encoding="utf-8") == original                 # the registered alignment came back


def test_a_stored_alignment_that_is_not_valid_json_is_made_again(world: World):
    world.prepare()
    name = take_id("base", 1)
    (world.data / "processed" / "alignments" / f"{name}.alignment.json").write_text("{}\n", encoding="utf-8")
    report, aligner = world.prepare()
    assert aligner.calls == 1 and by_id(report)[name].status == "unchanged"


# ---------------------------------------------------------------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------------------------------------------------------------

def test_the_baseline_is_built_from_the_dev_speakers_baseline_takes_only(world: World):
    world.add(take_id("base", 1, speaker="spk_test_01"), dt.normal_layout(WORDS, pace=1.2), seed=31)
    report, _ = world.prepare(build_baseline=True)
    ((passage_id, record, error),) = report.baselines
    assert passage_id == "p001" and error == ""
    assert record.baseline_recording_ids == [take_id("base", n) for n in (1, 2, 3)]
    stats = world.data / "processed" / "baseline_stats" / "p001.json"
    assert stats.is_file()
    loaded = BaselineProvider(world.data / "processed" / "baseline_stats").get("p001", passage_id="p001")
    assert loaded.sha256 == record.sha256 and loaded.verify_sha256()
    assert loaded.n_pauses_within_phrase > 0 and loaded.n_pauses_cross_sentence > 0
    assert report.dataset_ok is True


def test_the_baseline_is_not_built_unless_asked_for(world: World):
    report, _ = world.prepare()
    assert report.baselines == [] and not (world.data / "processed" / "baseline_stats").exists()


def test_the_baseline_is_the_same_every_time(world: World):
    world.prepare(build_baseline=True)
    first = (world.data / "processed" / "baseline_stats" / "p001.json").read_bytes()
    report, _ = world.prepare(build_baseline=True, realign=True)
    ((_pid, record, error),) = report.baselines
    assert error == "" and record is not None                          # an existing baseline file is replaced, not an error
    assert (world.data / "processed" / "baseline_stats" / "p001.json").read_bytes() == first


def test_a_baseline_that_cannot_be_measured_is_reported_not_raised(world: World, capsys):
    for n in (1, 2, 3):
        flat = dt.normal_layout(WORDS)
        flat.gaps = [0.08] * len(flat.gaps)                          # no pause anywhere
        world.add(take_id("base", n), flat, seed=n)
    report, _ = world.prepare(build_baseline=True)
    ((passage_id, record, error),) = report.baselines
    assert passage_id == "p001" and record is None and "pause" in error
    assert not (world.data / "processed" / "baseline_stats" / "p001.json").exists()
    text = pr.render(report, world.data)
    assert "NOT built" in text and "Send this message to the team lead" in text


def test_no_baseline_is_built_for_a_passage_without_dev_baseline_takes(world: World):
    for p in world.incoming.glob("*base*"):
        p.unlink()
    report, _ = world.prepare(build_baseline=True)
    assert report.baselines == []


def test_a_test_speakers_baseline_takes_never_make_a_baseline(world: World):
    for p in world.incoming.glob("*base*"):
        p.unlink()
    for n in (1, 2, 3):
        world.add(take_id("base", n, speaker="spk_test_01"), dt.normal_layout(WORDS), seed=40 + n)
    report, _ = world.prepare(build_baseline=True)
    assert report.baselines == [] and not (world.data / "processed" / "baseline_stats").exists()
    assert {e["split"] for e in world.manifest().values() if e["speaker_id"] == "spk_test_01"} == {"test"}


# ---------------------------------------------------------------------------------------------------------------------------------
# Output, command line, determinism
# ---------------------------------------------------------------------------------------------------------------------------------

def test_the_report_names_every_take_with_its_state_and_the_next_step(world: World):
    (world.incoming / "notes.wav").write_bytes(b"x")
    world.add(take_id("flaw_fast", 2), dt.normal_layout(WORDS), seed=3)
    world.plan_rows.append(dt.plan_row(take_id("flaw_fast", 2), "too_fast", *S3))
    world.write_plan()
    report, _ = world.prepare(build_baseline=True)
    text = pr.render(report, world.data)
    assert f"OK      {take_id('base', 1)}  (registered; " in text
    assert f"CHECK   {take_id('flaw_fast', 2)}" in text and "weak example" in text
    assert "FAILED  notes" in text and "does not follow the protocol" in text
    assert "Baseline for p001: built from 3 take(s)" in text
    assert "word-by-word profile: built (3 take(s) matched the passage text)" in text
    assert "Dataset check: valid" in text
    assert "Next: start the site with   python -m uvicorn app.main:app --app-dir backend" in text
    assert "PROPOSED from the plan" in text and "File > Import > Labels" in text
    assert "11 file(s):" in text and "not registered" in text


def test_the_report_says_when_the_baseline_has_no_word_profile_and_what_that_costs(world: World):
    (world.incoming / f"{take_id('base', 3)}.wav").unlink()                 # two baseline takes: enough for the overall statistics, not for a profile
    report, _ = world.prepare(build_baseline=True)
    text = pr.render(report, world.data)
    assert "Baseline for p001: built from 2 take(s)" in text
    assert "word-by-word profile: NOT built" in text and "at least 3 baseline takes" in text and "much less precise" in text
    text.encode("ascii")


def test_two_fresh_runs_write_identical_files(source: World, tmp_path: Path):
    runs = []
    for name in ("a", "b"):
        root = tmp_path / name
        copy = World(root)
        shutil.copytree(source.incoming, copy.incoming)
        shutil.copyfile(source.plan, copy.plan)
        copy.prepare(build_baseline=True)
        runs.append({k.split("/", 1)[1]: v for k, v in copy.files().items()})
    assert runs[0] == runs[1] and len(runs[0]) > 30


def test_command_line_exit_codes_and_output(world: World, capsys):
    argv = [str(world.incoming), "--data-dir", str(world.data), "--passages", str(world.passages), "--plan", str(world.plan), "--build-baseline"]
    assert pr.main(argv, aligner=dt.BurstAligner()) == 0
    out = capsys.readouterr().out
    assert "9 file(s): 9 registered" in out and "Baseline for p001: built" in out and "Dataset check: valid" in out
    assert pr.main(argv, aligner=dt.BurstAligner()) == 0
    assert "9 unchanged" in capsys.readouterr().out
    (world.incoming / "bad_name.wav").write_bytes(b"x")
    assert pr.main(argv, aligner=dt.BurstAligner()) == 1
    assert "FAILED  bad_name" in capsys.readouterr().out


def test_command_line_with_nothing_to_do_and_with_a_stopping_error(world: World, tmp_path: Path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    base = ["--data-dir", str(world.data), "--passages", str(world.passages), "--plan", str(world.plan)]
    assert pr.main([str(empty)] + base, aligner=dt.BurstAligner()) == 2
    assert "No WAV files found" in capsys.readouterr().err
    assert pr.main([str(world.incoming)] + base, aligner=dt.BurstAligner(fail_with=AlignmentModelError("no weights"))) == 1
    assert "Stopped:" in capsys.readouterr().err


def test_command_line_exits_with_one_when_the_baseline_cannot_be_built(world: World, capsys):
    for n in (1, 2, 3):
        flat = dt.normal_layout(WORDS)
        flat.gaps = [0.08] * len(flat.gaps)
        world.add(take_id("base", n), flat, seed=n)
    argv = [str(world.incoming), "--data-dir", str(world.data), "--passages", str(world.passages), "--plan", str(world.plan), "--build-baseline"]
    assert pr.main(argv, aligner=dt.BurstAligner()) == 1
    assert "NOT built" in capsys.readouterr().out


def test_the_dataset_check_looks_at_the_files_not_only_at_the_lists(world: World):
    report, _ = world.prepare()
    assert report.dataset_ok is True
    victim = world.data / "raw" / f"{take_id('clean')}.wav"
    victim.write_bytes(victim.read_bytes() + b"\x00\x00")                        # a file changed behind the manifest's back
    checked = pr.Report()
    pr.Preparer(world.data, world.passages, world.plan, aligner=dt.BurstAligner(), out=lambda _l: None)._validate(checked)
    assert checked.dataset_ok is False and any("sha256_audio mismatch" in e for e in checked.dataset_errors)


def test_a_stereo_recording_is_registered_with_its_channel_count(world: World):
    mono = dt.synth_take(dt.normal_layout(WORDS), seed=50)
    name = take_id("clean", 2)
    import scipy.io.wavfile as wavfile
    wavfile.write(str(world.incoming / f"{name}.wav"), dt.SR, np.round(np.stack([mono, mono], axis=1) * 32767).astype(np.int16))
    world.layouts[name] = dt.normal_layout(WORDS)
    report, _ = world.prepare()
    assert by_id(report)[name].status == "registered" and world.manifest()[name]["channels"] == 2


def test_flags_are_passed_through_to_new_manifest_entries(world: World):
    argv = [str(world.incoming), "--data-dir", str(world.data), "--passages", str(world.passages), "--plan", str(world.plan),
            "--microphone", "usb_headset_x", "--conditions", "study_room"]
    assert pr.main(argv, aligner=dt.BurstAligner()) == 0
    assert {(e["microphone"], e["recording_conditions"]) for e in world.manifest().values()} == {("usb_headset_x", "study_room")}


def test_a_person_s_edits_to_an_unchanged_entry_survive_a_rerun(world: World):
    world.prepare()
    path = world.data / "metadata" / "manifest.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    entries[0]["microphone"] = "edited_by_hand"
    entries[0]["note"] = "extra field"
    path.write_text(json.dumps(entries), encoding="utf-8")
    world.prepare(microphone="something_else")
    kept = world.manifest()[entries[0]["recording_id"]]
    assert kept["microphone"] == "edited_by_hand" and kept["note"] == "extra field"


# ---------------------------------------------------------------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------------------------------------------------------------

def test_clean_word_strips_punctuation_but_keeps_apostrophes():
    assert pr.clean_word("analytics.") == "analytics"
    assert pr.clean_word("“Hello,”") == "Hello"
    assert pr.clean_word("o'clock,") == "o'clock"
    assert pr.clean_word("don't") == "don't"


def test_the_stored_alignment_is_the_alignment_that_is_used():
    from app.schemas.common import AlignmentMethod
    from app.schemas.contracts import AlignedTranscript, AlignedWord

    raw = AlignedTranscript(text="a b", words=[AlignedWord(word="a", start_s=0.12349, end_s=0.5, confidence=0.123456),
                                              AlignedWord(word="b", start_s=None, end_s=None)],
                            alignment_method=AlignmentMethod.WHISPERX, total_coverage_pct=0.812345)
    text, stored = pr.alignment_to_json(raw)
    assert stored.words[0].start_s == 0.123 and stored.words[0].confidence == 0.1235 and stored.total_coverage_pct == 0.8123
    assert stored.words[1].start_s is None
    assert AlignedTranscript.model_validate_json(text) == stored
    assert text.endswith("}\n") and json.loads(text)["words"][0]["start_s"] == 0.123


def test_write_json_leaves_identical_content_untouched(tmp_path: Path):
    path = tmp_path / "x.json"
    pr.write_json(path, {"a": 1})
    first = path.stat().st_mtime_ns
    pr.write_json(path, {"a": 1})
    assert path.stat().st_mtime_ns == first
    pr.write_json(path, {"a": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 2}


def test_read_plan_reads_a_file_saved_with_a_byte_order_mark_and_reports_a_wrong_encoding(tmp_path: Path):
    bom = tmp_path / "bom.csv"
    bom.write_bytes("\ufefftake_id,flaw_type\nrec_x,too_fast\n".encode("utf-8"))
    assert pr.read_plan(bom) == {"rec_x": {"take_id": "rec_x", "flaw_type": "too_fast"}}
    legacy = tmp_path / "legacy.csv"
    legacy.write_bytes(b"take_id,flaw_type\nrec_x,\xe9\xff\n")
    with pytest.raises(pr.PrepareError, match="Cannot read the plan"):
        pr.read_plan(legacy)


def test_read_plan_handles_a_missing_file_and_a_broken_one(tmp_path: Path):
    assert pr.read_plan(None) == {} and pr.read_plan(tmp_path / "none.csv") == {}
    broken = tmp_path / "plan.csv"
    broken.write_text("order,name\n1,x\n", encoding="utf-8")
    with pytest.raises(pr.PrepareError, match="Cannot read the plan"):
        pr.read_plan(broken)


# ---------------------------------------------------------------------------------------------------------------------------------
# The committed plan and passages, end to end (the situation of the first real test)
# ---------------------------------------------------------------------------------------------------------------------------------

def test_the_committed_plan_and_passages_work_end_to_end(tmp_path: Path):
    passages = REPO / "data" / "plan" / "passages_v1.json"
    plan = pr.read_plan(REPO / "data" / "plan" / "v1" / "plan.csv")
    entry = next(e for e in json.loads(passages.read_text(encoding="utf-8")) if e["passage_id"] == "p001")
    words = [w for sentence in pt.passage_words(entry["text"]) for w in sentence]
    assert len(words) == 123
    world = World(tmp_path)
    world.passages = passages
    world.plan = REPO / "data" / "plan" / "v1" / "plan.csv"
    rows = [r for r in plan.values() if r["speaker_id"] == "spk_dev_01" and r["passage_id"] == "p001"]
    assert len(rows) == 15
    for seed, row in enumerate(rows):
        layout = dt.normal_layout(words, amplitude=0.1)
        number, flaw = int(row["take_id"][-2:]), row["flaw_type"]
        first, last = (int(row["stretch_first_word"] or 0), int(row["stretch_last_word"] or 0))
        if flaw == "too_fast":
            dt.speed_stretch(layout, first, last, mp.SPEED_FACTOR[(flaw, number)] * 0.9)
        elif flaw == "too_slow":
            dt.speed_stretch(layout, first, last, mp.SPEED_FACTOR[(flaw, number)] * 1.05)
        elif flaw in ("high_energy", "low_energy"):
            dt.level_stretch(layout, first, last, mp.LEVEL_DB[number] * (1 if flaw == "high_energy" else -1))
        elif flaw == "excessive_pause":
            dt.pause_after(layout, int(row["pause_after_word"]), sum(mp.PAUSE_SECONDS[number]) / 2)
        world.add(row["take_id"], layout, seed=seed + 1)
    preparer = pr.Preparer(world.data, passages, world.plan, aligner=dt.BurstAligner(), out=lambda _l: None, today="2026-10-13")
    report = preparer.run([world.incoming], build_baseline=True)
    assert [t.status for t in report.takes] == ["registered"] * 15, [(t.take_id, t.problem) for t in report.takes if t.status == "failed"]
    assert report.dataset_ok is True and report.dataset_errors == []
    ((_pid, record, error),) = report.baselines
    assert error == "" and len(record.baseline_recording_ids) == 3
    for row in rows:
        if row["category"] != "flawed_human_controlled":
            continue
        take = by_id(report)[row["take_id"]]
        assert not take.warned, (take.take_id, messages(take, tc.WARN))
        (flaw,) = world.annotation(take.take_id)["flaws"]
        times = world.layouts[take.take_id].times()
        if row["flaw_type"] == "excessive_pause":
            after = int(row["pause_after_word"])
            expected = (times[after - 1][1], times[after][0])
        else:
            expected = (times[int(row["stretch_first_word"]) - 1][0], times[int(row["stretch_last_word"]) - 1][1])
        assert flaw["flaw_type"] == row["flaw_type"] and flaw["severity_label"] == row["severity_label"]
        assert flaw["start_s"] == pytest.approx(expected[0], abs=0.04) and flaw["end_s"] == pytest.approx(expected[1], abs=0.04), take.take_id
