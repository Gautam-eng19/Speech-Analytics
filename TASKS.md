\# Task Board



\## STATUS DEFINITIONS



BACKLOG

→ Identified work that is not yet ready.



READY

→ Clear enough to be picked up.



IN PROGRESS

→ Someone is actively working on it.



REVIEW

→ Implementation is complete and awaiting teammate review.



BLOCKED

→ Cannot proceed because of a known dependency/problem.



DONE

→ Implemented, tested, reviewed, integrated, and documented.



\---



\# WORK-IN-PROGRESS LIMIT



Each teammate should normally have:



\- 1 primary task

\- optionally 1 small secondary task



Do not start many tasks simultaneously.



The goal is finishing work, not maximizing the number of active tasks.



\---



\# TASK TEMPLATE



\## TASK-XXX — <Task Name>



Area:

Foundation / Backend / Audio / Alignment / Features /

Grounding / Scoring / Explanation / Frontend / Testing / Docs



Status:

BACKLOG



Owner:

Unassigned



Reviewer:

Unassigned



Priority:

P0 / P1 / P2



Dependencies:

None



Objective:

<one clear outcome>



Inputs:

<what the task consumes>



Outputs:

<what the task must produce>



Allowed Scope:

<files/directories expected to change>



Acceptance Criteria:

\- \[ ] requirement 1

\- \[ ] requirement 2

\- \[ ] tests pass

\- \[ ] output follows agreed contract



Notes:

<important information>



\---



\# PRIORITY DEFINITIONS



P0:

Required for the core demo or required Track C functionality.



P1:

Strong improvement to correctness, robustness, explainability,

visualization, or demo quality.



P2:

Useful polish that should only be attempted after P0/P1 work is safe.



\---



\# FOUNDATION



\## TASK-001 — Architecture

Status: DONE

Priority: P0



Objective:

Define the complete technical architecture and data flow.



\---



\## TASK-002 — API Contract

Status: DONE

Priority: P0



Objective:

Define the request/response schemas connecting frontend and backend.



\---



\## TASK-003 — Dataset Schema

Status: DONE

Priority: P0



Objective:

Define the structure for paired baseline/flawed recordings,

transcripts, alignment information, annotations and metadata.



\---



\## TASK-004 — Development Environment

Status: REVIEW

Priority: P0



Objective:

Make backend, frontend and required development tools runnable

on all three team machines.

Delivered:
Setup guide and pinned-range requirements merged (7e2d061); installs and the full test suite run on Linux in an isolated venv (2026-10-09). Running on all three team machines is not evidenced. Dependencies are `>=` ranges with no lockfile (ARCHITECTURE §26.5 asks for exact pins).

\---



\# BACKEND



\## TASK-010 — FastAPI Application Skeleton

Status: DONE

Priority: P0

Delivered:
FastAPI app factory, /api/v1 routers and the ErrorResponse 422 handler (0a24470).

\## TASK-011 — Health Endpoint

Status: DONE

Priority: P0

Delivered:
GET /api/v1/health returning HealthResponse (0a24470).

\## TASK-012 — Audio Upload

Status: DONE

Priority: P0

Delivered:
Upload validation (a1b8048): extension, content type, size, config_version. POST /api/v1/analyze now runs the orchestrated pipeline in a worker thread and maps every failure to a public error code (DEC-032).

\## TASK-013 — Audio Preprocessing

Status: DONE

Priority: P0

Delivered:
Deterministic mono/16 kHz/peak-normalised preprocessing with silence trimming (f1a0836). The preprocessor still returns an empty array for all-silence input; the pipeline rejects it with VALIDATION_ERROR (DEC-032).

\## TASK-013A — Preserve source-time provenance when trimming audio

Status: REVIEW

Priority: P0

Delivered:
PreprocessedAudio.trim_start_s and source_duration_s plus find_active_span() (33e9330); trim_silence(), audio_array and sha256 unchanged. Conversion to source time is deliberately NOT applied anywhere yet: it must happen exactly once, at response assembly (DEC-023). Merged 2026-10-09; awaiting teammate review.

\---



