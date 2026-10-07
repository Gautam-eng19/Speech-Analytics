# API Contract (TASK-002)

Canonical Pydantic models: `backend/app/schemas/` (`common.py`, `request.py`, `response.py`).
Source concepts: ARCHITECTURE.md §6.3, §9, §21, §23; DEC-009/011/013/016/018/021.
Frontend TypeScript types must be derived from these models (never hand-extended).

## Versioning
- URL prefix `/api/v1`; `API_CONTRACT_VERSION` (semver, `schemas/common.py`) is returned in
  `HealthResponse.api_contract_version` and `AnalysisResult.api_contract_version`.
- MAJOR = breaking change (new URL prefix); MINOR = backward-compatible optional additions.
- Independent of `config_version` (analytical parameters) and `pipeline_version` (pipeline structure).
- All models use `extra="forbid"`.

## Endpoints
| Method | Path | Success | Errors |
|---|---|---|---|
| GET | `/api/v1/health` | 200 `HealthResponse` | – |
| POST | `/api/v1/analyze` | 200 `AnalysisResult` (sync, DEC-016) | 400, 404, 422, 500 `ErrorResponse` |
| GET | `/api/v1/status/{analysis_id}` | 200 `StatusResponse` (`done`/`not_found`) | – |
| GET | `/api/v1/result/{analysis_id}` | 200 `AnalysisResult` | 404 `RESULT_NOT_FOUND` |

`POST /analyze` is `multipart/form-data`: file part `participant_audio` (WAV/MP3) plus the
`AnalyzeRequest` form fields: `baseline_id`, `passage_id` (required, `[A-Za-z0-9_-]{1,64}`),
`speaker_gender`, `config_version`, `manual_transcript` (optional).
`AudioUploadMeta` describes the file part for validation; limits come from `core/config.py`.

`status` values `processing`/`failed` are reserved for the DEC-016 async upgrade and are not
emitted at P0.

## Errors
Body is always `{ "error": ErrorCode, "detail": str, "analysis_id": str | null }`.

| ErrorCode | HTTP |
|---|---|
| VALIDATION_ERROR | 422 |
| UNSUPPORTED_AUDIO_FORMAT, FILE_TOO_LARGE, AUDIO_TOO_LONG, CONFIG_VERSION_MISMATCH | 400 |
| BASELINE_NOT_FOUND, RESULT_NOT_FOUND | 404 |
| PROCESSING_ERROR | 500 |

The mapping is `ERROR_HTTP_STATUS`. TASK-010 must install exception handlers so FastAPI's
default 422 body is replaced by `ErrorResponse`.

## AnalysisResult
| Field | Architecture concept |
|---|---|
| `analysis_id`, `config_version`, `pipeline_version` | §26.2 |
| `audio` (sha256, duration, sample rate, channels, peak) | PreprocessedAudio §9.1 |
| `baseline` (ids, sha256, dataset_version) | BaselineStats identity §9.5 |
| `alignment_method`, `alignment[]` | AlignedTranscript §9.3 |
| `transcript` | Transcript.text §9.2 |
| `features` (f0/energy/rate timelines, pause events; mfcc/clarity P1 optional) | FeatureBundle §9.4 |
| `baseline_stats` | BaselineStats §9.5 |
| `flaws[]` (id, type, start/end/duration, severity, reliability, low_confidence, typed evidence, explanation, recommendation, explanation_method) | GroundedFlaw §9.9 + §9.11 |
| `scores` (feature_scores, composite_score, scoring_version) | ScoredResult §9.10 |
| `overall_summary` | §9.11 (optional) |
| `processing_meta` (whisper_model, transcript_source, processing_time_s, cached) | run info |

Evidence is a typed model per flaw family with fields exactly as ARCHITECTURE.md §21; a `Flaw`
is rejected if its evidence class does not match its `type`, if `end_s <= start_s`, or if it
extends beyond the audio duration.

## Reproducibility
- `AnalysisResult.deterministic_json()` excludes `analysis_id` and `processing_meta`;
  identical input + config must give an identical string. `feature_scores` keys are emitted in
  canonical `FeatureName` order.
- Unvoiced F0 frames are `null` (NaN is not valid JSON).
- `audio.sha256`, `baseline.sha256`, `config_version`, `pipeline_version`, `alignment_method`,
  `processing_meta.whisper_model` / `transcript_source` identify the exact run (§26.3).

## Assumptions / deviations from the §6.3 sample (shape only, no new analytics)
1. `config_version` request field is optional (§23: "optional for P0").
2. `scores` is `{feature_scores, composite_score, scoring_version}` per §9.10 rather than
   composite nested among sub-scores.
3. Audio/baseline provenance is grouped into `audio` / `baseline` objects; `alignment_method`
   appears once (top level), not duplicated in `processing_meta`.
4. `Flaw.duration_s` included (§9.9). `BaselineStats.pause_cross_sentence_std_s` is kept as optional/provisional: §16 requires a per-type standard deviation for pause z-score calculation, but §9.5 and §6.3 omit it from the canonical schema. Keeping it optional allows the backend to consume it when available while maintaining strict §9.5 schema compliance when omitted.
5. `speaker_calibration_audio` (P1) is not in the contract.
6. Severity formula (DEC-P006), thresholds and weights remain PROPOSED; the contract only
   bounds severity to [0,1] and scores to [0,100].
