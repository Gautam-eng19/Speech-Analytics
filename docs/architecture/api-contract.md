# API Contract

Canonical Pydantic models: `backend/app/schemas/` (`common.py`, `request.py`, `response.py`).
Frontend TypeScript types must be derived from these models (never hand-extended).

## Versioning
- URL prefix `/api/v1`; `API_CONTRACT_VERSION` (semver, `schemas/common.py`) is returned in
  `HealthResponse.api_contract_version` and `AnalysisResult.api_contract_version`.
- MAJOR = breaking change (new URL prefix); MINOR = backward-compatible optional additions.
- History: **1.0.0** initial contract. **1.1.0** adds `Flaw.rule`, `Flaw.affected_words`, `Flaw.warnings`,
  `AudioInfo.trim_start_s` / `source_duration_s`, `AnalysisResult.notes` and `config_fingerprint` (all optional with
  defaults, so 1.0.0 payloads remain valid) and checks flaw bounds against the analysed audio in source time.
  **1.2.0** adds `GET /baselines` with `BaselineSummary`, `UnavailableBaseline` and `BaselineListResponse`; no existing
  field changed. **1.3.0** adds custom passages: `POST /custom/baselines`, `DELETE /custom/baselines/{baseline_id}`, the models
  `CustomBaselineResult`, `CustomTakeSummary` and `CustomBaselineDeleted`, and `BaselineSummary.custom`; no existing field changed.
- Independent of `config_version` (analytical parameters) and `pipeline_version` (pipeline structure).
- All models use `extra="forbid"`.

## Endpoints
| Method | Path | Success | Errors |
|---|---|---|---|
| GET | `/api/v1/health` | 200 `HealthResponse` | – |
| GET | `/api/v1/baselines` | 200 `BaselineListResponse` | – |
| POST | `/api/v1/custom/baselines` | 200 `CustomBaselineResult` (sync) | 400, 422, 500 `ErrorResponse` |
| DELETE | `/api/v1/custom/baselines/{baseline_id}` | 200 `CustomBaselineDeleted` | 404, 422 `ErrorResponse` |
| POST | `/api/v1/analyze` | 200 `AnalysisResult` (sync) | 400, 404, 422, 500 `ErrorResponse` |
| GET | `/api/v1/status/{analysis_id}` | 200 `StatusResponse` (`done`/`not_found`) | – |
| GET | `/api/v1/result/{analysis_id}` | 200 `AnalysisResult` | 404 `RESULT_NOT_FOUND` |

`POST /analyze` is `multipart/form-data`: file part `participant_audio` (WAV/MP3) plus the
`AnalyzeRequest` form fields: `baseline_id`, `passage_id` (required, `[A-Za-z0-9_-]{1,64}`),
`speaker_gender`, `config_version`, `manual_transcript` (optional).
`AudioUploadMeta` describes the file part for validation; limits come from `core/config.py`.

`status` values `processing`/`failed` are reserved for a future asynchronous mode and are not
emitted today.

### Baseline catalogue (1.2.0)
`GET /baselines` lists what an analysis can be run against, so a client can offer a choice instead of asking for ids:
- `baselines[]`: `baseline_id` (the value to send), `passage_id`, `dataset_version`, `sha256`, `n_baseline_recordings`, `n_rate_windows`,
  `n_pauses_within_phrase`, `thin_rate_statistics` / `thin_pause_statistics` (the same rules that produce the `baseline_thin_*`
  analysis notes) and, when the passage catalog knows the passage, `passage_title`, `passage_text`, `passage_word_count`.
  Sorted by `passage_id`, then `baseline_id`.
- `unavailable[]`: baseline files that exist but cannot be used, as `{baseline_id, reason}` with `reason` one of `unreadable`,
  `invalid_file`, `integrity_check_failed`. Server paths and exception text are never included.
- An empty list is a normal answer (no baseline has been built yet), not an error.