\# TRANSCRIPTION / ALIGNMENT



\## TASK-020 — Transcript Input

Status: REVIEW

Priority: P0

Delivered:
The pipeline uses `manual_transcript` instead of Whisper (`processing_meta.transcript_source` = manual) and aligns it with WhisperX, which wraps text without segments into one segment spanning the audio. `AlignmentMethod.MANUAL` is still never produced (alignment is always by the aligner). Not verified with the real WhisperX model in this environment.

\## TASK-021 — Transcription Integration

Status: DONE

Priority: P0

Delivered:
Whisper transcription with deterministic settings (29e6e39). The real-model smoke test (`-m smoke`) has not been run in this environment.

\## TASK-022 — Forced Alignment

Status: DONE

Priority: P0

Delivered:
WhisperX forced alignment to AlignedTranscript (52ded6e). WhisperX-only: the DEC-009 Whisper-timestamp fallback is not implemented; the real-model smoke test has not been run in this environment; the whisperx package itself is not installed in the verification environment (tests inject fakes).

\## TASK-023 — Alignment Validation

Status: DONE

Priority: P1

Delivered:
Deterministic alignment validation (c3b5bbb).

\---



\# FEATURE EXTRACTION



\## TASK-030 — Pitch / F0 Timeline

Status: DONE

Priority: P0

Delivered:
pYIN F0 timeline with explicit unvoiced frames (dfbe1f5).

\## TASK-031 — MFCC Features

Status: DONE

Priority: P0

Delivered:
13-coefficient MFCC extraction (e2a440c). P1 use only; not consumed by any detection rule.

\## TASK-032 — Energy Timeline

Status: REVIEW

Priority: P0

Delivered:
energy.py: frame RMS in dBFS, pinned zero padding, 10 ms hop (468a01b). Merged 2026-10-09; awaiting teammate review. 32 ms window is an agent choice (DEC-027).

\## TASK-033 — Speech Rate

Status: REVIEW

Priority: P0

Delivered:
rate.py: DEC-020 rolling-window WPM, skipped-with-reason when too few windows (2a7247a). Merged 2026-10-09; awaiting teammate review.

\## TASK-034 — Pause Detection

Status: REVIEW

Priority: P0

Delivered:
pause.py: DEC-011 VAD + alignment-gap combination, boundary types from punctuation (88b608d). Merged 2026-10-09; awaiting teammate review.

\## TASK-035 — Vocal Clarity Measure

Status: BACKLOG

Priority: P1



\---



\# CONTRASTIVE ANALYSIS



\## TASK-040 — Baseline Representation

Status: REVIEW

Priority: P0

Delivered:
BaselineStatsRecord (834c08f), BaselineProvider (cc28792) and scripts/dataset/build_baseline_stats.py (14aa3d5). Merged 2026-10-09; awaiting teammate review. No baseline stats file exists yet: there are no recordings (the schema fixtures are rejected by the builder).

\## TASK-041 — Feature Normalization

Status: REVIEW

Priority: P0

Delivered:
services/grounding/normalizer.py: baseline-relative z-scores with explicit missing/zero-variance handling (8777964). Merged 2026-10-09; awaiting teammate review.

\## TASK-042 — Baseline vs Participant Comparison

Status: REVIEW

Priority: P0

Delivered:
No separate module: per ARCHITECTURE §16 the contrastive delta equals the participant z-score, delivered by the normalized bundle (TASK-041).

\## TASK-043 — Deviation Detection

Status: REVIEW

Priority: P0

Delivered:
Delivered as the threshold rules of TASK-050 (d1268c5).

\---



\# TEMPORAL GROUNDING



\## TASK-050 — Candidate Flaw Windows

Status: REVIEW

Priority: P0

Delivered:
services/grounding/candidates.py (d1268c5): rate, energy and pause rules with PROPOSED, uncalibrated thresholds in core/config.py. flat_pitch is not implemented (needs a baseline statistic of within-window F0 variation; decision required). Merged 2026-10-09; awaiting teammate review.

\## TASK-051 — Window Merging

Status: REVIEW

