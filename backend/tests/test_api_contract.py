"""Contract tests for TASK-002 (request, response, errors, determinism)."""
import copy
import json

import pytest
from pydantic import ValidationError

from app.schemas import (
    API_CONTRACT_VERSION, ERROR_HTTP_STATUS, AnalysisResult, AnalysisStatus,
    AnalyzeRequest, AudioUploadMeta, ErrorCode, ErrorResponse, HealthResponse,
    StatusResponse,
)

SHA = "a" * 64


def valid_result_dict() -> dict:
    return {
        "analysis_id": "3f2b8c1e-0000-4000-8000-000000000001",
        "config_version": "1.0.0",
        "pipeline_version": "1.0.0",
        "audio": {"sha256": SHA, "duration_s": 20.0, "sample_rate_hz": 16000,
                  "channels": 1, "peak_dbfs": -3.0},
        "baseline": {"baseline_id": "passage01_base", "passage_id": "passage01",
                     "sha256": "b" * 64, "dataset_version": "0.1"},
        "alignment_method": "whisper_word_timestamps",
        "transcript": "hello world",
        "alignment": [
            {"word": "hello", "start_s": 0.41, "end_s": 0.73, "confidence": 0.95},
            {"word": "world", "start_s": 0.80, "end_s": 1.20, "confidence": 0.90},
        ],
        "features": {
            "f0_timeline": {"times_s": [0.0, 0.01, 0.02],
                            "values_hz": [None, 120.5, 121.0],
                            "voiced": [False, True, True]},
            "energy_timeline": {"times_s": [0.0, 0.01], "values_db": [-30.1, -28.4]},
            "speech_rate_timeline": {"times_s": [4.0, 8.0], "words_per_min": [140.0, 187.3]},
            "pause_events": [{"start_s": 1.2, "end_s": 1.9, "duration_s": 0.7,
                              "detection_source": "both",
                              "boundary_type": "within_phrase"}],
        },
        "baseline_stats": {
            "f0_voiced_hz_mean": 118.0, "f0_voiced_hz_std": 20.0,
            "energy_db_mean": -30.0, "energy_db_std": 4.0,
            "rate_wpm_mean": 142.6, "rate_wpm_std": 18.4,
            "pause_within_phrase_mean_s": 0.3, "pause_within_phrase_std_s": 0.1,
            "pause_cross_sentence_mean_s": 0.6,
        },
        "flaws": [{
            "flaw_id": "flaw_001", "type": "too_fast",
            "start_s": 12.4, "end_s": 15.8, "duration_s": 3.4,
            "severity": 0.78, "reliability": 1.0, "low_confidence": False,
            "evidence": {
                "rate_participant_wpm": 187.3, "rate_baseline_mean_wpm": 142.6,
                "rate_baseline_std_wpm": 18.4, "rate_delta_wpm": 44.7,
                "rate_delta_pct": 31.4, "rate_z_score": 2.41, "peak_z_score": 3.12,
                "window_duration_s": 3.4, "word_count_in_window": 11,
            },
            "explanation": "Between 12.4-15.8 s, speech rate was 31.4% above baseline.",
            "recommendation": "Slow down and pause at phrase boundaries.",
            "explanation_method": "template",
        }],
        "scores": {
            "feature_scores": {
                "pitch": {"score": 100.0, "weight": 0.25, "flaw_count": 0, "penalty_total": 0.0},
                "speech_rate": {"score": 61.0, "weight": 0.30, "flaw_count": 1, "penalty_total": 39.0},
                "pauses": {"score": 100.0, "weight": 0.25, "flaw_count": 0, "penalty_total": 0.0},
                "energy": {"score": 100.0, "weight": 0.20, "flaw_count": 0, "penalty_total": 0.0},
            },
            "composite_score": 88.3,
            "scoring_version": "1.0.0",
        },
        "overall_summary": None,
        "processing_meta": {"whisper_model": "base", "transcript_source": "asr",
                            "processing_time_s": 14.2, "cached": False},
    }


# ---------------------------------------------------------------- requests
def test_valid_request():
    r = AnalyzeRequest(baseline_id="passage01_base", passage_id="passage01")
    assert r.speaker_gender is None and r.config_version is None
    r2 = AnalyzeRequest(baseline_id="b-1", passage_id="p1", speaker_gender="female",
                        config_version="1.0.0", manual_transcript="hello world")
    assert r2.speaker_gender.value == "female"


@pytest.mark.parametrize("bad", [
    {"baseline_id": "../etc/passwd", "passage_id": "p1"},
    {"baseline_id": "", "passage_id": "p1"},
    {"baseline_id": "b1"},
    {"baseline_id": "b1", "passage_id": "p1", "speaker_gender": "other"},
    {"baseline_id": "b1", "passage_id": "p1", "manual_transcript": "   "},
    {"baseline_id": "b1", "passage_id": "p1", "unknown_field": 1},
])
def test_invalid_request(bad):
    with pytest.raises(ValidationError):
        AnalyzeRequest(**bad)


def test_valid_upload_meta_and_sanitized_filename():
    m = AudioUploadMeta(filename="C:\\x\\..\\speech.WAV", content_type="audio/x-wav",
                        size_bytes=1000)
    assert m.filename == "speech.WAV"
    AudioUploadMeta(filename="a.mp3", content_type="audio/mpeg; charset=x", size_bytes=1)
    m.ensure_within_limit(1000)


@pytest.mark.parametrize("kwargs", [
    dict(filename="a.ogg", content_type="audio/ogg", size_bytes=10),
    dict(filename="a.wav", content_type="audio/mpeg", size_bytes=10),  # mismatch
    dict(filename="a.wav", content_type="text/plain", size_bytes=10),
    dict(filename="a.wav", content_type="audio/wav", size_bytes=0),
    dict(filename="noext", content_type="audio/wav", size_bytes=10),
])
def test_invalid_upload_meta(kwargs):
    with pytest.raises(ValidationError):
        AudioUploadMeta(**kwargs)


