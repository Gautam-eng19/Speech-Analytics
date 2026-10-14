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

Status: REVIEW (delivered as part of TASK-130, DEC-040; calibration on real takes remains in TASK-131)

Priority: P0

Notes:
The energy rule judged single 10 ms frames against a wide baseline spread (std about 9 dB), so changes of +6 to +18 dB and -12 to -20 dB in a whole sentence were not flagged even after the loudness scaling of DEC-036; the first replay on real takes confirmed it (0 of 12 loud and quiet flaws found). Replaced, when the baseline has a word profile, by a comparison of the level of every word with the baseline's level for the same word (a run of at least 10 words, a change of at least 3 dB, more than 4 spreads of a run of that length). The frame rule stays as the fallback.

\## TASK-130 — Word-by-Word Comparison With the Baseline

Status: REVIEW

Priority: P0

Delivered (2026-10-13, DEC-040), after the first replay on the team's real recordings (too_fast 1 of 6 found, too_slow 5 of 6 but 2 s off, loud and quiet 0 of 12, 6 of 8 clean takes flagged, ordinary pauses of 0.8 to 1.25 s flagged with severity 1.0, the same passage region flagged in every take): the baseline keeps a word profile (expected slot and level of every passage word, spread of a run of words measured leave-one-out, spread of the overall pace; built from the passage text and at least three baseline takes by `build_baseline_stats.py` / `prepare_recordings.py --build-baseline`), and pace and loudness are judged word by word against it (`grounding/profile.py`, `profile_detection.py`): runs of words found by a scan, boundaries on word boundaries, the reading's own overall pace and level removed first, a reading that is off as a whole judged as one finding, size guards (15 % pace, 3 dB), a pause counts at most 0.25 s towards a word's pace; severity follows the size of the change; a pause needs 1.2 s to be excessive; `evaluate_takes.py --sweep` compares settings in one table; explanation wording, dashboard wording and notes (`baseline_without_profile`, `profile_not_applicable`) say what was compared. In simulation (human-like readings) clean takes flagged 46 % -> 3 to 5 %, a 1.33 times faster sentence found 33 % -> 78 % with ranges 2 to 3 times too long -> 0.9 times, 5 dB louder or quieter sentences 0 % -> 89 to 91 %. Demo samples regenerated (clean probe 2 of 10 -> 0 of 10; the quiet sentence of the mixed sample is found). 97 new backend tests, 11 end-to-end, 3 dashboard tests.

Known limitation:
Not run on real recordings: every threshold is from simulation. Baselines must be rebuilt. With six baseline takes the spreads are themselves estimated; two speakers pooled in one baseline enlarge the spread of the overall pace; pitch findings are still not detected.

\## TASK-131 — Calibrate the Word-by-Word Settings on the Real Dev Takes

Status: IN PROGRESS (first real check done 2026-10-14, DEC-041: settings kept; listening to the disagreements and confirming the annotations remain)

Priority: P0

Done (2026-10-14, DEC-041): the baselines were rebuilt with the word profile and `evaluate_takes.py` and `--sweep` were run on the 48 real dev takes: 34 of 40 planned flaws found (pause 8 of 8, slow 8 of 8, loud 7 of 8, fast 6 of 8, quiet 5 of 8), ranges 0.8 to 1.0 times the plan, 1 of 8 clean takes flagged; all six misses are takes of one speaker; of the 14 extras on flawed takes 7 are on a planned stretch, 3 right next to one and 4 away. The sweep shows the DEC-040 settings at the point where raising a limit loses real flaws and lowering it adds flags faster than it finds flaws, so they stay.

Remaining:
1. Listen to the places the report lists under "Listen to these first" (`evaluate_takes.py --labels` writes `<take>.detected.txt` for Audacity) and confirm or correct the annotations (`annotation_status: confirmed`); re-record a take whose registration check says it is a weak example. Re-run `--sweep` with `--confirmed-only`.
2. Choose the final values from that table, record them (DEC), then freeze with `THRESHOLDS_CALIBRATED=true` and a CONFIG_VERSION bump.
3. Decide, with the confirmed labels, whether a shorter minimum run (`RUN_MIN_WORDS` 8) or a size guard of 4 dB for loudness is worth its cost (the planned stretches are all whole sentences, so the current takes cannot show it).
4. After rebuilding the baselines (DEC-042), look at the flat-pitch flags the same replay now produces on the real clean and flawed takes: any of them is either a stretch that really was flat or a pitch-tracking error, and the ear and Praat decide (TASK-135).