Priority: P1

Delivered:
Same-type window merging in candidates.py (d1268c5); excessive pauses are deliberately not merged.

\## TASK-052 — Flaw Severity

Status: REVIEW

Priority: P0

Delivered:
services/grounding/severity.py (c0e351b), DEC-028: severity = clip((|mean z| - 1) / 3, 0, 1) x clip(flagged seconds / 5, 0, 1); `excessive_pause` has no duration component. All constants are in core/config.py and PROPOSED (uncalibrated). Merged 2026-10-09; awaiting teammate review.

\## TASK-053 — Evidence Attachment

Status: REVIEW

Priority: P0

Delivered:
services/grounding/flaws.py (c0b53d2): typed evidence (rate, energy, pause) computed from the normalized bundle, the baseline record and the alignment, with the detection rule and the covered words. Every number is derived deterministically; pitch evidence does not exist because flat_pitch is not implemented. Awaiting teammate review.

\## TASK-054 — Final Timestamped Flaw Schema

Status: REVIEW

Priority: P0

Delivered:
Public `Flaw` with start/end/duration, severity, reliability, typed evidence, `rule`, `affected_words`, `warnings`, explanation, recommendation (c0b53d2). API contract 1.1.0 (DEC-029) adds only optional fields. `reliability` is the constant 1.0 and `low_confidence` is false at P0 (not measured). Awaiting teammate review.

\---



\# SCORING



\## TASK-060 — Feature Scoring Rules

Status: REVIEW

Priority: P0

Delivered:
services/scoring/scoring.py (8ab467a), DEC-030: penalty = BASE_PENALTY (30) x severity x reliability per flaw, mapped to its feature (rate -> speech_rate, pauses, energy). Constants PROPOSED, uncalibrated.

\## TASK-061 — Score Normalization

Status: REVIEW

Priority: P0

Delivered:
Sub-score = max(0, 100 - penalty total), rounded to 2 dp (8ab467a, DEC-030). A feature that could not be evaluated (flat_pitch not implemented -> pitch; unavailable features) is omitted, never scored 100 or 0, and its reason is returned.

\## TASK-062 — Overall Score

Status: REVIEW

Priority: P0

Delivered:
Composite = weighted mean of the EVALUATED sub-scores with renormalised effective weights (0.4 / 0.333333 / 0.266667 while pitch is unevaluated) so it can be re-derived from the response (8ab467a, DEC-030). It measures deviation from the baseline, not speech quality, and is uncalibrated.

\## TASK-063 — Reproducibility Validation

Status: BACKLOG

Priority: P0

Progress (task NOT complete):
Determinism is verified on synthetic speech: identical `deterministic_json()` across independent pipeline instances, a cache key covering every input and a configuration fingerprint (tests/test_pipeline_e2e.py, backend/tests/test_pipeline.py; DEC-032). Not yet verified on real recordings, with the real Whisper/WhisperX models, or across machines.

\---



\# EXPLANATION



\## TASK-070 — Evidence-to-Explanation Mapping

Status: REVIEW

Priority: P0

Delivered:
services/explanation/ (d79feb8), DEC-031: a per-flaw fact sheet is the only source of numbers; deterministic templates per flaw type insert fact-sheet strings only.

\## TASK-071 — Recommendation Generation

Status: REVIEW

Priority: P1

Delivered:
Template recommendations per flaw type built from the same fact sheet (d79feb8). They state a direction and, where the baseline provides it, a target value; no advice is generated without evidence.

\## TASK-072 — LLM Explanation Guardrails

Status: REVIEW

Priority: P0

Delivered:
services/explanation/guard.py (d79feb8), DEC-031: an independent check that every number in a text is in the fact sheet and that no spelled-out quantity appears; failing texts fall back to a minimal statement. Only the template provider exists; the LLM call itself is NOT implemented (an LLM provider must pass this same guard).

\---



\# FRONTEND



\## TASK-080 — Frontend Skeleton

Status: REVIEW

Priority: P0

