"""Tests for scripts/dataset/evaluate_takes.py (TASK-127a, DEC-039).

The matching and the report are tested on hand-made intervals; the replay is tested on synthetic takes registered with a stand-in aligner, so the
real analysis (preprocessing, features, baseline comparison, grounding, scoring) runs without any speech model. Covers the 50 % rule on both sides of its
limit, best-overlap pairing and single use of a detection, boundary-error signs, extra detections, the summary and the report text, annotation status,
what is selected (dev only, no baseline takes, the sealed test split), takes that cannot be replayed, the file written with --json, determinism, and the
sweep table that compares several values of a setting (DEC-040).
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import List

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "dataset"))
sys.path.insert(0, str(Path(__file__).parent))

import dataset_takes as dt  # noqa: E402
import evaluate_takes as ev  # noqa: E402
import prepare_recordings as pr  # noqa: E402
from test_prepare_recordings import S3, S5, World, take_id  # noqa: E402

A = ev.Annotated
D = ev.Detected


def det(kind: str, start: float, end: float, severity: float = 0.5) -> ev.Detected:
    return D(kind, start, end, severity, "")


# ---------------------------------------------------------------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------------------------------------------------------------

def test_a_detection_covering_exactly_half_of_the_plan_counts_and_a_little_less_does_not():
    plan = [A("too_fast", 10.0, 20.0, "confirmed")]
    (hit,), extras = ev.match_flaws(plan, [det("too_fast", 15.0, 30.0)])
    assert hit.found is not None and extras == [] and hit.overlap_s == pytest.approx(5.0)
    (miss,), extras = ev.match_flaws(plan, [det("too_fast", 15.1, 30.0)])
    assert miss.found is None and len(extras) == 1


def test_floating_point_noise_does_not_decide_whether_half_the_plan_is_covered():
    plan = [A("too_fast", 0.01, 0.08, "x")]
    (m,), _ = ev.match_flaws(plan, [det("too_fast", 0.045000000000000005, 1.08)])              # mathematically exactly half; in floating point 0.034999999999999996 < 0.035
    assert m.found is not None


def test_equal_overlaps_go_to_the_earlier_detection():
    (m,), extras = ev.match_flaws([A("too_fast", 10.0, 14.0, "x")], [det("too_fast", 8.0, 12.0, 0.1), det("too_fast", 12.0, 16.0, 0.2)])
    assert m.found.severity == 0.1 and [e.severity for e in extras] == [0.2]


def test_boundary_errors_have_a_sign_and_the_overlap_and_range_are_reported():
    plan = [A("too_fast", 10.0, 14.0, "proposed")]
    (m,), _ = ev.match_flaws(plan, [det("too_fast", 8.0, 15.0)])
    assert m.start_error_s == pytest.approx(-2.0) and m.end_error_s == pytest.approx(1.0)       # started 2 s early, ended 1 s late
    assert m.iou == pytest.approx(4.0 / 7.0) and m.range_ratio == pytest.approx(7.0 / 4.0) and m.overlap_s == pytest.approx(4.0)


def test_only_a_detection_of_the_same_type_can_match():
    (m,), extras = ev.match_flaws([A("too_fast", 10.0, 14.0, "x")], [det("too_slow", 10.0, 14.0)])
    assert m.found is None and [e.flaw_type for e in extras] == ["too_slow"]


def test_the_detection_with_the_largest_overlap_is_chosen_and_each_is_used_once():
    plan = [A("excessive_pause", 10.0, 12.0, "x"), A("excessive_pause", 10.5, 12.5, "x")]
    (first, second), extras = ev.match_flaws(plan, [det("excessive_pause", 9.0, 10.8), det("excessive_pause", 10.0, 12.4)])
    assert first.found.end_s == 12.4                                       # 2.0 s overlap beats 0.8 s
    assert second.found is None or second.found.end_s != 12.4              # the same detection is not used twice
    assert len(extras) + sum(1 for m in (first, second) if m.found) == 2


def test_detections_nobody_planned_are_extras_and_an_empty_plan_matches_nothing():
    matches, extras = ev.match_flaws([], [det("too_fast", 1.0, 2.0), det("low_energy", 3.0, 4.0)])
    assert matches == [] and [e.flaw_type for e in extras] == ["too_fast", "low_energy"]
    assert ev.match_flaws([A("too_fast", 1.0, 2.0, "x")], []) [0][0].found is None


def test_an_empty_planned_interval_can_never_be_found():
    (m,), _ = ev.match_flaws([A("too_fast", 5.0, 5.0, "x")], [det("too_fast", 4.0, 6.0)])
    assert m.found is None


def test_overlap_of_disjoint_intervals_is_zero():
    assert ev.overlap(0.0, 1.0, 2.0, 3.0) == 0.0 and ev.overlap(0.0, 2.0, 1.0, 3.0) == 1.0


# ---------------------------------------------------------------------------------------------------------------------------------
# Summary and report
# ---------------------------------------------------------------------------------------------------------------------------------

def results() -> List[ev.TakeResult]:
    flawed = ev.TakeResult("rec_a_flaw_fast_01", "flawed_human_controlled", "spk_dev_01", 50.0, 80.0)
    flawed.matches, flawed.extras = ev.match_flaws(
        [A("too_fast", 10.0, 14.0, "proposed"), A("excessive_pause", 20.0, 22.0, "confirmed")],
        [det("too_fast", 8.0, 15.0), det("low_energy", 30.0, 31.0, 0.2)])
    clean = ev.TakeResult("rec_a_clean_01", "clean_control", "spk_dev_01", 60.0, 95.0)
    clean.extras = [det("too_fast", 1.0, 2.0), det("excessive_pause", 5.0, 6.0)]
    quiet = ev.TakeResult("rec_a_clean_02", "clean_control", "spk_dev_01", 60.0, 99.0)
    broken = ev.TakeResult("rec_a_flaw_slow_01", "flawed_human_controlled", "spk_dev_01", 0.0, error="its stored alignment is missing")
    return [flawed, clean, quiet, broken]


def test_the_summary_counts_what_the_report_claims():
    s = ev.summarise(results())
    fast = s["types"]["too_fast"]
    assert (fast["planned"], fast["found"]) == (1, 1) and fast["mean_abs_start_error_s"] == pytest.approx(2.0) and fast["mean_abs_end_error_s"] == pytest.approx(1.0)
    assert fast["mean_iou"] == pytest.approx(4.0 / 7.0) and fast["mean_range_ratio"] == pytest.approx(1.75)
    pause = s["types"]["excessive_pause"]
    assert (pause["planned"], pause["found"], pause["mean_iou"]) == (1, 0, None)
    assert s["extras_on_flawed_takes"] == 1
    assert (s["clean_takes"], s["clean_takes_with_a_flag"], s["false_alarms_on_clean_takes"]) == (2, 1, 2)
    assert s["clean_minutes"] == pytest.approx(2.0)
    assert (s["annotations_proposed"], s["annotations_total"], s["failed_takes"]) == (1, 2, 1)


def test_the_report_names_every_finding_miss_extra_and_failure():
    text = ev.render(results())
    assert "rec_a_flaw_fast_01  (flawed_human_controlled)  score 80" in text
    assert "FOUND   too_fast" in text and "planned 10.0-14.0 s, detected 8.0-15.0 s: start -2.0 s, end +1.0 s, overlap 57%, detected range 1.8x the plan" in text
    assert "MISSED  excessive_pause" in text and "EXTRA   low_energy" in text and "severity 0.20" in text
    assert "nothing flagged" in text and "could not be replayed: its stored alignment is missing" in text
    assert "1 of 2 had at least one flag; 2 false alarms in 2.0 minutes" in text.replace("clean takes: ", "")
    assert "1 of 2 planned flaws are annotations that no person has confirmed by ear yet" in text
    assert "1 take(s) could not be replayed" in text
    text.encode("ascii")


# ---------------------------------------------------------------------------------------------------------------------------------
# The replay
# ---------------------------------------------------------------------------------------------------------------------------------

def build_human_world(root: Path) -> World:
    """The same nine takes as test_prepare_recordings, but every reading varies a little (as a person's does), so the baseline has a real spread."""
    from test_prepare_recordings import S2, S4, WORDS

    world = World(root)

    def reading(seed: int):
        return dt.normal_layout(WORDS, jitter=0.15, seed=seed)

    for n in (1, 2, 3):
        world.add(take_id("base", n), reading(n), seed=n)
    world.add(take_id("clean"), reading(10), seed=10)
    world.add(take_id("flaw_fast"), dt.speed_stretch(reading(11), *S3, 0.55), seed=11)
    world.add(take_id("flaw_slow"), dt.speed_stretch(reading(12), *S4, 1.6), seed=12)
    world.add(take_id("flaw_loud"), dt.level_stretch(reading(13), *S2, 8.0), seed=13)
    world.add(take_id("flaw_quiet"), dt.level_stretch(reading(14), *S5, -8.0), seed=14)
    world.add(take_id("flaw_pause"), dt.pause_after(reading(15), S3[1], 3.0), seed=15)
    world.plan_rows = [
        dt.plan_row(take_id("flaw_fast"), "too_fast", *S3), dt.plan_row(take_id("flaw_slow"), "too_slow", *S4),
        dt.plan_row(take_id("flaw_loud"), "high_energy", *S2), dt.plan_row(take_id("flaw_quiet"), "low_energy", *S5),
        dt.plan_row(take_id("flaw_pause"), "excessive_pause", S3[1], S3[1] + 1, pause_after=S3[1]),
    ]
    world.write_plan()
    return world


@pytest.fixture(scope="module")
def registered(tmp_path_factory) -> World:
    world = build_human_world(tmp_path_factory.mktemp("evaluate"))
    preparer = pr.Preparer(world.data, world.passages, world.plan, aligner=dt.BurstAligner(), out=lambda _l: None, today="2026-10-13")
    report = preparer.run([world.incoming], build_baseline=True)
    assert [t.status for t in report.takes] == ["registered"] * 9 and report.baselines[0][1] is not None
    return world


@pytest.fixture()
def copy(registered: World, tmp_path: Path) -> World:
    shutil.copytree(registered.data, tmp_path / "data")
    world = World.__new__(World)
    world.root, world.data = tmp_path, tmp_path / "data"
    return world


def test_the_replay_runs_the_real_analysis_without_any_speech_model(registered: World):
    out = ev.Evaluator(registered.data).run(["dev"], only="flaw_fast")
    (r,) = out
    assert r.error == "" and r.recording_id == take_id("flaw_fast") and r.composite_score is not None
    assert len(r.matches) == 1 and r.matches[0].planned.flaw_type == "too_fast" and r.matches[0].planned.status == "proposed"
    assert all(isinstance(d, ev.Detected) for d in r.extras)


def test_selection_leaves_out_baseline_takes_and_other_splits_unless_asked(registered: World):
    e = ev.Evaluator(registered.data)
    names = [x["recording_id"] for x in e.select(["dev"], False, None)]
    assert names == sorted(names) and len(names) == 6 and not any("_base_" in n for n in names)
    assert len(e.select(["dev"], True, None)) == 9
    assert e.select(["test"], True, None) == []
    assert [x["recording_id"] for x in e.select(["dev"], False, "flaw_pause")] == [take_id("flaw_pause")]


def test_clean_takes_have_no_planned_flaws_so_whatever_is_flagged_is_a_false_alarm(registered: World):
    (r,) = ev.Evaluator(registered.data).run(["dev"], only="clean")
    assert r.matches == [] and r.error == ""


def test_confirmed_only_drops_the_proposed_annotations(registered: World, copy: World):
    name = take_id("flaw_pause")
    path = copy.data / "annotations" / f"{name}.flaws.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["annotation_status"] = "confirmed"
    path.write_text(json.dumps(data), encoding="utf-8")
    (kept,) = ev.Evaluator(copy.data).run(["dev"], only="flaw_pause", confirmed_only=True)
    (dropped,) = ev.Evaluator(copy.data).run(["dev"], only="flaw_fast", confirmed_only=True)
    assert len(kept.matches) == 1 and kept.matches[0].planned.status == "confirmed" and dropped.matches == []


def test_an_annotation_written_by_hand_has_an_unknown_status(copy: World):
    name = take_id("flaw_slow")
    (copy.data / "annotations" / f"{name}.flaws.json").write_text(
        json.dumps({"flaws": [{"flaw_type": "too_slow", "start_s": 2.0, "end_s": 4.0}]}), encoding="utf-8")
    assert ev.load_annotations(copy.data, name) == [A("too_slow", 2.0, 4.0, "unknown")]
    assert ev.load_annotations(copy.data, "rec_missing") == []


def test_a_missing_or_changed_alignment_is_reported_for_that_take_only(copy: World):
    (copy.data / "processed" / "alignments" / f"{take_id('flaw_fast')}.alignment.json").unlink()
    (copy.data / "processed" / "alignments" / f"{take_id('flaw_slow')}.alignment.json").write_text("{}\n", encoding="utf-8")
    out = {r.recording_id: r for r in ev.Evaluator(copy.data).run(["dev"])}
    assert "stored alignment is missing" in out[take_id("flaw_fast")].error
    assert "no longer matches the manifest" in out[take_id("flaw_slow")].error
    assert out[take_id("clean")].error == "" and out[take_id("flaw_pause")].error == ""


def test_a_missing_baseline_is_reported_for_the_take(copy: World):
    shutil.rmtree(copy.data / "processed" / "baseline_stats")
    (r,) = ev.Evaluator(copy.data).run(["dev"], only="clean")
    assert r.error and "baseline" in r.error.lower()


def test_the_replay_is_deterministic(registered: World):
    first = ev.render(ev.Evaluator(registered.data).run(["dev"], only="flaw_"))
    assert first == ev.render(ev.Evaluator(registered.data).run(["dev"], only="flaw_"))


def test_command_line_guards_output_and_exit_codes(registered: World, capsys, tmp_path: Path):
    base = ["--data-dir", str(registered.data), "--only", "flaw_fast"]
    assert ev.main(base + ["--splits", "test"]) == 1
    assert "sealed" in capsys.readouterr().err
    assert ev.main(base + ["--splits", "test", "--allow-test"]) == 1                   # allowed, but there are no test takes
    assert "No takes matched" in capsys.readouterr().err
    out_file = tmp_path / "report.json"
    assert ev.main(base + ["--json", str(out_file)]) == 0
    printed = capsys.readouterr().out
    assert "Summary" in printed and take_id("flaw_fast") in printed
    saved = json.loads(out_file.read_text(encoding="utf-8"))
    assert set(saved) == {"summary", "takes"} and saved["takes"][0]["recording_id"] == take_id("flaw_fast")
    assert saved["summary"]["annotations_total"] == 1


def test_command_line_exit_code_is_one_when_a_take_cannot_be_replayed(copy: World, capsys):
    (copy.data / "processed" / "alignments" / f"{take_id('flaw_fast')}.alignment.json").unlink()
    assert ev.main(["--data-dir", str(copy.data), "--only", "flaw_fast"]) == 1
    assert "could not be replayed" in capsys.readouterr().out


def test_an_unreadable_manifest_stops_with_a_message(tmp_path: Path, capsys):
    (tmp_path / "metadata").mkdir()
    assert ev.main(["--data-dir", str(tmp_path)]) == 1
    assert "Cannot read the manifest" in capsys.readouterr().err


# ---------------------------------------------------------------------------------------------------------------------------------
# --detect
# ---------------------------------------------------------------------------------------------------------------------------------

def test_detection_settings_are_read_from_name_value_pairs():
    from app.schemas.common import FlawType

    assert ev.detection_config([]) is None
    cfg = ev.detection_config(["z_pause_within=3", "refine_rate=false", "refine_min_words=6", "min_pause_s=0.8", "min_flaw_s=0.7"])
    assert cfg.z_pause_within == 3.0 and cfg.refine_rate is False and cfg.refine_min_words == 6
    assert cfg.min_duration_s[FlawType.EXCESSIVE_PAUSE] == 0.8 and cfg.min_duration_s[FlawType.TOO_FAST] == 0.7 and cfg.min_duration_s[FlawType.LOW_ENERGY] == 0.7
    assert ev.detection_config(["refine_rate=ON"]).refine_rate is True


@pytest.mark.parametrize("bad,message", [("nonsense=1", "Unknown setting"), ("z_rate_fast", "Unknown setting"), ("z_rate_fast=fast", "not a valid value"),
                                          ("refine_rate=maybe", "not a valid value"), ("z_rate_fast=-1", "positive"), ("refine_min_words=1", "refine_min_words")])
def test_bad_detection_settings_are_refused_with_a_reason(bad, message):
    with pytest.raises(ev.EvaluationError, match=message):
        ev.detection_config([bad])


def test_the_word_by_word_settings_can_be_changed_too():
    cfg = ev.detection_config(["use_profile=false", "z_run_rate=3", "z_run_energy=5", "run_min_words=12", "min_rate_change_pct=20",
                               "min_energy_change_db=2.5", "global_tempo_change_pct=40"])
    assert cfg.use_profile is False and (cfg.z_run_rate, cfg.z_run_energy, cfg.run_min_words) == (3.0, 5.0, 12)
    assert (cfg.min_rate_change_pct, cfg.min_energy_change_db, cfg.global_tempo_change_pct) == (20.0, 2.5, 40.0)
    with pytest.raises(ev.EvaluationError, match="run_min_words"):
        ev.detection_config(["run_min_words=1"])


def test_the_evidence_note_names_what_was_expected():
    from types import SimpleNamespace

    rate = SimpleNamespace(evidence=SimpleNamespace(rate_participant_wpm=244.4, rate_baseline_mean_wpm=187.2, rate_z_score=5.24))
    level = SimpleNamespace(evidence=SimpleNamespace(energy_mean_db=-16.9, energy_baseline_mean_db=-24.1, energy_z_score=10.2))
    pause = SimpleNamespace(evidence=SimpleNamespace(pause_duration_s=3.52, pause_baseline_mean_s=0.59, pause_z_score=22.9))
    assert ev.evidence_note(rate) == "rate 244 words/min against 187 expected, z 5.2"
    assert ev.evidence_note(level) == "level -16.9 dBFS against -24.1 expected, z 10.2"
    assert ev.evidence_note(pause) == "pause 3.52 s against 0.59 s usual, z 22.9"
    assert ev.evidence_note(SimpleNamespace(evidence=SimpleNamespace())) == ""


def test_a_changed_setting_changes_the_replay_and_is_named_in_the_report(registered: World, capsys):
    name = take_id("flaw_pause")
    normal = ev.Evaluator(registered.data).run(["dev"], only="flaw_pause")[0]
    assert normal.matches[0].found is not None                              # the planned silence is found with the normal settings
    cfg = ev.detection_config(["z_pause_within=1000", "z_pause_cross=1000"])
    blind = ev.Evaluator(registered.data, detection=cfg).run(["dev"], only="flaw_pause")[0]
    assert blind.matches[0].found is None and not any(d.flaw_type == "excessive_pause" for d in blind.extras)
    assert ev.main(["--data-dir", str(registered.data), "--only", name, "--detect", "z_pause_within=1000", "z_pause_cross=1000"]) == 0
    out = capsys.readouterr().out
    assert "Detection settings changed for this run: z_pause_within=1000 z_pause_cross=1000" in out and "MISSED  excessive_pause" in out
    assert ev.main(["--data-dir", str(registered.data), "--only", name, "--detect", "bogus=1"]) == 1
    assert "Unknown setting" in capsys.readouterr().err


# ---------------------------------------------------------------------------------------------------------------------------------
# --sweep
# ---------------------------------------------------------------------------------------------------------------------------------

def test_a_sweep_lists_every_value_of_every_setting_and_checks_the_names():
    assert ev.parse_sweep(["z_run_rate=3,3.5, 4", "run_min_words=8"]) == [("z_run_rate", "3"), ("z_run_rate", "3.5"), ("z_run_rate", "4"), ("run_min_words", "8")]
    for bad in ("nonsense=1,2", "z_run_rate", "z_run_rate=", "z_run_rate=,", "3.5"):
        with pytest.raises(ev.EvaluationError, match="Unknown or empty sweep"):
            ev.parse_sweep([bad])


def test_a_list_that_powershell_cut_at_its_commas_is_put_back_together():
    # unquoted, PowerShell hands over  z_run_rate=3  3.5  4  run_min_words=8  10
    assert ev.parse_sweep(["z_run_rate=3", "3.5", "4", "run_min_words=8", "10"]) == [
        ("z_run_rate", "3"), ("z_run_rate", "3.5"), ("z_run_rate", "4"), ("run_min_words", "8"), ("run_min_words", "10")]
    assert ev.parse_sweep(["min_pause_s=1", "1.2,1.5"]) == [("min_pause_s", "1"), ("min_pause_s", "1.2"), ("min_pause_s", "1.5")]
    assert ev.parse_sweep(["min_energy_change_db=-1", "2"]) == [("min_energy_change_db", "-1"), ("min_energy_change_db", "2")]
    with pytest.raises(ev.EvaluationError, match="Unknown or empty sweep"):
        ev.parse_sweep(["4", "z_run_rate=3"])                         # values with no setting before them
    with pytest.raises(ev.EvaluationError, match="Unknown or empty sweep"):
        ev.parse_sweep(["z_run_rate=3", "abc"])                       # not a number: a typo, not the rest of a list


def test_the_sweep_table_has_one_line_per_setting_and_says_what_each_column_counts():
    base = ev.summarise(results())
    stricter = ev.summarise([r for r in results() if r.recording_id != "rec_a_clean_01"])
    text = ev.render_sweep([("normal settings", base), ("z_run_rate=5", stricter)], take_count=4)
    lines = text.splitlines()
    assert lines[0].startswith("Sweep over 4 take(s). Each row changes ONE setting")
    header = next(l for l in lines if l.startswith("setting"))
    for column in ("fast", "pause", "found", "extras", "clean flagged", "false/min"):
        assert column in header
    normal = next(l for l in lines if l.startswith("normal settings"))
    assert "1/1" in normal and "0/1" in normal and "1/2" in normal and "2/2" not in normal.replace("1/2", "")      # fast 1/1, pause 0/1, clean flagged 1/2
    assert "1.00" in normal                                                                                         # 2 false alarms in 2.0 clean minutes
    assert next(l for l in lines if l.startswith("z_run_rate=5")).endswith("0.00")                                  # the clean take with the flags is gone
    assert "A good setting finds more and flags less." in text
    text.encode("ascii")


def test_the_sweep_replays_the_takes_once_per_setting_and_the_command_line_prints_the_table(registered: World, capsys):
    rows, count = ev.sweep(registered.data, ["z_pause_within=1000", "z_pause_cross=1000"], ["dev"], False, "flaw_pause", False, False)
    assert count == 1 and [label for label, _ in rows] == ["normal settings", "z_pause_within=1000", "z_pause_cross=1000"]
    found = [sum(v["found"] for v in s["types"].values()) for _, s in rows]
    assert found == [1, 1, 0]            # the planned pause falls between two sentences: found normally, unaffected by the in-phrase threshold, hidden once the other is unreachable
    assert ev.main(["--data-dir", str(registered.data), "--only", "flaw_pause", "--sweep", "z_pause_within=1000"]) == 0
    out = capsys.readouterr().out
    assert "Sweep over 1 take(s)" in out and "z_pause_within=1000" in out and "normal settings" in out


def test_a_sweep_does_not_run_the_pitch_and_mfcc_extraction_again_for_every_setting(registered: World):
    from unittest import mock
    from app.services.features.f0 import F0Extractor

    calls = []
    original = F0Extractor.extract

    def counting(self, audio):
        calls.append(audio.sha256)
        return original(self, audio)

    with mock.patch.object(F0Extractor, "extract", counting):
        ev.sweep(registered.data, ["z_pause_within=1000,2000,3000"], ["dev"], False, "flaw_pause", False, False)
    assert len(calls) == 1                                                       # four replays of one take, one pitch extraction


def test_a_sweep_refuses_unknown_settings_a_second_run_mode_and_an_unreplayable_take(registered: World, copy: World, capsys):
    assert ev.main(["--data-dir", str(registered.data), "--sweep", "bogus=1"]) == 1
    assert "Unknown or empty sweep" in capsys.readouterr().err
    assert ev.main(["--data-dir", str(registered.data), "--sweep", "z_run_rate=3", "--detect", "z_run_rate=4"]) == 1
    assert "not both" in capsys.readouterr().err
    assert ev.main(["--data-dir", str(registered.data), "--sweep", "z_run_rate=3", "--splits", "test"]) == 1
    assert "sealed" in capsys.readouterr().err
    assert ev.main(["--data-dir", str(registered.data), "--sweep", "z_run_rate=3", "--only", "no_such_take"]) == 1
    assert "No takes matched" in capsys.readouterr().err
    (copy.data / "processed" / "alignments" / f"{take_id('flaw_fast')}.alignment.json").unlink()
    assert ev.main(["--data-dir", str(copy.data), "--sweep", "z_run_rate=3", "--only", "flaw_fast"]) == 1
    assert "could not be replayed" in capsys.readouterr().err