\## TASK-126 — Registration and Labelling Tools

Status: REVIEW

Priority: P0

Delivered (2026-10-13, DEC-038):
`scripts/dataset/prepare_recordings.py` (registers a folder of checked WAV files: quality check again, copy to data/raw, SHA-256, preprocessing, WhisperX alignment with the passage text, alignment plausibility checks, alignment JSON, manifest/speaker/passage entries, proposed flaw annotations from the plan with a "was the flaw really performed" check against the speaker's own baseline takes, Audacity label files, dataset validation, optional `--build-baseline`; idempotent, `--replace` for re-recorded takes, confirmed annotations never overwritten), `scripts/dataset/take_checks.py` (the pure checks), `scripts/check_environment.py` (plain-language environment check and one-time model download), the schema fixtures retired (real passages, four anonymous speakers, empty manifest), `docs/methodology/dataset-guide.md` step 6 (PowerShell steps). 127 new tests, including the committed plan and passages end to end with synthetic takes and a stand-in aligner.

Known limitation:
The real WhisperX and Whisper models have never run: the tool was exercised with a stand-in aligner that finds the word bursts in the audio. The first run on the team's computer is the real test and may need changes. All limits of the plausibility and "performed" checks are proposed and uncalibrated. Conversion of hand-made Audacity labels into annotation JSON (protocol workflow B) is not built.

\## TASK-129 — Accuracy of Rate and Pause Findings

Status: REVIEW

Priority: P0

Delivered (2026-10-13, DEC-039), after the first test on real recordings (a fast sentence was reported with an extra range; pauses found but not accurate):
rate findings narrowed from their 8 s windows to the words that really deviate (maximum-subarray over word slots, accepted only if the stretch itself is beyond the threshold with a length-scaled spread, otherwise the window interval is kept), silences longer than 1 s counted as 1 s in the speech rate (a deliberate long pause is no longer also reported as slow speech), a pause needs at least 0.8 s to be reported as excessive, findings clipped to the audio, evidence of a narrowed finding describing the narrowed stretch, dashboard wording. In an experiment with human-like synthetic readings the planned fast sentence went from 4.1 times its length (24 % overlap) to 1.0 times (95 %), the slow one from 2.0 times (51 %) to 1.1 times (95 %). 33 new tests; of 38 injected bugs 36 were caught, the other two cannot change behaviour.

Known limitation:
Not run on real recordings. Superseded for pace by TASK-130 (DEC-040): the narrowing is now the fallback for a baseline without a word profile, and the pause floor is 1.2 s. Baselines must be rebuilt.

\## TASK-127a — Replay Evaluation Tool

Status: REVIEW

Priority: P0

Delivered (2026-10-13, DEC-039): `scripts/dataset/evaluate_takes.py`: replays registered dev takes (real audio, stored alignment and baseline, passage text as transcript, no speech model) through the real analysis and compares the findings with the annotations (found or missed, start and end error, overlap, detected range against the plan, extra detections, false alarms on clean takes), `--detect NAME=VALUE` to try other settings, `--json`, the test split sealed (`--allow-test`), baseline takes left out (`--include-baseline`). 30 tests; all 23 injected bugs caught.

Extended (2026-10-14, DEC-041): every MISSED planned flaw says why (the registration check's sentence, the change measured over the planned words against what a finding needs, whether the same kind of flaw was found elsewhere in the take); every EXTRA on a flawed take says whether it lies on a planned stretch, within 3 s of one or away from all of them; a "Listen to these first" list; `--labels` writes the detections as Audacity labels; the sweep table has an `away` column. `measure_stretch` (grounding/profile_detection.py) is the one implementation of the yardstick.

\## TASK-127 — Evaluation and Tuning Tools

Status: BACKLOG (the replay tool and the one-setting-at-a-time sweep, `--sweep`, are done; the rest remains)

Priority: P0

Notes:
Matching of predictions to annotations (50 % overlap), precision/recall/F1 per flaw type with the number of events, boundary error, false-alarm rate on clean takes, speaker variation, determinism, a guard against analysing the sealed test split before the freeze (the replay already refuses it), and the final frozen run on the test split (protocol sections 12.3 to 12.5). Delivered with the replay tool and TASK-130: replay, found/missed, boundary error, extras, false alarms per clean minute, `--sweep`.

\## TASK-132 — Calibrate the Scores

Status: BACKLOG

Priority: P1

Notes:
Found 2026-10-14 on the real replay (DEC-041): a take with one clear planned flaw scores 86 to 98 (a 3 s pause 90 to 92, a slow sentence 86 to 95, a loud sentence 92 to 98), a take with nothing found 100. The score subtracts points only for the flawed seconds of the affected feature (DEC-030: penalty = 30 x severity x reliability, mapped to the feature; sub-scores combined with weights), which is a defensible rule, but the scale is still the initial one and has never been compared with what a listener would call a good, a fair and a poor delivery. Decide with the leader what a score should mean (for example which score a take with one clear flaw, three clear flaws or a flaw in every sentence should get), then set the constants from the real dev takes and record it (DEC). Until then every score is indicative, as the analysis notes already say (`thresholds_uncalibrated`). Not started; the constants must not change without that decision: the scoring methodology is protected (AGENTS.md section 18).

\## TASK-133 — Flat Pitch Detection

Status: REVIEW

Priority: P0

Delivered (2026-10-14, DEC-042), after the comparison with a competing project's approach showed that `flat_pitch` was the one core flaw category the system still did not judge: the word profile of the baseline (DEC-040) now also keeps how much the pitch moved on every word (the pitch part, `word_profile.pitch`: expected movement of each passage word, a leave-one-out noise model, the spread of the speaker's overall expressiveness), and `profile_detection.py` scans runs of at least 10 words for less movement than the baseline readers showed on the same words (one-sided, so livelier speech is never flagged), plus one whole-reading finding. The finding carries the movement in Hz (participant and baseline on the same words), the z-score, the voiced share and the words; severity follows the size of the change (a third of the baseline's movement = 1.0); the explanation is a template that passes the number guard; pitch is now part of the score when it was judged and the note `pitch_not_judged` says why when it was not. The dashboard, the evaluation tool (`flat_pitch` is measured, explained and counted like the other kinds), the baseline builder, the registration report and the demo builder know the new part. 9 new settings (`Z_RUN_PITCH` 4.5 and others, all in `core/config.py`). Hash-compatible: a baseline without the pitch part keeps its hash and answers "flat pitch not checked".

Follow-up (DEC-043): the first run on real takes built no pitch part (the strict voicing decision left 5 % of the frames); a permissive pitch track was added and the pitch part now builds from five real takes without flagging the two clean ones. Rebuild the baselines again.

Known limitation:
Not run on real recordings: no real monotone recording exists, the thresholds come from simulation (synthetic expressive speech analysed with the real pitch tracker: 0 of 40 clean readings flagged; a stretch spoken with 0.1 or 0.3 times the movement found 8 of 8, 0.5 times 4 of 8, 0.7 times 0 of 8 -- by design, a mild loss of intonation is not reported). Pitch trackers make octave and voicing errors on real voices, so the first real replay will show whether clean takes get flat-pitch flags. Baselines must be rebuilt (`prepare_recordings.py data\incoming --build-baseline`) to get the pitch part. Scores of takes that were judged for pitch changed (pitch is now weighted). `pitch_instability` is still not detected (TASK-134).

\## TASK-134 — Pitch Instability Detection

Status: BACKLOG

Priority: P1

Notes:
The remaining unjudged flaw category with a measurable definition. It needs recordings of unstable pitch (a shaky or jumping voice) to calibrate against, as the instability of a stretch cannot be separated from ordinary intonation by a rule written without examples. Do not add a detector from simulation alone: record the examples first (TASK-135), then decide the statistic (for example the frame-to-frame jump of the pitch contour on voiced stretches against the baseline readers') in a decision record.

\## TASK-135 — Record Flat-Pitch Examples and Check the Pitch Detection on Them

Status: BACKLOG

Priority: P0

Notes:
Two monotone takes per dev speaker and passage (one planned sentence, one whole passage; recording protocol 5.2 and 6), registered and replayed with `evaluate_takes.py` like the other kinds. Check: is the monotone stretch found (and where), do the clean takes stay quiet, how large was the change (`flat_pitch` is explained like the others). If clean takes are flagged, listen to the stretch and look at the pitch in Praat: the likely causes are tracker errors (octave jumps, voicing flicker), and the remedy is a setting (`Z_RUN_PITCH`, `MIN_FLAT_PITCH_CHANGE_PCT`) chosen with `--sweep`, not a new rule. Then freeze together with TASK-131.

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