Delivered:
`frontend/`: Vite + React 19 + strict TypeScript (DEC-002, DEC-033); hash routes, small stores, a typed API client whose types are generated from `frontend/openapi.json` (exported from the FastAPI app, drift-tested), design tokens with light and dark themes, a custom icon set, the application shell (sidebar, top bar, whole-recording ribbon, playback bar, command palette, keyboard shortcuts, toasts) and a Vitest suite. The API serves the build at `/` (`backend/app/main.py`, `GET /api/v1/baselines`, CORS; API contract 1.2.0). Docs: `docs/architecture/frontend.md`.

\## TASK-081 — Audio Upload UI

Status: REVIEW

Priority: P0

Delivered:
`features/analyze`: drag and drop, WAV/MP3 check, preview player, baseline and passage chosen from the live catalogue (thin-statistics warning, passage to read), optional manual transcript, offline and empty-catalogue states, API errors shown with their own detail. Exercised in a real browser against a MOCKED API and in component tests; not run against the real Whisper/WhisperX models.

\## TASK-082 — Analysis Progress UI

Status: REVIEW

Priority: P1

Delivered:
Upload progress in bytes, then an indeterminate "analysing" state with elapsed time and a cancel button. The API is synchronous (DEC-016) and reports nothing finer, and the page says so instead of inventing stages.

\## TASK-083 — Overall Score Card

Status: REVIEW

Priority: P1

Delivered:
Overview: the deviation score (exact backend value), a readout from `overall_summary`, the score by dimension with effective weights and penalties, a "not scored" row with the backend's reason for any dimension that was left out, every note grouped by category, and a provenance panel (ids, hashes, versions).

\## TASK-084 — Feature Visualization

Status: REVIEW

Priority: P0

Delivered:
Signals page and the shared plot (`frontend/src/charts/`): speech rate, loudness, pitch (context only) and pauses against the baseline's mean and spread, with linked zoom, tables of the values, the pause table and the MFCC summary. Charts only draw backend series (long ones thinned, extremes kept).

\## TASK-085 — Temporal Flaw Timeline

Status: REVIEW

Priority: P0

Delivered:
Timeline ("scope"): every signal and the findings on one time axis, zoom, pan and fit, crosshair with the values under the pointer, playback with a playhead and an optional follow mode, lane toggles, and for demo samples the injected ground truth with detected and missed flaws. The whole-recording ribbon is on every analysis page.

\## TASK-086 — Flaw Detail Panel

Status: REVIEW

Priority: P0

Delivered:
Flaws page: filterable list and, for one finding, a close-up of the moment, the evidence, the explanation, the recommendation, the detection rule in words, warnings and affected words, with play, loop and keyboard navigation.

\## TASK-087 — Evidence Visualization

Status: REVIEW

Priority: P0

Delivered:
Evidence table and gauge (`components/EvidenceView.tsx`): the participant value against the baseline mean and spread in the measurement's own unit, the z-score and where the finding's rule flags. All numbers are the backend's.

\## TASK-088 — Report, Library, Settings and Help Pages

Status: REVIEW

Priority: P1

Delivered:
An A4 printable report (print stylesheet), a library of the demo samples and of the analyses opened in this browser, settings (theme, density, motion, time format, timeline, API address, versions), and help (guide, glossary, shortcuts, questions).

\## TASK-089 — Demo Samples

Status: REVIEW

Priority: P1

Delivered:
`scripts/demo/build_demo_samples.py` and `frontend/public/samples/` (DEC-034): four synthetic recordings with the results the real pipeline produced for them, labelled as synthetic everywhere, with the selection rule, ground truth and calibration diagnostics in `index.json`. `tests/test_demo_samples.py` guards their integrity.

\## TASK-090 — In-Browser Recording

Status: REVIEW

Priority: P1

Delivered:
`frontend/src/recording/` and `features/analyze/RecorderPanel.tsx` (DEC-035): "Record now" beside "Upload a file", with the passage shown as the prompt, a level scope and clipping warning (capture aids only), device choice, a 5-minute limit and a preview. The microphone is requested with echo cancellation, noise suppression and automatic gain control off; raw samples are converted to 16 kHz mono by a deterministic windowed-sinc resampler and written as a 16-bit WAV that goes into the ordinary upload form. 22 tests with a scripted audio graph, 12 for the converter and WAV writer, 11 for the panel; `npm run smoke` records from Chromium's fake microphone and inspects the uploaded WAV header.

