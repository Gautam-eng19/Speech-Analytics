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
Upload validation only (a1b8048): extension, content type, size, config_version. POST /api/v1/analyze does NOT run the analysis pipeline yet; see PROJECT_STATE.md.

\## TASK-013 — Audio Preprocessing

Status: DONE

Priority: P0

Delivered:
Deterministic mono/16 kHz/peak-normalised preprocessing with silence trimming (f1a0836). Gap: all-silence input returns an empty array that downstream extractors reject.

\## TASK-013A — Preserve source-time provenance when trimming audio

Status: REVIEW

Priority: P0

Delivered:
PreprocessedAudio.trim_start_s and source_duration_s plus find_active_span() (33e9330); trim_silence(), audio_array and sha256 unchanged. Conversion to source time is deliberately NOT applied anywhere yet: it must happen exactly once, at response assembly (DEC-023). Merged 2026-10-09; awaiting teammate review.

\---



\# TRANSCRIPTION / ALIGNMENT



\## TASK-020 — Transcript Input

Status: BACKLOG

Priority: P0

Delivered:
Not implemented. The API accepts `manual_transcript` but no pipeline code consumes it, and no manual-transcript alignment path exists (AlignmentMethod.MANUAL is never produced).

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

Status: BACKLOG

Priority: P0



\## TASK-053 — Evidence Attachment

Status: BACKLOG

Priority: P0



\## TASK-054 — Final Timestamped Flaw Schema

Status: BACKLOG

Priority: P0



\---



\# SCORING



\## TASK-060 — Feature Scoring Rules

Status: BACKLOG

Priority: P0



\## TASK-061 — Score Normalization

Status: BACKLOG

Priority: P0



\## TASK-062 — Overall Score

Status: BACKLOG

Priority: P0



\## TASK-063 — Reproducibility Validation

Status: BACKLOG

Priority: P0



\---



\# EXPLANATION



\## TASK-070 — Evidence-to-Explanation Mapping

Status: BACKLOG

Priority: P0



\## TASK-071 — Recommendation Generation

Status: BACKLOG

Priority: P1



\## TASK-072 — LLM Explanation Guardrails

Status: BACKLOG

Priority: P0



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



\## TASK-107 — Invalid Input Test

Status: BACKLOG

Priority: P1



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

