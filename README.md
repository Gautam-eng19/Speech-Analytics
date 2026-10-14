<div align="center">

# 🎙️ VAANI

### Contrastive speech analytics with temporal flaw grounding

**Hear the difference. Understand the why.**

![Python](https://img.shields.io/badge/Python-3.10--3.13-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5.9-3178C6?logo=typescript&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-7-646CFF?logo=vite&logoColor=white)
![Speech models](https://img.shields.io/badge/Whisper%20%2B%20WhisperX-speech%20models-74AA9C)
![Tests](https://img.shields.io/badge/tests-1389%20backend%20%2B%20386%20dashboard-2EA043)
![API contract](https://img.shields.io/badge/API%20contract-1.3.0-6E7681)
![Track C](https://img.shields.io/badge/IIT%20Mandi%20Multimodal%20AI%20Hackathon%202026-Track%20C-F28C5B)

[Quick start](#quick-start) · [How it works](#how-it-works) · [Tech stack](#tech-stack) · [API](#api-reference) · [Technical report](docs/TECHNICAL_REPORT.md) · [Documentation](#documentation)

<img src="docs/demo/screenshots/landing.jpg" alt="The VAANI home page. A live instrument draws the speech-rate trace and the loudness of a demo recording, with labelled copper intervals where the delivery deviated from the baseline." width="100%">

</div>

> [!NOTE]
> **At a glance**
>
> - VAANI evaluates **delivery** (pace, pauses, loudness, pitch movement) against a baseline reading of the *same text*, and ties every finding to a time interval and to measured evidence.
> - Every number comes from deterministic analysis code; the same input and configuration always give the same result.
> - **No LLM runs anywhere.** Explanations are templates filled from measured evidence, and an independent guard rejects any sentence containing a number that is not in that evidence.
> - Everything runs on your own machine, and the dashboard talks only to its own server.

## Contents

[Overview](#overview) · [Features](#features) · [Screenshots](#screenshots) · [How it works](#how-it-works) · [Flaw types](#flaw-types) · [Tech stack](#tech-stack) · [Project structure](#project-structure) · [Quick start](#quick-start) · [Using the dashboard](#using-the-dashboard) · [Configuration](#configuration) · [API reference](#api-reference) · [Running the tests](#running-the-tests) · [Dataset kit](#dataset-kit) · [Documentation](#documentation) · [Engineering principles](#engineering-principles) · [Roadmap](#roadmap) · [Privacy and consent](#privacy-and-consent) · [Acknowledgements and licence](#acknowledgements-and-licence)

## Overview

**VAANI** (वाणी, "speech, voice") compares a spoken delivery with an *effective reading of the same passage* and answers six questions about it:

1. **Where** did the delivery drift from the reference?
2. **Which** measurable signal changed: pace, pauses, loudness, pitch movement?
3. **How much**, in the signal's own units (words per minute, seconds, dB, Hz)?
4. **When**: from which word to which word, in seconds?
5. **Why** is that a delivery flaw, in terms of the evidence?
6. **What** should the speaker do about it?

A recording goes in. What comes out is a short list of **findings**, each tied to a time interval, to the measurements that support it and to a recommendation, plus a 0–100 score that is nothing more than the arithmetic of those findings.

| Principle | What it means here |
|---|---|
| **Contrast, not an average** | The reference is a good reading of the *same* text, not a universal human average. The comparison runs word by word, so a naturally long word or an expected pause is not mistaken for a flaw. |
| **Grounded in time** | A flaw without an interval is incomplete. Every finding has a start and an end, on word boundaries wherever possible. |
| **Evidence before explanation** | Every sentence the user reads is built from structured evidence. A number that is not in the evidence cannot appear. |
| **Deterministic** | The same audio, baseline and configuration give the same findings, the same score and the same `analysis_id`. |
| **Transparent** | Every result carries notes that describe how it was produced. |
| **The backend owns the truth** | The dashboard only draws what the API returns. It computes no pitch, rate, severity or score. |

Youtube Link : (https://youtube.com/watch?v=RAUbhJ1S9z4&si=YDYDUJuvXlpIbj_i)

## Features

**Dashboard** (React, dark by default, light on request)

- **Home page** with a live instrument that draws the real analysis of a demo recording: hover to read any moment, click a labelled interval to hear it.
- **New analysis**: upload a WAV or MP3 or record in the browser, pick a baseline, analyse.
- **Custom passage**: paste your own text, add two to six recordings of a good reading to make a baseline, then analyse your own reading against it.
- **Overview** (score, score profile radar, readout), **Timeline** (every signal on one zoomable time axis, linked to playback), **Flaws** (evidence, explanation and recommendation for each finding; CSV export), **Signals**, **Transcript**, **Baseline and method**, and a **printable report**.
- **Library** of the demo samples and your analyses (kept in your browser), settings, help, a command palette (`Ctrl+K`), keyboard shortcuts, light and dark themes.

**API** (FastAPI, documented, versioned as contract 1.3.0)

- Upload a recording, get the full structured `AnalysisResult`: features, flaws with evidence, scores, notes. Results are cached under a deterministic id and can be fetched again.

**Dataset kit**

- A deterministic recording plan with an on-screen prompter, a recording quality checker, a registration tool that aligns and annotates takes, and a replay tool that runs registered takes through the analysis and compares the findings with the plan.

## Screenshots

> All screenshots show the built-in **demo samples** (a speech-synthesiser voice with deliberate flaws). They show the interface.

<p align="center">
  <a href="docs/demo/screenshots/overview.jpg"><img src="docs/demo/screenshots/overview.jpg" alt="Overview page of the Mixed flaws demo: deviation score 84.5 out of 100 and a readout of three findings" width="100%"></a><br>
  <b>Overview</b>: the score, and a plain-language readout of the findings behind it
</p>

<p align="center">
  <a href="docs/demo/screenshots/profile.jpg"><img src="docs/demo/screenshots/profile.jpg" alt="Score profile radar: speech rate 84.0, pauses 77.4, energy 75.0, pitch 100.0, with a tooltip on the speech-rate axis" width="100%"></a><br>
  <b>Score profile</b>: each dimension against the reference ring of 100, and what the findings cost
</p>

<p align="center">
  <a href="docs/demo/screenshots/timeline.jpg"><img src="docs/demo/screenshots/timeline.jpg" alt="Timeline page: findings, words, loudness, pitch, speech rate and pauses on one time axis with a selected excessive pause" width="100%"></a><br>
  <b>Timeline</b>: every signal on one time axis, linked to playback; hover reads any moment
</p>

<p align="center">
  <a href="docs/demo/screenshots/finding.jpg"><img src="docs/demo/screenshots/finding.jpg" alt="Flaws page: the too-fast finding from 5.4 to 9.1 seconds with severity, the words, measured evidence and the explanation" width="100%"></a><br>
  <b>A finding</b>: interval, severity, the words it covers, measured evidence and explanation
</p>

<p align="center">
  <a href="docs/demo/screenshots/landing-phone.jpg"><img src="docs/demo/screenshots/landing-phone.jpg" alt="The home page at phone width" width="260"></a><br>
  <b>Phone width</b>: the same instrument, with shorter labels
</p>

## How it works

### The pipeline

```mermaid
flowchart TB
    IN(["Recording<br/>WAV or MP3"])
    BASE[("Baseline<br/>statistics and word profile,<br/>made from good readings<br/>of the same text")]

    subgraph S1["1 · Prepare the audio"]
        direction LR
        P1["Preprocessing<br/>16 kHz mono,<br/>speech level"] --> P2["Transcription<br/>Whisper"] --> P3["Forced alignment<br/>WhisperX,<br/>word times"]
    end
    subgraph S2["2 · Measure and compare"]
        direction LR
        M1["Feature extraction<br/>F0, MFCC, energy,<br/>rate, pauses"] --> M2["Baseline<br/>normalisation<br/>z-scores"] --> M3["Contrastive<br/>comparison<br/>word by word"]
    end
    subgraph S3["3 · Judge and explain"]
        direction LR
        J1["Flaw detection<br/>start, end, type"] --> J2["Severity<br/>0 to 1"] --> J3["Scoring<br/>deterministic"] --> J4["Explanation<br/>templates and<br/>number guard"]
    end

    IN --> S1
    S1 --> S2
    BASE --> S2
    S2 --> S3
    S3 --> API["API response<br/>contract 1.3.0"]
    API --> UI["Dashboard<br/>presentation only"]
```

| # | Stage | What happens | Code |
|---|---|---|---|
| 1 | **Preprocessing** | Decodes WAV or MP3, mixes to mono, resamples to 16 kHz, scales loudness so typical speech sits at −26 dBFS (peak capped at −1 dBFS), trims leading and trailing silence and remembers the offset so every timestamp refers to the original file. Limits: 10 MB and 5 minutes. | `services/audio/` |
| 2 | **Transcription** | Whisper (`base` model, English) turns the speech into text. A `manual_transcript` can be supplied instead. | `services/transcription/` |
| 3 | **Forced alignment** | WhisperX gives every word a start and an end time; implausible alignments are rejected. | `services/alignment/` |
| 4 | **Feature extraction** | Pitch (pYIN F0, 75–500 Hz), 13 MFCCs, energy (RMS in dBFS), speech rate (rolling 8 s windows every 4 s), and pauses (energy voice-activity detection plus gaps between aligned words), all on a 10 ms grid. | `services/features/` |
| 5 | **Baseline normalisation** | Expresses the participant's measurements relative to the baseline's statistics (z-scores). | `services/grounding/normalizer.py` |
| 6 | **Contrastive comparison** | Judges pace, loudness and pitch movement *word by word* against how the baseline readers read the same words (see below). | `services/grounding/profile*.py` |
| 7 | **Flaw detection and grounding** | Turns deviations into candidate findings with a start, an end and a type. | `services/grounding/candidates.py`, `flaws.py` |
| 8 | **Severity** | A number from 0 to 1 from the *size* of the change and how long it lasted. | `services/grounding/severity.py` |
| 9 | **Scoring** | Deterministic arithmetic over the findings (see below). | `services/scoring/` |
| 10 | **Explanation** | Fills a template from the finding's evidence and checks every number with an independent guard. | `services/explanation/` |
| 11 | **API response** | One typed `AnalysisResult`, cached under a deterministic id. | `schemas/`, `core/cache.py` |
| 12 | **Dashboard** | Draws the result and plays the audio. | `frontend/` |

Orchestration lives in `backend/app/services/pipeline.py`.

### The baseline and the word profile

A single average pace for a whole passage cannot tell a rushed sentence from a sentence that is simply full of short words. So the baseline keeps, **for every word of the passage**, how long it took, how loud it was and how much the pitch moved on it in each good reading, and how much those readings differ from one another. A new reading is compared with that, word by word:

- A **pace or loudness finding** is a run of consecutive words that clearly differs from the baseline readers' pace or level on those same words, after the reading's own overall pace and level have been taken out. A reading that is fast, slow, loud or quiet *as a whole* becomes one finding covering the whole reading.
- A **flat-pitch finding** is a run of words (or the whole reading) with clearly less pitch movement than the baseline readers had on the same words.
- An **excessive pause** is a pause that is much longer than the baseline's pauses at that kind of place (inside a sentence or between sentences).
- With **three or more baseline readings** VAANI builds the full word profile; with two it uses overall averages and says so in the result's `notes`.

### Severity and score

- **Severity** (0–1) combines the size of the change with how long the deviation lasted (a pause's severity depends on its excess length).
- **Score:** each finding costs its dimension points in proportion to its severity (`30 × severity`). A dimension starts at 100. The overall score is the weighted sum of the four dimensions: **speech rate 30 %, pitch 25 %, pauses 25 %, energy 20 %**. A dimension that could not be judged is left out and the other weights are renormalised. **100 means "no deviation detected".**

Worked example, the *Mixed flaws* demo (three findings, one in each of three dimensions):

| Dimension | Findings | Penalty | Score | Weight |
|---|---|---|---|---|
| Speech rate | 1 (too fast, severity 0.5343) | 30 × 0.5343 = 16.03 | 83.97 | 30 % |
| Pitch | 0 | 0 | 100.00 | 25 % |
| Pauses | 1 | 22.58 | 77.42 | 25 % |
| Energy | 1 | 25.04 | 74.96 | 20 % |

Overall: `0.30 × 83.97 + 0.25 × 100.00 + 0.25 × 77.42 + 0.20 × 74.96 = 84.54`.

### Explanations and the number guard

The explanation of a finding is a **template filled from its structured evidence** (`explanation_method: "template"`). Before it is shown, an independent guard (`services/explanation/guard.py`) checks that every numeric token equals a value in the finding's fact sheet and rejects spelled-out quantities such as "twice" or "half". An explanation layer that cannot invent a number is what lets every figure on screen be traced back to a measurement.

### A finding, end to end

A real finding from the *Mixed flaws* demo, trimmed (shortened: some fields omitted):

```jsonc
{
  "flaw_id": "flaw_001",
  "type": "too_fast",
  "start_s": 5.3996,
  "end_s": 9.0548,
  "duration_s": 3.6552,
  "severity": 0.5343,
  "evidence": {
    "rate_participant_wpm": 276.9105,
    "rate_baseline_mean_wpm": 166.8481,
    "rate_baseline_std_wpm": 6.0538,
    "rate_delta_wpm": 110.0625,
    "rate_delta_pct": 65.9657,
    "rate_z_score": 18.1808,
    "word_count_in_window": 17
  },
  "explanation": "5.4–9.1 s: speech rate averaged 276.9 words/min, 66.0% above the 166.8 words/min the baseline readings had for these same words (18.18 standard deviations above it), covering “Over” to “they”. …",
  "recommendation": "Slow down in this stretch: aim for about 166.8 words/min, the pace the baseline readings had for these words, and keep the pauses between phrases.",
  "explanation_method": "template",
  "affected_words": ["Over", "the", "past", "year", "…", "they"]
}
```

The chain is always the same: **timestamp → measured evidence → flaw type → explanation → recommendation.**

### Reproducibility

The `analysis_id` is a UUID derived from a SHA-256 of everything the result depends on: the preprocessed audio, the baseline, the passage, any manual transcript, the configuration, the pipeline and API versions, a fingerprint of every analytical constant, and the library versions. Same request, same id, same stored result; a changed configuration gives a new id, so a stale result is never served. Randomness plays no part in any number the user sees.

<details>
<summary><b>Terms used</b></summary>

| Term | Meaning |
|---|---|
| **Baseline** | Statistics (and a word profile) built from good readings of the same passage. The reference for every comparison. |
| **Word profile** | For each word of the passage: how long it took, how loud it was and how much the pitch moved, in the baseline readings, plus how much those readings vary. |
| **z-score** | How many "natural spreads" a measurement is from the baseline's average. Larger means less likely to be ordinary variation. |
| **Forced alignment** | Matching known text to audio to get a start and end time for every word. |
| **F0** | Fundamental frequency, i.e. the pitch of the voice, in Hz. |
| **MFCC** | Mel-frequency cepstral coefficients, a compact description of the spectral shape of the voice. Extracted and shown on the Signals page. |
| **dBFS** | Loudness relative to the loudest level a digital recording can hold (0 dBFS). |
| **Severity** | How serious a deviation is, from 0 to 1. |

</details>

## Flaw types

| Type | What it means | Measured evidence |
|---|---|---|
| `too_fast` | A run of words spoken faster than the baseline readers spoke the same words | rate, baseline rate and spread, difference in words/min and %, z-score, word count |
| `too_slow` | The same, slower | same fields |
| `excessive_pause` | A pause far longer than the baseline's pauses at that kind of place | pause length, baseline mean and spread, difference in s, z-score, where (inside or between sentences) |
| `low_energy` | Words spoken quieter than the baseline readers spoke them | level, baseline level and spread, difference in dB, z-score |
| `high_energy` | The same, louder | same fields |
| `flat_pitch` | Clearly less pitch movement than the baseline readers had on the same words | movement in Hz against the baseline's, z-score, voiced share, the words |

Each category has measurable evidence, a detection rule, temporal grounding, a scoring policy, an explanation policy and tests.

## Tech stack

| Layer | Technology | Used for |
|---|---|---|
| **API** | Python 3.10–3.13, **FastAPI**, **Uvicorn**, **Pydantic v2**, python-multipart, python-dotenv | Typed contract, uploads, settings, serving the built dashboard |
| **Audio** | **PyAV** (`av`), NumPy, SciPy | WAV and MP3 decoding (no ffmpeg needed), polyphase resampling, numerics |
| **Acoustic features** | **librosa** | pYIN F0, MFCC, RMS energy |
| **Speech models** | **OpenAI Whisper** (`openai-whisper`), **WhisperX** (+ PyTorch) | Transcription and forced word alignment |
| **Analysis** | Plain, deterministic Python | Word profile, detection, severity, scoring, template explanations, number guard |
| **Dashboard** | **React 19**, **TypeScript 5.9**, **Vite 7** | Single-page app with hash routing and small external stores |
| **Charts** | Hand-built **SVG**, no chart or UI library | Radar, timeline lanes, live instrument |
| **Design** | One token-based design system (VAANI): obsidian and graphite surfaces, ivory type, cyan for signal, copper for deviation, steel for the reference; IBM Plex Sans and Mono, Newsreader (self-hosted through Fontsource) | Light and dark themes, reduced-motion support |
| **Storage** | JSON files on disk, no database | Result cache, baseline statistics, custom passages |
| **Tests** | **pytest**; **Vitest**, Testing Library, jsdom; **axe-core**; **Playwright** (Chromium) scripts | Unit, API, end-to-end, accessibility and browser checks |
| **Types** | **openapi-typescript** | The dashboard's API types are generated from the API's own OpenAPI document |

Not used: a database, Docker, ffmpeg, an external LLM or any API key, a chart library, a UI framework, third-party analytics.

```mermaid
flowchart LR
    subgraph Browser["Browser"]
        UI["React dashboard<br/>renders backend<br/>output only"]
    end
    subgraph Server["FastAPI server, one process"]
        direction TB
        STAT["Serves the built dashboard<br/>frontend/dist"]
        API["/api/v1 routes<br/>health, baselines, analyze,<br/>status, result, custom"]
        PIPE["Analysis pipeline and services<br/>audio, transcription, alignment,<br/>features, grounding, scoring,<br/>explanation"]
        API --> PIPE
    end
    subgraph Disk["Files on disk"]
        direction TB
        BS[("data/processed/<br/>baseline_stats")]
        CU[("data/custom")]
        CA[("data/processed/<br/>cache")]
    end
    UI -->|"loads the app"| STAT
    UI -->|"JSON over HTTP,<br/>same origin"| API
    PIPE --> BS
    PIPE --> CU
    PIPE --> CA
```

## Project structure

```text
speechdummy/
├── README.md
├── requirements.txt          Python dependencies
├── .env.example              optional settings
├── backend/
│   ├── app/                  FastAPI app: api/, core/, schemas/, services/
│   │   └── services/         audio, transcription, alignment, features, grounding, scoring, explanation
│   └── tests/                backend unit and API tests
├── frontend/                 the dashboard (React + TypeScript + Vite), tests and demo samples
├── scripts/                  environment check, OpenAPI export, demo samples, dataset kit
├── data/                     dataset metadata, recording plan, baseline statistics
├── docs/                     setup, API contract, architecture, methodology, screenshots
└── tests/                    integration and end-to-end tests
```

## Quick start

### What you need

| Tool | Version | Needed for |
|---|---|---|
| **Git** | any recent | getting the code |
| **Node.js** (with npm) | 20.19 or newer | the dashboard (Options A and B) |
| **Python** | 3.10 to 3.13 | the API and the analysis (Options B, C and D) |
| **Disk and internet** | several GB | PyTorch (pulled in by Whisper and WhisperX) and, on the first real analysis, the speech models |

No ffmpeg, no database, no Docker and no API keys are needed.

```bash
git clone https://github.com/rubella2121/speechdummy.git
cd speechdummy
```

### Option A: look at the demo (about 2 minutes, no Python)

```bash
cd frontend
npm ci
npm run dev
```

Open <http://localhost:5173> and press **Explore a demo analysis**. The four demo analyses are files shipped with the dashboard, so no API is needed (the sidebar shows *API offline* and the terminal may print `http proxy error` lines while it looks for one). Analysing a recording of your own needs the API (Option B).

### Option B: the full app (API and dashboard on one address)

Run these from the repository root.

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

cd frontend
npm ci
npm run build
cd ..

python -m uvicorn app.main:app --app-dir backend
```

**macOS and Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

(cd frontend && npm ci && npm run build)

python -m uvicorn app.main:app --app-dir backend
```

Open <http://127.0.0.1:8000/>. The API serves the built dashboard at `/` and itself at `/api/v1`, so there is one address and nothing to configure. Interactive API documentation is at <http://127.0.0.1:8000/docs>, and <http://127.0.0.1:8000/api/v1/health> should answer `{"status":"ok", …, "api_contract_version":"1.3.0"}`. Stop the server with `Ctrl+C`. Next time, activate the virtual environment and run only the last command.

To check that the computer has everything (and to see exactly what is missing and how to fix it):

```bash
python scripts/check_environment.py
```

A `.env` file is optional (every setting has a default): copy `.env.example` to `.env` (`Copy-Item .env.example .env` in PowerShell, `cp .env.example .env` elsewhere) and edit it. Never commit it.

### Option C: analyse your own voice on your own text

This uses the real speech models, so download them once (large; needs internet):

```bash
python scripts/check_environment.py --download-models
```

Then start the server (Option B), open **Custom passage** in the sidebar and:

1. **Paste your passage**: 30 to 400 words, at least two sentences ending in `.`, `!` or `?`.
2. **Add 2 to 6 recordings of a good reading** of it (**Upload files** or **Record now**) and press **Make the baseline**. Three or more recordings give the precise word-by-word comparison; with two, VAANI falls back to overall averages and says so.
3. **Read the passage once more** (upload or record) and press **Analyse my reading**. The result opens on its own page.

Your passage and the baseline statistics are saved under `data/custom/`. They stay listed on the **Custom passage** page (where you can delete them) and can be chosen on **New analysis** to analyse more readings against the same baseline. The audio is never stored.

### Option D: call the API directly

A fresh clone has no baseline, so first make one with **Custom passage** (Option C) or from recorded data ([dataset kit](#dataset-kit)). Then:

```bash
# which baselines can I use?
curl http://127.0.0.1:8000/api/v1/baselines

# analyse a recording against one (WAV or MP3, up to 10 MB and 5 minutes)
curl -F "participant_audio=@take.wav;type=audio/wav" \
     -F "baseline_id=<baseline_id>" \
     -F "passage_id=<passage_id>" \
     http://127.0.0.1:8000/api/v1/analyze

# fetch the stored result again, also after a restart
curl http://127.0.0.1:8000/api/v1/result/<analysis_id>
```

For a custom passage, `baseline_id` and `passage_id` are the same `custom-…` id from `/baselines`. On **Windows PowerShell** type `curl.exe` instead of `curl` (in Windows PowerShell 5.1 plain `curl` is an alias for something else) and write the command on one line instead of using `\`. The `;type=audio/wav` part matters: without it `curl` labels the file `application/octet-stream` and the API answers `400 UNSUPPORTED_AUDIO_FORMAT`. Use `;type=audio/mpeg` for MP3.

### Development mode

Two terminals, from the repository root:

```bash
python -m uvicorn app.main:app --app-dir backend --reload     # the API on port 8000
```
```bash
cd frontend && npm run dev                                    # the dashboard on port 5173, forwards /api to port 8000
```

`VITE_API_TARGET` changes where the dev server forwards `/api`. After changing the API's schemas run `python scripts/export_openapi.py`, then `npm run gen:types` in `frontend/`. `npm run samples` rebuilds the demo samples (needs ffmpeg with libflite; see `scripts/demo/build_demo_samples.py`).

<details>
<summary><b>Troubleshooting</b></summary>

| Symptom | What to do |
|---|---|
| PowerShell: *running scripts is disabled* when activating the virtual environment | Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then activate again. It affects only that window. |
| `python` is not recognised (Windows) | Install Python from python.org and tick *Add python.exe to PATH*, or use the launcher: `py -3.12 -m venv .venv`. |
| `npm ci` complains about the Node version | Install Node 20.19 or newer (`node --version` shows yours). |
| `pip install` takes very long or uses several GB | Expected: Whisper and WhisperX pull in PyTorch. Option A works without Python. Afterwards `python scripts/check_environment.py` says what is missing. |
| Port 8000 is already in use | Add `--port 8010` to the `uvicorn` command and open that port instead. |
| `/` shows `{"detail":"Not Found"}` instead of the dashboard | The dashboard is not built. Run `npm run build` in `frontend/`, then restart the server from the repository root. |
| The first analysis takes a long time | The speech models are loaded (and downloaded the first time). Run `python scripts/check_environment.py --download-models` once beforehand. |
| **Record now** says the microphone is unavailable | The page must be `http://127.0.0.1:…`, `http://localhost:…` or `https://`, and the browser must be allowed to use the microphone. |
| `400 UNSUPPORTED_AUDIO_FORMAT` from `curl` | Add `;type=audio/wav` to the file argument (see Option D). |
| `404 BASELINE_NOT_FOUND` | The analysis needs a baseline. Make one with **Custom passage** (Option C). |
| `Invoke-RestMethod -Form` does not exist (Windows PowerShell 5.1) | Use `curl.exe` as shown in Option D. |

</details>

## Using the dashboard

| Page | What it is for |
|---|---|
| **Home** | The landing page: the live instrument, the method, and the analysis flow. |
| **New analysis** | Upload a file or record in the browser, choose a baseline, press **Analyse recording**. The four demo analyses open from here without a baseline. |
| **Custom passage** | Make a baseline from your own text and recordings, then analyse your reading. |
| **Library** | The demo samples and your analyses (stored in this browser only). |
| **Overview** | The score, the score-profile radar (outer ring = 100, the copper stretch = what findings cost), and a plain-language readout. |
| **Timeline** | Findings, words, loudness, pitch, speech rate and pauses on one time axis. Scroll to zoom, drag to pan, click to move the playhead; hover reads every signal at that moment. |
| **Flaws** | Each finding with its interval, severity, the words it covers, measured evidence against the baseline, the explanation and the recommendation. Export as CSV. |
| **Signals** | The raw measurements: speech rate, loudness, pitch (F0), every pause, and an MFCC summary (descriptive, not scored). |
| **Transcript** | The words with their timing, the pauses between them and the findings that cover them. |
| **Baseline and method** | Which baseline was used, how the comparison works and which notes apply. |
| **Report** | A printable report (paper-white in either theme). |
| **Settings, Help** | Appearance and timeline options (saved in this browser), the connection to the API, shortcuts and answers to common questions. |

<details>
<summary><b>Keyboard shortcuts</b></summary>

| Keys | Action |
|---|---|
| `Ctrl+K` (`⌘K` on Mac) | Search and jump to anything |
| `?` | Show the shortcut list |
| `B` / `T` | Collapse or expand the sidebar / switch between light and dark |
| `g` then `n`, `c`, `l`, `s`, `h` | Go to New analysis, Custom passage, Library, Settings, Help |
| `1` to `6` | Overview, Timeline, Flaws, Signals, Transcript, Baseline and method (with an analysis open) |
| `E` | Export the result as JSON |
| `Space` | Play or pause |
| `←` `→` | Seek 1 s back or forward (5 s with `Shift`) |
| `[` `]` | Previous or next flaw |
| `Home` | Back to the start |
| Timeline: scroll, `Shift`+scroll, drag, double-click, `+` `−`, `0` | Zoom, pan, pan, fit everything, zoom, fit everything |
| Flaws list: `j` `k`, `Enter`, `Esc` | Next or previous flaw, play it, clear the selection |

</details>

The dashboard has been checked for accessibility with axe-core (70 page and state combinations in both themes, no violations), for layout from 320 to 2560 px wide, and for reduced-motion and keyboard use.

## Configuration

Every setting is an environment variable with a default in `backend/app/core/config.py`; [`.env.example`](.env.example) lists all of them. The ones you are most likely to want:

| Setting | Default | Meaning |
|---|---|---|
| `WHISPER_MODEL` / `WHISPER_LANGUAGE` | `base` / `en` | Which Whisper model transcribes, and in which language |
| `EXPLANATION_PROVIDER` | `template` | Explanations are built from evidence templates |
| `CACHE_DIR` / `DATA_DIR` | `data/processed/cache` / `data` | Where results and dataset files live (relative to where the server is started) |
| `MAX_UPLOAD_BYTES` / `MAX_DURATION_S` | 10 MB / 300 s | Upload limits |
| `FRONTEND_DIST_DIR` | `frontend/dist` | The built dashboard the server serves at `/` |
| `CORS_ORIGINS` | the Vite dev server | Browser origins allowed to call the API (only needed when the dashboard is served from elsewhere) |

## API reference

All endpoints are under `/api/v1`. The full contract is in [`docs/architecture/api-contract.md`](docs/architecture/api-contract.md), the interactive documentation is served at `/docs`, and the machine-readable schema at `/openapi.json`.

| Method and path | Purpose |
|---|---|
| `GET /health` | Service, configuration, pipeline and API-contract versions |
| `GET /baselines` | Baselines that can be used, with their passage text and whether their statistics are thin; unusable files are listed with a reason code |
| `POST /analyze` | Multipart form: `participant_audio` (WAV or MP3), `baseline_id` and `passage_id` (both required); optional `manual_transcript`, `speaker_gender` (`male` or `female`), `config_version`. Runs the whole pipeline synchronously and returns the `AnalysisResult`. |
| `GET /status/{analysis_id}` | `done` or `not_found` |
| `GET /result/{analysis_id}` | The stored result, or `404 RESULT_NOT_FOUND` |
| `POST /custom/baselines` | Multipart form: `passage_text`, optional `title`, and 2 to 6 `baseline_audio` files. Makes a baseline under a `custom-…` id. Only statistics are stored. |
| `DELETE /custom/baselines/{baseline_id}` | Deletes a custom baseline and its passage text |

**The result** (`AnalysisResult`) contains: `api_contract_version`, `analysis_id`, `config_version`, `pipeline_version`, `audio` (duration, trim offset, hash), `baseline`, `alignment_method`, `transcript`, `alignment` (word timings), `features` (pitch, MFCC, energy, speech-rate and pause series), `baseline_stats`, `flaws` (see [A finding, end to end](#a-finding-end-to-end)), `scores` (per dimension and composite), `overall_summary`, `processing_meta`, `notes` (how the result was produced) and `config_fingerprint`.

**Errors** share one shape, `{"error": "<CODE>", "detail": "…", "analysis_id": null}`:

| Code | HTTP | When |
|---|---|---|
| `VALIDATION_ERROR` | 422 | Missing or invalid field, empty file, or audio with no speech |
| `UNSUPPORTED_AUDIO_FORMAT` | 400 | Not WAV or MP3 (checked by extension and content type) |
| `FILE_TOO_LARGE` | 400 | Over `MAX_UPLOAD_BYTES` |
| `AUDIO_TOO_LONG` | 400 | Over `MAX_DURATION_S` |
| `CONFIG_VERSION_MISMATCH` | 400 | `config_version` supplied and different from the server's |
| `BASELINE_NOT_FOUND` | 404 | No usable baseline with that id for that passage |
| `RESULT_NOT_FOUND` | 404 | No stored result for that id |
| `PROCESSING_ERROR` | 500 | Unexpected failure; details are logged, never returned |

## Running the tests

```bash
# Backend and integration tests (repository root, virtual environment active)
python -m pytest                              # 1389 tests, about 10 minutes
python -m pytest tests/test_api_e2e.py        # one file
python -m pytest -m smoke                     # optional: runs the real Whisper and WhisperX models
python scripts/export_openapi.py --check      # the committed OpenAPI snapshot matches the API
python scripts/dataset/validate_dataset.py    # the dataset metadata is consistent

# Dashboard (from frontend/)
npm test                                      # 386 tests (Vitest, Testing Library, jsdom)
npm run typecheck
npm run build

# Browser checks (need the server on port 8000 and a Chromium; set CHROME_PATH if it is not found)
npm run a11y                                  # axe-core over every page and state: 70 combinations
npm run smoke                                 # drives the real app in Chromium: 42 checks
npm run shots                                 # screenshots of every page
```

What the tests cover: normal input, edge cases, invalid input and a repeated run that must give the identical result, for the audio, feature, baseline, detection, severity, scoring and explanation code; the HTTP API end to end; and the dashboard's components, charts and flows. On several parts of the code (the recorder, the registration tool, the custom-passage service, the landing instrument) the tests were also checked by deliberately injecting bugs to see whether a test noticed.

## Dataset kit

Tools for recording and registering a speech dataset (for your own passage, use **Custom passage** instead). The plain-language guide is [`docs/methodology/dataset-guide.md`](docs/methodology/dataset-guide.md); the protocol and consent form are next to it.

```bash
# 1. Plan who records what (deterministic), with an on-screen prompter page per speaker
python scripts/dataset/make_plan.py --dev 2 --test 2 --tier pilot

# 2. Check recordings against the quality gates (format, level, clipping, room noise, length, hum)
python scripts/dataset/check_recordings.py data/incoming --passages data/plan/passages_v1.json

# 3. Register them: copy, hash, align with WhisperX, propose flaw annotations, build the baseline
python scripts/dataset/prepare_recordings.py data/incoming --build-baseline

# 4. Replay the registered takes through the analysis and compare with the annotations
python scripts/dataset/evaluate_takes.py
```

Recordings go in `data/incoming/` (or any folder) and are never committed. `scripts/dataset/build_baseline_stats.py` builds baseline statistics directly (`--passage-id p001 --splits dev`; `--splits` is required on purpose).

Dataset download: (https://drive.google.com/drive/folders/1kmk0tuiJ4oNRsaD_QJ-qc3IXxK6TFdk6?usp=sharing)

## Documentation

| Document | What is in it |
|---|---|
| [`docs/TECHNICAL_REPORT.md`](docs/TECHNICAL_REPORT.md) | The technical report: architecture, pipeline, API, dashboard, engineering practices (also as [PDF](docs/TECHNICAL_REPORT.pdf)) |
| [`docs/setup.md`](docs/setup.md) | Environment setup, dependencies, baselines, notes for the first real run |
| [`docs/architecture/api-contract.md`](docs/architecture/api-contract.md) | The API contract (1.3.0) |
| [`docs/architecture/frontend.md`](docs/architecture/frontend.md) | The dashboard's architecture and design system |
| [`docs/methodology/dataset-guide.md`](docs/methodology/dataset-guide.md) | How to record, check, register and evaluate a dataset, in plain language |
| [`docs/methodology/recording-protocol.md`](docs/methodology/recording-protocol.md) | The recording protocol and quality gates |
| [`docs/methodology/dataset-schema.md`](docs/methodology/dataset-schema.md) | Dataset files and fields |
| [`docs/methodology/consent-form-template.md`](docs/methodology/consent-form-template.md) | A consent form for people who are recorded |

## Engineering principles

- **Deterministic numbers.** Feature extraction, normalisation, comparison, detection, severity and scoring are deterministic. Randomness never affects a score.
- **Evidence before explanation.** No explanation without measurable evidence; an LLM, if one is ever added, may only phrase already-computed evidence.
- **One implementation per concept.** Pitch lives in `services/features/`, scoring in `services/scoring/`, grounding in `services/grounding/`, schemas in `schemas/`. The frontend consumes the canonical backend output and never recomputes it.
- **Stable contract.** The API contract is versioned, and the dashboard's types are generated from it.
- **Explicit configuration.** Every analysis parameter is a named setting.

## Roadmap

- Detection of pitch instability and reduced vocal clarity.
- Coaching phrased by an LLM that receives only the measured fact sheet and must pass the same number guard.
- More speakers and passages in the dataset kit.

## Privacy and consent

- **Recordings of people are never committed.** `.gitignore` excludes `data/raw/`, `data/incoming/`, `data/custom/` and the result cache; the audio stays on the team's own drive. If you record other people, get their consent first. A template is in [`docs/methodology/consent-form-template.md`](docs/methodology/consent-form-template.md).
- **Everything runs on your machine.** Audio is analysed by the local server. The only things downloaded are the speech-model files on first use, and, when installing, Python and npm packages. Explanations are templates, so no text is sent to any LLM service.
- **The dashboard talks only to its own server.** Opening every page in a real browser produced requests to its own address and nowhere else: fonts are bundled, and there is no analytics or tracking.
- **What the server keeps.** Each analysis result (which includes the transcript text) is cached as a JSON file under `data/processed/cache/`; delete the folder to clear it. Custom passages keep their text and baseline statistics under `data/custom/`. **The server does not keep uploaded audio**, and a result opened later by its id has no audio to play.
- **What the browser keeps.** Settings and your list of analyses stay in your browser's local storage and can be cleared on the Settings and Library pages.
- There are no accounts and no sign-in.

## Acknowledgements and licence

VAANI stands on [OpenAI Whisper](https://github.com/openai/whisper) (transcription), [WhisperX](https://github.com/m-bain/whisperX) (forced alignment), [librosa](https://librosa.org) (pYIN pitch tracking after Mauch and Dixon, 2014, MFCC and energy), [FastAPI](https://fastapi.tiangolo.com) and [Pydantic](https://docs.pydantic.dev), [React](https://react.dev) and [Vite](https://vite.dev), [Vitest](https://vitest.dev), [axe-core](https://github.com/dequelabs/axe-core) and [Playwright](https://playwright.dev), and the IBM Plex and Newsreader typefaces distributed through [Fontsource](https://fontsource.org).

Built for the **IIT Mandi Multimodal AI Hackathon 2026, Track C**: contrastive analysis, temporal flaw grounding, acoustic feature extraction, reproducible scoring and actionable feedback.
