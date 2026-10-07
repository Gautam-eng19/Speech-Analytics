# Development Environment Setup Guide

## Track C — Contrastive Speech Analytics & Temporal Flaw Grounding
**Task:** TASK-004 — Development Environment  
**Last Updated:** 2026-10-07  

---

## 1. Overview & System Requirements

This document provides clear, reproducible setup instructions for setting up the development environment across teammate machines.

### 1.1 Prerequisites
- **Operating System:** Windows 10/11, macOS, or Linux (Team development is on Windows PowerShell).
- **Python:** 3.10 to 3.13 (Python 3.13+ verified on Windows).
- **Node.js:** v18.0+ or v20.0+ LTS recommended (v24.x verified for tooling; required for Vite/React frontend).
- **Git:** Version control.
- **Audio Tooling (System Binary):** `ffmpeg` (required later for audio decoding and format normalization).

---

## 2. Quickstart for Team Members (Windows PowerShell)

Follow these steps from the root of the cloned repository (`d:\Speech-Analytics`):

### Step 1: Create and Activate Python Virtual Environment
```powershell
# Create virtual environment in root .venv
python -m venv .venv

# Activate virtual environment in PowerShell
.\.venv\Scripts\Activate.ps1
```
*(If execution of scripts is restricted in PowerShell, run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` once).*

### Step 2: Install Python Dependencies
```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Step 3: Configure Environment Variables
Copy `.env.example` to `.env`:
```powershell
Copy-Item .env.example .env
```
Default configuration values in `.env` are pre-tuned for local development without requiring any external cloud secrets.

### Step 4: Run Verification Tests
Verify that the environment and test runners function correctly:
```powershell
# 1. Run all tests (API contracts and dataset schema validation)
python -m pytest

# 2. Run dataset integrity check script
python scripts/dataset/validate_dataset.py
```
Expected output: All 47 tests pass and dataset validation reports `PASSED`.

---

## 3. Python Environment Details

### Dependencies (`requirements.txt`)
The initial environment includes only dependencies strictly justified by the finalized architecture (FastAPI/backend stack, Pydantic contracts, numerical foundations, and testing):
- `fastapi`: API layer framework (DEC-003).
- `uvicorn[standard]`: ASGI server for development and execution.
- `pydantic`: Schema definitions and strict validation (TASK-002 API Contract).
- `python-multipart`: Handling `multipart/form-data` audio file uploads.
- `python-dotenv`: Environment configuration management.
- `numpy`: Numerical representation for audio arrays and feature contracts.
- `pytest`: Unified test runner.

*Note on heavy audio/ML packages:* Packages such as `librosa`, `soundfile`, `openai-whisper`, and `whisperx` are deferred to their respective implementation tasks (TASK-013, TASK-021, TASK-022, TASK-030) to prevent dependency conflicts and keep bootstrap lightweight.

---

## 4. Node.js & Frontend Environment (DEC-002)

The frontend stack is **React + Vite + TypeScript**.

### Required Tools
- Node.js: `>= 18.0.0`
- npm: `>= 9.0.0`

### Frontend Bootstrapping (Preview for TASK-080)
The `frontend/` directory is currently initialized as a placeholder directory. Full frontend dependencies and scaffold will be established in TASK-080 (`Frontend Skeleton`).

---

## 5. Security & Hygiene Checklist
- `.env` is ignored by `.gitignore` and must never be committed.
- Virtual environments (`.venv/`, `backend/.venv/`, `env/`) are ignored.
- Pytest and Python bytecode caches (`__pycache__/`, `.pytest_cache/`) are ignored.
- Audio and runtime caches in `data/processed/cache/` are ignored.
