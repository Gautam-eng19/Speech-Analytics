"""End to end: the word-by-word comparison with the baseline on synthetic readings that behave like a person's (DEC-040).

Readings of the real passage (tests/dataset_takes.human_layout: what a word is decides how long it takes and how loud it is, plus chance variation and
two speakers of a slightly different pace) are registered with the stand-in aligner, the baseline is built from them (with its word profile), and the
registered takes are replayed through the real analysis. A faster, a slower, a louder and a quieter sentence and a long pause were put into five takes;
three further readings are clean. The checks are the ones that matter to the user: the planned flaws are found, they are found WHERE they were put (the
words, not a window of eight seconds), nothing is flagged on the clean readings, the same data analysed with the old overall statistics shows what was
wrong before, and a baseline without a profile, or a transcript that does not match, falls back openly.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Dict

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "dataset"))
sys.path.insert(0, str(Path(__file__).parent))

import dataset_takes as dt  # noqa: E402
import evaluate_takes as ev  # noqa: E402
import passage_text as pt  # noqa: E402
import prepare_recordings as pr  # noqa: E402
from app.schemas.contracts import BaselineStatsRecord  # noqa: E402
from app.schemas.request import AnalyzeRequest  # noqa: E402
from test_prepare_recordings import World  # noqa: E402

REPO = Path(__file__).parent.parent
ENTRY = next(e for e in json.loads((REPO / "data" / "plan" / "passages_v1.json").read_text(encoding="utf-8")) if e["passage_id"] == "p001")
SENTENCES = pt.passage_words(ENTRY["text"])
WORDS = [w for s in SENTENCES for w in s]
RANGES = []
_at = 1
for _s in SENTENCES:
    RANGES.append((_at, _at + len(_s) - 1))
    _at += len(_s)
S2, S3, S4, S5 = RANGES[1], RANGES[2], RANGES[3], RANGES[4]        # sentences of 18, 22, 19 and 17 words (1-based word numbers)


def name(kind: str, number: int = 1) -> str:
    return f"rec_p001_spk_dev_01_{kind}_{number:02d}"


def reading(seed: int, tempo: float = 1.0) -> dt.Layout:
    return dt.human_layout(WORDS, seed, tempo=tempo, amplitude=0.1)


def build(root: Path) -> World:
    world = World(root)
    world.passages.write_text(json.dumps([ENTRY]), encoding="utf-8")
    for n, tempo in enumerate((0.95, 1.05, 0.95, 1.05, 0.95, 1.05), start=1):
        world.add(name("base", n), reading(100 + n, tempo), seed=n)
    for n, tempo in enumerate((1.0, 1.08, 0.97), start=1):
        world.add(name("clean", n), reading(200 + n, tempo), seed=10 + n)
    world.add(name("flaw_fast"), dt.speed_stretch(reading(301), *S3, 0.55), seed=21)
    world.add(name("flaw_slow"), dt.speed_stretch(reading(302), *S5, 1.8), seed=22)
    world.add(name("flaw_loud"), dt.level_stretch(reading(303), *S2, 8.0), seed=23)
    world.add(name("flaw_quiet"), dt.level_stretch(reading(304), *S4, -8.0), seed=24)
    world.add(name("flaw_pause"), dt.pause_after(reading(305), S3[0] + 6, 3.0), seed=25)
    world.plan_rows = [
        dt.plan_row(name("flaw_fast"), "too_fast", *S3), dt.plan_row(name("flaw_slow"), "too_slow", *S5),
        dt.plan_row(name("flaw_loud"), "high_energy", *S2), dt.plan_row(name("flaw_quiet"), "low_energy", *S4),
        dt.plan_row(name("flaw_pause"), "excessive_pause", S3[0] + 6, S3[0] + 7, pause_after=S3[0] + 6),
    ]
    world.write_plan()
    return world


@pytest.fixture(scope="module")
def registered(tmp_path_factory) -> World:
    world = build(tmp_path_factory.mktemp("profile_e2e"))
    preparer = pr.Preparer(world.data, world.passages, world.plan, aligner=dt.BurstAligner(), out=lambda _l: None, today="2026-10-13")
    report = preparer.run([world.incoming], build_baseline=True)
    assert all(t.status == "registered" for t in report.takes), [(t.take_id, t.problem) for t in report.takes if t.status == "failed"]
    assert report.baselines[0][1] is not None
    world.report = report
    return world


@pytest.fixture(scope="module")
def replay(registered: World) -> Dict[str, ev.TakeResult]:
    return {r.recording_id: r for r in ev.Evaluator(registered.data).run(["dev"])}


def analysis(data: Path, take: str, text=None):
    """The full AnalysisResult of one registered take (replayed alignment, the passage text as the transcript unless `text` is given)."""
    evaluator = ev.Evaluator(data)
    entry = next(e for e in evaluator.select(["dev"], True, take))
    with tempfile.TemporaryDirectory() as tmp:
        pipeline = evaluator.pipeline_for(entry, Path(tmp))
        wav = data.parent / entry["audio_file"]
        request = AnalyzeRequest(baseline_id="p001", passage_id="p001", manual_transcript=text or ENTRY["text"])
        return pipeline.analyze(wav.read_bytes(), request)


# ------------------------------------------------------------------------------------------------------------------------------
def test_registration_builds_the_word_profile_and_says_so(registered: World):
    record = BaselineStatsRecord.model_validate_json((registered.data / "processed" / "baseline_stats" / "p001.json").read_text(encoding="utf-8"))
    profile = record.word_profile
    assert profile is not None and profile.n_takes == 6 and len(profile.words) == len(WORDS) == len(profile.slot_s)
    assert profile.max_gap_s == 0.25 and 0.04 < profile.tempo_sd < 0.12 and record.verify_sha256()
    assert 0.1 < profile.rate_noise.word < 0.35 and 1.0 < profile.level_noise.word < 4.0
    text = pr.render(registered.report, registered.data)
    assert "word-by-word profile: built (6 take(s) matched the passage text)" in text


def test_every_planned_flaw_is_found_where_it_was_put(replay):
    for take, kind in (("flaw_fast", "too_fast"), ("flaw_slow", "too_slow"), ("flaw_loud", "high_energy"), ("flaw_quiet", "low_energy"),
                       ("flaw_pause", "excessive_pause")):
        (match,) = replay[name(take)].matches
        assert match.planned.flaw_type == kind and match.found is not None, f"{kind} was not found"
        assert match.iou >= 0.7, f"{kind}: overlap {match.iou:.0%}"
        assert abs(match.start_error_s) <= 1.5 and abs(match.end_error_s) <= 1.5 and 0.7 <= match.range_ratio <= 1.3


def test_the_found_ranges_are_those_of_the_flawed_sentences_not_of_eight_second_windows(replay):
    for take in ("flaw_fast", "flaw_slow", "flaw_loud", "flaw_quiet"):
        (match,) = replay[name(take)].matches
        assert 0.65 <= match.range_ratio <= 1.35, f"{take}: detected range {match.range_ratio:.2f}x the plan"      # off by a word or two at each end, not by seconds


def test_no_pace_or_loudness_is_flagged_on_the_clean_readings_or_outside_the_flawed_sentences(replay):
    def pace_or_loudness(extras):
        return [(e.flaw_type, e.start_s, e.end_s, e.note) for e in extras if e.flaw_type != "excessive_pause"]

    for n in (1, 2, 3):
        r = replay[name("clean", n)]
        assert r.error == "" and pace_or_loudness(r.extras) == [], n
        assert all(e.severity < 0.4 for e in r.extras)                                  # a natural pause just over the floor is a mild finding at most
    for take in ("flaw_fast", "flaw_slow", "flaw_loud", "flaw_quiet", "flaw_pause"):
        assert pace_or_loudness(replay[name(take)].extras) == [], take


def test_the_old_overall_statistics_never_see_a_louder_or_quieter_sentence_on_the_same_takes(registered: World):
    legacy = ev.Evaluator(registered.data, detection=ev.detection_config(["use_profile=false"]))
    for take in ("flaw_loud", "flaw_quiet"):
        (result,) = legacy.run(["dev"], only=take)
        assert result.matches[0].found is None                                      # the frame rule never saw an 8 dB change in a sentence


def test_the_findings_carry_the_run_of_words_their_evidence_and_a_size_based_severity(registered: World):
    result = analysis(registered.data, "flaw_fast")
    (fast,) = [f for f in result.flaws if f.type.value == "too_fast"]
    assert fast.rule.feature == "rate_run_z" and fast.rule.direction == "above"
    ev_ = fast.evidence
    assert ev_.rate_participant_wpm > 1.5 * ev_.rate_baseline_mean_wpm and ev_.rate_delta_pct > 50.0
    assert (ev_.rate_participant_wpm - ev_.rate_baseline_mean_wpm) / ev_.rate_baseline_std_wpm == pytest.approx(ev_.rate_z_score, abs=0.01)
    assert 0.3 < fast.severity <= 1.0 and fast.affected_words and "words" in fast.warnings[0]
    assert not any(n.code in ("baseline_without_profile", "profile_not_applicable") for n in result.notes)
    loud = analysis(registered.data, "flaw_loud")
    (up,) = [f for f in loud.flaws if f.type.value == "high_energy"]
    assert up.rule.feature == "energy_run_z" and 5.0 < up.evidence.energy_delta_db < 11.0


def test_a_long_pause_is_judged_by_its_length_and_does_not_make_the_words_around_it_look_slow(registered: World):
    result = analysis(registered.data, "flaw_pause")
    assert {f.type.value for f in result.flaws} == {"excessive_pause"}              # no too_slow from the silence around it
    pause = max(result.flaws, key=lambda f: f.evidence.pause_duration_s)
    assert pause.evidence.pause_duration_s == pytest.approx(3.0, abs=0.3) and 0.55 < pause.severity < 0.95      # (3.0 - ~0.5) of the 3.5 s scale
    assert all(f.severity < 0.4 for f in result.flaws if f is not pause)


def test_a_baseline_without_a_profile_falls_back_to_the_overall_statistics_and_says_so(registered: World, tmp_path: Path):
    shutil.copytree(registered.data, tmp_path / "data")
    path = tmp_path / "data" / "processed" / "baseline_stats" / "p001.json"
    plain = BaselineStatsRecord.model_validate_json(path.read_text(encoding="utf-8")).model_copy(update={"word_profile": None}).with_computed_sha256()
    path.write_text(plain.model_dump_json(indent=2), encoding="utf-8")
    result = analysis(tmp_path / "data", "flaw_loud")
    assert any(n.code == "baseline_without_profile" for n in result.notes)
    assert not any(f.type.value == "high_energy" for f in result.flaws)                 # the overall frame rule does not see it
    assert not any(f.rule.feature.endswith("_run_z") for f in result.flaws)


def test_a_transcript_that_is_not_the_passage_falls_back_and_says_so(registered: World):
    result = analysis(registered.data, "flaw_fast", text=" ".join(["wrong"] * len(WORDS)))
    assert any(n.code == "profile_not_applicable" for n in result.notes) or any(n.code == "content_mismatch" for n in result.notes)


def test_the_analysis_is_reproducible(registered: World):
    one = analysis(registered.data, "flaw_slow")
    two = analysis(registered.data, "flaw_slow")
    assert one.deterministic_json() == two.deterministic_json()


def test_the_sweep_table_compares_settings_on_these_takes(registered: World):
    rows, count = ev.sweep(registered.data, ["z_run_rate=40", "min_pause_s=5"], ["dev"], False, "flaw_", False, False)
    assert count == 5 and [label for label, _ in rows] == ["normal settings", "z_run_rate=40", "min_pause_s=5"]
    found = {label: sum(v["found"] for v in s["types"].values()) for label, s in rows}
    assert found["normal settings"] == 5                                               # all five planned flaws
    assert found["z_run_rate=40"] == 3                                                 # no pace finding can reach 40 spreads: loudness and the pause remain
    assert found["min_pause_s=5"] == 4                                                 # a pause floor above the 3 s pause hides it
    table = ev.render_sweep(rows, count)
    assert "normal settings" in table and "z_run_rate=40" in table and "false/min" in table
    table.encode("ascii")
