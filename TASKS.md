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

Status: BACKLOG

Priority: P0



\## TASK-081 — Audio Upload UI

Status: BACKLOG

Priority: P0



\## TASK-082 — Analysis Progress UI

Status: BACKLOG

Priority: P1



\## TASK-083 — Overall Score Card

Status: BACKLOG

Priority: P1



\## TASK-084 — Feature Visualization

Status: BACKLOG

Priority: P0



\## TASK-085 — Temporal Flaw Timeline

Status: BACKLOG

Priority: P0



\## TASK-086 — Flaw Detail Panel

Status: BACKLOG

Priority: P0



\## TASK-087 — Evidence Visualization

Status: BACKLOG

Priority: P0



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
A step-by-step recording, labelling and usage protocol is drafted in docs/methodology/recording-protocol.md (proposed, awaiting team-leader confirmation of its decisions). No recordings exist yet. Recording tools (plan sheet, quality check, registration/alignment, label conversion, evaluation) are not written; see §14 of the protocol.

\## TASK-123 — Demo Video

Status: BACKLOG

Priority: P0



\## TASK-124 — Final Demo Run

Status: BACKLOG

Priority: P0



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

