# Development Environment Setup Guide

## Track C — Contrastive Speech Analytics & Temporal Flaw Grounding
**Task:** TASK-004 — Development Environment
**Last Updated:** 2026-10-09

---

## 1. Requirements

- **OS:** Windows, macOS or Linux (the commands below are given for PowerShell and for bash).
- **Python:** 3.10 – 3.13 (the 2026-10-09 verification used 3.13).
- **Git.**
- **Node.js ≥ 18 / npm ≥ 9** — only for the future frontend (React + Vite + TypeScript, DEC-002). `frontend/` is still a placeholder.
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

Expected: all tests pass (487 on 2026-10-09) and dataset validation reports `PASSED`.

Real-model smoke tests (downloads the Whisper base model and the English wav2vec2 alignment model):
```bash
python -m pytest -m smoke
```
These have not been run in the 2026-10-09 verification environment.

### Run the API
```bash
python -m uvicorn app.main:app --app-dir backend --reload
```
`GET /api/v1/health` works. `POST /api/v1/analyze` currently only validates the upload; the analysis pipeline is not yet orchestrated behind it.

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
