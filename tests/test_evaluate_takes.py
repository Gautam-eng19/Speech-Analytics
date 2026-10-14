"""Tests for scripts/dataset/evaluate_takes.py (TASK-127a, DEC-039).

The matching and the report are tested on hand-made intervals; the replay is tested on synthetic takes registered with a stand-in aligner, so the
real analysis (preprocessing, features, baseline comparison, grounding, scoring) runs without any speech model. Covers the 50 % rule on both sides of its
limit, best-overlap pairing and single use of a detection, boundary-error signs, extra detections, the summary and the report text, annotation status,
what is selected (dev only, no baseline takes, the sealed test split), takes that cannot be replayed, the file written with --json, determinism, the
sweep table that compares several values of a setting (DEC-040), and what helps a person judge the findings: where each extra flag lies against the planned
flaws, why a planned flaw was missed (the registration check and the measured change), the list of places to listen to first, and the Audacity labels of the
detections (DEC-041).
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
from app.services.grounding import DetectionConfig  # noqa: E402
from app.services.grounding.profile_detection import SignalReading, StretchReading, measure_stretch  # noqa: E402
from test_prepare_recordings import S3, S5, World, take_id  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent.parent / "backend" / "tests"))
from profile_helpers import make_profile, reading as hand_reading  # noqa: E402  (hand-made readings with known words, times and levels)

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
    planned = [A("too_fast", 10.0, 14.0, "proposed"), A("excessive_pause", 20.0, 22.0, "confirmed")]
    flawed.matches, flawed.extras = ev.match_flaws(planned, [det("too_fast", 8.0, 15.0), det("low_energy", 30.0, 31.0, 0.2)])
    ev.relate_extras(planned, flawed.extras)
    flawed.matches[1].why = ["registration check: the silence after the word lasts 0.4 s (the plan asked for 1.5 to 2 s); this take is a weak example of the flaw"]
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
    assert (fast["unplanned_flags"], fast["precision"], fast["f1"]) == (1, 0.5, pytest.approx(2 / 3))        # one found, one more flag of that kind (on a clean take), nothing missed
    assert (pause["unplanned_flags"], pause["precision"], pause["f1"]) == (1, 0.0, 0.0)                      # nothing found, a stray flag of that kind on a clean take, one missed
    assert s["extras_on_flawed_takes"] == 1
    assert (s["extras_on_planned_flaws"], s["extras_next_to_planned_flaws"], s["extras_away_from_planned_flaws"]) == (0, 0, 1)     # 8 s after the planned pause
    assert (s["clean_takes"], s["clean_takes_with_a_flag"], s["false_alarms_on_clean_takes"]) == (2, 1, 2)
    assert s["clean_minutes"] == pytest.approx(2.0)
    assert (s["annotations_proposed"], s["annotations_total"], s["failed_takes"]) == (1, 2, 1)


def test_the_report_names_every_finding_miss_extra_and_failure():
    text = ev.render(results())
    assert "rec_a_flaw_fast_01  (flawed_human_controlled)  score 80" in text
    assert "FOUND   too_fast" in text and "planned 10.0-14.0 s, detected 8.0-15.0 s: start -2.0 s, end +1.0 s, overlap 57%, detected range 1.8x the plan" in text
    assert "MISSED  excessive_pause" in text and "EXTRA   low_energy" in text and "severity 0.20" in text
    assert "              - registration check: the silence after the word lasts 0.4 s" in text                      # the reason sits under the miss
    assert "severity 0.20 - away from every planned flaw" in text
    assert "extra detections on flawed takes: 1 (0 on a planned stretch, 0 right next to one, 1 away from every planned flaw)" in text
    assert "detected range 1.8x the plan; 1 flag(s) of this kind nobody planned, precision 50%, F1 0.67" in text
    assert "excessive_pause  found 0 of 1; 1 flag(s) of this kind nobody planned, F1 0.00" in text
    assert "nothing flagged" in text and "could not be replayed: its stored alignment is missing" in text
    assert "1 of 2 had at least one flag; 2 false alarms in 2.0 minutes" in text.replace("clean takes: ", "")
    assert "1 of 2 planned flaws are annotations that no person has confirmed by ear yet" in text
    assert "1 take(s) could not be replayed" in text
    text.encode("ascii")


# ---------------------------------------------------------------------------------------------------------------------------------
# Helping a person judge the findings (DEC-041)
# ---------------------------------------------------------------------------------------------------------------------------------

def test_an_extra_is_told_apart_by_where_it_lies_against_the_planned_flaws():
    planned = [A("low_energy", 25.5, 32.5, "x"), A("too_fast", 50.0, 55.0, "x")]
    extras = [det("too_slow", 27.4, 33.2), det("too_slow", 20.5, 24.5), det("too_slow", 32.5, 33.5), det("too_slow", 35.5, 37.0),
              det("too_slow", 35.75, 37.0), det("too_slow", 40.0, 41.0)]
    ev.relate_extras(planned, extras)
    assert [(e.where, e.where_note) for e in extras] == [
        ("on", "on the planned low_energy stretch"),                       # overlaps it
        ("next", "1.0 s before the planned low_energy stretch"),
        ("next", "0.0 s after the planned low_energy stretch"),            # touching is not overlapping, but it is right next to it
        ("next", "3.0 s after the planned low_energy stretch"),            # exactly the limit still counts as next to it
        ("away", "away from every planned flaw"),                          # 3.25 s
        ("away", "away from every planned flaw"),
    ]


def test_the_nearest_planned_flaw_is_the_one_an_extra_is_related_to_and_an_overlap_beats_touching():
    planned = [A("low_energy", 10.0, 20.0, "x"), A("too_fast", 24.0, 30.0, "x")]
    (between,) = [det("too_slow", 22.0, 23.0)]
    ev.relate_extras(planned, [between])
    assert between.where_note == "1.0 s before the planned too_fast stretch"               # 2 s after the first flaw, 1 s before the second
    touching_first = [A("low_energy", 10.0, 20.0, "x"), A("too_fast", 19.0, 25.0, "x")]
    inside = det("too_slow", 20.0, 22.0)                                                  # touches the first and lies in the second
    ev.relate_extras(touching_first, [inside])
    assert (inside.where, inside.where_note) == ("on", "on the planned too_fast stretch")


def test_a_take_without_planned_flaws_has_nothing_to_relate_its_extras_to_and_the_limit_can_be_changed():
    stray = det("too_slow", 1.0, 2.0)
    ev.relate_extras([], [stray])
    assert (stray.where, stray.where_note) == ("", "")
    far = det("too_slow", 36.0, 37.0)
    ev.relate_extras([A("low_energy", 25.5, 32.5, "x")], [far], near_s=5.0)
    assert far.where == "next" and far.where_note == "3.5 s after the planned low_energy stretch"


def test_the_registration_check_is_read_from_the_end_of_the_annotator_notes():
    check = ("the stretch was +2.4 dB against the rest of the take, compared with the baseline takes (the plan asked for about +8 dB); "
             "this take is a weak example of the flaw")
    notes = f"Proposed from the recording plan (sentence 3; words 30 to 47), placed by forced alignment. Not yet confirmed by ear. Take check: {check}."
    assert ev.take_check_note(notes) == check
    assert ev.take_check_note("Proposed from the recording plan. Not yet confirmed by ear.") == ""
    assert ev.take_check_note("") == "" and ev.take_check_note(None) == ""
    assert ev.take_check_note("Take check: the silence after the word lasts 1.4 s (the plan asked for 1.5 to 2 s)") == "the silence after the word lasts 1.4 s (the plan asked for 1.5 to 2 s)"


def test_the_notes_of_an_annotation_are_read_with_it(copy: World):
    name = take_id("flaw_slow")
    path = copy.data / "annotations" / f"{name}.flaws.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "Take check:" in data["flaws"][0]["annotator_notes"]
    (planned,) = ev.load_annotations(copy.data, name)
    assert planned.notes == data["flaws"][0]["annotator_notes"] and ev.take_check_note(planned.notes)
    path.write_text(json.dumps({"flaws": [{"flaw_type": "too_slow", "start_s": 2.0, "end_s": 4.0}]}), encoding="utf-8")
    assert ev.load_annotations(copy.data, name)[0].notes == ""


RULES = DetectionConfig()


def stretch(rate=None, level=None, reason=None):
    return StretchReading(rate, level, reason)


def test_a_stretch_below_the_limits_is_described_with_its_size_its_z_and_the_limits():
    pace = ev.describe_stretch("too_fast", stretch(SignalReading(14, 9.4, 1.8), SignalReading(14, 0.4, 0.3)), RULES)
    assert pace == ("those 14 words were 9% faster than the baseline readers spoke the same words (z 1.8); a finding needs a change of at least 15% "
                    "with z above 4 over at least 10 words")
    loud = ev.describe_stretch("high_energy", stretch(None, SignalReading(14, 2.46, 2.1)), RULES)
    assert loud == ("those 14 words were 2.5 dB louder than the baseline readers spoke the same words (z 2.1); a finding needs a change of at least 3 dB "
                    "with z above 4 over at least 10 words")
    assert "quieter" in ev.describe_stretch("low_energy", stretch(None, SignalReading(14, -2.0, -1.5)), RULES)
    assert "slower" in ev.describe_stretch("too_slow", stretch(SignalReading(14, -12.0, -2.5), None), RULES)


def test_the_limits_in_the_description_are_those_of_the_settings_in_use():
    strict = DetectionConfig(min_rate_change_pct=20, z_run_rate=5.5, run_min_words=12, min_energy_change_db=4.5, z_run_energy=6)
    assert "at least 20% with z above 5.5 over at least 12 words" in ev.describe_stretch("too_fast", stretch(SignalReading(14, 9.0, 1.8)), strict)
    assert "at least 4.5 dB with z above 6 over at least 12 words" in ev.describe_stretch("low_energy", stretch(None, SignalReading(14, -2.0, -1.8)), strict)


def test_a_stretch_that_changed_the_wrong_way_a_stretch_that_passes_every_limit_and_a_short_one_are_said_so():
    wrong = ev.describe_stretch("too_slow", stretch(SignalReading(12, 20.0, 5.0)), RULES)
    assert wrong.endswith(". That is the opposite of what was planned") and "20% faster" in wrong
    wrong_loudness = ev.describe_stretch("high_energy", stretch(None, SignalReading(12, -6.0, -5.0)), RULES)
    assert wrong_loudness.endswith("the opposite of what was planned") and "quieter" in wrong_loudness
    passes = ev.describe_stretch("too_fast", stretch(SignalReading(20, 60.0, 9.0)), RULES)
    assert passes.endswith("send this line to the developer") and "something else held the finding back" in passes
    short = ev.describe_stretch("too_fast", stretch(SignalReading(8, 60.0, 9.0)), RULES)
    assert "(this stretch has only 8)" in short and "passes all three" not in short                    # large enough, but too few words for a finding
    for weak in (SignalReading(20, 10.0, 9.0), SignalReading(20, 60.0, 4.0)):                          # too small a change / z exactly on the limit
        assert "passes all three" not in ev.describe_stretch("too_fast", stretch(weak), RULES)
    assert "passes all three" not in ev.describe_stretch("high_energy", stretch(None, SignalReading(20, 2.9, 9.0)), RULES)
    assert "passes all three" in ev.describe_stretch("high_energy", stretch(None, SignalReading(20, 3.0, 4.1)), RULES)             # a change of exactly the minimum counts
    assert "passes all three" in ev.describe_stretch("too_fast", stretch(SignalReading(20, 15.0, 4.1)), RULES)
    assert "passes all three" not in ev.describe_stretch("too_fast", stretch(SignalReading(20, 14.9, 9.0)), RULES)
    on_the_limit = ev.describe_stretch("too_fast", stretch(SignalReading(10, 60.0, 9.0)), RULES)                                    # exactly the words a finding needs
    assert "passes all three" in on_the_limit and "this stretch has only" not in on_the_limit
    assert "this stretch has only 9" in ev.describe_stretch("too_fast", stretch(SignalReading(9, 60.0, 9.0)), RULES)


def test_a_stretch_the_profile_could_not_judge_is_described_by_the_reason():
    assert "do not match the passage" in ev.describe_stretch("too_fast", stretch(None, None, "transcript_mismatch"), RULES)
    assert "too few words could be compared" in ev.describe_stretch("low_energy", stretch(None, None, "too_few_words"), RULES)
    assert "no word that the baseline knows lies in that stretch" in ev.describe_stretch("too_slow", stretch(SignalReading(0, None, None), None), RULES)
    assert ev.describe_stretch("excessive_pause", stretch(SignalReading(14, 9.4, 1.8), SignalReading(14, 0.4, 0.3)), RULES) == ""      # a pause is not judged word by word


def test_the_planned_stretch_is_measured_in_the_time_of_the_processed_audio_not_of_the_file(tmp_path: Path):
    profile, obs = make_profile(), hand_reading(600, stretches=[(30, 47, 0.6)])
    start, end, trimmed = float(obs.start_s[30]), float(obs.end_s[47]), 2.5          # 2.5 s of silence were cut off the start: time in the file = time in the audio + 2.5 s
    match = ev.Match(A("too_fast", start + trimmed, end + trimmed, "proposed"), None)
    ev.Evaluator(tmp_path).explain_miss(match, [], obs, profile, trimmed)
    exact = measure_stretch(obs, profile, DetectionConfig(), start, end)               # the very words of the planned stretch
    assert exact.rate.n_words == 18 and match.measured["rate"]["n_words"] == 18
    assert match.measured["rate"]["change"] == pytest.approx(exact.rate.change) and match.measured["rate"]["z"] == pytest.approx(exact.rate.z)
    assert match.measured["level"]["z"] == pytest.approx(exact.level.z)


def test_precision_and_f1_count_every_stray_flag_of_a_kind_including_those_on_clean_takes():
    s = ev.summarise(listening_results())
    low = s["types"]["low_energy"]                                   # planned once, not found, no flag of that kind anywhere
    assert (low["planned"], low["found"], low["unplanned_flags"], low["precision"], low["f1"]) == (1, 0, 0, None, 0.0)
    pause = s["types"]["excessive_pause"]                            # planned once, found, no stray flag
    assert (pause["unplanned_flags"], pause["precision"], pause["f1"]) == (0, 1.0, 1.0)
    many = ev.TakeResult("rec_b_flaw_fast_01", "flawed_human_controlled", "spk", 50.0, 90.0)
    planned = [A("too_fast", 10.0, 14.0, "x"), A("too_fast", 30.0, 34.0, "x"), A("too_fast", 50.0, 54.0, "x")]
    many.matches, many.extras = ev.match_flaws(planned, [det("too_fast", 10.0, 14.0), det("too_fast", 30.0, 34.0), det("too_fast", 70.0, 72.0), det("too_fast", 80.0, 82.0)])
    clean = ev.TakeResult("rec_b_clean_01", "clean_control", "spk", 60.0, 100.0)
    clean.extras = [det("too_fast", 5.0, 6.0)]
    fast = ev.summarise([many, clean])["types"]["too_fast"]
    assert (fast["planned"], fast["found"], fast["unplanned_flags"]) == (3, 2, 3)               # two on the flawed take, one on the clean take
    assert fast["precision"] == pytest.approx(2 / 5) and fast["f1"] == pytest.approx(2 * 2 / (2 * 2 + 3 + 1))
    broken = ev.TakeResult("rec_b_flaw_fast_02", "flawed_human_controlled", "spk", 0.0, error="x")
    assert ev.summarise([many, clean, broken])["types"]["too_fast"]["unplanned_flags"] == 3      # a take that could not be replayed adds nothing


def test_only_a_flag_of_the_same_kind_counts_as_the_planned_flaw_found_elsewhere(tmp_path: Path):
    match = ev.Match(A("too_fast", 10.0, 14.0, "proposed"), None)
    ev.Evaluator(tmp_path).explain_miss(match, [det("too_slow", 1.0, 2.0), det("too_fast", 30.0, 33.0), det("high_energy", 40.0, 41.0)], None, None, 0.0)
    elsewhere = [line for line in match.why if "found elsewhere" in line]
    assert elsewhere == ["a too_fast was found elsewhere in this take (30.0-33.0 s): the flaw may have been performed in another place than planned"]
    twice = ev.Match(A("too_slow", 10.0, 14.0, "proposed"), None)
    ev.Evaluator(tmp_path).explain_miss(twice, [det("too_slow", 1.0, 2.0), det("too_slow", 30.0, 33.0)], None, None, 0.0)
    assert any("(1.0-2.0 s, 30.0-33.0 s)" in line for line in twice.why)


def test_a_missed_flaw_is_explained_with_what_is_known_and_never_with_what_is_not(tmp_path: Path):
    check = "the stretch took 0.97 times as long as in the speaker's baseline takes (the plan asked for about 0.75); this take is a weak example of the flaw"
    plan = A("too_fast", 10.0, 14.0, "proposed", f"Proposed from the recording plan. Not yet confirmed by ear. Take check: {check}.")
    explain = ev.Evaluator(tmp_path).explain_miss
    no_measurements = ev.Match(plan, None)
    explain(no_measurements, [], None, make_profile(), 0.0)                                  # for example nothing was measured: the registration check still speaks
    assert no_measurements.why == [f"registration check: {check}"] and no_measurements.measured is None
    no_profile = ev.Match(plan, None)
    explain(no_profile, [], hand_reading(600), None, 0.0)
    assert no_profile.why[1].startswith("measured by the analysis: this baseline has no word profile (rebuild it with --build-baseline)") and no_profile.measured is None
    switched_off = ev.Match(plan, None)
    ev.Evaluator(tmp_path, detection=ev.detection_config(["use_profile=false"])).explain_miss(switched_off, [], hand_reading(600), make_profile(), 0.0)
    assert switched_off.why[1] == "measured by the analysis: the word-by-word comparison is switched off in this run" and switched_off.measured is None
    pause = ev.Match(A("excessive_pause", 10.0, 12.0, "proposed", "Take check: the silence after the word lasts 0.4 s (the plan asked for 1.5 to 2 s)."), None)
    explain(pause, [], hand_reading(600), make_profile(), 0.0)
    assert pause.why == ["registration check: the silence after the word lasts 0.4 s (the plan asked for 1.5 to 2 s)"] and pause.measured is None     # a pause is not a pace
    bare = ev.Match(A("too_slow", 10.0, 14.0, "unknown"), None)
    explain(bare, [], None, make_profile(), 0.0)
    assert bare.why == []                                                                    # nothing to say: not even a hint


def listening_results() -> List[ev.TakeResult]:
    flawed = ev.TakeResult("rec_a_flaw_quiet_01", "flawed_human_controlled", "spk_dev_01", 50.0, 90.0)
    planned = [A("low_energy", 25.5, 32.5, "proposed")]
    flawed.matches, flawed.extras = ev.match_flaws(planned, [det("too_slow", 27.0, 33.0), det("too_fast", 34.0, 38.0), det("high_energy", 1.0, 7.0),
                                                             det("high_energy", 28.0, 29.0)])
    ev.relate_extras(planned, flawed.extras)
    clean = ev.TakeResult("rec_a_clean_02", "clean_control", "spk_dev_01", 60.0, 95.0)
    clean.extras = [det("too_slow", 23.8, 28.9)]
    found = ev.TakeResult("rec_a_flaw_pause_01", "flawed_human_controlled", "spk_dev_01", 60.0, 92.0)
    found.matches, found.extras = ev.match_flaws([A("excessive_pause", 20.0, 22.0, "x")], [det("excessive_pause", 20.0, 22.0)])
    broken = ev.TakeResult("rec_a_flaw_slow_01", "flawed_human_controlled", "spk_dev_01", 0.0, error="its stored alignment is missing")
    broken.extras = [det("too_slow", 1.0, 2.0)]
    return [clean, flawed, found, broken]


def test_the_summary_counts_the_extras_on_a_planned_stretch_next_to_one_and_away_apart():
    s = ev.summarise(listening_results())
    assert s["extras_on_flawed_takes"] == 4
    assert (s["extras_on_planned_flaws"], s["extras_next_to_planned_flaws"], s["extras_away_from_planned_flaws"]) == (2, 1, 1)        # the flag on the clean take is not counted
    assert "extra detections on flawed takes: 4 (2 on a planned stretch, 1 right next to one, 1 away from every planned flaw)" in ev.render(listening_results())


def test_the_sweep_table_shows_the_extras_away_from_the_plan_apart_from_all_the_extras():
    text = ev.render_sweep([("normal settings", ev.summarise(listening_results()))], take_count=4)
    row = next(line for line in text.splitlines() if line.startswith("normal settings"))
    assert row.split()[-5:] == ["1/2", "4", "1", "1/1", "1.00"]            # found 1 of 2, extras 4 of which away 1, clean flagged 1 of 1, one false alarm in a clean minute


def test_the_listening_list_has_the_disagreements_and_not_the_side_effects():
    rows = ev.listen_first(listening_results())
    assert rows == [
        ("rec_a_clean_02", 23.8, 28.9, "too_slow flagged on a clean take"),
        ("rec_a_flaw_quiet_01", 1.0, 7.0, "high_energy flagged away from the planned flaw"),            # sorted by time inside a take
        ("rec_a_flaw_quiet_01", 25.5, 32.5, "planned low_energy, not found"),
    ]                                                                                                    # the flag on the planned stretch, the one right next to it, the found flaw and the broken take are left out
    text = ev.render(listening_results())
    assert "Listen to these first" in text and "rec_a_clean_02" in text.split("Listen to these first")[1]
    assert "  rec_a_flaw_quiet_01                  25.5-32.5 s    planned low_energy, not found" in text
    assert "rec_a_flaw_pause_01" not in text.split("Listen to these first")[1]
    text.encode("ascii")


def test_nothing_to_listen_to_when_everything_agrees_and_the_report_then_has_no_such_section():
    agree = ev.TakeResult("rec_a_flaw_pause_01", "flawed_human_controlled", "spk_dev_01", 60.0, 92.0)
    agree.matches, agree.extras = ev.match_flaws([A("excessive_pause", 20.0, 22.0, "x")], [det("excessive_pause", 20.0, 22.0)])
    clean = ev.TakeResult("rec_a_clean_01", "clean_control", "spk_dev_01", 60.0, 100.0)
    assert ev.listen_first([agree, clean]) == [] and "Listen to these first" not in ev.render([agree, clean])
    assert "extra detections on flawed takes: 0\n" in ev.render([agree, clean]) + "\n"                                # no breakdown of nothing


def test_the_detections_are_written_as_audacity_labels_next_to_the_other_labels(tmp_path: Path):
    folder = tmp_path / "data" / "processed" / "labels"
    folder.mkdir(parents=True)
    stale = folder / "rec_a_clean_01.detected.txt"
    stale.write_text("1.000\t2.000\told finding\n", encoding="utf-8")
    flawed = ev.TakeResult("rec_a_flaw_fast_01", "flawed_human_controlled", "spk_dev_01", 50.0, 80.0)
    planned = [A("too_fast", 10.0, 14.0, "proposed")]
    flawed.matches, flawed.extras = ev.match_flaws(planned, [D("too_fast", 8.0, 15.0, 0.5, "rate 296 words/min against 175 expected, z 10.9"),
                                                             D("low_energy", 30.0, 31.0, 0.2, ""), D("high_energy", 1.0, 2.0, 0.1, "")])
    ev.relate_extras(planned, flawed.extras)
    clean = ev.TakeResult("rec_a_clean_01", "clean_control", "spk_dev_01", 60.0, 100.0)
    broken = ev.TakeResult("rec_a_flaw_slow_01", "flawed_human_controlled", "spk_dev_01", 0.0, error="its stored alignment is missing")
    assert ev.write_detected_labels(tmp_path / "data", [flawed, clean, broken]) == 2
    rows = [line.split("\t") for line in (folder / "rec_a_flaw_fast_01.detected.txt").read_text(encoding="utf-8").splitlines()]
    assert rows == [["1.000", "2.000", "EXTRA high_energy severity 0.10 - away from every planned flaw"],             # in time order, whatever kind of detection
                    ["8.000", "15.000", "FOUND too_fast severity 0.50 (rate 296 words/min against 175 expected, z 10.9)"],
                    ["30.000", "31.000", "EXTRA low_energy severity 0.20 - away from every planned flaw"]]
    assert stale.read_text(encoding="utf-8") == ""                                       # nothing was flagged on the clean take: an old file must not say otherwise
    assert not (folder / "rec_a_flaw_slow_01.detected.txt").exists()                     # a take that could not be replayed gets no file


def test_the_labels_option_writes_the_files_and_says_where_and_a_sweep_refuses_it(registered: World, copy: World, capsys):
    assert ev.main(["--data-dir", str(copy.data), "--only", "flaw_fast", "--labels"]) == 0
    out = capsys.readouterr().out
    label = copy.data / "processed" / "labels" / f"{take_id('flaw_fast')}.detected.txt"
    assert "Audacity labels of the detections: 1 file(s) written to" in out and label.is_file()
    assert not (registered.data / "processed" / "labels" / f"{take_id('flaw_fast')}.detected.txt").exists()
    assert ev.main(["--data-dir", str(registered.data), "--only", "flaw_fast", "--sweep", "z_run_rate=3", "--labels"]) == 1
    assert "--labels belongs to a normal run" in capsys.readouterr().err
    assert ev.main(["--data-dir", str(registered.data), "--only", "flaw_fast"]) == 0
    assert "Audacity labels" not in capsys.readouterr().out                               # no option, no files


def test_what_the_report_adds_is_in_the_json_file_too(registered: World, tmp_path: Path):
    out_file = tmp_path / "report.json"
    assert ev.main(["--data-dir", str(registered.data), "--only", "flaw_", "--json", str(out_file)]) == 0
    saved = json.loads(out_file.read_text(encoding="utf-8"))
    assert {"extras_on_planned_flaws", "extras_next_to_planned_flaws", "extras_away_from_planned_flaws"} <= set(saved["summary"])
    take = saved["takes"][0]
    assert {"why", "measured"} <= set(take["matches"][0]) and all({"where", "where_note"} <= set(extra) for t in saved["takes"] for extra in t["extras"])


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
    for column in ("fast", "pause", "found", "extras", "away", "clean flagged", "false/min"):
        assert column in header
    normal = next(l for l in lines if l.startswith("normal settings"))
    assert "1/1" in normal and "0/1" in normal and "1/2" in normal and "2/2" not in normal.replace("1/2", "")      # fast 1/1, pause 0/1, clean flagged 1/2
    assert normal.split()[-5:] == ["1/2", "1", "1", "1/2", "1.00"]                          # found 1/2, extras 1 of which away 1, clean flagged 1/2, false/min 1.00
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
