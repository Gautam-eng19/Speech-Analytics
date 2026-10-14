"""End to end: flat pitch on synthetic readings whose pitch moves like a person's (DEC-042).

Readings of the real passage (tests/dataset_takes.human_layout with `expressive_pitch`: the intonation of the passage is shared by every reading,
each reading adds its own register, wander and word jitter, and the speaker is more or less expressive) are registered with the stand-in aligner,
the baseline is built from six of them (with its word profile and the pitch part of it), and further readings are replayed through the real analysis
with the REAL pitch tracker: four ordinary ones, one with a sentence spoken in a monotone, one with a monotone last sentence by the more reserved
speaker, and one that is flat as a whole. The checks are the ones that matter to the user: the monotone stretch is found WHERE it was put, ordinary
readings (also of the reserved speaker) are not flagged for flat pitch, the finding carries its evidence and an explanation that passes the number
guard, pitch is now part of the score, and a baseline without the pitch part says that flat pitch was not checked.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Dict, Tuple

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "dataset"))
sys.path.insert(0, str(Path(__file__).parent))

import dataset_takes as dt  # noqa: E402
import prepare_recordings as pr  # noqa: E402
from app.schemas.common import FeatureName, FlawType  # noqa: E402
from app.schemas.contracts import BaselineStatsRecord  # noqa: E402
from test_prepare_recordings import World  # noqa: E402
from test_profile_e2e import ENTRY, S3, S5, WORDS, analysis  # noqa: E402

DATA_NOTE = "p001"


def name(kind: str, number: int = 1) -> str:
    return f"rec_p001_spk_dev_01_{kind}_{number:02d}"


def reading(seed: int, scale: float = 1.0) -> dt.Layout:
    return dt.human_layout(WORDS, seed, amplitude=0.1, expressive_pitch=True, pitch_scale=scale)


def where(layout: dt.Layout, first: int, last: int) -> Tuple[float, float]:
    """The true time of words first..last (1-based) on the timeline of the written file (= source time)."""
    times = layout.times()
    return times[first - 1][0], times[last - 1][1]


def overlap(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


@pytest.fixture(scope="module")
def registered(tmp_path_factory) -> World:
    world = World(tmp_path_factory.mktemp("pitch_e2e"))
    world.passages.write_text(json.dumps([ENTRY]), encoding="utf-8")
    for n in range(1, 7):
        world.add(name("base", n), reading(100 + n, 1.0 if n % 2 else 0.8), seed=n)
    for n in range(1, 5):
        world.add(name("clean", n), reading(200 + n, 1.0 if n % 2 else 0.8), seed=10 + n)
    flat_one = dt.flatten_pitch(reading(305), *S3, scale=0.1)
    flat_two = dt.flatten_pitch(reading(306, 0.8), *S5, scale=0.1)
    world.add(name("clean", 5), flat_one, seed=25)
    world.add(name("clean", 6), flat_two, seed=26)
    world.add(name("clean", 7), reading(307, 0.1), seed=27)
    world.write_plan()
    preparer = pr.Preparer(world.data, world.passages, world.plan, aligner=dt.BurstAligner(), out=lambda _l: None, today="2026-10-14")
    world.report = preparer.run([world.incoming], build_baseline=True)
    world.where = {5: where(flat_one, *S3), 6: where(flat_two, *S5)}
    assert all(t.status == "registered" for t in world.report.takes), [(t.take_id, t.problem) for t in world.report.takes if t.status == "failed"]
    assert world.report.baselines[0][1] is not None
    return world


@pytest.fixture(scope="module")
def results(registered: World) -> Dict[int, object]:
    return {n: analysis(registered.data, name("clean", n)) for n in range(1, 8)}


def flat(result):
    return [f for f in result.flaws if f.type == FlawType.FLAT_PITCH]


# ------------------------------------------------------------------------------------------------------------------------------
def test_the_baseline_has_the_pitch_part_and_the_registration_report_says_so(registered: World):
    record = BaselineStatsRecord.model_validate_json((registered.data / "processed" / "baseline_stats" / f"{DATA_NOTE}.json").read_text(encoding="utf-8"))
    pitch = record.word_profile.pitch
    assert pitch is not None and len(pitch.movement_st2) == len(WORDS) and record.verify_sha256()
    assert (pitch.min_voiced_frames, pitch.deviation_clip_st) == (5, 6.0) and pitch.noise.word > 0.0
    assert "pitch profile: built" in pr.render(registered.report, registered.data)


def test_ordinary_readings_of_both_speakers_are_not_flagged_for_flat_pitch(results):
    for n in (1, 2, 3, 4):
        assert flat(results[n]) == [], n
        assert not any(note.code == "pitch_not_judged" for note in results[n].notes), n


def test_a_monotone_sentence_is_found_on_the_words_it_was_put_on(registered: World, results):
    (flaw,) = flat(results[5])
    planned = registered.where[5]
    assert flaw.rule.feature == "pitch_run_z" and flaw.rule.direction == "below"
    assert overlap((flaw.start_s, flaw.end_s), planned) / (planned[1] - planned[0]) >= 0.7             # most of the sentence is inside the finding
    assert abs(flaw.start_s - planned[0]) <= 1.5 and abs(flaw.end_s - planned[1]) <= 1.5
    assert flaw.end_s - flaw.start_s <= 1.6 * (planned[1] - planned[0])                              # and it is not several times too long


def test_a_monotone_sentence_of_the_more_reserved_speaker_is_found_too(registered: World, results):
    (flaw,) = flat(results[6])
    planned = registered.where[6]
    assert overlap((flaw.start_s, flaw.end_s), planned) / (planned[1] - planned[0]) >= 0.7
    assert abs(flaw.start_s - planned[0]) <= 1.5 and abs(flaw.end_s - planned[1]) <= 1.5


def test_a_reading_that_is_flat_as_a_whole_is_one_finding_over_the_recording(results):
    (flaw,) = flat(results[7])
    assert flaw.rule.feature == "pitch_overall_z" and flaw.end_s - flaw.start_s > 0.8 * results[7].audio.duration_s


def test_the_finding_carries_its_evidence_and_an_explanation_that_passes_the_number_guard(results):
    (flaw,) = flat(results[5])
    ev = flaw.evidence
    assert ev.f0_std_hz_in_window < 0.5 * ev.f0_std_baseline_hz and ev.f0_std_z < -4.0 and 0.0 < ev.f0_voiced_fraction <= 1.0
    assert 0.0 < flaw.severity <= 1.0 and flaw.affected_words and flaw.explanation_method.value == "template"
    assert "more monotone" in flaw.explanation and f"{ev.f0_std_hz_in_window:.1f}" in flaw.explanation and f"{ev.f0_std_baseline_hz:.1f}" in flaw.explanation
    assert "melody" in flaw.recommendation and not any(n.code == "explanation_fallback_used" for n in results[5].notes)


def test_pitch_is_part_of_the_score_and_a_flat_stretch_lowers_it(results):
    clean, flawed = results[1].scores, results[5].scores
    assert FeatureName.PITCH in clean.feature_scores and clean.feature_scores[FeatureName.PITCH].score == 100.0
    assert flawed.feature_scores[FeatureName.PITCH].score < 100.0 and flawed.feature_scores[FeatureName.PITCH].flaw_count == 1
    assert flawed.composite_score < clean.composite_score
    assert not any(n.code == "pitch_not_scored" for n in results[5].notes)


def test_a_baseline_without_the_pitch_part_says_flat_pitch_was_not_checked(registered: World, tmp_path: Path):
    shutil.copytree(registered.data, tmp_path / "data")
    path = tmp_path / "data" / "processed" / "baseline_stats" / f"{DATA_NOTE}.json"
    record = BaselineStatsRecord.model_validate_json(path.read_text(encoding="utf-8"))
    plain = record.model_copy(update={"word_profile": record.word_profile.model_copy(update={"pitch": None})}).with_computed_sha256()
    path.write_text(plain.model_dump_json(indent=2), encoding="utf-8")
    result = analysis(tmp_path / "data", name("clean", 5))
    assert flat(result) == []
    (note,) = [n for n in result.notes if n.code == "pitch_not_judged"]
    assert "no pitch profile" in note.message
    assert any(n.code == "pitch_not_scored" for n in result.notes)                                  # and pitch is left out of the score, as before


def test_the_analysis_with_pitch_is_reproducible(registered: World):
    one = analysis(registered.data, name("clean", 5))
    two = analysis(registered.data, name("clean", 5))
    assert one.deterministic_json() == two.deterministic_json()