def test_upload_over_limit():
    m = AudioUploadMeta(filename="a.wav", content_type="audio/wav", size_bytes=11)
    with pytest.raises(ValueError):
        m.ensure_within_limit(10)


# ---------------------------------------------------------------- responses
def test_valid_result_roundtrip():
    res = AnalysisResult.model_validate(valid_result_dict())
    assert res.api_contract_version == API_CONTRACT_VERSION
    again = AnalysisResult.model_validate_json(res.model_dump_json())
    assert again == res


def test_result_json_has_no_nan():
    js = AnalysisResult.model_validate(valid_result_dict()).model_dump_json()
    assert "NaN" not in js
    assert json.loads(js)["features"]["f0_timeline"]["values_hz"][0] is None


def test_deterministic_serialization_and_key_order():
    a = AnalysisResult.model_validate(valid_result_dict())
    d = valid_result_dict()
    d["scores"]["feature_scores"] = dict(reversed(list(d["scores"]["feature_scores"].items())))
    b = AnalysisResult.model_validate(d)
    assert a.deterministic_json() == b.deterministic_json()
    assert a.model_dump_json() == a.model_dump_json()
    assert list(json.loads(a.deterministic_json())["scores"]["feature_scores"]) == [
        "speech_rate", "pitch", "pauses", "energy"]


def test_deterministic_json_excludes_run_specific_fields():
    a = AnalysisResult.model_validate(valid_result_dict())
    d = valid_result_dict()
    d["analysis_id"] = "other"
    d["processing_meta"]["processing_time_s"] = 99.0
    d["processing_meta"]["cached"] = True
    assert a.deterministic_json() == AnalysisResult.model_validate(d).deterministic_json()


def _mutate(fn):
    d = valid_result_dict()
    fn(d)
    return d


@pytest.mark.parametrize("mutator", [
    lambda d: d["flaws"][0].update(severity=1.5),
    lambda d: d["flaws"][0].update(end_s=12.4),                      # no interval
    lambda d: d["flaws"][0].update(end_s=99.0, duration_s=86.6),     # beyond audio
    lambda d: d["flaws"][0].update(duration_s=1.0),                  # inconsistent
    lambda d: d["flaws"][0].update(type="flat_pitch"),               # evidence mismatch
    lambda d: d["flaws"][0].update(type="made_up_flaw"),
    lambda d: d["flaws"][0].pop("evidence"),
    lambda d: d["flaws"][0]["evidence"].pop("rate_z_score"),
    lambda d: d["flaws"][0].update(explanation=""),
    lambda d: d["flaws"][0].update(explanation_method="gpt"),
    lambda d: d["flaws"].append(copy.deepcopy(d["flaws"][0])),       # duplicate id
    lambda d: d["scores"].update(composite_score=101),
    lambda d: d["scores"].update(scoring_version="9.9.9"),
    lambda d: d["scores"]["feature_scores"].update(bogus={"score": 1, "weight": 0, "flaw_count": 0, "penalty_total": 0}),
    lambda d: d["features"]["energy_timeline"].update(values_db=[-30.0]),  # length
    lambda d: d["features"]["f0_timeline"]["values_hz"].__setitem__(1, None),  # voiced w/o f0
    lambda d: d["audio"].update(sha256="xyz"),
    lambda d: d["alignment"][0].update(end_s=0.1),
    lambda d: d.update(alignment_method="magic"),
    lambda d: d.update(extra_field=1),
])
def test_invalid_result_rejected(mutator):
    with pytest.raises(ValidationError):
        AnalysisResult.model_validate(_mutate(mutator))


def test_result_without_flaws_is_valid():
    d = valid_result_dict()
    d["flaws"] = []
    assert AnalysisResult.model_validate(d).flaws == []


def test_all_flaw_types_have_matching_evidence():
    from app.schemas.response import _EVIDENCE_FOR_TYPE
    from app.schemas.common import FlawType
    assert set(_EVIDENCE_FOR_TYPE) == set(FlawType)


# ------------------------------------------------- health / status / errors
def test_health_and_status():
    h = HealthResponse(status="ok", config_version="1.0.0", pipeline_version="1.0.0")
    assert h.api_contract_version == API_CONTRACT_VERSION
    with pytest.raises(ValidationError):
        HealthResponse(status="down", config_version="1", pipeline_version="1")
    assert StatusResponse(analysis_id="x", status="done").status is AnalysisStatus.DONE
    assert StatusResponse(analysis_id="x", status="not_found").status is AnalysisStatus.NOT_FOUND
    with pytest.raises(ValidationError):
        StatusResponse(analysis_id="x", status="weird")


def test_error_models_and_http_mapping():
    e = ErrorResponse(error="VALIDATION_ERROR", detail="bad audio")
    assert e.analysis_id is None
    assert json.loads(e.model_dump_json()) == {
        "error": "VALIDATION_ERROR", "detail": "bad audio", "analysis_id": None}
    with pytest.raises(ValidationError):
        ErrorResponse(error="NOPE", detail="x")
    with pytest.raises(ValidationError):
        ErrorResponse(error="PROCESSING_ERROR", detail="")
    assert set(ERROR_HTTP_STATUS) == set(ErrorCode)
    assert ERROR_HTTP_STATUS[ErrorCode.BASELINE_NOT_FOUND] == 404
    assert ERROR_HTTP_STATUS[ErrorCode.PROCESSING_ERROR] == 500