Known limitation:
Never tried with a real microphone, in Safari or Firefox, or on a phone. The first real recording session is the test.

\## TASK-091 — Waveform View

Status: BACKLOG

Priority: P2

Notes:
Needs audio decoded in the browser; the loudness timeline covers the need until then (DEC-033).

\## TASK-092 — Findings Export and Page Link

Status: REVIEW

Priority: P2

Delivered:
"Export CSV" (Flaws page, command palette): one row per finding in time order, backend values unrounded, evidence flattened to `evidence.<field>` columns, RFC 4180 with a UTF-8 byte-order mark. "Copy a link to this page" (top bar, command palette). `lib/csv.ts`, `tests/export.test.ts` (13 tests, parsed back with a small RFC 4180 reader).

\## TASK-093 — Track frontend/src/lib

Status: REVIEW

Priority: P0

Delivered:
The Python template rule `lib/` in `.gitignore` had hidden `frontend/src/lib/` from git, so PR #13 reached `main` without eleven modules and a fresh clone could not type-check or build the frontend. Fixed in PR #14 with a negation in `.gitignore` and the modules committed; a fresh clone of `main` now installs, type-checks (0 errors), passes its tests and builds.

Lesson:
Verify a PR from a fresh clone of its branch before merging, not from the working copy that produced it.

\---



\# TESTING / STRESS TESTING



\## TASK-100 — Unit Test Suite

Status: BACKLOG

Priority: P0



\## TASK-101 — Integration Test

Status: BACKLOG

Priority: P0

Progress (task NOT complete):
tests/test_flaw_detection_e2e.py and tests/test_pipeline_e2e.py run the real preprocessing, features, detection, scoring, explanation and cache on synthetic speech with injected flaws at known times (Whisper and WhisperX replaced by exact-timing stand-ins). No test uses real speech or the real models.

\## TASK-102 — Speaker Variation Test

Status: BACKLOG

Priority: P0



\## TASK-103 — Background Noise Test

Status: BACKLOG

Priority: P0



\## TASK-104 — Speech Rate Stress Test

Status: BACKLOG

Priority: P0



\## TASK-105 — Microphone Variation Test

Status: BACKLOG

Priority: P1



\## TASK-106 — Repeated-Run Reproducibility Test

Status: BACKLOG

Priority: P0

Progress (task NOT complete):
Repeated and independent runs give an identical result on synthetic speech (tests/test_pipeline_e2e.py). Not run on real recordings or on a second machine.

\## TASK-107 — Invalid Input Test

Status: BACKLOG

Priority: P1

Progress (task NOT complete):
Invalid input paths are tested: bad extension/type/size, empty upload, undecodable audio, audio too long, silent audio, unknown or mismatched baseline, empty transcript, unalignable speech, model failures, and that no internal text is returned (backend/tests/test_api_analyze.py, test_pipeline.py). Still open: corrupted-but-decodable audio and noise-only recordings against the real models.

\---



\# SUBMISSION



\## TASK-120 — README

Status: BACKLOG

Priority: P1



\## TASK-121 — Technical Documentation

Status: BACKLOG

Priority: P0



\## TASK-122 — Dataset Finalization

Status: BACKLOG

Priority: P0

Progress (task NOT complete):
The recording protocol (docs/methodology/recording-protocol.md; the leader confirmed speakers, equipment and loudness on 2026-10-11, DEC-036 and DEC-037) and a plain-language guide (docs/methodology/dataset-guide.md) exist. The recording kit (TASK-125) and the registration tool (TASK-126) are built and tested on synthetic audio. The team recorded the first 15 takes (speaker spk_dev_01, passage p001: 3 baseline, 2 clean, 10 flawed); all passed the quality check on 2026-10-12. They are on the team's computer, not in the repository. Still to do: run the registration on them with the real WhisperX and confirm the proposed flaws by ear, the tier after the pilot, the other speakers and passage p002, the evaluation and tuning tools (TASK-127), and the use of the data (baseline, measurement, calibration, frozen test run).