### Custom passages (1.3.0)
A user can bring their own passage: the text and 2 to 6 recordings of a good reading become a baseline that `POST /analyze` uses unchanged
(`baseline_id` = `passage_id` = the returned `custom-<12 hex>` id), and that `GET /baselines` lists with `custom: true`.
- `POST /custom/baselines` is `multipart/form-data`: `passage_text` (required), `title` (optional, at most 80 characters), and 2 to 6 file parts
  `baseline_audio` (WAV or MP3, each within `MAX_UPLOAD_BYTES`). It runs synchronously (it aligns every recording to the text; about a minute
  per recording on a CPU) and holds the same lock as the analysis because the speech models are shared.
- **Checked** (`VALIDATION_ERROR` 422 with a sentence for the user, never internal text): the passage has `CUSTOM_MIN_PASSAGE_WORDS`..`CUSTOM_MAX_PASSAGE_WORDS`
  words and at least two sentences; 2 to 6 distinct recordings; each recording is aligned to the text with at least `CUSTOM_MIN_TIMED_WORD_SHARE`
  of its words timed; when the speech recogniser is available, what was recognised matches the passage (below `CUSTOM_MIN_CONTENT_MATCH` the recording
  is refused, below `CUSTOM_WARN_CONTENT_MATCH` a warning is returned). Unsupported or oversized audio: 400 as for `/analyze`.
- `CustomBaselineResult`: `baseline_id`/`passage_id` (the same `custom-<12 hex>` id, a function of the normalised text and the recordings, so the same
  input is the same baseline and a repeat is answered with `already_existed: true` without recomputation), `title`, `passage_text`, `passage_word_count`,
  `n_recordings`, `word_profile_built` (needs three recordings; without it the analysis compares with the overall averages and says so),
  `pitch_profile_built`, `takes[]` (per recording: `filename`, `duration_s`, `words_per_min`, `timed_word_share`, `content_match` or null) and `warnings[]`.
- Only the statistics (a `BaselineStatsRecord`) and the passage text are stored, under `data/custom/` (git-ignored); the recordings are not kept.
  Custom ids start with `custom-` and are resolved only from that directory, so they can never shadow a project baseline.
- `DELETE /custom/baselines/{baseline_id}` removes a custom baseline and its passage (404 `BASELINE_NOT_FOUND` if absent, 422 for an id that is not
  a custom id: project baselines cannot be deleted). CORS now allows `DELETE`.

### Browsers and the dashboard
- **CORS:** only the origins in `CORS_ORIGINS` (default: the Vite dev server on port 5173) may read API responses from a browser; methods
  `GET`/`POST`/`OPTIONS`; no credentials. Setting it empty switches CORS off.
- **Serving the dashboard:** if `FRONTEND_DIST_DIR` (default `frontend/dist`) contains an `index.html`, the same server serves it at
  `/`, after all API routes, so `/api/v1/*`, `/docs` and `/openapi.json` always win. Without a build, `/` is simply 404.
- **Types:** `frontend/openapi.json` is a committed snapshot of the API's OpenAPI document (`python scripts/export_openapi.py`); the
  dashboard's TypeScript types are generated from it and a test fails if the snapshot is out of date.

### Analysis identity and result retrieval
- `analysis_id` is deterministic: a UUIDv5 of everything that can change the stored result (the audio, its trim offset and
  length in the uploaded file, the baseline file and its content hash, the passage text, the `speaker_gender` hint, a manual
  transcript, all versions, a fingerprint of every analytical constant, and the numeric library versions). The same request
  therefore returns the same `analysis_id`, and the second request is answered from the store with
  `processing_meta.cached = true` and the same `deterministic_json()`.
- `POST /analyze` is synchronous; the server runs one analysis at a time and queues the others.
- `GET /result/{analysis_id}` returns the stored `AnalysisResult` exactly as `POST /analyze` returned it (the stored copy has
  `cached = false`; a repeated `POST` reports `cached = true`). Results are kept on disk, so they survive a server restart.
- `GET /status/{analysis_id}` answers `done` when the result exists and `not_found` otherwise, always with HTTP 200. A malformed
  id is simply `not_found` (and is never echoed back in an error body).
