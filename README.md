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

## Status (2026-10-10)

Working and tested (934 backend and 290 dashboard tests, on synthetic speech):

- audio preprocessing with source-time provenance, Whisper transcription, WhisperX alignment and validation
- features: pitch (pYIN), MFCC, energy (dBFS), rolling-window speech rate, pauses (energy VAD + alignment gaps)
- baseline statistics (record, builder script, provider) and baseline-relative z-score normalization
- flaws with start/end times, severity and typed evidence: `too_fast`, `too_slow`, `low_energy`, `high_energy`, `excessive_pause`
- deterministic scoring that leaves unevaluated dimensions out (pitch is currently "not scored")
- template explanations and recommendations whose numbers are checked by an independent guard (no LLM is called)
- `POST /api/v1/analyze` runs the whole pipeline; `GET /api/v1/status/{id}` and `GET /api/v1/result/{id}` return stored results
  (deterministic ids, file cache), with a `notes` list that states everything not evaluated or uncalibrated; `GET /api/v1/baselines`
  lists the baselines that can be used
- the **dashboard** (`frontend/`, light and dark): upload or in-browser recording and baseline choice, overview with the score and its
  dimensions, a timeline with every signal on one time axis, findings with their evidence, explanation and recommendation (exportable as
  CSV), signals, transcript, baseline and method, a printable report, a library, settings and a command palette. It renders backend output only and ships four demo samples
  (synthetic voice, deliberate flaws, analysed by the real pipeline) that open without a baseline

- the **recording kit** for the dataset (`scripts/dataset/make_plan.py`, `check_recordings.py`, final passages in `data/plan/`): a deterministic plan for any number of speakers,
  a prompter page per speaker and a quality check of the recorded files; start with [`docs/methodology/dataset-guide.md`](docs/methodology/dataset-guide.md)

Not done yet: `flat_pitch` detection, an LLM explanation provider. The in-browser recorder has only been tried with Chromium's fake
microphone, not with a real microphone, Safari, Firefox or a phone. There are **no recordings** in the repository,
so detection thresholds and weights are uncalibrated starting values and nothing has been evaluated on real speech. The real
Whisper/WhisperX models were not run in the development sandbox: the pipeline is tested end to end with stand-ins for those two
models, and `python -m pytest -m smoke` (run it on a machine that can download them) is the first thing to do. See `PROJECT_STATE.md`.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate        # PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest
```

Build and open the dashboard (the four demo samples need nothing else; Node 20.19+):

```bash
(cd frontend && npm ci && npm run build)
python -m uvicorn app.main:app --app-dir backend         # then open http://127.0.0.1:8000/
```

Run the API and analyse a recording (needs a baseline statistics file, see [`docs/setup.md`](docs/setup.md) §4):

```bash
python -m uvicorn app.main:app --app-dir backend
curl -F participant_audio=@take.wav -F baseline_id=p001 -F passage_id=p001 http://127.0.0.1:8000/api/v1/analyze
curl http://127.0.0.1:8000/api/v1/result/<analysis_id>      # the stored result, also after a restart
```

Details and options: [`docs/setup.md`](docs/setup.md); the response is documented in [`docs/architecture/api-contract.md`](docs/architecture/api-contract.md).

## Repository map

| Path | Contents |
|---|---|
| `backend/app/` | FastAPI app, schemas (`schemas/`), configuration (`core/`), analytical services (`services/`) |
| `backend/tests/`, `tests/` | unit/API tests and integration/end-to-end tests |
| `scripts/dataset/` | dataset validator, baseline-statistics builder, recording plan generator with an on-screen prompter, recording quality checker |
| `data/` | dataset metadata schema fixtures (no audio yet) |
| `docs/` | architecture proposal, API contract, dashboard, dataset methodology, setup |
| `frontend/` | the dashboard (React + Vite + TypeScript), its tests and the demo samples; see [`docs/architecture/frontend.md`](docs/architecture/frontend.md) |
| `scripts/demo/` | builds the synthetic demo samples |

Project control documents: `AGENTS.md` (rules), `ARCHITECTURE.md` (canonical design), `DECISIONS.md`, `TASKS.md`, `PROJECT_STATE.md`.

## Principles

- Analytical truth is deterministic and backend-owned; an LLM may only phrase already-computed evidence.
- The baseline is the effective delivery of the same content, not a universal human average.
- Missing measurements stay missing; nothing is silently replaced by zero or a default.
- No claim of calibration or accuracy beyond the evaluation evidence that actually exists.
