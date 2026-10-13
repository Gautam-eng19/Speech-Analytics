# Development Environment Setup Guide

## Track C — Contrastive Speech Analytics & Temporal Flaw Grounding
**Task:** TASK-004 — Development Environment
**Last Updated:** 2026-10-09

---

## 1. Requirements

- **OS:** Windows, macOS or Linux (the commands below are given for PowerShell and for bash).
- **Python:** 3.10 – 3.13 (the 2026-10-09 verification used 3.13).
- **Git.**
- **Node.js ≥ 20.19 / npm ≥ 10** — only to build or develop the dashboard (React + Vite + TypeScript, DEC-002, DEC-033). Not needed to run the API or its tests.
- **ffmpeg is NOT required.** MP3 decoding uses PyAV (`av`), and Whisper receives NumPy arrays directly.
- **Disk / network:** `openai-whisper` pulls in PyTorch (several GB). The first real Whisper/WhisperX run downloads model weights.

---

## 2. Quickstart

From the repository root.

PowerShell:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

bash:
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

`.env` is optional (all values have defaults) and must never be committed.

### Verify

```bash
python -m pytest                                  # whole suite; real-model smoke tests are deselected
python scripts/dataset/validate_dataset.py        # dataset schema check (the committed files are fixtures)
```

Expected: all tests pass (810 on 2026-10-09; 2 smoke tests deselected) and dataset validation reports `PASSED`.

Real-model smoke tests (downloads the Whisper base model and the English wav2vec2 alignment model):
```bash
python -m pytest -m smoke
```
These have not been run in the 2026-10-09 verification environment.

### Run the API
```bash
python -m uvicorn app.main:app --app-dir backend --reload
```
Interactive documentation: `http://127.0.0.1:8000/docs`.

| Endpoint | What it does |
|---|---|
| `GET /api/v1/health` | versions of the service |
| `POST /api/v1/analyze` | multipart upload (`participant_audio` WAV/MP3, `baseline_id`, `passage_id`, optional `manual_transcript`, `speaker_gender`, `config_version`); runs the whole pipeline synchronously and returns the `AnalysisResult` |
| `GET /api/v1/status/{analysis_id}` | `done` or `not_found` |
| `GET /api/v1/result/{analysis_id}` | the stored result, or 404 `RESULT_NOT_FOUND` |

### Run the dashboard

```bash
cd frontend && npm ci && npm run build        # once: writes frontend/dist
cd .. && python -m uvicorn app.main:app --app-dir backend
```

Open `http://127.0.0.1:8000/`: the API serves the built dashboard at `/` and itself at `/api/v1`, so there is one origin and no CORS to
configure. The four demo samples (synthetic voice, `frontend/public/samples/`) open without a baseline or the real models; analysing your
own recording needs a baseline (§4). For development run `npm run dev` in `frontend/` (port 5173, proxies `/api` to port 8000).
`FRONTEND_DIST_DIR` (default `frontend/dist`) and `CORS_ORIGINS` (default the Vite dev server) are in `.env.example`.
`npm test` runs the dashboard's tests; `npm run shots` takes screenshots of every page, `npm run a11y` audits every page and state with
axe-core and `npm run smoke` drives the running app in Chromium, including a recording with a fake microphone (the last three need the
server running and a Chromium; see `docs/architecture/frontend.md`).

**Recording in the browser** (New analysis, "Record now") needs a secure page: `http://127.0.0.1:8000/` and `http://localhost:...` count as
secure, a plain `http://` address on another machine does not (the browser refuses microphone access there, and the panel says so).
The take is saved as a 16 kHz mono WAV and handed to the upload form; keep recordings of people out of git.

| Extra endpoint | What it does |
|---|---|
| `GET /api/v1/baselines` | usable baselines with their passage text and whether their statistics are thin; unusable files listed with a reason code |

Notes for the first real run:
- The first analysis loads the Whisper model and downloads the WhisperX alignment model (this can take a while on a slow
  connection; the time has not been measured); later analyses reuse them. The server analyses one recording at a time.
- `baseline_id` is the name of a file `data/processed/baseline_stats/<baseline_id>.json` (normally the passage id, see §4), and it
  must describe `passage_id`; without it the endpoint answers 404 `BASELINE_NOT_FOUND`.
- Results are stored as `<CACHE_DIR>/<analysis_id>.json` (default `data/processed/cache/`). The id is derived from the audio, the
  baseline, the passage text, the configuration and the library versions, so the same request returns the same id and the
  stored result; delete the folder to clear it.
- `THRESHOLDS_CALIBRATED` stays `false` until the thresholds have been calibrated on recordings; every result then carries the
  note `thresholds_uncalibrated`. Variable names are listed in `.env.example`.

---

## 3. Dependencies (`requirements.txt`)

Ranges (`>=`) without a lockfile; ARCHITECTURE.md §26.5 asks for exact pins, which is still to do.

| Package | Used for |
|---|---|
| `fastapi`, `uvicorn[standard]`, `python-multipart` | API and uploads (DEC-003) |
| `pydantic`, `python-dotenv` | contracts and settings |
| `numpy`, `scipy`, `av` | audio decoding, resampling, numerics |
| `librosa` | pYIN F0, MFCC, RMS energy |
| `openai-whisper` | transcription (DEC-P001) |
| `whisperx` | forced alignment (DEC-P002) |
| `pytest` | tests |

---

## 4. Baseline statistics

There are no recordings yet, so no baseline statistics file exists. With recordings registered in `data/metadata/manifest.json`
(real SHA-256 hashes, alignment files as `AlignedTranscript` JSON):
```bash
python scripts/dataset/build_baseline_stats.py --passage-id p001 --splits dev
```
`--splits` is required on purpose (it decides which speakers' baselines may contribute). See DEC-024.

---

## 5. Security & hygiene

- `.env` is gitignored; never commit secrets (`.env.example` lists variable names only).
- Virtual environments, `__pycache__/` and `.pytest_cache/` are gitignored.
- Runtime caches under `data/processed/cache/` are gitignored.
