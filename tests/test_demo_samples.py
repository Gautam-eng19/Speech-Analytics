"""Integrity of the committed dashboard demo samples (frontend/public/samples, built by scripts/demo/build_demo_samples.py).

The samples are synthetic: a speech synthesiser reading one passage with deliberate flaws, analysed by the real pipeline. These tests
make sure the committed files are what they claim to be: valid API results, for exactly the audio that is shipped next to them, with
the stored ground truth inside the recording and the synthetic nature stated.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from app.schemas.response import AnalysisResult
from app.services.audio import AudioPreprocessor

SAMPLES = Path(__file__).resolve().parents[1] / "frontend" / "public" / "samples"
INDEX = json.loads((SAMPLES / "index.json").read_text(encoding="utf-8"))


def test_the_index_states_that_everything_is_synthetic_and_how_samples_were_chosen():
    assert INDEX["synthetic"] is True
    assert "synthetic" in INDEX["voice"].lower() or "synthesiser" in INDEX["voice"].lower()
    assert "not a measurement of detection accuracy" in INDEX["selection_note"]
    diag = INDEX["diagnostics"]
    assert 0 <= diag["clean_takes_flagged"] <= diag["clean_takes_probed"] > 0
    assert INDEX["passage"]["word_count"] > 50 and len(INDEX["samples"]) >= 3


@pytest.mark.parametrize("sample", INDEX["samples"], ids=lambda s: s["id"])
def test_a_sample_is_a_valid_result_for_exactly_the_audio_next_to_it(sample):
    result = AnalysisResult.model_validate_json((SAMPLES / sample["result"]).read_text(encoding="utf-8"))
    wav = (SAMPLES / sample["audio"]).read_bytes()
    processed = AudioPreprocessor().process(wav)
    assert processed.sha256 == result.audio.sha256, "the shipped WAV is not the audio that was analysed"
    assert result.analysis_id == sample["analysis_id"]
    assert result.audio.source_duration_s == pytest.approx(sample["duration_s"], abs=0.01)
    assert result.audio.trim_start_s > 0.3                                   # the leading silence is real, so source time matters
    assert "demo" in (result.processing_meta.whisper_model or "")            # never claims a real Whisper model produced it
    assert any(n.code == "thresholds_uncalibrated" for n in result.notes)


@pytest.mark.parametrize("sample", INDEX["samples"], ids=lambda s: s["id"])
def test_stored_ground_truth_lies_inside_the_recording_and_its_outcome_is_recorded(sample):
    result = AnalysisResult.model_validate_json((SAMPLES / sample["result"]).read_text(encoding="utf-8"))
    for truth in sample["injected"]:
        assert 0.0 <= truth["start_s"] < truth["end_s"] <= sample["duration_s"] + 0.01
        assert isinstance(truth["detected"], bool)
        overlapping = [f for f in result.flaws if f.type.value == truth["type"]
                       and min(f.end_s, truth["end_s"]) - max(f.start_s, truth["start_s"]) >= 0.5 * (truth["end_s"] - truth["start_s"])]
        assert bool(overlapping) == truth["detected"], f"{sample['id']}: stored 'detected' disagrees with the stored result"


def test_the_clean_control_has_no_flaw_and_every_injected_flaw_of_the_mixed_sample_is_found():
    by_id = {s["id"]: s for s in INDEX["samples"]}
    clean = AnalysisResult.model_validate_json((SAMPLES / by_id["clean-delivery"]["result"]).read_text(encoding="utf-8"))
    assert clean.flaws == [] and clean.scores.composite_score == 100.0
    mixed = by_id["mixed-flaws"]["injected"]
    assert [t["type"] for t in mixed] == ["too_fast", "excessive_pause", "low_energy"]
    assert [t["detected"] for t in mixed] == [True, True, True]          # the quiet sentence is found by the word-by-word loudness comparison
    assert by_id["mixed-flaws"]["extra_detections"] == 0


def test_the_samples_were_judged_word_by_word_against_the_baseline():
    result = AnalysisResult.model_validate_json((SAMPLES / "mixed-flaws.json").read_text(encoding="utf-8"))
    assert {f.rule.feature for f in result.flaws} == {"rate_run_z", "pause_z", "energy_run_z"}
    assert not any(n.code in ("baseline_without_profile", "profile_not_applicable") for n in result.notes)
    assert INDEX["diagnostics"]["clean_takes_flagged"] == 0


def _ffmpeg_has_flite() -> bool:
    if shutil.which("ffmpeg") is None:
        return False
    out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    return "flite" in out


@pytest.mark.skipif(not _ffmpeg_has_flite(), reason="ffmpeg with libflite is needed to synthesise the voice")
def test_the_generator_is_deterministic_for_a_given_seed():
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("build_demo_samples", Path(__file__).resolve().parents[1] / "scripts" / "demo" / "build_demo_samples.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_demo_samples"] = module
    spec.loader.exec_module(module)
    a, b = module.build_take(7, (module.Fast(3, 1.8),)), module.build_take(7, (module.Fast(3, 1.8),))
    assert (a.audio == b.audio).all() and a.injected == b.injected
    assert [(w.start_s, w.end_s) for w in a.words] == [(w.start_s, w.end_s) for w in b.words]
    c = module.build_take(8, (module.Fast(3, 1.8),))
    assert not (len(c.audio) == len(a.audio) and (c.audio == a.audio).all())
