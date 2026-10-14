# VAANI

**Contrastive Speech Analytics & Temporal Flaw Grounding** — IIT Mandi Multimodal AI Hackathon 2026, Track C.

VAANI compares a participant's delivery of a passage with an effective baseline delivery of the
**same passage**, finds where the delivery deviates (pace, pauses, loudness, …), measures how much, and pins each
finding to a time interval with the numbers that support it. It evaluates **delivery**, not content, and it is not a
generic speech-quality score or an LLM giving advice: every number comes from deterministic backend code.

```
audio → preprocessing → transcription → forced alignment → feature extraction → baseline statistics
      → normalization → contrastive comparison → flaw candidates → severity → scoring → evidence-backed explanation
      → API → dashboard
```

## Status (2026-10-14)

Working and tested (1389 backend and 386 dashboard tests, on synthetic speech):

- audio preprocessing with source-time provenance, Whisper transcription, WhisperX alignment and validation
- features: pitch (pYIN), MFCC, energy (dBFS), rolling-window speech rate, pauses (energy VAD + alignment gaps)
- baseline statistics (record, builder script, provider) and baseline-relative z-score normalization
- flaws with start/end times, severity and typed evidence: `too_fast`, `too_slow`, `low_energy`, `high_energy`, `excessive_pause`
- deterministic scoring that leaves unevaluated dimensions out (pitch is scored when the baseline has a pitch profile)
- template explanations and recommendations whose numbers are checked by an independent guard (no LLM is called)
- `POST /api/v1/analyze` runs the whole pipeline; `GET /api/v1/status/{id}` and `GET /api/v1/result/{id}` return stored results
  (deterministic ids, file cache), with a `notes` list that states everything not evaluated or uncalibrated; `GET /api/v1/baselines`
  lists the baselines that can be used
- the **dashboard** (`frontend/`, dark by default, light on request; the VAANI identity of DEC-045: a home page with a live instrument that draws a real analysis of a demo recording, hover to read any moment, click a finding to hear it): upload or in-browser recording and baseline choice, overview with the score and its
  dimensions, a timeline with every signal on one time axis, findings with their evidence, explanation and recommendation (exportable as
  CSV), signals, transcript, baseline and method, a printable report, a library, settings and a command palette. It renders backend output only and ships four demo samples
  (synthetic voice, deliberate flaws, analysed by the real pipeline) that open without a baseline

- the **recording kit** for the dataset (`scripts/dataset/make_plan.py`, `check_recordings.py`, final passages in `data/plan/`): a deterministic plan for any number of speakers,
  a prompter page per speaker and a quality check of the recorded files; start with [`docs/methodology/dataset-guide.md`](docs/methodology/dataset-guide.md)
- the **registration tool** (`scripts/dataset/prepare_recordings.py`, with `scripts/check_environment.py`): turns a folder of checked recordings into dataset files (manifest, hashes,
  word alignment with the passage text, proposed flaw annotations that a person confirms by ear, Audacity label files) and builds the baseline. Tested end to end with a stand-in for the
  alignment model; the real WhisperX run on real recordings is still to be done
- the **evaluation tool** (`scripts/dataset/evaluate_takes.py`): replays registered takes through the real analysis without any speech model and measures, against the annotations, which flaws were found, how far off the start and end are, and how many false alarms a clean take gets; for a missed flaw it says how big the change really was and what the registration check said, tells a flag next to a planned flaw (a side effect of how it was performed) from one far away, lists what to listen to first and writes the detections as Audacity labels (`--labels`); `--sweep` compares several values of a setting in one table
- **custom passages** (DEC-044): a page of the dashboard where a user pastes their own text, adds two or three recordings of a good reading to make a baseline, and then analyses their own reading against it (the audio is never stored, only statistics and the text; `POST /api/v1/custom/baselines`)
- **word-by-word comparison** (DEC-040): the baseline keeps how the same passage words were read (expected duration and level of every word, and how much a reading varies), and pace and loudness findings are runs of words judged against it, so a
  finding starts and ends on word boundaries and the content of the words is not mistaken for delivery
- **flat pitch** (DEC-042): the same word profile also keeps how much the pitch moved on every word, so a stretch or a whole reading that is more monotone than the baseline readers read the same words is reported with the movement in Hz,
  the baseline's movement on the same words and where it happened (tried on synthetic speech with a real pitch tracker; no real monotone recording exists yet)

Not done yet: `pitch_instability` detection, an LLM explanation provider. The in-browser recorder has only been tried with Chromium's fake
microphone, not with a real microphone, Safari, Firefox or a phone. No recordings of people are in the repository (they are kept out of git on purpose);
the team evaluated the system on its own 48 recordings of two speakers (40 with a planned flaw, 8 clean): 34 of the 40 planned flaws were found, 1 of the 8 clean readings was flagged
(see `DECISIONS.md`, DEC-041, and `PROJECT_STATE.md`). Detection thresholds and weights are still starting values, not calibrated, and every result says so in its `notes`.
The automated tests use stand-ins for Whisper and WhisperX (they cannot be downloaded in a sandbox); `python -m pytest -m smoke` runs the real models on a machine that can download them.

## Quickstart

**Prerequisites:** Python 3.10 to 3.13, Git, and Node.js 20.19 or newer (only to build the dashboard). No ffmpeg. Analysing a recording with the real speech models downloads Whisper and a WhisperX
alignment model on first use (PyTorch is several GB), so allow time and disk space; the four demo samples need none of that.

**Three ways to try it**

1. **Look at a demo (no models, no recordings):** build and open the dashboard (below); on *New analysis* open one of the four demo samples (synthetic voice with deliberate flaws, analysed by the real pipeline).
2. **Analyse your own voice on your own text:** open *Custom passage*, paste a text (30+ words, two sentences or more), add two or three recordings of a good reading to make a baseline, then add one more reading and analyse it.
   This uses the real speech models, so run `python scripts/check_environment.py --download-models` once first.
3. **Use the API directly:** see the `curl` example below (needs a baseline statistics file, which *Custom passage* creates, or see [`docs/setup.md`](docs/setup.md) §4 for the dataset route).

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
| `scripts/dataset/` | dataset validator, baseline-statistics builder, recording plan generator with an on-screen prompter, recording quality checker, registration tool |
| `scripts/check_environment.py` | checks that a computer has what the project needs and downloads the speech models once |
| `data/` | dataset metadata (real passages, anonymous speakers, empty manifest until recordings are registered; no audio is committed) |
| `docs/` | architecture proposal, API contract, dashboard, dataset methodology, setup |
| `frontend/` | the dashboard (React + Vite + TypeScript), its tests and the demo samples; see [`docs/architecture/frontend.md`](docs/architecture/frontend.md) |
| `scripts/demo/` | builds the synthetic demo samples |
| `docs/submission/` | the hackathon submission material: demo video script, Devpost description draft, checklist |

Project control documents: `AGENTS.md` (rules), `ARCHITECTURE.md` (canonical design), `DECISIONS.md`, `TASKS.md`, `PROJECT_STATE.md`.

## Principles

- Analytical truth is deterministic and backend-owned; an LLM may only phrase already-computed evidence.
- The baseline is the effective delivery of the same content, not a universal human average.
- Missing measurements stay missing; nothing is silently replaced by zero or a default.
- No claim of calibration or accuracy beyond the evaluation evidence that actually exists.
