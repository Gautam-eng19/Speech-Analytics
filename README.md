# Speech-Analytics

**Contrastive Speech Analytics & Temporal Flaw Grounding** — IIT Mandi Multimodal AI Hackathon 2026, Track C.

Speech-Analytics compares a participant's delivery of a passage with an effective baseline delivery of the
**same passage**, finds where the delivery deviates (pace, pauses, loudness, …), measures how much, and pins each
finding to a time interval with the numbers that support it. It evaluates **delivery**, not content, and it is not a
generic speech-quality score or an LLM giving advice: every number comes from deterministic backend code.

```
audio → preprocessing → transcription → forced alignment → feature extraction → baseline statistics
      → normalization → contrastive comparison → flaw candidates → severity → scoring → evidence-backed explanation
      → API → dashboard
```

## Status (2026-10-09)

Working and tested (487 tests):

- audio preprocessing with source-time provenance, Whisper transcription, WhisperX alignment and validation
- features: pitch (pYIN), MFCC, energy (dBFS), rolling-window speech rate, pauses (energy VAD + alignment gaps)
- baseline statistics (record, builder script, provider) and baseline-relative z-score normalization
- flaw candidates with start/end times: `too_fast`, `too_slow`, `low_energy`, `high_energy`, `excessive_pause`

Not done yet: severity, scoring, explanations, the orchestrated `POST /api/v1/analyze` (it only validates uploads),
result caching, `flat_pitch` detection, and the frontend. There are **no recordings** in the repository, so detection
thresholds are uncalibrated starting values and nothing has been evaluated on real speech. See `PROJECT_STATE.md`.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate        # PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest
```

Details and options: [`docs/setup.md`](docs/setup.md).

## Repository map

| Path | Contents |
|---|---|
| `backend/app/` | FastAPI app, schemas (`schemas/`), configuration (`core/`), analytical services (`services/`) |
| `backend/tests/`, `tests/` | unit/API tests and integration/end-to-end tests |
| `scripts/dataset/` | dataset validator and baseline-statistics builder |
| `data/` | dataset metadata schema fixtures (no audio yet) |
| `docs/` | architecture proposal, API contract, dataset methodology, setup |
| `frontend/` | placeholder (React + Vite + TypeScript planned) |

Project control documents: `AGENTS.md` (rules), `ARCHITECTURE.md` (canonical design), `DECISIONS.md`, `TASKS.md`, `PROJECT_STATE.md`.

## Principles

- Analytical truth is deterministic and backend-owned; an LLM may only phrase already-computed evidence.
- The baseline is the effective delivery of the same content, not a universal human average.
- Missing measurements stay missing; nothing is silently replaced by zero or a default.
- No claim of calibration or accuracy beyond the evaluation evidence that actually exists.