- `baseline_id` selects a baseline statistics file; it must describe `passage_id`. By default `baseline_id` equals the passage id;
  several baselines (for example different baseline speakers) may exist for one passage under other ids.

## Errors
Body is always `{ "error": ErrorCode, "detail": str, "analysis_id": str | null }`.

| ErrorCode | HTTP |
|---|---|
| VALIDATION_ERROR | 422 |
| UNSUPPORTED_AUDIO_FORMAT, FILE_TOO_LARGE, AUDIO_TOO_LONG, CONFIG_VERSION_MISMATCH | 400 |
| BASELINE_NOT_FOUND, RESULT_NOT_FOUND | 404 |
| PROCESSING_ERROR | 500 |

The mapping is `ERROR_HTTP_STATUS`. FastAPI's default 422 body is replaced by `ErrorResponse` (`main.py`).

Which condition produces which error (all analysis failures store nothing):

| Condition | ErrorCode |
|---|---|
| Missing/blank field, bad id, empty upload, blank manual transcript | VALIDATION_ERROR |
| Extension or content type is not WAV/MP3; audio that cannot be decoded | UNSUPPORTED_AUDIO_FORMAT |
| Upload larger than `MAX_UPLOAD_BYTES` | FILE_TOO_LARGE |
| Audio longer than `MAX_DURATION_S` | AUDIO_TOO_LONG |
| Client `config_version` differs from the server's | CONFIG_VERSION_MISMATCH |
| Audio is silent after trimming; the transcript is empty; no word could be aligned; `baseline_id` describes another passage | VALIDATION_ERROR |
| No baseline statistics under `baseline_id` | BASELINE_NOT_FOUND |
| Transcription or alignment model failure; alignment fails validation; baseline file fails its integrity check or cannot be used for normalization; any unexpected exception | PROCESSING_ERROR |
| Unknown `analysis_id` on `GET /result/{id}` | RESULT_NOT_FOUND |

`detail` is a short, user-safe message built only from the project's own validation messages and the client's own identifiers.
Text raised by decoders, models or the file system, and server paths, are logged on the server and never returned; an unexpected
exception is reported only as a generic PROCESSING_ERROR.

## AnalysisResult
| Field | Architecture concept |
|---|---|
| `analysis_id`, `config_version`, `pipeline_version` | §26.2 |
| `audio` (sha256, duration, sample rate, channels, peak, `trim_start_s`, `source_duration_s`) | PreprocessedAudio §9.1 |
| `baseline` (ids, sha256, dataset_version) | BaselineStats identity §9.5 |
| `alignment_method`, `alignment[]` | AlignedTranscript §9.3 |
| `transcript` | Transcript.text §9.2 |
| `features` (f0/energy/rate timelines, pause events; mfcc/clarity P1 optional) | FeatureBundle §9.4 |
| `baseline_stats` | BaselineStats §9.5 |
| `flaws[]` (id, type, start/end/duration, severity, reliability, low_confidence, typed evidence, `rule`, `affected_words`, `warnings`, explanation, recommendation, explanation_method) | GroundedFlaw §9.9 + §9.11 |
| `scores` (feature_scores, composite_score, scoring_version) | ScoredResult §9.10 |
| `overall_summary` | §9.11 (optional) |
| `processing_meta` (whisper_model, transcript_source, processing_time_s, cached) | run info |
| `notes[]` (`code`, `message`), `config_fingerprint` | what was NOT evaluated and analysis limitations; exact analytical configuration |

Evidence is a typed model per flaw family with fields exactly as; a `Flaw`
is rejected if its evidence class does not match its `type`, if `end_s <= start_s`, or if it
extends beyond the audio duration.

## Timeline convention (1.1.0)
Every time in an `AnalysisResult` (alignment words, F0/energy/rate timelines, pause events, flaw intervals) is in
**source time**: the timeline of the uploaded recording, so a marker at `start_s` lines up with the user's own audio.
Internally the pipeline works in processed-audio time (leading/trailing silence trimmed) and converts exactly once,
at response assembly. `audio.duration_s` is the duration of the analysed audio and `audio.trim_start_s` the
leading silence removed, so the analysed audio spans `[trim_start_s, trim_start_s + duration_s]` and flaws are validated
against that end. MP3 decoder delay is not compensated.

