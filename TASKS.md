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

Status: READY

Priority: P0



Objective:

Define the complete technical architecture and data flow.



\---



\## TASK-002 — API Contract

Status: BACKLOG

Priority: P0



Objective:

Define the request/response schemas connecting frontend and backend.



\---



\## TASK-003 — Dataset Schema

Status: BACKLOG

Priority: P0



Objective:

Define the structure for paired baseline/flawed recordings,

transcripts, alignment information, annotations and metadata.



\---



\## TASK-004 — Development Environment

Status: BACKLOG

Priority: P0



Objective:

Make backend, frontend and required development tools runnable

on all three team machines.



\---



\# BACKEND



\## TASK-010 — FastAPI Application Skeleton

Status: BACKLOG

Priority: P0



\## TASK-011 — Health Endpoint

Status: BACKLOG

Priority: P0



\## TASK-012 — Audio Upload

Status: BACKLOG

Priority: P0



\## TASK-013 — Audio Preprocessing

Status: BACKLOG

Priority: P0



\---



\# TRANSCRIPTION / ALIGNMENT



\## TASK-020 — Transcript Input

Status: BACKLOG

Priority: P0



\## TASK-021 — Transcription Integration

Status: BACKLOG

Priority: P0



\## TASK-022 — Forced Alignment

Status: BACKLOG

Priority: P0



\## TASK-023 — Alignment Validation

Status: BACKLOG

Priority: P1



\---



\# FEATURE EXTRACTION



\## TASK-030 — Pitch / F0 Timeline

Status: BACKLOG

Priority: P0



\## TASK-031 — MFCC Features

Status: BACKLOG

Priority: P0



\## TASK-032 — Energy Timeline

Status: BACKLOG

Priority: P0



\## TASK-033 — Speech Rate

Status: BACKLOG

Priority: P0



\## TASK-034 — Pause Detection

Status: BACKLOG

Priority: P0



\## TASK-035 — Vocal Clarity Measure

Status: BACKLOG

Priority: P1



\---



\# CONTRASTIVE ANALYSIS



\## TASK-040 — Baseline Representation

Status: BACKLOG

Priority: P0



\## TASK-041 — Feature Normalization

Status: BACKLOG

Priority: P0



\## TASK-042 — Baseline vs Participant Comparison

Status: BACKLOG

Priority: P0



\## TASK-043 — Deviation Detection

Status: BACKLOG

Priority: P0



\---



\# TEMPORAL GROUNDING



\## TASK-050 — Candidate Flaw Windows

Status: BACKLOG

Priority: P0



\## TASK-051 — Window Merging

Status: BACKLOG

Priority: P1



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

