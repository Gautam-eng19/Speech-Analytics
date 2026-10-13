# Architecture Proposal
## Track C — Contrastive Speech Analytics & Temporal Flaw Grounding

**Document type:** PROPOSAL — not an official architecture decision  
**Status:** Awaiting team review and approval  
**Author:** AI Architecture Investigation Agent  
**Date:** 2026-10-07  
**Version:** 0.1  

> **IMPORTANT:** This document is a proposal only. Nothing here is an official architectural
> decision. Official decisions must be approved by the team leader and recorded in DECISIONS.md.
> No implementation files have been created or modified during the production of this document.

---

## Table of Contents

1. [Project Understanding](#1-project-understanding)
2. [Recommended End-to-End Architecture](#2-recommended-end-to-end-architecture)
3. [System Data Flow](#3-system-data-flow)
4. [Component Responsibilities](#4-component-responsibilities)
5. [Technology Recommendations](#5-technology-recommendations)
6. [Decision Matrix](#6-decision-matrix)
7. [Baseline Methodology](#7-baseline-methodology)
8. [Feature Methodology](#8-feature-methodology)
9. [Contrastive Methodology](#9-contrastive-methodology)
10. [Temporal Grounding Methodology](#10-temporal-grounding-methodology)
11. [Severity and Reliability Methodology](#11-severity-and-reliability-methodology)
12. [Scoring Methodology](#12-scoring-methodology)
13. [Evidence Model](#13-evidence-model)
14. [LLM Boundary](#14-llm-boundary)
15. [Dataset Strategy](#15-dataset-strategy)
16. [Evaluation Strategy](#16-evaluation-strategy)
17. [Reproducibility Strategy](#17-reproducibility-strategy)
18. [Deployment Proposal](#18-deployment-proposal)
19. [Risk Register](#19-risk-register)
20. [Implementation Dependencies](#20-implementation-dependencies)
21. [P0/P1/P2 Priorities](#21-p0p1p2-priorities)
22. [Decisions Requiring Team Approval](#22-decisions-requiring-team-approval)
23. [Assumptions](#23-assumptions)
24. [How Our Design Improves on Reference Implementations](#24-how-our-design-improves-on-reference-implementations)
25. [Executive Summary](#25-executive-summary)

---

## 1. Project Understanding

### What the system does

The system evaluates **speech delivery quality** by comparing a participant's recording against
an effective same-content **baseline** recording (or a set of baseline recordings).
It answers six core questions:

1. **Where** did delivery deviate from the effective baseline? (temporal grounding)
2. **Which** measurable acoustic behavior changed? (feature identification)
3. **How large** was the deviation? (deviation quantification)
4. **When** did the deviation occur? (timestamp)
5. **Why** does the deviation represent a delivery flaw? (evidence-backed explanation)
6. **What** actionable feedback should the participant receive? (recommendation)

### What the system does NOT do

- Does not evaluate factual correctness of speech content.
- Does not evaluate literary or rhetorical quality.
- Does not compare against a universal human average.
- Does not produce scores without measurable evidence.
- Does not allow the frontend to compute any analytical truth.
- Does not allow LLMs to invent any numerical value.

### Core architectural principle

**Analytical truth is deterministic and backend-owned.**
**LLMs translate evidence into language.**
**The frontend visualizes what the backend computed.**

---

## 2. Recommended End-to-End Architecture

### High-level system components

```
+------------------------------------------------------------------+
|                         FRONTEND                                 |
|  React + Vite + TypeScript                                       |
|  Upload UI | Progress | Score Card | Timeline | Feature Charts   |
|  Evidence Panel | Audio Playback | Recommendations               |
+-----------------------------+------------------------------------+
                              |  HTTP/JSON (REST)
+-----------------------------v------------------------------------+
|                       BACKEND API LAYER                          |
|  FastAPI                                                         |
|  /api/v1/analyze  /api/v1/status  /api/v1/result  /api/v1/health |
+-----------------------------+------------------------------------+
                              |
+-----------------------------v------------------------------------+
|                   ANALYSIS ORCHESTRATOR                          |
|  Coordinates the canonical pipeline                              |
|  Manages caching, determinism, provenance                        |
+--+-------+-------+-------+-------+-------+-------+--------------+
   |       |       |       |       |       |       |
   v       v       v       v       v       v       v
[audio] [trans] [align] [feat] [ground] [score] [explain]
  svc     svc     svc     svc    svc      svc      svc
```

### Canonical pipeline (as defined in AGENTS.md — not to be replaced silently)

```
Audio Input (participant + baseline reference)
    |
    v
[1] Preprocessing Service
    Resample -> Mono -> Normalize amplitude -> Trim silence edges -> SHA-256
    |
    v
[2] Transcription Service
    Whisper -> word-level transcript with approximate timestamps
    |
    v
[3] Forced Alignment Service
    WhisperX aligner -> word-level time-anchored transcript
    |
    v
[4] Feature Extraction Service
    F0 timeline | MFCC matrix | Energy timeline |
    Speech rate (rolling window) | Pause detection | Clarity proxy
    |
    v
[5] Baseline Normalization
    Speaker-aware z-score normalization against pooled baseline statistics
    |
    v
[6] Contrastive Comparison
    Frame-level and segment-level delta computation
    |
    v
[7] Temporal Flaw Detection
    Threshold-based candidate window generation
    |
    v
[8] Severity Estimation
    Per-flaw severity in [0, 1] based on deviation magnitude + duration
    |
    v
[9] Deterministic Scoring
    Weighted feature sub-scores -> composite score [0, 100]
    |
    v
[10] Evidence-backed Explanation
    Structured evidence -> LLM-generated (or template) natural language
    |
    v
[11] API Response
    Structured JSON consumed by frontend
    |
    v
[12] Dashboard Visualization
    Timeline, waveform overlay, feature charts, flaw cards
```

---

## 3. System Data Flow

### 3.1 API Input

```
POST /api/v1/analyze
{
  "participant_audio":  <multipart file or pre-uploaded reference ID>,
  "baseline_id":        "<dataset baseline ID>",
  "passage_id":         "<text passage identifier>",
  "speaker_meta":       { "gender": optional, "native_language": optional },
  "config_version":     "1.0.0"
}
```

### 3.2 Internal intermediate objects (not exposed directly)

Each stage produces a typed, versioned intermediate object passed to the next stage:

```
PreprocessedAudio
  -> TranscriptWithTimings
  -> AlignedTranscript             (word_start, word_end, confidence per word)
  -> FeatureBundle                 (per-frame arrays + segment summaries)
  -> NormalizedFeatureBundle       (z-scored relative to baseline statistics)
  -> ContrastiveBundle             (delta per feature per frame/segment)
  -> FlawCandidates[]              (raw detections with evidence)
  -> MergedFlaws[]                 (temporally merged, severity-assigned)
  -> ScoredResult                  (sub-scores + composite)
  -> ExplainedResult               (flaws with natural language explanation)
```

### 3.3 API Output (proposed schema)

```json
{
  "analysis_id": "uuid",
  "config_version": "1.0.0",
  "pipeline_version": "1.0.0",
  "participant_audio_sha256": "...",
  "baseline_sha256": "...",
  "transcript": "The quick brown fox...",
  "alignment": [
    { "word": "The",   "start": 0.10, "end": 0.25, "confidence": 0.97 },
    { "word": "quick", "start": 0.27, "end": 0.54, "confidence": 0.94 }
  ],
  "features": {
    "f0_timeline":           { "times_s": [...], "values_hz": [...], "voiced": [...] },
    "energy_timeline":       { "times_s": [...], "values_db": [...] },
    "speech_rate_timeline":  { "times_s": [...], "words_per_min": [...] },
    "pause_events":          [{ "start": 1.2, "end": 1.9, "duration_s": 0.7 }],
    "mfcc_summary":          { "mean": [...], "std": [...] },
    "clarity_timeline":      { "times_s": [...], "hf_ratio": [...] }
  },
  "baseline_stats": {
    "f0_voiced_hz_mean": 142.3,
    "f0_voiced_hz_std":   18.4,
    "energy_db_mean":    -18.2,
    "energy_db_std":       4.1,
    "rate_wpm_mean":      142.6,
    "rate_wpm_std":        18.4
  },
  "flaws": [
    {
      "flaw_id": "flaw_001",
      "start": 12.4,
      "end": 15.8,
      "type": "too_fast",
      "severity": 0.78,
      "reliability": 0.91,
      "low_confidence": false,
      "evidence": {
        "rate_participant_wpm": 187.3,
        "rate_baseline_mean_wpm": 142.6,
        "rate_baseline_std_wpm": 18.4,
        "rate_delta_wpm": 44.7,
        "rate_delta_pct": 31.4,
        "rate_z_score": 2.41,
        "peak_z_score": 3.12,
        "window_duration_s": 3.4,
        "word_count_in_window": 11
      },
      "explanation": "Between 12.4-15.8 s, speech rate was 31.4% above the normalized baseline (z = 2.41), indicating accelerated delivery.",
      "recommendation": "Slow down at this passage. Practice at 130 WPM before gradually returning to target pace.",
      "explanation_method": "gemini"
    }
  ],
  "scores": {
    "pitch":        { "score": 74, "weight": 0.20, "flaw_count": 1 },
    "energy":       { "score": 88, "weight": 0.15, "flaw_count": 0 },
    "speech_rate":  { "score": 61, "weight": 0.25, "flaw_count": 2 },
    "pauses":       { "score": 79, "weight": 0.20, "flaw_count": 1 },
    "clarity":      { "score": 83, "weight": 0.10, "flaw_count": 0 },
    "mfcc":         { "score": 80, "weight": 0.10, "flaw_count": 0 },
    "composite":    82
  },
  "processing_meta": {
    "whisper_model": "base",
    "processing_time_s": 14.2,
    "cached": false
  }
}
```

---

## 4. Component Responsibilities

### 4.1 `backend/app/services/audio/`

**Responsibilities:**
- Validate audio format, sample rate, bit depth, and duration
- Resample to target sample rate (recommended: 16 kHz)
- Convert to mono
- Apply amplitude normalization (recommended: peak normalization to -3 dBFS)
- Trim leading/trailing silence using energy-based VAD
- Compute SHA-256 hash of the preprocessed audio for provenance
- Return a `PreprocessedAudio` typed object

**Must NOT do:** feature extraction, transcription, analysis.

---

### 4.2 `backend/app/services/transcription/`

**Responsibilities:**
- Accept `PreprocessedAudio`, return `TranscriptWithTimings`
- Run Whisper to produce word-level transcript with approximate timestamps
- Store model name and version in output metadata
- Accept a manually-supplied transcript to skip ASR (controlled experiments)

**Must NOT do:** alignment precision, feature extraction.

---

### 4.3 `backend/app/services/alignment/`

**Responsibilities:**
- Accept `PreprocessedAudio` + `TranscriptWithTimings`, return `AlignedTranscript`
- Perform forced alignment to refine word-level time boundaries
- Produce per-word `{ word, start_s, end_s, confidence }` records
- Validate alignment quality (total coverage, maximum gap check)

**Must NOT do:** transcription, feature extraction.

---

### 4.4 `backend/app/services/features/`

**Responsibilities — single canonical implementation of each feature:**

| Feature | Method |
|---|---|
| F0 / Pitch | Frame-level fundamental frequency using PYIN |
| MFCC | 13 (or 20) coefficients per frame using librosa |
| Energy | RMS per frame converted to dBFS |
| Speech Rate | Rolling-window WPM using aligned word timestamps |
| Pause Detection | Energy-based VAD + alignment-gap detection |
| Clarity proxy | High-frequency energy ratio (spectral rolloff proxy) |

All feature extractors:
- Accept preprocessed audio + aligned transcript
- Return frame-level arrays with timestamps
- Are stateless, deterministic, and version-pinned

**Must NOT do:** normalization, comparison, scoring, explanation.

---

### 4.5 `backend/app/services/grounding/`

**Responsibilities:**
- Accept `NormalizedFeatureBundle` + `ContrastiveBundle`
- Generate candidate flaw windows per feature using threshold rules
- Apply temporal smoothing / hysteresis to avoid fragmented detections
- Merge overlapping or adjacent windows within a flaw category
- Refine boundaries using aligned word boundaries
- Attach evidence values to each merged flaw
- Return `MergedFlaws[]`

**Must NOT do:** scoring, explanation, feature extraction.

---

### 4.6 `backend/app/services/scoring/`

**Responsibilities:**
- Accept `MergedFlaws[]` + `NormalizedFeatureBundle`
- Compute per-feature sub-scores using documented deterministic formulas
- Compute composite weighted score
- Record scoring formula version in output
- Guarantee identical output for identical inputs

**Must NOT do:** explanation, feature extraction, comparison.

---

### 4.7 `backend/app/services/explanation/`

**Responsibilities:**
- Accept fully populated `ScoredResult` (all numbers pre-computed, no values to invent)
- Generate natural-language explanation per flaw using structured templates or LLM
- Generate actionable per-flaw recommendations
- Guarantee all numerical values in explanation text originate from `ScoredResult`
- Record whether LLM or template was used in output metadata (`explanation_method`)

**Must NOT do:** compute timestamps, features, deviations, severity, or scores.

---

### 4.8 `backend/app/api/`

**Responsibilities:**
- Expose REST endpoints: `/analyze`, `/status/{id}`, `/result/{id}`, `/health`
- Validate all inputs (audio format, file size, passage ID existence)
- Orchestrate service calls in pipeline order
- Return structured JSON conforming to Pydantic schemas
- Return appropriate HTTP error codes and error detail

---

### 4.9 `backend/app/schemas/`

**Responsibilities:**
- Define all Pydantic models for request and response bodies
- This is the single source of truth for the API contract
- Frontend TypeScript types should be derived from these schemas

---

### 4.10 `backend/app/core/`

**Responsibilities:**
- Store all tunable configuration (thresholds, weights, window sizes) in one place
- Expose a `config_version` string included in all responses
- Manage environment variable loading

---

## 5. Technology Recommendations

> All recommendations below are **proposals** requiring team approval.

### 5.1 Audio Preprocessing

**Recommended:** `librosa` for loading and resampling, `soundfile` for file I/O,
`pydub` as optional for format conversion from MP3/M4A.

| Option | Pros | Cons |
|---|---|---|
| `librosa` + `soundfile` | Mature, deterministic, integrates with features | Requires ffmpeg for some formats |
| `pydub` | Broad format support | Wraps ffmpeg — must pin ffmpeg version |
| `torchaudio` | GPU-accelerated | Heavy dependency, overkill for preprocessing |

**Target spec:** 16 kHz, mono, float32, peak-normalized to -3 dBFS.

**Hackathon fit:** `librosa` + `soundfile` — pip installable, no system complications.

---

### 5.2 Transcription

**Recommended:** `openai-whisper` (local, open-source), `base` model for speed,
`small` or `medium` if GPU is available.

| Option | Pros | Cons |
|---|---|---|
| `openai-whisper` (local) | Free, offline, reproducible, no API key | CPU inference is slow on longer clips |
| `faster-whisper` | Faster CTranslate2 backend | Additional dependency |
| `whisperx` | Combines transcription + alignment | More complex install |
| Cloud STT APIs | High accuracy | Network dependency, cost, non-reproducible |

**Recommendation:** `openai-whisper` with `base` model for hackathon. Model version must be
pinned in config. If GPU available on demo machine, upgrade to `small`.

---

### 5.3 Forced Alignment

**Recommended:** `WhisperX` (wav2vec2-based word-level aligner).

| Option | Pros | Cons |
|---|---|---|
| `WhisperX` | Same ecosystem as Whisper, pip-installable, word-level | Requires torchaudio; CUDA preferred |
| `Montreal Forced Aligner` | High accuracy, language models | Non-trivial install (conda-based), slower setup |
| `Aeneas` | Simple | Less accurate at word level |
| `Whisper word_timestamps=True` | Zero additional dependency | Approximate only — not true forced alignment |

**Recommendation:** `WhisperX` for hackathon; MFA as fallback if alignment quality is
insufficient after empirical testing.

**Risk:** WhisperX install requires careful CUDA/CPU version management. Allocate time on Day 1.

---

### 5.4 F0 / Pitch Extraction

**Recommended:** `librosa.pyin` (Probabilistic YIN).

| Option | Pros | Cons |
|---|---|---|
| `librosa.pyin` | Voiced/unvoiced detection, confidence output, deterministic | Slightly slower than basic autocorrelation |
| `librosa.yin` | Faster | No confidence, more false detections |
| `parselmouth` (Praat) | Industry standard | System-level Praat binary dependency |
| `pyworld` | Very high quality | Complex install |

**Recommendation:** `librosa.pyin` — voiced/unvoiced flags are critical for flat pitch detection.
fmin/fmax bounds should be configurable (and optionally informed by speaker gender metadata).

---

### 5.5 MFCC Extraction

**Recommended:** `librosa.feature.mfcc`.

| Option | Pros | Cons |
|---|---|---|
| `librosa.feature.mfcc` | Standard, well-tested, deterministic | None significant |
| `python_speech_features` | Lightweight | Less actively maintained |
| `torchaudio.transforms.MFCC` | GPU-compatible | Requires PyTorch |

**Recommendation:** `librosa.feature.mfcc`, n_mfcc=13, hop_length and n_fft pinned in config.
Delta and delta-delta coefficients may be added for richer voice quality representation (P1).

---

### 5.6 Energy Extraction

**Recommended:** `librosa.feature.rms` converted to dBFS.

```
energy_db = 20 * log10(max(rms_value, 1e-9))
```

Normalize by subtracting baseline mean energy to obtain relative loudness.

---

### 5.7 Speech Rate — Rolling Window (critical design decision)

**Critical note:** Speech rate must NOT be computed as inverse individual word duration.
That produces noisy, fragmented, unstable estimates — an error seen in simpler systems.

**Recommended approach:** Rolling-window WPM over the aligned transcript.

```
For each time point t:
  window = aligned words whose midpoint falls in [t - W/2, t + W/2]
  effective_duration_s = last_word_end - first_word_start (in window)
  rate_wpm(t) = (len(window) / effective_duration_s) * 60
```

- Window size `W`: propose 8 seconds with 50% step (4-second stride). Configurable.
- Minimum word count per window: 5 (shorter windows produce unreliable estimates).
- Rate is computed at each stride position producing a timeline.

**Alternative:** Phrase-level segmentation (rate per silence-delimited phrase).
Less temporally smooth but more interpretable. Can be offered as supplementary output.

---

### 5.8 Pause Detection

**Recommended:** Two-pass approach combining:

1. **Energy-based VAD:** Mark frames as voiced/unvoiced using energy threshold.
2. **Alignment gap detection:** Use inter-word gaps from forced alignment.

A pause candidate must satisfy:
- Duration >= minimum threshold (proposed: 0.4 s within-phrase, 1.0 s cross-sentence). Configurable.
- Is not at the very end of the recording.
- Optional: sentence-boundary pauses weighted differently (use transcript punctuation).

---

### 5.9 Acoustic Clarity Proxy

**Honest constraint:** There is no simple acoustic feature that perfectly measures
intelligibility. We present what follows as an **acoustic proxy**, not a perceptual
intelligibility measure.

**Recommended primary proxy:** Spectral high-frequency energy ratio (HF ratio).

```
hf_ratio(frame) = energy(freq > cutoff_hz) / total_energy(frame)
```

Proposed cutoff: 3000-4000 Hz (configurable). Higher HF ratio correlates broadly with
clearer consonant articulation. A reduction compared to baseline may indicate mumbling,
muffled microphone, or reduced articulatory precision.

**Secondary proxy:** `librosa.feature.spectral_rolloff` — the frequency below which 85%
of spectral energy is concentrated. Lower rolloff compared to baseline can indicate
reduced high-frequency content.

**MFCC-based voice quality:** Word-segment cosine distance in MFCC space (see §9)
used alongside HF ratio as a second independent signal for Reduced Clarity detection.

**Displayed to users as:** "Acoustic clarity proxy" — explicitly not "intelligibility score."
Given measurement uncertainty, clarity should carry a lower weight in final scoring.

---

## 6. Decision Matrix

| Decision Area | Recommended | Alternatives | Hackathon Risk |
|---|---|---|---|
| Transcription | openai-whisper base | faster-whisper, cloud STT | Low |
| Alignment | WhisperX | MFA, Whisper word_timestamps | Medium (install) |
| Preprocessing | librosa + soundfile | pydub + ffmpeg | Low |
| F0 extraction | librosa.pyin | librosa.yin, parselmouth | Low |
| MFCC | librosa.feature.mfcc | python_speech_features | Low |
| Energy | librosa.feature.rms | torchaudio | Low |
| Speech rate method | Rolling-window WPM (W=8s) | Phrase-level | Low |
| Pause method | Energy VAD + alignment gap | VAD-only | Low |
| Clarity proxy | HF ratio + MFCC distance | Spectral rolloff, SNR | Medium (accuracy) |
| Pitch normalization | Z-score on voiced frames | Semitone normalization | Low |
| Energy normalization | Z-score after peak norm | Global mean subtraction | Low |
| Baseline representation | Pooled multi-reference stats | Single reference | Low |
| Flaw detection | Z-score threshold + hysteresis | Fixed delta threshold | Medium (calibration) |
| Severity formula | Sigmoid (magnitude, duration) | Linear clamp | Low |
| Scoring | Penalty-based sub-scores + weighted composite | Raw z-score | Low |
| LLM explanation | Gemini API + template fallback | Ollama, template-only | Low (has fallback) |
| Caching | File-based hash-keyed JSON | SQLite, Redis | Low |
| Deployment | Local Uvicorn + Vite dev | Docker | Low |

---

## 7. Baseline Methodology

### Core principle

The baseline represents effective delivery of the **same speech content** — not a
universal human speaking average. Comparisons must be relative to this content-specific baseline.

### Multi-reference baseline

Each `passage_id` has 1 to N effective reference recordings from different speakers.
Baseline statistics are computed by pooling across all valid baseline recordings for that passage.

**Minimum viable (hackathon):** Start with a single high-quality reference per passage.
The data model is designed to support multiple from Day 1.

### Baseline statistics per passage (stored as JSON)

```json
{
  "passage_id": "p001",
  "dataset_version": "1.0.0",
  "baseline_recording_ids": ["rec_p001_s01_base", "rec_p001_s02_base"],
  "f0_stats": {
    "voiced_hz_mean": 145.2,
    "voiced_hz_std":   22.1,
    "voiced_hz_p05":  108.3,
    "voiced_hz_p95":  196.7
  },
  "energy_stats": {
    "db_mean": -18.4,
    "db_std":    4.2
  },
  "rate_stats": {
    "mean_wpm": 142.3,
    "std_wpm":   18.4
  },
  "pause_stats": {
    "mean_within_phrase_s": 0.38,
    "std_within_phrase_s":  0.14,
    "mean_cross_sentence_s": 0.82
  },
  "clarity_stats": {
    "hf_ratio_mean": 0.31,
    "hf_ratio_std":  0.06
  }
}
```

### Speaker-aware normalization

Raw absolute values (Hz, dB) are not directly comparable across speakers.
Z-score normalization using baseline statistics handles speaker-to-speaker variability:

```
z_f0(t) = (f0_participant(t) - baseline_f0_mean) / baseline_f0_std
```

Where `baseline_f0_mean` and `baseline_f0_std` are computed across voiced frames of
all baseline recordings for this passage. This means a participant with a habitually
lower or higher voice is evaluated relative to the effective delivery, not a global human mean.

**Voiced-only constraint:** F0 statistics computed only on voiced frames
(PYIN voiced probability > configurable threshold, proposed 0.85).

---

## 8. Feature Methodology

### 8.1 F0 / Pitch

- Algorithm: PYIN (`librosa.pyin`)
- Output: frame-level Hz + voiced boolean + voiced probability
- Frame size (hop_length): configurable, propose 10 ms
- Voiced threshold: configurable, propose 0.85 probability
- Normalization: z-score on voiced frames using baseline stats
- Used for: Flat Pitch, Pitch Instability flaws

### 8.2 MFCC

- Algorithm: `librosa.feature.mfcc`, n_mfcc=13
- Output: 13-dimensional vector per frame
- Hop length and n_fft pinned in config
- Primary use: word-segment cosine distance for voice quality / Reduced Clarity
- Not used for direct frame-level threshold detection (too noisy)

### 8.3 Energy

- Algorithm: `librosa.feature.rms` -> dBFS
- Output: energy_db per frame
- Normalization: z-score using baseline energy stats (after preprocessing normalization)
- Used for: Low Energy, High Energy flaws, VAD for pause detection

### 8.4 Speech Rate

- Algorithm: rolling-window WPM over aligned transcript
- Window size W: 8 s (configurable), step: 4 s (configurable)
- Minimum words per window: 5 (configurable)
- Output: WPM at each step position
- Normalization: z-score using baseline WPM stats
- Used for: Too Fast, Too Slow flaws

### 8.5 Pause Detection

**Pass 1 (energy-based VAD):**
- Energy below threshold for >= min_pause_duration -> unvoiced segment
- Threshold: configurable (proposed: -50 dBFS)

**Pass 2 (alignment-based gap detection):**
- Inter-word gap from alignment > min_gap_s -> pause candidate
- Proposed min_gap_s: 0.3 s (configurable)

**Union of both passes:** A pause is confirmed if both methods agree (reduces false positives).

Output: list of pause events with `{ start_s, end_s, duration_s, detection_method }`.

### 8.6 Clarity Proxy

**Primary signal (HF ratio):**
- Compute power spectral density per frame
- HF ratio = power(freq > cutoff_hz) / total_power
- Cutoff: 3000 Hz (configurable)
- Normalization: z-score using baseline HF ratio stats

**Secondary signal (MFCC distance per word segment):**
- Compute mean MFCC vector for each word segment in participant audio
- Compare to mean MFCC vector of the same word position in baseline recordings
- Distance metric: cosine distance
- Used as: supplementary evidence for Reduced Clarity flaw

---

## 9. Contrastive Methodology

### 9.1 Frame-level comparison (pitch, energy, clarity)

```
delta_f0(t)      = z_f0_participant(t)      - 0   (baseline is z=0 by definition)
delta_energy(t)  = z_energy_participant(t)  - 0
delta_clarity(t) = z_clarity_participant(t) - 0
```

Note: After z-scoring against baseline statistics, the baseline mean is 0.
Deviations are directly expressed in standard deviation units.

### 9.2 Window-level comparison (speech rate)

```
delta_rate(window) = rate_participant_wpm - baseline_rate_mean_wpm
z_rate(window)     = delta_rate(window) / baseline_rate_std_wpm
```

### 9.3 Event-level comparison (pauses)

```
for each pause event in participant:
  relative_excess = (pause.duration_s - baseline_mean_pause_s) / baseline_std_pause_s
```

Cross-sentence pauses compared against cross-sentence baseline stats.
Within-phrase pauses compared against within-phrase baseline stats.

### 9.4 Segment-level MFCC comparison (voice quality)

```
for each word_position in alignment:
  participant_mfcc_mean = mean MFCC over word segment
  baseline_mfcc_mean    = mean MFCC over same word from baseline recordings
  mfcc_distance         = cosine_distance(participant_mfcc_mean, baseline_mfcc_mean)
```

High MFCC distance over a sustained region is evidence for Reduced Clarity or vocal quality change.

---

## 10. Temporal Grounding Methodology

### Step 1: Candidate generation

For each feature, apply threshold rules to the contrastive signal:

| Flaw Type | Feature | Detection Condition |
|---|---|---|
| Too Fast | Speech rate z-score | z_rate > +Z_RATE for window duration >= MIN_DURATION |
| Too Slow | Speech rate z-score | z_rate < -Z_RATE for window duration >= MIN_DURATION |
| Excessive Pause | Pause event duration | pause.duration_s > PAUSE_MAX_S |
| Flat Pitch | F0 std per voiced segment | f0_std_z < -Z_FLAT in voiced segment >= MIN_DURATION |
| Pitch Instability | F0 variance per segment | f0_var_z > +Z_INSTAB in segment >= MIN_DURATION |
| Low Energy | Energy z-score | z_energy < -Z_ENERGY for >= MIN_DURATION |
| High Energy | Energy z-score | z_energy > +Z_ENERGY for >= MIN_DURATION |
| Reduced Clarity | HF ratio z-score OR MFCC distance | z_clarity < -Z_CLARITY or mfcc_dist > MFCC_DIST_MAX |

All threshold constants (`Z_RATE`, `PAUSE_MAX_S`, etc.) must be:
- Stored in versioned configuration (not hard-coded)
- Calibrated on the dev split only
- Documented with rationale

### Step 2: Temporal smoothing / hysteresis

**Hysteresis approach (reduces toggling):**
- Enter FLAW state when signal exceeds `UPPER_THRESHOLD`
- Exit FLAW state only when signal drops below `LOWER_THRESHOLD < UPPER_THRESHOLD`
- `LOWER_THRESHOLD` = `UPPER_THRESHOLD * HYSTERESIS_RATIO` (configurable, proposed 0.75)

**Pre-smoothing (reduces noise):**
- Apply median filter with kernel size `SMOOTHING_FRAMES` to contrastive signal before thresholding
- Kernel size configurable per feature

### Step 3: Minimum duration filter

Discard candidate windows shorter than `MIN_FLAW_DURATION_S` (proposed: 0.5 s, configurable).
Brief threshold crossings from natural speech variation should not produce flaws.

### Step 4: Window merging

If two candidate windows of the same flaw type are separated by a gap smaller than
`MERGE_GAP_S` (proposed: 0.5 s, configurable), merge them into one window.

### Step 5: Boundary refinement

Snap flaw start/end times to the nearest word boundary from the aligned transcript.
This makes timestamps interpretable ("from 'the' to 'delivery'") rather than arbitrary
frame positions. Maximum snap distance: `MAX_SNAP_S` (proposed: 0.3 s, configurable).

### Step 6: Evidence attachment

For each merged, refined flaw window, compute and attach:
- Feature values within the window (participant)
- Baseline statistics for comparison
- Absolute deviation, percentage deviation
- Z-score (mean and peak within window)
- Window duration in seconds
- Word count within window

---

## 11. Severity and Reliability Methodology

### 11.1 Severity

Severity is a value in [0.0, 1.0] per flaw instance.

**Proposed formula (requires team selection):**

**Option A — Sigmoid:**
```
magnitude_score = |peak_z_score| / Z_SEVERE
duration_score  = min(flaw_duration_s / DURATION_SEVERE, 1.0)
raw_score       = w_magnitude * magnitude_score + w_duration * duration_score
severity        = 1 / (1 + exp(-(raw_score - bias)))
```

**Option B — Linear product (simpler):**
```
severity = clip((mean_z_score - Z_MIN) / (Z_MAX - Z_MIN), 0, 1)
         * clip(duration_s / DURATION_FULL, 0, 1)
```

Both are deterministic given the same inputs and configuration.
The team must select one before implementation begins.

Where:
- `Z_SEVERE` / `Z_MAX` = z-score considered fully severe (proposed: 4.0)
- `DURATION_SEVERE` / `DURATION_FULL` = duration considered fully severe (proposed: 5.0 s)
- All constants configurable

### 11.2 Reliability

Separate from severity. Indicates how much we trust the detection.

**Proposed factors:**
- `alignment_confidence`: mean word alignment confidence within the flaw window (from WhisperX)
- `feature_confidence`: PYIN voiced probability mean (for pitch flaws) or energy level (for energy/rate flaws)
- `signal_quality`: energy level of participant audio (very quiet signal -> lower confidence)
- `duration_factor`: very short windows get lower reliability

**Proposed aggregation:**
```
reliability = harmonic_mean(alignment_confidence, feature_confidence, signal_quality_factor)
```

All factors normalized to [0, 1]. Reliability in [0, 1].

Flaws with `reliability < RELIABILITY_THRESHOLD` (proposed: 0.4):
- Included in the response
- Flagged with `"low_confidence": true`
- Receive reduced penalty contribution to feature sub-score

---

## 12. Scoring Methodology

### 12.1 Per-feature sub-scores

Each feature produces a sub-score in [0, 100]:

```
feature_sub_score = max(0, 100 - total_penalty)

total_penalty = sum over all flaws of this feature type:
  flaw_penalty = BASE_PENALTY * severity * duration_weight * reliability_factor

duration_weight   = min(flaw_duration_s / DURATION_NORM_S, 1.0)
reliability_factor = reliability  (low-confidence flaws penalize less)
```

Where:
- `BASE_PENALTY` = maximum penalty for a single fully severe flaw (proposed: 30 points, configurable)
- `DURATION_NORM_S` = duration considered a "full duration" flaw (proposed: 4 s, configurable)

Score is clipped to [0, 100].

### 12.2 Composite weighted score

```
composite_score = sum(feature_sub_score[i] * weight[i])  for i in all features
```

**Proposed weights (requiring team approval):**

| Feature | Proposed Weight | Rationale |
|---|---|---|
| Speech Rate | 0.25 | Primary delivery indicator |
| Pitch (F0) | 0.20 | Monotone / instability clearly perceptible |
| Pauses | 0.20 | Directly affects engagement |
| Energy | 0.15 | Important but more variable |
| MFCC / Voice Quality | 0.10 | Supplementary |
| Clarity proxy | 0.10 | Proxy — lower weight due to measurement uncertainty |

Weights must sum to 1.0. Stored in versioned configuration.

### 12.3 Scoring version

Every score response includes `"scoring_version"` so scores from different pipeline
versions can be compared and validated.

### 12.4 Scoring principles

- Score is deterministic: same input + same config = same score
- Score formula is fully documented in configuration
- Score formula does not change at runtime
- LLMs do not adjust, override, or invent scores

---

## 13. Evidence Model

Every flaw in the API response must carry a populated `evidence` object.

**All numerical values in `evidence` originate exclusively from the analytical pipeline.**
The LLM (if used) only produces text fields (`explanation`, `recommendation`).

```json
{
  "flaw_id": "flaw_001",
  "start": 12.4,
  "end": 15.8,
  "type": "too_fast",
  "severity": 0.78,
  "reliability": 0.91,
  "low_confidence": false,
  "evidence": {
    "rate_participant_wpm": 187.3,
    "rate_baseline_mean_wpm": 142.6,
    "rate_baseline_std_wpm": 18.4,
    "rate_delta_wpm": 44.7,
    "rate_delta_pct": 31.4,
    "rate_z_score": 2.41,
    "peak_z_score": 3.12,
    "window_duration_s": 3.4,
    "word_count_in_window": 11
  },
  "explanation": "...",
  "recommendation": "...",
  "explanation_method": "gemini"
}
```

**Evidence must be fully populated before the explanation service is called.**
The explanation service receives `evidence` as read-only input.

---

## 14. LLM Boundary

### 14.1 Permitted LLM use

| Use | Input to LLM | Output |
|---|---|---|
| Flaw explanation | Pre-computed `evidence` object (all numbers) | Natural language explanation text |
| Recommendation | `flaw_type` + `evidence` + `severity` | Actionable coaching text |
| Summary | All scored flaws (structured) | Overall delivery feedback summary |

### 14.2 Prohibited LLM use

The LLM must NOT determine or generate:
- `start` / `end` timestamps
- Any value in `evidence` (WPM, Hz, dB, z-scores, percentages, durations)
- `severity`
- `reliability`
- Feature sub-scores
- Composite score
- Whether a flaw exists at all

### 14.3 Implementation guard

**Proposed pattern:**
1. Analytical pipeline produces fully populated `ScoredResult` (all numbers present)
2. Explanation service receives `ScoredResult` as read-only input
3. Service builds a structured prompt containing pre-computed evidence only
4. LLM returns text — only string fields are extracted from the response
5. No numerical field is ever read from LLM output
6. Output passes through a validation step: all numerical values must still match the pre-computed evidence

### 14.4 Fallback

Template-based explanations must always be implemented independently of LLM.
If the LLM is unavailable or returns a malformed response:
- Use the template-based explanation
- Set `"explanation_method": "template"` in the output
- The dashboard must remain fully functional

### 14.5 LLM provider options

| Option | Pros | Cons |
|---|---|---|
| Google Gemini API (free tier) | Free, good quality | Requires API key, network |
| OpenAI GPT-4o-mini | Low cost, fast | API key, cost |
| Local Ollama (llama3) | No API key, offline | Hardware-dependent |
| Template-only | Zero dependency, fully deterministic | Less natural text |

**Recommendation:** Gemini API for demo, with template fallback always present.
Configurable via `EXPLANATION_PROVIDER` environment variable.

---

## 15. Dataset Strategy

### 15.1 Dataset categories

| Category | Description | Purpose |
|---|---|---|
| `baseline_effective` | Human-recorded effective deliveries | Baseline statistics source |
| `flawed_human_controlled` | Human-performed specific flaw recordings | Primary detection validation |
| `flawed_synthetic` | Speed/pitch-shifted variants of baselines | Additional coverage for underrepresented flaws |
| `clean_control` | Normal speech with no introduced flaws | False-positive measurement |

### 15.2 Passage design

- 2-5 passages, each 30-90 seconds
- Each passage has a fixed transcript
- Each passage has at least 1 (ideally 3+) baseline effective recordings
- Each flaw category has at least 1 controlled flawed recording per passage
- Passages should represent realistic speech contexts (e.g., a short presentation, a reading)

### 15.3 Speaker design

- 3-5 speakers across recordings
- At least one speaker reserved exclusively for the held-out test split
- No speaker may appear in both dev and test splits (speaker-separated evaluation)
- Speaker metadata: speaker_id, gender (optional), estimated vocal range (optional)

### 15.4 Recording metadata schema (per recording)

```json
{
  "recording_id": "rec_p001_s02_base_01",
  "passage_id": "p001",
  "speaker_id": "spk_02",
  "category": "baseline_effective",
  "flaw_category": null,
  "flaw_severity_label": null,
  "flaw_start_s": null,
  "flaw_end_s": null,
  "transcript": "...",
  "alignment_file": "data/processed/rec_p001_s02_base_01_alignment.json",
  "audio_file": "data/raw/rec_p001_s02_base_01.wav",
  "sha256_audio": "...",
  "sha256_alignment": "...",
  "recording_conditions": "quiet_room",
  "microphone": "headset_usb_logitech",
  "sample_rate_hz": 44100,
  "duration_s": 47.3,
  "split": "dev",
  "dataset_version": "1.0.0",
  "created_at": "2026-10-07"
}
```

### 15.5 Split assignment

- `dev` — used for threshold calibration and feature validation
- `test` — held out; touched exactly once for final evaluation
- Rule: speaker-separated — no speaker in both splits

### 15.6 Dataset validation

- SHA-256 checksums for all audio and annotation files
- Manifest JSON listing all recordings with checksums and metadata
- Automated validation script: `scripts/dataset/validate_dataset.py`
- Dataset version field for tracking changes across collection rounds

### 15.7 Dataset construction procedure (proposed)

1. Record baseline effective speeches (multiple speakers per passage)
2. Record human-controlled flaw variants
3. Generate synthetic variants using `librosa.effects.time_stretch` and `librosa.effects.pitch_shift`
4. Record clean control recordings
5. Compute SHA-256 for all audio and annotation files
6. Populate manifest JSON
7. Run validation script
8. Assign splits (preserving speaker separation)
9. Tag dataset version

---

## 16. Evaluation Strategy

### 16.1 Primary metrics

**Event detection (per flaw category):**
- Precision: TP / (TP + FP)
- Recall: TP / (TP + FN)
- F1-Score: harmonic mean
- True Positive definition: predicted window overlaps >= 50% of annotated flaw window

**Temporal boundary accuracy:**
- Mean absolute error between predicted and annotated start/end times
- Report at word-level resolution

**False positive rate:**
- Measured on `clean_control` recordings
- Target: < 10% of clean recordings trigger any flaw detection

### 16.2 Robustness tests

| Test | Method | Proposed Pass Criterion |
|---|---|---|
| Background noise | Add pink noise at SNR 20 dB, 10 dB | F1 drop < 15% at 20 dB SNR |
| Gain change | +6 dB / -6 dB applied to participant audio | Score change < 5 points |
| Microphone variation | Recordings of same content on different microphones | F1 drop < 10% |
| Compression | MP3 128 kbps encode/decode cycle | F1 drop < 5% |
| Resampling | 44100 -> 22050 -> 16000 Hz chain | Score change < 2 points |
| Speech rate stress | 80%, 120%, 150% of baseline WPM | Detection recall > 80% |
| Repeated-run | Same input, same config, 3 consecutive runs | Score must be bit-identical |
| Held-out speakers | Evaluate on test-split speakers only | F1 > 0.65 per P0 flaw category |

### 16.3 Calibration rule (critical)

**Thresholds calibrated only on `dev` split.**
The `test` split is touched exactly once for final evaluation.
No threshold tuning is permitted after test results are inspected.

### 16.4 Speaker variation test

Compute score for the same passage recorded by two different effective baseline speakers.
Verify both receive high scores (> 75) despite different absolute pitch/energy characteristics.
This validates that z-score normalization handles speaker variation correctly.

---

## 17. Reproducibility Strategy

### 17.1 Configuration versioning

- All tunable values (thresholds, weights, window sizes) live in `backend/app/core/config.py`
- Configuration includes a `config_version` string (e.g., "1.0.0")
- `config_version` included in every API response and every cached result
- Changing any analytical parameter must increment `config_version`

### 17.2 Library version pinning

- All analytical libraries pinned to exact versions in `requirements.txt`
- NumPy, librosa, whisper, whisperx, scipy all pinned
- Different library versions may produce different floating-point results — this is known

### 17.3 Input hashing

- SHA-256 hash of preprocessed audio computed before any analysis
- Hash stored in API response as `participant_audio_sha256`
- Hash is part of the deterministic cache key

### 17.4 Deterministic caching

```
cache_key = sha256(
  participant_audio_sha256 +
  baseline_sha256 +
  config_version +
  pipeline_version
)
```

- Cache hit: return stored result immediately without recomputing
- Cache miss: run full pipeline, store result, return result
- Cache is persistent (file-based JSON in `data/processed/cache/`)
- Cached results are always identical to freshly computed results

### 17.5 Model version recording

- Whisper model name recorded in every response
- WhisperX aligner version recorded
- All processing parameters logged per request

### 17.6 Cross-machine reproducibility

**Guaranteed:** Feature extraction from identical preprocessed audio + identical library versions.

**Not fully guaranteed (documented limitation):**
- Whisper transcription may produce slightly different word boundaries across hardware/OS
  due to floating-point differences in GPU vs CPU implementations
- Acceptable tolerance: < 50 ms boundary difference

**Mitigation:** For official evaluation, run on a single controlled machine.
For the demo, document that minor cross-machine variation is possible in transcription/alignment
but not in deterministic feature extraction and scoring from a given aligned transcript.

---

## 18. Deployment Proposal

### 18.1 Hackathon demo deployment

**Recommended:** Single machine, local deployment. No Docker required for hackathon.

```
Frontend:  http://localhost:5173  (Vite dev server)
Backend:   http://localhost:8000  (Uvicorn)
```

**Backend startup:**
```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Frontend startup:**
```bash
cd frontend && npm run dev
```

### 18.2 Environment variables

```
WHISPER_MODEL=base
EXPLANATION_PROVIDER=gemini       # or "template"
GEMINI_API_KEY=...                # from environment, never committed
CACHE_DIR=data/processed/cache
CONFIG_VERSION=1.0.0
PIPELINE_VERSION=1.0.0
LOG_LEVEL=INFO
```

Store in `.env` (gitignored). Template in `.env.example` (committed with placeholder values).

### 18.3 Post-hackathon / production (aspirational, P2)

- Docker + Docker Compose
- Nginx reverse proxy for frontend static assets
- Redis for distributed caching
- GPU node for Whisper inference
- Async task queue (Celery + Redis) for longer audio files

---

## 19. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| WhisperX install fails on demo machine | Medium | High | Fallback: openai-whisper with word_timestamps=True |
| Whisper too slow on CPU for demo | High | Medium | Use `base` model; precompute results for demo recordings |
| Pitch normalization fails for very different speakers | Medium | High | Test speaker variation early (Day 2-3) |
| High false positive rate from natural variation | High | High | Calibrate thresholds conservatively; enforce minimum duration |
| LLM API unavailable during demo | Medium | Medium | Template fallback always required and tested |
| Alignment boundary error degrades temporal grounding | Medium | Medium | Test alignment quality independently before full pipeline |
| Dataset too small for robust evaluation | High | Medium | Plan 3+ baselines and 5+ flawed recordings per flaw type |
| MFCC comparison insufficient for clarity detection | High | Medium | Lower clarity weight; document as acoustic proxy |
| Frontend/backend API contract drift | Medium | High | Define Pydantic schemas before frontend development begins |
| Hackathon time pressure causes scope creep | High | Medium | P0 must be complete before P1 is attempted |
| Scoring formula uncalibrated before demo | Medium | High | Calibrate on dev set by Day 5 at the latest |
| Synthetic flaw detection does not generalize | Medium | Medium | Prioritize human-recorded controlled flawed recordings |
| Speaker-separated test set too small | High | Medium | Allocate at least one speaker per passage for test split from Day 1 |

---

## 20. Implementation Dependencies

### 20.1 Python packages (proposed)

| Package | Purpose | Risk |
|---|---|---|
| `fastapi` | API framework | Low |
| `uvicorn` | ASGI server | Low |
| `pydantic` | Schema validation | Low |
| `librosa` | Audio I/O, feature extraction | Low |
| `soundfile` | Audio file I/O | Low |
| `numpy` | Numerical computation | Low |
| `scipy` | Signal processing, median filter | Low |
| `openai-whisper` | Transcription | Low |
| `whisperx` | Forced alignment | Medium (install) |
| `torch` | Required by whisperx | Medium (size) |
| `python-dotenv` | Environment config | Low |
| `google-generativeai` | Gemini API | Low |
| `pytest` | Testing | Low |

### 20.2 Frontend packages (proposed)

| Package | Purpose |
|---|---|
| `react` + `react-dom` | UI framework |
| `vite` | Build tool |
| `typescript` | Type safety |
| `axios` | HTTP API calls |
| `recharts` | Feature timelines and charts |
| `wavesurfer.js` | Waveform display and audio playback |
| `tailwindcss` | Styling |

### 20.3 System requirements

- Python 3.10+
- Node.js 18+
- ffmpeg (for audio format handling via librosa/pydub)
- 16 GB RAM recommended (Whisper + alignment pipeline in memory)
- GPU optional but strongly preferred for `small`/`medium` Whisper models

---

## 21. P0/P1/P2 Priorities

### P0 — Required for core demo

| Task | Area |
|---|---|
| Audio preprocessing (resample, mono, normalize, SHA-256) | Backend / Audio |
| Transcription (Whisper base) | Backend / Transcription |
| Forced alignment (WhisperX) | Backend / Alignment |
| F0 extraction + z-score normalization | Backend / Features |
| Energy extraction + z-score normalization | Backend / Features |
| Speech rate rolling-window | Backend / Features |
| Pause detection | Backend / Features |
| Temporal flaw detection for all 8 flaw types | Backend / Grounding |
| Severity calculation | Backend / Grounding |
| Deterministic per-feature and composite scoring | Backend / Scoring |
| Structured evidence model (mandatory per flaw) | Backend / Schemas |
| Template-based explanation (LLM fallback) | Backend / Explanation |
| FastAPI app skeleton (main.py, router, error handling) | Backend / API |
| Pydantic schemas for all request/response types | Backend / Schemas |
| Health endpoint | Backend / API |
| Analysis endpoint | Backend / API |
| Frontend: upload UI (participant + baseline selection) | Frontend |
| Frontend: overall score card | Frontend |
| Frontend: temporal flaw timeline | Frontend |
| Frontend: flaw detail panel with evidence | Frontend |
| Frontend: audio playback with flaw markers | Frontend |
| Baseline dataset: >= 1 recording per passage | Dataset |
| Dev dataset: labeled flawed recordings | Dataset |
| Config versioning (config_version in all responses) | Backend / Core |
| Input SHA-256 hashing | Backend / Audio |
| Reproducibility: repeated-run test | Testing |

### P1 — Strong improvement

| Task | Area |
|---|---|
| LLM explanation (Gemini API) | Backend / Explanation |
| Multiple baseline references (pooled stats) | Backend / Baseline |
| MFCC word-segment contrastive comparison | Backend / Features |
| Clarity proxy (HF ratio + MFCC distance) | Backend / Features |
| Hysteresis-based thresholding | Backend / Grounding |
| Window merging for adjacent flaws | Backend / Grounding |
| Boundary refinement (snap to word boundaries) | Backend / Grounding |
| Reliability/confidence per flaw | Backend / Grounding |
| Speaker variation test | Testing |
| Held-out evaluation (speaker-separated test split) | Testing |
| Robustness tests (noise, gain, compression) | Testing |
| Feature visualization (F0/energy/rate charts) | Frontend |
| Semitone pitch display | Frontend |
| Deterministic file-based caching | Backend / Core |
| Dataset manifest with SHA-256 checksums | Dataset |
| Dataset validation script | Scripts |

### P2 — Polish (only after P0/P1 safe)

| Task | Area |
|---|---|
| Docker Compose | DevOps |
| Multiple LLM provider support (Ollama fallback) | Backend / Explanation |
| Sentence-boundary-aware pause analysis | Backend / Grounding |
| Interactive transcript (click word -> jump to evidence) | Frontend |
| Export to PDF report | Frontend |
| Demo video production | Submission |
| Technical documentation (docs/methodology/) | Docs |

---

## 22. Decisions Requiring Team Approval

> The following are proposals corresponding to the 15 unresolved items from DECISIONS.md
> plus additional decisions discovered during investigation.
> **None are official until approved by team leader and recorded in DECISIONS.md.**

| # | Decision | Recommended Option | Must Decide Before |
|---|---|---|---|
| 1 | Transcription technology | openai-whisper (base model) | TASK-021 |
| 2 | Forced-alignment technology | WhisperX | TASK-022 |
| 3 | Audio preprocessing config | 16 kHz, mono, float32, peak -3 dBFS | TASK-013 |
| 4 | Feature extraction libraries | librosa (primary), soundfile | TASK-030 to TASK-035 |
| 5 | Pitch normalization methodology | Speaker-aware z-score on voiced frames | TASK-030 |
| 6 | Energy normalization methodology | Z-score after peak normalization | TASK-032 |
| 7 | Baseline construction methodology | Pooled stats across all baseline recordings per passage | TASK-040 |
| 8 | Feature comparison methodology | Frame-level z-score delta (pitch, energy, clarity); rolling-window (rate); segment MFCC cosine distance | TASK-042 |
| 9 | Temporal grounding thresholds | Calibrate on dev set; initial Z=2.0 starting point | TASK-043 / TASK-050 |
| 10 | Severity calculation formula | Sigmoid OR linear product — team to select | TASK-052 |
| 11 | Feature score formulas | Penalty-based: score = 100 - sum(penalties) | TASK-060 |
| 12 | Overall score weighting | Rate 0.25, Pitch 0.20, Pauses 0.20, Energy 0.15, MFCC 0.10, Clarity 0.10 | TASK-062 |
| 13 | Clarity metric/proxy | HF ratio (freq > 3 kHz / total), presented as acoustic proxy | TASK-035 |
| 14 | Dataset size and construction | >= 3 passages, >= 1 baseline/passage, >= 8 flawed recordings per flaw category | TASK-003 / TASK-122 |
| 15 | Deployment architecture | Local Uvicorn + Vite dev server for demo | TASK-004 / TASK-121 |
| 16 | Speech rate window size | W=8s, step=4s, minimum 5 words per window | TASK-033 |
| 17 | Pause threshold values | Within-phrase >= 0.4 s; cross-sentence >= 1.0 s | TASK-034 |
| 18 | Minimum flaw duration | 0.5 s for all flaw types (configurable per type) | TASK-050 |
| 19 | LLM provider | Gemini API free tier with mandatory template fallback | TASK-070 / TASK-072 |
| 20 | Caching strategy | File-based JSON keyed on (audio_sha256 + baseline_sha256 + config_version) | TASK-063 |
| 21 | Reliability score formula | Harmonic mean of alignment confidence + feature confidence + signal quality | TASK-052 |
| 22 | MFCC usage | Word-segment cosine distance for Reduced Clarity evidence (not frame-level thresholding) | TASK-031 |
| 23 | Frontend charting library | recharts (React-native, TypeScript, declarative) | TASK-084 |
| 24 | Audio playback library | wavesurfer.js | TASK-081 |

---

## 23. Assumptions

1. Demo will run on a machine with >= 16 GB RAM.
2. ffmpeg is installable on the demo machine (required for audio format handling).
3. Python 3.10+ and Node.js 18+ are available on all team machines.
4. At least one passage (30-60 s) can be recorded by team members before Day 3.
5. GPU is not guaranteed — system must work on CPU (with slower Whisper inference).
6. English is the primary language for the demo; multilingual support is out of scope.
7. Audio input will be WAV or MP3; other formats handled via ffmpeg.
8. Baseline recordings will be of controlled quality (quiet room, decent microphone).
9. The LLM API key will be available securely on the demo machine (in .env, not committed).
10. Alignment boundary error of <= 200 ms is acceptable for the hackathon demo.
11. The team can produce at least 3 baseline recordings and controlled flawed recordings
    for at least 4 of the 8 flaw categories before Day 5.
12. Scoring weights do not need to be empirically optimal for the demo — they need to be
    reasonable and documented.

---

## 24. How Our Design Improves on Reference Implementations

### vs. RhetorTrace

| RhetorTrace Strength | Our Approach |
|---|---|
| Multiple reference recordings | Designed-in from Day 1 — pooled multi-reference baseline statistics per passage |
| Word-level baseline statistics | Alignment-anchored per-word statistics for rate and pitch |
| Speaker-aware normalization | Z-score on voiced frames, baseline-relative, not global human average |
| Temporal smoothing / hysteresis | Explicit configurable hysteresis with upper/lower thresholds |
| Evidence-rich findings | Mandatory structured evidence object per flaw with >= 6 numerical fields |
| Interactive visualization | Timeline + feature charts + evidence panel in React frontend |

| RhetorTrace Weakness | Our Improvement |
|---|---|
| Synthetic-flaw dependence | Human-recorded controlled flawed recordings as primary evaluation ground truth |
| Weak clarity detection | HF-ratio timeline + MFCC segment cosine distance — two independent signals |
| Scoring concerns | Explicit penalty formula, version-pinned weights, all thresholds in config |
| Limited held-out generalization evidence | Speaker-separated dev/test split enforced from dataset design phase |
| False positives from natural reference variation | Configurable hysteresis + minimum duration filter + merging |

### vs. SpeechLens

| SpeechLens Strength | Our Approach |
|---|---|
| Held-out speakers | Speaker-separated splits defined at dataset design stage |
| Frozen evaluation configuration | config_version in all responses; configuration never modified after test evaluation |
| Dataset checksums | SHA-256 for audio and alignment; manifest validation script |
| Clean controls and stress testing | Explicit clean_control category + robustness test matrix |

| SpeechLens Weakness | Our Improvement |
|---|---|
| Weak detection for some flaw categories | Dual-signal clarity detection; hysteresis reduces fragmentation |
| Non-trivial temporal boundary error | Alignment-based boundary snapping; word-boundary refinement step |
| Limited reference-free detection | Honestly documented: our detection requires baseline reference (not a limitation we hide) |

### vs. SpeechMirror

| SpeechMirror Strength | Our Approach |
|---|---|
| Manifest-driven dataset | Full manifest JSON with flaw annotations, checksums, speaker and condition metadata |
| Dataset validation | Automated validation script in scripts/dataset/ |
| SHA-256 provenance | SHA-256 for audio + alignment files; recorded in every API response |
| Deterministic caching | Hash-keyed file cache including config version in cache key |
| API input validation | Pydantic models for all requests/responses |

| SpeechMirror Weakness | Our Improvement |
|---|---|
| Single-reference baseline | Multi-reference baseline pooling as first-class design goal |
| Simplistic word-level speech rate | Rolling-window WPM over aligned transcript |
| Limited MFCC use in detection | MFCC word-segment cosine distance as independent clarity signal |
| Simpler temporal grounding | Hysteresis + merging + word-boundary snapping |
| Simplistic scoring | Penalty-based per-feature sub-scores + weighted composite with config versioning |
| Dashboard / analysis coupling | Strict boundary: frontend never computes analytical values |

### Key differentiators unique to our design

1. **Mandatory evidence-before-explanation guarantee:** The evidence object is fully populated
   before the explanation service is called. No exception. If LLM fails, template fallback
   ensures the dashboard still works.

2. **Dual-signal clarity detection:** HF ratio + MFCC segment distance independently,
   both honestly presented as acoustic proxies with lower scoring weight.

3. **Configurable-everything approach:** Every threshold, weight, window size, and duration
   is stored in versioned config. Changing any parameter bumps config_version.

4. **Explicit reliability per flaw:** Low-confidence detections are included, flagged, and
   weighted down — not silently hidden.

5. **Speaker-separated evaluation from Day 1:** Dataset split design enforces speaker
   separation before any calibration begins.

6. **Rolling-window speech rate:** Avoids the instability of per-word duration inversion.

---

## 25. Executive Summary

### Recommended choices (proposed, not approved)

| Category | Recommendation |
|---|---|
| Transcription | openai-whisper, base model |
| Alignment | WhisperX |
| Preprocessing | librosa + soundfile, 16 kHz mono, -3 dBFS peak |
| F0 | librosa.pyin, z-score normalized (voiced frames only) |
| Energy | librosa.feature.rms -> dBFS -> z-score |
| Speech rate | Rolling-window WPM, W=8s, step=4s |
| Pause | Energy VAD + alignment gap >= 0.4s within-phrase |
| MFCC | librosa.feature.mfcc, 13 coefficients, word-segment cosine distance |
| Clarity | HF ratio (>3 kHz / total) + spectral rolloff secondary |
| Baseline | Pooled multi-reference stats per passage, speaker-aware z-score |
| Flaw detection | Z-score threshold, hysteresis, merging, word-boundary snapping |
| Severity | Sigmoid OR linear product of (peak z-score, duration) — team to select |
| Scoring | Penalty-based sub-scores + weighted composite, all in versioned config |
| LLM | Gemini API free tier + mandatory template fallback |
| Caching | File-based hash-keyed JSON cache |
| Deployment | Local Uvicorn + Vite dev server |
| Frontend charts | recharts |
| Audio playback | wavesurfer.js |

### Unresolved choices requiring team decision before implementation

All 24 items in §22. The most time-sensitive decisions:

1. **WhisperX vs. MFA** (alignment) — must decide before TASK-022; allocate time on Day 1
2. **Severity formula** (sigmoid vs. linear) — must be selected once before TASK-052
3. **Composite score weights** — require empirical calibration; initial proposal in §12
4. **Speech rate window size** (8s vs. 5s vs. phrase-based) — affects detection quality
5. **Minimum flaw duration threshold** — single most impactful parameter for false positive rate

### Experiments to run before final approval

1. **Alignment quality test:** Run WhisperX on 2 baseline recordings; measure word boundary
   error. If > 300 ms typical error, evaluate MFA instead.
2. **Speech rate window sweep:** Test W=5s, 8s, 10s on controlled too-fast/too-slow recordings;
   choose W minimizing fragmented detections.
3. **Normalization speaker test:** Record same passage with 2 speakers, verify both effective
   baselines score > 75 after z-score normalization.
4. **Threshold sensitivity sweep:** Sweep Z from 1.5 to 3.0 on dev set; select conservative
   operating point from precision/recall curve.
5. **Severity formula sanity check:** Verify selected formula produces intuitive values
   (mild flaw ~0.3, severe flaw ~0.85) before committing.
6. **Whisper speed benchmark:** Time Whisper base on 60-second audio on CPU.
   If > 30s, plan for async processing endpoint.
7. **LLM guardrail integration test:** Verify no LLM output is ever used to populate
   a numerical field in the response.

### Dependencies that would be introduced

**Python:**
openai-whisper, whisperx, librosa, soundfile, scipy, numpy,
pydantic, fastapi, uvicorn, python-dotenv, google-generativeai, pytest

**Frontend:**
react, recharts, wavesurfer.js, tailwindcss, axios, vite, typescript

**System:**
ffmpeg (binary, required for audio format conversion)

### Risks requiring team attention

1. **WhisperX install complexity** — allocate a full team session for environment setup on Day 1
2. **Calibration timeline** — thresholds must be calibrated before Day 5; dataset must exist by Day 3
3. **False positive rate** — natural speech variation may trigger detections without sufficient
   hysteresis; test early and aggressively
4. **Clarity detection weakness** — HF ratio and MFCC distance are approximate proxies;
   the team must accept and honestly communicate this limitation
5. **GPU availability** — Whisper `base` on CPU is 2-3x real-time for short clips; acceptable
   for demo but must be tested and communicated

---

*End of Architecture Proposal v0.1*

*This document is a PROPOSAL only.*
*All recommendations require team leader approval before becoming official project decisions.*
*Official decisions must be recorded in DECISIONS.md and ARCHITECTURE.md.*
*No implementation files were created or modified during the production of this document.*
