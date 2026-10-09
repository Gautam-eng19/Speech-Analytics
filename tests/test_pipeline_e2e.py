"""The orchestrated pipeline on synthetic speech with injected, known flaws (DEC-016, DEC-023, DEC-029, DEC-032).

Everything is real - preprocessing, F0 / energy / rate / pause features, normalization, detection, severity, evidence, scoring,
explanations, assembly, cache - except the two heavyweight models. Whisper and WhisperX cannot be downloaded in CI, so they are
replaced by stand-ins that answer from the known synthetic timings (`FakeTranscriber`, `FakeAligner`); exact word timings are also
what makes the assertions below exact. The REAL models are therefore not exercised here (see the smoke tests).

Scenario (same as test_flaw_detection_e2e.py): the participant starts like the baseline, then

    words 12-19   very quiet                    -> low_energy
    gap after 19  1.5 s of silence mid-phrase   -> excessive_pause
    words 20-35   fast                          -> too_fast

What is verified here, beyond the detection itself:
    * the result is a valid, JSON-round-trippable `AnalysisResult` whose flaws are complete (time, evidence, rule, text);
    * all response times are in SOURCE time, converted exactly once (a recording with leading/trailing silence moves every time
      by exactly the trim offset - not by 0 and not by twice that);
    * the result is deterministic across independent pipeline instances, and served from the cache (also across instances);
    * the cache key reacts to every input that can change the stored result;
    * notes state what was not evaluated or limited; one analysis runs at a time.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "dataset"))

import build_baseline_stats as bbs  # noqa: E402
from app.core.baseline import BaselineProvider  # noqa: E402
from app.core.cache import ResultCache  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.passages import PassageCatalog  # noqa: E402
from app.schemas.common import API_CONTRACT_VERSION, ExplanationMethod, FeatureName, FlawType, TranscriptSource  # noqa: E402
from app.schemas.request import AnalyzeRequest  # noqa: E402
from app.schemas.response import AnalysisResult  # noqa: E402
from app.services.audio import AudioPreprocessor  # noqa: E402
from app.services.features.energy import extract_energy  # noqa: E402
from app.services.features.f0 import extract_f0  # noqa: E402
from app.services.features.pause import detect_pauses  # noqa: E402
from app.services.features.rate import extract_rate  # noqa: E402
from app.services.grounding import DetectionConfig  # noqa: E402
from app.services.pipeline import AnalysisPipeline, PipelineConfig  # noqa: E402
from synthetic_speech import FakeAligner, FakeTranscriber, build_speech, normal_delivery  # noqa: E402

GAPS = {5: 0.4, 11: 0.6, 17: 0.3}
FLAWED_ITEMS = (
    normal_delivery(12, special_gaps=GAPS) + [("gap", 0.6)]
    + normal_delivery(8, amp_scale=0.1, start_index=12) + [("gap", 1.5)]
    + normal_delivery(16, word_dur=0.2, gap=0.03, start_index=20)
)
SHORT_ITEMS = normal_delivery(10, special_gaps={4: 0.4})
LEAD_S, TAIL_S = 1.0, 0.8
RICH_GAPS = {k: g for r in range(4) for k, g in {5 + 24 * r: 0.4, 11 + 24 * r: 0.6, 17 + 24 * r: 0.3}.items()}
REQUEST = AnalyzeRequest(baseline_id="p001", passage_id="p001")


# ------------------------------------------------------------------------------------ workspace
def _record_from(items, passage_id: str = "p001"):
    """Baseline statistics built (as the offline script does) from one clean take."""
    wav, aligned = build_speech(items)
    audio = AudioPreprocessor().process(wav)
    energy = extract_energy(audio)
    f0, rate = extract_f0(audio), extract_rate(aligned)
    pauses = detect_pauses(aligned=aligned, energy=energy).events
    rec = bbs.RecordingFeatures("rec_base", f0.voiced_values_hz, energy.values_db, rate.words_per_min, pauses)
    return bbs.aggregate_baseline_stats(passage_id, "1.0.0", [rec])


def _write_baseline(record, directory: Path, stem: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    text = json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True, allow_nan=False)
    (directory / f"{stem}.json").write_text(text + "\n", encoding="utf-8")


@dataclass
class Workspace:
    root: Path
    baselines: Path
    passages: Path
    passage_text: str


@pytest.fixture(scope="module")
def workspace(tmp_path_factory) -> Workspace:
    root = tmp_path_factory.mktemp("pipeline_e2e")
    baselines = root / "baselines"
    _write_baseline(_record_from(normal_delivery(24, special_gaps=GAPS)), baselines, "p001")            # a thin baseline
    _write_baseline(_record_from(normal_delivery(96, special_gaps=RICH_GAPS)), baselines, "p001_rich")  # a well-supported one
    _write_baseline(_record_from(normal_delivery(24, special_gaps=GAPS), passage_id="p002"), baselines, "p002")
    passage_text = build_speech(FLAWED_ITEMS)[1].text
    passages = root / "passages.json"
    passages.write_text(json.dumps([{"passage_id": "p001", "text": passage_text}]), encoding="utf-8")
    return Workspace(root, baselines, passages, passage_text)


@dataclass
class Run:
    result: AnalysisResult
    pipeline: AnalysisPipeline
    transcriber: FakeTranscriber
    aligner: FakeAligner
    wav: bytes
    cache_dir: Path


def make_pipeline(ws: Workspace, aligned, cache_dir: Path, *, transcript_text: Optional[str] = None,
                  config: Optional[PipelineConfig] = None, passages: Optional[Path] = None,
                  baselines: Optional[Path] = None) -> tuple:
    transcriber = FakeTranscriber(aligned.text if transcript_text is None else transcript_text)
    aligner = FakeAligner(aligned)
    pipeline = AnalysisPipeline(
        transcriber=transcriber, aligner=aligner, baseline_provider=BaselineProvider(baselines or ws.baselines),
        cache=ResultCache(cache_dir), passages=PassageCatalog(passages if passages is not None else ws.passages), config=config,
    )
    return pipeline, transcriber, aligner


def run_analysis(ws: Workspace, items, name: str, request: AnalyzeRequest = REQUEST, **kwargs) -> Run:
    wav, aligned = build_speech(items)
    cache_dir = ws.root / f"cache_{name}"
    pipeline, transcriber, aligner = make_pipeline(ws, aligned, cache_dir, **kwargs)
    return Run(pipeline.analyze(wav, request), pipeline, transcriber, aligner, wav, cache_dir)


@pytest.fixture(scope="module")
def plain(workspace) -> Run:
    return run_analysis(workspace, FLAWED_ITEMS, "plain")


@pytest.fixture(scope="module")
def shifted(workspace) -> Run:
    """The same speech inside a longer file: LEAD_S of silence before it and TAIL_S after it."""
    return run_analysis(workspace, [("gap", LEAD_S)] + FLAWED_ITEMS + [("gap", TAIL_S)], "shifted")


def _codes(result: AnalysisResult) -> List[str]:
    return [n.code for n in result.notes]


# --------------------------------------------------------------------------------- the result
def test_result_is_a_valid_contract_object_and_survives_a_json_round_trip(plain):
    res = plain.result
    assert res.api_contract_version == API_CONTRACT_VERSION
    assert AnalysisResult.model_validate_json(res.model_dump_json()) == res
    assert AnalysisResult.model_validate(json.loads(res.model_dump_json())) == res
    assert res.config_version == settings.CONFIG_VERSION and res.pipeline_version == settings.PIPELINE_VERSION
    assert res.baseline.baseline_id == "p001" and res.baseline.passage_id == "p001" and res.baseline.sha256


def test_exactly_the_injected_flaws_are_reported_in_time_order(plain):
    flaws = plain.result.flaws
    assert [(f.flaw_id, f.type) for f in flaws] == [
        ("flaw_001", FlawType.LOW_ENERGY), ("flaw_002", FlawType.TOO_FAST), ("flaw_003", FlawType.EXCESSIVE_PAUSE)]
    assert [f.start_s for f in flaws] == sorted(f.start_s for f in flaws)


def test_flaws_are_located_on_the_injected_words(plain):
    _, aligned = build_speech(FLAWED_ITEMS)
    w = aligned.words
    low, fast, pause = plain.result.flaws
    assert low.start_s == pytest.approx(w[12].start_s, abs=0.03) and low.end_s == pytest.approx(w[19].end_s, abs=0.03)
    assert low.affected_words == [f"w{i}" for i in range(12, 20)]
    assert pause.start_s == pytest.approx(w[19].end_s, abs=0.03) and pause.end_s == pytest.approx(w[20].start_s, abs=0.03)
    assert pause.affected_words == ["w19", "w20"]
    assert fast.end_s == pytest.approx(w[35].end_s, abs=0.05) and fast.start_s < w[20].start_s    # window resolution


def test_every_flaw_is_complete_and_its_text_uses_its_own_numbers(plain):
    for f in plain.result.flaws:
        assert f.duration_s == pytest.approx(f.end_s - f.start_s, abs=2e-4) and 0.0 < f.severity <= 1.0
        assert f.rule is not None and f.evidence is not None
        assert f.explanation_method == ExplanationMethod.TEMPLATE and not f.low_confidence
        assert f.explanation.strip() and f.recommendation.strip()
        assert f"{f.start_s:.1f}" in f.explanation and f"{f.end_s:.1f}" in f.explanation
    assert "explanation_fallback_used" not in _codes(plain.result)          # every text passed the number guard unchanged


def test_scores_follow_the_flaws_and_leave_pitch_out(plain):
    res = plain.result
    scores = res.scores
    assert set(scores.feature_scores) == {FeatureName.SPEECH_RATE, FeatureName.PAUSES, FeatureName.ENERGY}
    by_feature = {FeatureName.SPEECH_RATE: FlawType.TOO_FAST, FeatureName.PAUSES: FlawType.EXCESSIVE_PAUSE,
                  FeatureName.ENERGY: FlawType.LOW_ENERGY}
    flaw_by_type = {f.type: f for f in res.flaws}
    for feature, flaw_type in by_feature.items():
        fs = scores.feature_scores[feature]
        flaw = flaw_by_type[flaw_type]
        assert fs.flaw_count == 1
        assert fs.penalty_total == pytest.approx(settings.BASE_PENALTY * flaw.severity * flaw.reliability, abs=0.01)
        assert fs.score == pytest.approx(100.0 - fs.penalty_total, abs=0.01)
    assert sum(fs.weight for fs in scores.feature_scores.values()) == pytest.approx(1.0, abs=1e-5)
    assert scores.composite_score == pytest.approx(sum(fs.weight * fs.score for fs in scores.feature_scores.values()), abs=0.01)
    assert "pitch_not_scored" in _codes(res)
    assert "pitch" in res.overall_summary.lower()


def test_transcript_alignment_and_features_are_present_and_finite(plain):
    res = plain.result
    _, aligned = build_speech(FLAWED_ITEMS)
    assert res.transcript == aligned.text and len(res.alignment) == len(aligned.words)
    assert [w.word for w in res.alignment] == [w.word for w in aligned.words]
    feats = res.features
    assert len(feats.f0_timeline.times_s) == len(feats.f0_timeline.values_hz) > 0
    assert len(feats.energy_timeline.times_s) > 0 and len(feats.speech_rate_timeline.times_s) > 0
    assert feats.pause_events and feats.mfcc_summary is not None
    assert res.processing_meta.transcript_source == TranscriptSource.ASR and res.processing_meta.whisper_model == "small.en"
    assert res.processing_meta.cached is False and res.alignment_method == aligned.alignment_method


# ----------------------------------------------------------------------- source-time conversion
def test_a_recording_with_leading_and_trailing_silence_is_reported_in_source_time(plain, shifted):
    a, b = plain.result, shifted.result
    assert a.audio.trim_start_s == 0.0
    assert b.audio.trim_start_s == pytest.approx(LEAD_S, abs=1e-6)
    assert b.audio.duration_s == pytest.approx(a.audio.duration_s, abs=0.02)         # the trimmed signal is the same speech
    assert b.audio.source_duration_s == pytest.approx(a.audio.source_duration_s + LEAD_S + TAIL_S, abs=0.02)
    assert [f.type for f in b.flaws] == [f.type for f in a.flaws]
    for fa, fb in zip(a.flaws, b.flaws):
        assert fb.start_s == pytest.approx(fa.start_s + LEAD_S, abs=0.02), fb.flaw_id         # not +0 (missing), not +2 (twice)
        assert fb.end_s == pytest.approx(fa.end_s + LEAD_S, abs=0.02), fb.flaw_id
        assert fb.duration_s == pytest.approx(fa.duration_s, abs=0.02)
        assert fb.severity == pytest.approx(fa.severity, abs=0.01)
        assert f"{fb.start_s:.1f}" in fb.explanation                                # the text speaks in source time as well
    assert b.scores.composite_score == pytest.approx(a.scores.composite_score, abs=0.5)


def test_every_timeline_moves_by_the_offset_and_only_once(plain, shifted):
    a, b = plain.result, shifted.result
    assert len(b.alignment) == len(a.alignment)
    for wa, wb in zip(a.alignment, b.alignment):
        assert wb.word == wa.word
        assert wb.start_s == pytest.approx(wa.start_s + LEAD_S, abs=2e-3) and wb.end_s == pytest.approx(wa.end_s + LEAD_S, abs=2e-3)
    for name in ("f0_timeline", "energy_timeline", "speech_rate_timeline"):
        ta, tb = getattr(a.features, name).times_s, getattr(b.features, name).times_s
        assert abs(len(ta) - len(tb)) <= 2, name
        n = min(len(ta), len(tb))
        assert all(abs((tb[i] - ta[i]) - LEAD_S) < 2e-3 for i in range(n)), name
    assert len(b.features.pause_events) == len(a.features.pause_events)
    for pa, pb in zip(a.features.pause_events, b.features.pause_events):
        assert pb.start_s == pytest.approx(pa.start_s + LEAD_S, abs=2e-3) and pb.end_s == pytest.approx(pa.end_s + LEAD_S, abs=2e-3)
        assert pb.duration_s == pytest.approx(pa.duration_s, abs=2e-3)


def test_every_reported_time_lies_within_the_source_recording(shifted):
    res = shifted.result
    limit = res.audio.source_duration_s
    assert all(0.0 <= w.start_s <= w.end_s <= limit + 0.02 for w in res.alignment)
    assert all(0.0 <= f.start_s < f.end_s <= limit + 0.02 for f in res.flaws)
    assert all(t <= limit + 0.02 for t in res.features.energy_timeline.times_s)


def test_position_in_the_file_and_file_length_are_each_part_of_the_analysis_id(workspace):
    """The audio hash covers only the trimmed samples, so the offset and the file length must be keyed separately.

    A and B: same speech, same file length, different offset.  A and C: same speech, same offset, different file length.
    """
    a = run_analysis(workspace, [("gap", 1.0)] + SHORT_ITEMS + [("gap", 1.0)], "pos_a").result
    b = run_analysis(workspace, [("gap", 2.0)] + SHORT_ITEMS, "pos_b").result
    c = run_analysis(workspace, [("gap", 1.0)] + SHORT_ITEMS, "pos_c").result
    assert a.audio.sha256 == b.audio.sha256 == c.audio.sha256
    assert a.audio.source_duration_s == pytest.approx(b.audio.source_duration_s, abs=1e-6)
    assert a.audio.trim_start_s != b.audio.trim_start_s
    assert a.audio.trim_start_s == c.audio.trim_start_s and a.audio.source_duration_s != c.audio.source_duration_s
    assert len({a.analysis_id, b.analysis_id, c.analysis_id}) == 3


def test_rebuilt_baseline_statistics_under_the_same_id_are_a_different_analysis(workspace):
    """A baseline file that is replaced by new content (same id) must not be answered from the old cache entry."""
    rebuilt = workspace.root / "baselines_rebuilt"
    _write_baseline(_record_from(normal_delivery(96, special_gaps=RICH_GAPS)), rebuilt, "p001")
    original = run_analysis(workspace, SHORT_ITEMS, "rebuilt_original").result
    replaced = run_analysis(workspace, SHORT_ITEMS, "rebuilt_replaced", baselines=rebuilt).result
    assert replaced.baseline.baseline_id == original.baseline.baseline_id == "p001"
    assert replaced.baseline.sha256 != original.baseline.sha256
    assert replaced.analysis_id != original.analysis_id


# --------------------------------------------------------------------------- determinism / cache
def test_independent_pipelines_give_identical_results(workspace, plain):
    again = run_analysis(workspace, FLAWED_ITEMS, "plain_again")
    assert again.result.deterministic_json() == plain.result.deterministic_json()
    assert again.result.analysis_id == plain.result.analysis_id
    assert again.result.config_fingerprint == plain.result.config_fingerprint


def test_a_second_request_is_served_from_the_cache(workspace):
    run = run_analysis(workspace, FLAWED_ITEMS, "cache_hit")
    first = run.result
    calls = (run.transcriber.calls, run.aligner.calls)
    assert calls == (1, 1) and first.processing_meta.cached is False
    assert (run.cache_dir / f"{first.analysis_id}.json").is_file()

    second = run.pipeline.analyze(run.wav, REQUEST)
    assert second.processing_meta.cached is True and second.analysis_id == first.analysis_id
    assert (run.transcriber.calls, run.aligner.calls) == calls                      # nothing was recomputed
    assert second.deterministic_json() == first.deterministic_json()

    # A new pipeline instance on the same cache directory (e.g. after a restart) also hits it.
    _, aligned = build_speech(FLAWED_ITEMS)
    restarted, transcriber, aligner = make_pipeline(workspace, aligned, run.cache_dir)
    third = restarted.analyze(run.wav, REQUEST)
    assert third.processing_meta.cached is True and (transcriber.calls, aligner.calls) == (0, 0)
    assert third.deterministic_json() == first.deterministic_json()
    assert restarted.cache.get(first.analysis_id).processing_meta.cached is False   # the stored copy is the original


def test_a_corrupt_cache_entry_is_recomputed_and_replaced(workspace):
    run = run_analysis(workspace, SHORT_ITEMS, "corrupt")
    path = run.cache_dir / f"{run.result.analysis_id}.json"
    path.write_text("{ not json", encoding="utf-8")
    again = run.pipeline.analyze(run.wav, REQUEST)
    assert again.processing_meta.cached is False and run.transcriber.calls == 2
    assert again.deterministic_json() == run.result.deterministic_json()
    assert ResultCache(run.cache_dir).get(again.analysis_id) is not None


def test_the_cache_key_reacts_to_every_input_that_can_change_the_result(workspace):
    base = run_analysis(workspace, SHORT_ITEMS, "key_base").result
    variants: Dict[str, AnalysisResult] = {
        "manual transcript": run_analysis(workspace, SHORT_ITEMS, "key_manual", AnalyzeRequest(
            baseline_id="p001", passage_id="p001", manual_transcript="w0 w1 w2 w3 w4 w5 w6 w7 w8 w9")).result,
        "baseline": run_analysis(workspace, SHORT_ITEMS, "key_baseline", AnalyzeRequest(
            baseline_id="p001_rich", passage_id="p001")).result,
        "analysis config": run_analysis(workspace, SHORT_ITEMS, "key_config", config=PipelineConfig(
            detection=DetectionConfig(z_energy=2.5))).result,
        "speaker gender hint": run_analysis(workspace, SHORT_ITEMS, "key_gender", AnalyzeRequest(
            baseline_id="p001", passage_id="p001", speaker_gender="female")).result,
        "passage text": run_analysis(workspace, SHORT_ITEMS, "key_passage", passages=workspace.root / "missing.json").result,
        "audio": run_analysis(workspace, normal_delivery(10, special_gaps={4: 0.5}), "key_audio").result,
    }
    ids = {name: r.analysis_id for name, r in variants.items()}
    assert base.analysis_id not in ids.values(), ids
    assert len(set(ids.values())) == len(ids), ids
    assert variants["analysis config"].config_fingerprint != base.config_fingerprint
    assert all(r.config_fingerprint == base.config_fingerprint for n, r in variants.items() if n != "analysis config")


def test_whitespace_around_a_manual_transcript_does_not_change_the_analysis_id(workspace):
    text = "w0 w1 w2 w3 w4 w5 w6 w7 w8 w9"
    ids = {
        run_analysis(workspace, SHORT_ITEMS, f"ws_{i}", AnalyzeRequest(
            baseline_id="p001", passage_id="p001", manual_transcript=padded)).result.analysis_id
        for i, padded in enumerate([text, f"  {text}\n", f"\t{text}"])
    }
    assert len(ids) == 1


# --------------------------------------------------------------------------- inputs / notes
def test_a_manual_transcript_bypasses_asr_and_is_recorded(workspace):
    text = "w0 w1 w2 w3 w4 w5 w6 w7 w8 w9"
    request = AnalyzeRequest(baseline_id="p001", passage_id="p001", manual_transcript=f"  {text}  ")
    run = run_analysis(workspace, SHORT_ITEMS, "manual", request)
    assert run.transcriber.calls == 0 and run.aligner.calls == 1
    assert run.aligner.last_transcript.text == text and run.aligner.last_transcript.source == TranscriptSource.MANUAL
    assert run.result.processing_meta.transcript_source == TranscriptSource.MANUAL
    assert run.result.processing_meta.whisper_model is None


def test_notes_state_the_limits_of_the_analysis(plain):
    codes = _codes(plain.result)
    assert "thresholds_uncalibrated" in codes and settings.THRESHOLDS_CALIBRATED is False
    assert "baseline_thin_rate" in codes and "baseline_thin_pauses" in codes           # a single 24-word take
    assert "pauses_not_comparable" in codes                                            # no spread for cross-sentence pauses
    assert "passage_text_unavailable" not in codes and "content_mismatch" not in codes
    assert "speaker_gender_ignored" not in codes
    assert all(n.message.strip() for n in plain.result.notes) and len(codes) == len(set(codes))


def test_a_well_supported_baseline_does_not_trigger_the_thin_baseline_notes(workspace):
    run = run_analysis(workspace, FLAWED_ITEMS, "rich", AnalyzeRequest(baseline_id="p001_rich", passage_id="p001"))
    codes = _codes(run.result)
    assert "baseline_thin_rate" not in codes and "baseline_thin_pauses" not in codes
    assert run.result.baseline.baseline_id == "p001_rich"


def test_speaker_gender_is_reported_as_ignored(workspace):
    request = AnalyzeRequest(baseline_id="p001", passage_id="p001", speaker_gender="male")
    run = run_analysis(workspace, SHORT_ITEMS, "gender", request)
    assert "speaker_gender_ignored" in _codes(run.result)


def test_a_transcript_that_does_not_match_the_passage_is_flagged(workspace):
    other = "the quick brown fox jumps over the lazy dog while the rain keeps falling on the quiet town"
    run = run_analysis(workspace, FLAWED_ITEMS, "mismatch", transcript_text=other)
    note = next(n for n in run.result.notes if n.code == "content_mismatch")
    assert "similarity" in note.message
    assert "content_mismatch" not in _codes(run_analysis(workspace, FLAWED_ITEMS, "match_again").result)


def test_a_missing_passage_catalog_is_reported_not_fatal(workspace):
    run = run_analysis(workspace, SHORT_ITEMS, "nocatalog", passages=workspace.root / "missing.json")
    assert "passage_text_unavailable" in _codes(run.result) and "content_mismatch" not in _codes(run.result)


# ------------------------------------------------------------------------------ concurrency
def test_only_one_analysis_runs_at_a_time(workspace):
    wav, aligned = build_speech(SHORT_ITEMS)

    class SlowAligner(FakeAligner):
        def __init__(self, source):
            super().__init__(source)
            self.active = 0
            self.max_active = 0
            self._guard = threading.Lock()

        def align(self, audio, transcript):
            with self._guard:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            try:
                time.sleep(0.15)
                return super().align(audio, transcript)
            finally:
                with self._guard:
                    self.active -= 1

    aligner = SlowAligner(aligned)
    pipeline = AnalysisPipeline(
        transcriber=FakeTranscriber(aligned.text), aligner=aligner, baseline_provider=BaselineProvider(workspace.baselines),
        cache=ResultCache(workspace.root / "cache_threads"), passages=PassageCatalog(workspace.passages),
    )
    results: List[Any] = []

    def work(manual: str) -> None:
        results.append(pipeline.analyze(wav, AnalyzeRequest(baseline_id="p001", passage_id="p001", manual_transcript=manual)))

    threads = [threading.Thread(target=work, args=(f"w0 w1 w2 w3 w{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert len(results) == 2 and len({r.analysis_id for r in results}) == 2
    assert aligner.calls == 2 and aligner.max_active == 1
