\# Architecture Decisions



This file records important decisions that affect the structure,

methodology, reproducibility, or scope of the project.



AI agents may propose decisions.



Only the team leader/team may approve them.



\---



\## DEC-001 — Single Repository



Status:

ACCEPTED



Decision:

Use one GitHub repository for the entire project.



Reason:

All three teammates and all AI agents need one shared source of truth.



\---



\## DEC-002 — Frontend Stack



Status:

ACCEPTED



Decision:

React + Vite + TypeScript.



Reason:

Suitable for rapid development of an interactive dashboard.



\---



\## DEC-003 — Backend Stack



Status:

ACCEPTED



Decision:

Python + FastAPI.



Reason:

The project contains a Python-heavy audio/speech analysis pipeline

and requires a lightweight API layer.



\---



\## DEC-004 — Backend-Owned Analysis



Status:

ACCEPTED



Decision:

All analytical calculations are owned by the backend.



Reason:

Prevents duplicated logic and keeps the frontend focused on

visualization and interaction.



\---



\## DEC-005 — Deterministic Scoring



Status:

ACCEPTED



Decision:

Numerical scoring is deterministic.



Reason:

The project must provide reproducible evaluation results.



LLMs are not the source of numerical truth.



\---



\## DEC-006 — Task-Based Team Workflow



Status:

ACCEPTED



Decision:

The team will not use permanent backend/frontend/ML silos.



Instead, work is organized as small tasks with temporary ownership

and peer review.



Reason:

The system is tightly coupled and the team has three members.



\---



\## DEC-007 — Antigravity as Coding Environment



Status:

ACCEPTED



Decision:

All teammates may use Antigravity as the primary coding environment.



Model choice depends on task complexity.



Reason:

The repository remains identical even when different AI models

are used.



\---



\# UNRESOLVED DECISIONS



The following must be decided after technical investigation:



1\. Transcription technology

2\. Forced-alignment technology

3\. Audio preprocessing configuration

4\. Exact feature-extraction libraries

5\. Pitch normalization methodology

6\. Energy normalization methodology

7\. Baseline construction methodology

8\. Feature comparison methodology

9\. Temporal grounding thresholds

10\. Severity calculation

11\. Feature score formulas

12\. Overall score weighting

13\. Clarity metric/proxy

14\. Dataset size and construction procedure

15\. Deployment architecture



Do not invent these decisions.



Investigate → test → compare → decide → document.



\---



\# DECISION FORMAT



When adding a major decision, use:



\## DEC-XXX — <Decision Name>



Status:

PROPOSED / ACCEPTED / REJECTED / SUPERSEDED



Decision:

<what was selected>



Alternatives:

<other options considered>



Reason:

<why>



Trade-offs:

<advantages and disadvantages>



Impact:

<what parts of the project are affected>



Approved by:

<team leader/team>



Date:

<date>



\# END