\## TASK-123 — Demo Video

Status: BACKLOG

Priority: P0



\## TASK-124 — Final Demo Run

Status: BACKLOG

Priority: P0



\## TASK-125 — Dataset Recording Kit

Status: REVIEW

Priority: P0

Delivered:
`scripts/dataset/make_plan.py` (deterministic recording plan for any number of speakers and three nested tiers: pilot 9, minimum 36/28, recommended 112/86 takes, `--done` to continue after the pilot; plan files for the team's 2 + 2 speakers in `data/plan/pilot/` and `data/plan/v1/`; plan.csv, one on-screen prompter page per speaker with a setup checklist, highlighted flawed stretch, silent-pause marker and accept/reject tracking, session log), `scripts/dataset/check_recordings.py` (format, size, clipping, level, room noise, silence at the ends, length, mains hum, with plain-language fixes, JSON output and exit codes), `scripts/dataset/passage_text.py` (shared passage rules), final passages `data/plan/passages_v1.json`, `docs/methodology/dataset-guide.md`, `docs/methodology/consent-form-template.md`. 103 tests; 20 injected bugs all caught; the prompter driven in a real Chromium.

Known limitation:
Tested on synthetic audio only; the checker's thresholds come from the protocol and must be confirmed by the pilot. Target durations in the plan are estimates (150 words a minute).

\## TASK-128 — Windowed Energy Rule

Status: BACKLOG

Priority: P0

Notes:
The energy rule judges single 10 ms frames against a wide baseline spread (std about 9 dB), so changes of +6 to +18 dB and -12 to -20 dB in a whole sentence are not flagged even after the loudness scaling of DEC-036. Compare levels over 0.5 to 1 s windows with the baseline's distribution of such windows, then calibrate on real recordings. Analytical change: needs the team leader's approval and a decision record.

\## TASK-126 — Registration and Labelling Tools

Status: REVIEW

Priority: P0

Delivered (2026-10-13, DEC-038):
`scripts/dataset/prepare_recordings.py` (registers a folder of checked WAV files: quality check again, copy to data/raw, SHA-256, preprocessing, WhisperX alignment with the passage text, alignment plausibility checks, alignment JSON, manifest/speaker/passage entries, proposed flaw annotations from the plan with a "was the flaw really performed" check against the speaker's own baseline takes, Audacity label files, dataset validation, optional `--build-baseline`; idempotent, `--replace` for re-recorded takes, confirmed annotations never overwritten), `scripts/dataset/take_checks.py` (the pure checks), `scripts/check_environment.py` (plain-language environment check and one-time model download), the schema fixtures retired (real passages, four anonymous speakers, empty manifest), `docs/methodology/dataset-guide.md` step 6 (PowerShell steps). 126 new tests, including the committed plan and passages end to end with synthetic takes and a stand-in aligner.

Known limitation:
The real WhisperX and Whisper models have never run: the tool was exercised with a stand-in aligner that finds the word bursts in the audio. The first run on the team's computer is the real test and may need changes. All limits of the plausibility and "performed" checks are proposed and uncalibrated. Conversion of hand-made Audacity labels into annotation JSON (protocol workflow B) is not built.

\## TASK-127 — Evaluation and Tuning Tools

Status: BACKLOG

Priority: P0

Notes:
Matching of predictions to annotations (50 % overlap), precision/recall/F1 per flaw type with the number of events, boundary error, false-alarm rate on clean takes, speaker variation, determinism, a guard against analysing the sealed test split before the freeze, and a one-constant-at-a-time sweep on dev (protocol sections 12.3 to 12.5).

\---



\# TEAM RULE



Nobody permanently owns an entire area.



Tasks are pulled dynamically according to:



1\. availability

2\. skill fit

3\. current blocker

4\. project priority

5\. dependency order



Difficult tasks may have two people working together.



Every meaningful task has one Owner and one Reviewer.



\# END