## Flaw grounding fields (1.1.0)
- `rule`: why the finding was flagged: the normalized signal (`rate_z` / `energy_z` / `pause_z`; for a word-by-word comparison with the baseline `rate_run_z`, `rate_overall_z` or
  `energy_run_z`), the direction (`above` / `below`), `threshold_z` (signed) and `min_duration_s`. For flat pitch the feature is `pitch_run_z` or `pitch_overall_z`, the direction is `below`, and `threshold_z` is `-Z_RUN_PITCH`. Thresholds are initial, uncalibrated values.
- `affected_words`: words covered by the interval (rate/energy: midpoint inside the interval; pause: the word(s) it
  follows and precedes). The full alignment is in `alignment`.
- `warnings`: plain-language limitations of that finding (e.g. a rate finding is narrowed from its rolling windows to the words that deviate and can still be off by a word or two).
  For such a narrowed rate finding the rate evidence describes the narrowed stretch: `rate_participant_wpm` is its words / span, `rate_z_score` compares it with the baseline's window spread scaled for
  its length, `window_duration_s` is its length. The field names and types are unchanged.
- **Word-by-word findings (no field changed).** When the baseline has a word profile and the recognised words match the passage, a pace or loudness finding is a run of words judged against how the baseline
  readings read THOSE words. Its evidence keeps the same fields with this meaning: `rate_baseline_mean_wpm` / `energy_baseline_mean_db` is what the baseline readings had for these words (for pace, at the speaker's own overall
  pace; for loudness, plus the recording's overall level offset); `rate_baseline_std_wpm` / `energy_baseline_std_db` is the spread that makes the reported z-score true, |participant - baseline| / |z|, so
  `z = (participant - baseline) / std` still holds; `rate_z_score` is positive for faster, `energy_z_score` positive for louder; `peak_z_score` equals `rate_z_score`; `window_duration_s` is the span of the run
  (first word start to last word end), `word_count_in_window` the words starting inside it. `rule.feature` is `rate_run_z`, `rate_overall_z` (the whole recording differs from the baseline readers' pace by more than readers
  differ among themselves; one finding over all comparable words) or `energy_run_z`; `rule.threshold_z` is the threshold for a run (`Z_RUN_RATE` / `Z_RUN_ENERGY`). `severity` follows the size of the change (twice as fast
  or half as fast, 15 dB, a pause 3.5 s longer than usual = 1.0) times the duration component, not the z-score.
- **Flat pitch (no field changed).** A `flat_pitch` finding is a run of words (or, with `rule.feature` `pitch_overall_z`, the whole recording) whose pitch moved less than the baseline readings' pitch did on the
  same words. The pitch of each voiced frame is taken in semitones from the recording's own median pitch; `f0_std_hz_in_window` is the root-mean-square distance from that median over the run, expressed as Hz above
  the median pitch (the name keeps its contract-1.0 form: it is a movement, not a standard deviation of Hz), `f0_std_baseline_hz` is the same quantity for what the baseline readings did on these words (at the speaker's
  own overall range), `f0_std_z` is negative (the voice moved less; the spread is that of a run of this many words between baseline readings), `f0_voiced_fraction` is the share of the run's frames that were voiced,
  `window_duration_s` the span of the run. `severity` follows the size of the change (a third of the baseline's movement = 1.0) times the duration component. `pitch_instability` is not detected.
- `reliability` is a constant `1.0` at P0 and `low_confidence` is `false`; neither is a measured confidence.

## Notes (1.1.0)
`notes[]` carries `{code, message}` entries for everything the analysis did not or could not do: features that were
unavailable, flaw types not evaluated (e.g. flat pitch), alignment issues, a thin baseline, a transcript that does not
match the passage, and uncalibrated thresholds. The dashboard must show them; missing evidence is never silent.

Codes (the message carries the numbers; a code appears at most once, `{feature}` is a name such as `f0`, `energy`, `rate`, `pauses`
or a score dimension such as `pitch`, `speech_rate`):

| Code | Meaning |
|---|---|
| `thresholds_uncalibrated` | Thresholds and score weights are initial values, not calibrated on recordings (cleared only by `THRESHOLDS_CALIBRATED=true`) |
| `baseline_thin_rate`, `baseline_thin_pauses` | The baseline rests on very few rate windows / within-phrase pauses, so those z-scores can be over-sensitive |
| `audio_very_quiet` | The recording's mean level is below the extractor's quiet limit; energy findings can be unreliable |
| `passage_text_unavailable`, `content_mismatch` | The passage text is not available / the transcript matches it only partly (similarity in the message) |
| `alignment_warning` | A warning from alignment validation (for example low word coverage) |
| `baseline_without_profile` | The baseline has no word-by-word profile (built before profiles existed, or from fewer than three recordings that match the passage text): pace and loudness were compared with its overall averages, which is much less precise |
| `profile_not_applicable` | The baseline has a profile but too few of the recognised words match the passage, or too few words could be compared: overall averages were used |
| `{feature}_unavailable` | A feature could not be normalized against the baseline (reason in the message); not added for pace or loudness when the word-by-word comparison judged them |
| `pitch_not_judged` | Flat pitch was not checked word by word: the baseline has no pitch profile (rebuild it), the pitch of the words could not be measured, too few words had enough voiced speech, or the words did not match the passage; the message gives the reason and pitch is left out of the score |
| `pauses_not_comparable` | Some pauses have no usable baseline statistic (unknown pause type or no baseline spread) |
| `{feature}_not_scored` | A score dimension was not evaluated (for example `pitch_not_scored`: the baseline has no pitch profile, so flat pitch was not checked) and is left out of the composite |
| `words_without_timing` | Words without complete timing were left out of `alignment` |
| `speaker_gender_ignored` | The optional hint was ignored: baselines are not gender-specific |
| `mfcc_unavailable` | The MFCC summary could not be computed |
| `result_not_stored` | The analysis succeeded but the result could not be written, so `GET /result/{analysis_id}` will not find it |
| `explanation_provider_unavailable`, `explanation_fallback_used` | A non-template provider was configured but is not implemented / a text used the minimal fallback |

## Reproducibility
- `AnalysisResult.deterministic_json()` excludes `analysis_id` and `processing_meta`;
  identical input + config must give an identical string. `feature_scores` keys are emitted in
  canonical `FeatureName` order.
- Unvoiced F0 frames are `null` (NaN is not valid JSON).
- `audio.sha256`, `baseline.sha256`, `config_version`, `pipeline_version`, `alignment_method`,
  `processing_meta.whisper_model` / `transcript_source` identify the exact run (§26.3). `config_fingerprint`
  (SHA-256 of every analytical constant in effect) additionally detects threshold changes made without a
  `config_version` bump.

## Assumptions / deviations from the §6.3 sample (shape only, no new analytics)
1. `config_version` request field is optional (§23: "optional for P0").
2. `scores` is `{feature_scores, composite_score, scoring_version}` per §9.10 rather than
   composite nested among sub-scores.
3. Audio/baseline provenance is grouped into `audio` / `baseline` objects; `alignment_method`
   appears once (top level), not duplicated in `processing_meta`.
4. `Flaw.duration_s` included (§9.9). `BaselineStats.pause_cross_sentence_std_s` is kept as optional/provisional: §16 requires a per-type standard deviation for pause z-score calculation, but §9.5 and §6.3 omit it from the canonical schema. Keeping it optional allows the backend to consume it when available while maintaining strict §9.5 schema compliance when omitted.
5. `speaker_calibration_audio` (P1) is not in the contract.
6. Severity formula, thresholds and weights remain PROPOSED; the contract only
   bounds severity to [0,1] and scores to [0,100].
