# Architecture
## Track C — Contrastive Speech Analytics & Temporal Flaw Grounding

**Status:** CANONICAL — reviewed and accepted as implementation guide
**Supersedes:** docs/architecture/architecture-proposal.md (proposal, read-only reference)
**Last updated:** 2026-10-07
**Change procedure:** See §32

> AI agents MUST read this document before implementing any component.
> Do NOT invent architecture that is not defined here.
> Do NOT implement features outside the canonical pipeline.
> When uncertain, stop and report. Do not guess silently.

---

## 1. Status

Architecture review is complete.
This document is the canonical technical reference for all implementation work.

Empirically unresolved choices are explicitly marked PROPOSED.
Agents must not treat PROPOSED items as accepted.

---

## 2. Architecture Principles

1. **Analytical truth is deterministic and backend-owned.**
   Same input + same configuration must produce the same result, always.

2. **LLMs translate evidence into language. LLMs do not create evidence.**
   No LLM may produce timestamps, feature values, z-scores, deviation percentages,
   severity values, reliability values, or scores.

3. **The frontend visualizes what the backend computed.**
   The frontend never computes analytical features or scores.

4. **Every flaw must have measurable evidence and a timestamp.**
   A flaw without both is not a flaw.

5. **Evidence is populated before explanation is called.**
   The explanation service receives a fully populated evidence object and may only
   produce natural language from it.

6. **Baseline means effective delivery of the same content.**
   Not a universal human average.

7. **Speaker variation is handled by baseline-relative normalization, not speaker adaptation.**
   The system normalizes relative to the baseline recordings' statistics.
   This does not guarantee full speaker independence. Limitations are documented.

8. **Clarity is an acoustic proxy, not a perceptual intelligibility measure.**
   It is affected by microphone, room, speaker, and recording quality.
   Its weight in scoring is lower than directly measured features.
   It must not block the main demo.

9. **Thresholds and weights live in versioned configuration.**
   Hard-coded analytical constants are forbidden.

10. **The system is for an 8-day hackathon.**
    Simple, working, and correct is better than complex and incomplete.

---

## 3. System Boundaries

```
+---------------------------------------------------------------+
|                        FRONTEND                               |
|  React + Vite + TypeScript                                    |
|  Presentation | Interaction | Visualization | Playback        |
|  API communication only — no analytical computation           |
+----------------------------+----------------------------------+
                             |  REST HTTP/JSON
+----------------------------v----------------------------------+
|                     BACKEND API LAYER                         |
|  FastAPI — input validation, orchestration, response          |
+----------------------------+----------------------------------+
                             |
+----------------------------v----------------------------------+
|                  ANALYSIS ORCHESTRATOR                        |
|  Runs canonical pipeline in order                             |
|  Manages cache lookup, provenance, config version             |
+--+------+------+------+-------+------+------+----------------+
   |      |      |      |       |      |      |
   v      v      v      v       v      v      v
[audio][trans][align][feat] [ground][score][explain]
```

**Dependency direction (strict):**
```
api -> orchestrator -> audio -> transcription -> alignment
                             -> features
                             -> grounding (needs features + baseline)
                             -> scoring   (needs grounding)
                             -> explanation (needs scoring)
```

No service may call a service downstream of it in this chain.
No service may call the API layer.
The frontend may not call services directly.

---

## 4. Canonical Pipeline

This pipeline is defined in AGENTS.md and must not be silently replaced or reordered.

```
Audio Input (participant + baseline reference)
    |
    v
[1] Preprocessing      audio/
    |
    v
[2] Transcription      transcription/
    |
    v
[3] Forced Alignment   alignment/
    |
    v
[4] Feature Extraction features/
    |
    v
[5] Baseline Normalization  (inside features/ or a dedicated normalizer)
    |
    v
[6] Contrastive Comparison  grounding/ (first stage)
    |
    v
[7] Temporal Flaw Detection grounding/ (second stage)
    |
    v
[8] Severity Estimation    grounding/ (third stage)
    |
    v
[9] Deterministic Scoring  scoring/
    |
    v
[10] Evidence-backed Explanation  explanation/
    |
    v
[11] API Response           api/
    |
    v
[12] Dashboard Visualization  frontend
```

---

## 5. High-Level Component Diagram

```
backend/
  app/
    main.py              — FastAPI app entry point
    api/
      routes/
        analyze.py       — POST /api/v1/analyze
        health.py        — GET  /api/v1/health
        result.py        — GET  /api/v1/result/{analysis_id}
        status.py        — GET  /api/v1/status/{analysis_id}
    core/
      config.py          — All analytical configuration (single source)
      orchestrator.py    — Pipeline coordinator
      cache.py           — Deterministic file-based cache
    schemas/
      request.py         — Pydantic request models
      response.py        — Pydantic response models
      contracts.py       — Internal intermediate data contracts
    services/
      audio/             — Preprocessing
      transcription/     — ASR
      alignment/         — Forced alignment
      features/          — F0, MFCC, Energy, Rate, Pause, Clarity
      grounding/         — Contrastive comparison + flaw detection + severity
      scoring/           — Deterministic scoring
      explanation/       — Template + optional LLM explanation

frontend/
  src/
    api/                 — API client (fetch/axios)
    components/          — Upload, Score, Timeline, Flaw panel, Charts, Playback
    types/               — TypeScript types (derived from backend Pydantic schemas)
    App.tsx

data/
  raw/                   — Original audio files
  processed/
    alignments/          — Alignment JSON files
    cache/               — Analysis result cache
  metadata/
    manifest.json        — Dataset manifest with checksums
  annotations/           — Flaw annotations

scripts/
  dataset/
    validate_dataset.py  — SHA-256 integrity check
    build_baseline_stats.py — Compute and store baseline statistics
```

---

## 6. Data Flow

### 6.1 Request input (API)

```
POST /api/v1/analyze
Content-Type: multipart/form-data

fields:
  participant_audio  — audio file (WAV or MP3, max 10 MB)
  baseline_id        — string: dataset baseline ID
  passage_id         — string: passage identifier
  speaker_gender     — optional string: "male" | "female" | null
  config_version     — string: must match server config_version or rejected
```

### 6.2 Internal pipeline objects

Each service consumes the output of the previous service.
All objects are typed via Pydantic models defined in `backend/app/schemas/contracts.py`.

```
PreprocessedAudio
  -> Transcript
  -> AlignedTranscript
  -> FeatureBundle
  -> NormalizedFeatureBundle
  -> ContrastiveBundle
  -> FlawCandidates[]
  -> GroundedFlaws[]
  -> ScoredResult
  -> ExplanationResult  (= final API response body)
```

### 6.3 API response (canonical shape)

```json
{
  "analysis_id": "<uuid>",
  "config_version": "1.0.0",
  "pipeline_version": "1.0.0",
  "participant_audio_sha256": "<hex>",
  "baseline_id": "<id>",
  "baseline_sha256": "<hex>",
  "alignment_method": "whisperx | whisper_word_timestamps | manual",
  "transcript": "<full text>",
  "alignment": [
    { "word": "hello", "start_s": 0.41, "end_s": 0.73, "confidence": 0.95 }
  ],
  "features": {
    "f0_timeline":          { "times_s": [], "values_hz": [], "voiced": [] },
    "energy_timeline":      { "times_s": [], "values_db": [] },
    "speech_rate_timeline": { "times_s": [], "words_per_min": [] },
    "pause_events":         [{ "start_s": 1.2, "end_s": 1.9, "duration_s": 0.7,
                               "detection_source": "both | vad | alignment",
                               "boundary_type": "within_phrase | cross_sentence" }],
    "mfcc_summary":         { "mean_13": [], "std_13": [] },
    "clarity_timeline":     { "times_s": [], "hf_ratio": [] }
  },
  "baseline_stats": {
    "f0_voiced_hz_mean": 0.0, "f0_voiced_hz_std": 0.0,
    "energy_db_mean": 0.0,    "energy_db_std": 0.0,
    "rate_wpm_mean": 0.0,     "rate_wpm_std": 0.0,
    "pause_within_phrase_mean_s": 0.0, "pause_within_phrase_std_s": 0.0,
    "pause_cross_sentence_mean_s": 0.0,
    "hf_ratio_mean": 0.0,     "hf_ratio_std": 0.0
  },
  "flaws": [
    {
      "flaw_id": "flaw_001",
      "type": "too_fast",
      "start_s": 12.4,
      "end_s": 15.8,
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
      "explanation_method": "template | gemini"
    }
  ],
  "scores": {
    "speech_rate": { "score": 61, "weight": 0.0, "flaw_count": 2, "penalty_total": 39.0 },
    "pitch":       { "score": 74, "weight": 0.0, "flaw_count": 1, "penalty_total": 26.0 },
    "pauses":      { "score": 79, "weight": 0.0, "flaw_count": 1, "penalty_total": 21.0 },
    "energy":      { "score": 88, "weight": 0.0, "flaw_count": 0, "penalty_total": 0.0  },
    "mfcc":        { "score": 80, "weight": 0.0, "flaw_count": 0, "penalty_total": 0.0  },
    "clarity":     { "score": 83, "weight": 0.0, "flaw_count": 0, "penalty_total": 0.0  },
    "composite":   82
  },
  "processing_meta": {
    "whisper_model": "base",
    "alignment_method": "whisperx",
    "processing_time_s": 14.2,
    "cached": false
  }
}
```

Note: Actual weights for each feature are read from config at runtime and included
in the response. They are NOT hardcoded to the values above.

---

## 7. Module Responsibilities

### 7.1 `services/audio/`

**Owns:** Preprocessing
**Input:** Raw audio file (bytes)
**Output:** `PreprocessedAudio`

Responsibilities:
- Validate format (WAV, MP3), duration (max configurable), sample rate
- Convert to mono
- Resample to `TARGET_SAMPLE_RATE` (config, default 16 000 Hz)
- Peak-normalize to `TARGET_PEAK_DBFS` (config, default −3 dBFS)
- Trim leading/trailing silence using energy VAD (threshold configurable)
- Compute SHA-256 of the preprocessed PCM bytes
- Return `PreprocessedAudio`

**Must NOT:** extract features, call transcription, perform analysis.

---

### 7.2 `services/transcription/`

**Owns:** Automatic speech recognition
**Input:** `PreprocessedAudio`
**Output:** `Transcript`

Responsibilities:
- Run Whisper with the configured model name
- Accept an optional manually-supplied transcript string (bypasses ASR)
- Record model name in output metadata
- Return `Transcript { text, words: [{word, approx_start_s, approx_end_s}], model_name }`

**Must NOT:** perform forced alignment, extract features.

---

### 7.3 `services/alignment/`

**Owns:** Word-level forced alignment
**Input:** `PreprocessedAudio`, `Transcript`
**Output:** `AlignedTranscript`

Responsibilities:
- Attempt forced alignment with the configured primary method (WhisperX when installed)
- Fall back to Whisper `word_timestamps=True` if primary method fails
- Record `alignment_method` in output (`"whisperx"` | `"whisper_word_timestamps"` | `"manual"`)
- Validate that total word coverage > `MIN_COVERAGE_PCT` (config)
- Return `AlignedTranscript`

The `AlignedTranscript` interface is identical regardless of alignment method.
Downstream services must not branch on `alignment_method`.

**Must NOT:** run ASR, extract features.

---

### 7.4 `services/features/`

**Owns:** All analytical feature extraction — single canonical implementation of each.

**Input:** `PreprocessedAudio`, `AlignedTranscript`
**Output:** `FeatureBundle`

Sub-modules (one file per feature — no feature implemented in two files):

| Sub-module | Feature | Output |
|---|---|---|
| `f0.py` | F0 / Pitch via PYIN | Frame-level Hz + voiced boolean + voiced probability |
| `mfcc.py` | MFCC via librosa | 13-coefficient frame matrix |
| `energy.py` | RMS energy via librosa | Frame-level dBFS values |
| `rate.py` | Rolling-window speech rate | WPM timeline from aligned words |
| `pause.py` | Pause detection | Pause event list |
| `clarity.py` | HF energy ratio proxy (P1) | Frame-level HF ratio |

All feature extractors:
- Accept fixed, pinned configuration (hop_length, n_fft, etc. from `config.py`)
- Return arrays with explicit time axes
- Are stateless and produce identical output for identical input + config
- Do not normalize — normalization is the next stage

**Must NOT:** normalize, compare to baseline, score, explain.

---

### 7.5 `services/grounding/`

**Owns:** Normalization, contrastive comparison, temporal flaw detection, severity, reliability

This service implements stages 5–8 of the pipeline.

**Input:** `FeatureBundle`, `BaselineStats`
**Output:** `GroundedFlaws[]`

Sub-stages (in order, in this service):

1. **Baseline normalization** — z-score each feature relative to `BaselineStats`
2. **Contrastive comparison** — compute delta/z-score timelines
3. **Candidate generation** — threshold rules per flaw type
4. **Smoothing** — median filter on contrastive signal (P1; simple threshold acceptable for P0)
5. **Hysteresis** — upper/lower threshold entry/exit (P1)
6. **Minimum duration filter** — discard windows < `MIN_FLAW_DURATION_S`
7. **Window merging** — merge windows of same type within `MERGE_GAP_S`
8. **Boundary refinement** — snap to word boundaries within `MAX_SNAP_S` (P1)
9. **Evidence extraction** — compute all evidence fields for each flaw
10. **Severity computation** — deterministic formula from config
11. **Reliability computation** — deterministic formula from config (P1)

**Must NOT:** score, explain, call the API layer.

---

### 7.6 `services/scoring/`

**Owns:** Deterministic scoring
**Input:** `GroundedFlaws[]`, `FeatureBundle` (for global statistics)
**Output:** `ScoredResult`

Responsibilities:
- Compute per-feature sub-score using penalty formula (see §20)
- Compute composite weighted score using weights from config
- Record `scoring_version` in output
- Guarantee bit-identical output for identical inputs and config

**Must NOT:** explain, extract features, compare to baseline.

---

### 7.7 `services/explanation/`

**Owns:** Natural language generation
**Input:** `ScoredResult` (read-only — all numbers already computed)
**Output:** `ExplanationResult` (final response body)

Responsibilities:
- For each flaw, build a natural language explanation from `evidence` using templates
- Optionally call LLM API if `EXPLANATION_PROVIDER=gemini` and API key is set
- If LLM unavailable or call fails: use template silently, set `explanation_method="template"`
- Never read numerical values from LLM output; only string fields are accepted
- Record `explanation_method` per flaw

**Must NOT:** compute timestamps, evidence fields, severity, reliability, or scores.
**Must NOT:** modify any numerical field in `ScoredResult`.

---

### 7.8 `api/`

**Owns:** HTTP interface, input validation, orchestration call, response serialization

Responsibilities:
- Validate audio upload (format, size, duration)
- Validate `baseline_id` existence
- Validate `config_version` matches server config
- Check cache before calling orchestrator
- Call orchestrator for cache miss
- Serialize `ExplanationResult` to JSON response
- Return appropriate HTTP status codes

---

### 7.9 `core/config.py`

**Owns:** All analytical configuration — single source of truth

Responsibilities:
- Expose all thresholds, weights, window sizes, model names as named constants
- Expose `CONFIG_VERSION` string (increment on any analytical parameter change)
- Expose `PIPELINE_VERSION` string (increment on structural pipeline changes)
- Load from environment variables where appropriate (model name, LLM provider)

No analytical constant may be hardcoded outside `config.py`.

---

### 7.10 `core/cache.py`

**Owns:** Deterministic file-based result cache

Cache key:
```
cache_key = sha256(
  participant_audio_sha256 +
  baseline_id +
  baseline_sha256 +
  config_version +
  pipeline_version
)
```

Behavior:
- Cache hit: return stored JSON immediately
- Cache miss: run pipeline, store JSON, return JSON
- Never return a cached result whose key was computed under different configuration
- Cache files stored in `CACHE_DIR` (config)

---

## 8. Dependency Direction

```
api
 └─> orchestrator
      ├─> audio
      ├─> transcription (needs audio)
      ├─> alignment     (needs audio + transcription)
      ├─> features      (needs audio + alignment)
      ├─> grounding     (needs features + baseline_stats)
      ├─> scoring       (needs grounding)
      └─> explanation   (needs scoring)
```

Forbidden import directions:
- A service may never import from `api`
- A service may never import from a service later in the pipeline
- `features` may never import from `grounding`
- `grounding` may never import from `scoring`
- `scoring` may never import from `explanation`
- Frontend may never import backend modules

---

## 9. Intermediate Data Contracts

Defined in `backend/app/schemas/contracts.py`. All fields listed below are required
unless marked `optional`.

### 9.1 PreprocessedAudio

```
sample_rate_hz:    int          — always TARGET_SAMPLE_RATE after preprocessing
channels:          int          — always 1 (mono)
duration_s:        float
audio_array:       np.ndarray   — float32 PCM
sha256:            str          — hex digest of audio_array bytes
peak_dbfs:         float        — measured peak after normalization
```

### 9.2 Transcript

```
text:              str          — full transcript string
words:             list of {
  word:              str
  approx_start_s:    float
  approx_end_s:      float
}
model_name:        str          — e.g. "whisper_base"
source:            str          — "asr" | "manual"
```

### 9.3 AlignedTranscript

```
words:             list of {
  word:              str
  start_s:           float
  end_s:             float
  confidence:        float      — alignment confidence [0, 1]
}
alignment_method:  str          — "whisperx" | "whisper_word_timestamps" | "manual"
total_coverage_pct: float       — fraction of audio covered by aligned words
```

### 9.4 FeatureBundle

```
f0_times_s:        np.ndarray   — frame timestamps
f0_values_hz:      np.ndarray   — F0 per frame (NaN for unvoiced)
f0_voiced:         np.ndarray   — bool per frame
f0_voiced_prob:    np.ndarray   — PYIN voiced probability per frame

energy_times_s:    np.ndarray
energy_db:         np.ndarray

rate_times_s:      np.ndarray   — one value per rolling window step
rate_wpm:          np.ndarray

pause_events:      list of {
  start_s:           float
  end_s:             float
  duration_s:        float
  detection_source:  str        — "vad" | "alignment" | "both"
  boundary_type:     str        — "within_phrase" | "cross_sentence" | "unknown"
}

mfcc_times_s:      np.ndarray   (P1 — optional at P0)
mfcc_matrix:       np.ndarray   — shape (n_frames, 13)

clarity_times_s:   np.ndarray   (P1 — optional at P0)
clarity_hf_ratio:  np.ndarray

config_snapshot:   dict         — copy of config values used during extraction
```

### 9.5 BaselineStats

```
passage_id:            str
dataset_version:       str
baseline_recording_ids: list[str]
f0_voiced_hz_mean:     float
f0_voiced_hz_std:      float
f0_voiced_hz_p05:      float
f0_voiced_hz_p95:      float
energy_db_mean:        float
energy_db_std:         float
rate_wpm_mean:         float
rate_wpm_std:          float
pause_within_phrase_mean_s:  float
pause_within_phrase_std_s:   float
pause_cross_sentence_mean_s: float
hf_ratio_mean:         float    (optional, for P1 clarity)
hf_ratio_std:          float    (optional)
sha256:                str      — hash of this stats file
```

### 9.6 NormalizedFeatureBundle

Extends `FeatureBundle` with z-scored fields:
```
f0_z:              np.ndarray   — (f0_values_hz - mean) / std, voiced frames only
energy_z:          np.ndarray
rate_z:            np.ndarray
clarity_z:         np.ndarray   (P1)
```

### 9.7 ContrastiveBundle

For frame/window timelines, after normalization baseline is z=0 by definition:
```
f0_delta_z:        np.ndarray   — participant z-score (direct comparison to baseline mean)
energy_delta_z:    np.ndarray
rate_delta_z:      np.ndarray
pause_delta_s:     list[float]  — per pause: duration - baseline_mean_pause_s
clarity_delta_z:   np.ndarray   (P1)
```

### 9.8 FlawCandidate

```
type:              str          — one of the 8 supported flaw types
start_s:           float
end_s:             float
peak_z:            float        — max absolute z-score in the window
mean_z:            float
detection_feature: str          — which feature triggered this candidate
raw_evidence:      dict         — feature values and baseline stats in the window
```

### 9.9 GroundedFlaw

```
flaw_id:           str          — "flaw_NNN"
type:              str
start_s:           float        — refined, snapped to word boundary if P1 enabled
end_s:             float
duration_s:        float
severity:          float        — [0.0, 1.0] deterministic
reliability:       float        — [0.0, 1.0] deterministic (P1; 1.0 default at P0)
low_confidence:    bool
evidence:          dict         — all numerical evidence fields (see §21)
```

### 9.10 ScoredResult

```
flaws:             list[GroundedFlaw]
feature_scores:    dict[str, FeatureScore]  — one per feature dimension
composite_score:   float        — [0, 100]
scoring_version:   str
config_version:    str
```

`FeatureScore`:
```
feature:           str
score:             float        — [0, 100]
weight:            float        — from config
flaw_count:        int
penalty_total:     float
```

### 9.11 ExplanationResult

Extends `ScoredResult`, adds per-flaw:
```
explanation:       str
recommendation:    str
explanation_method: str         — "template" | "gemini"
```

Plus top-level:
```
overall_summary:   str          — optional overall feedback (LLM or template)
```

---

## 10. Audio Architecture

**Target preprocessing spec:**
- Sample rate: `TARGET_SAMPLE_RATE = 16000` Hz (config)
- Channels: 1 (mono)
- Format: float32 PCM
- Peak normalization: `TARGET_PEAK_DBFS = -3.0` dBFS (config)
- Silence trimming: energy VAD with `VAD_ENERGY_THRESHOLD_DBFS = -50.0` (config)
- Input formats accepted: WAV, MP3 (ffmpeg required for MP3)
- Max upload size: `MAX_UPLOAD_BYTES = 10_485_760` (10 MB, config)
- Max duration: `MAX_DURATION_S = 300` (5 min, config)

**Provenance:**
SHA-256 is computed over the normalized float32 PCM bytes after all preprocessing is applied.
This hash is stable: same audio content → same hash.

---

## 11. Transcription Architecture

**Primary (PROPOSED, not yet installed-verified):** `openai-whisper`
- Model: configured via `WHISPER_MODEL` env var (default `"base"`)
- Model name recorded in `Transcript.model_name`
- Word timestamps enabled by default

**Manual override:**
If a manual transcript is supplied in the request, ASR is skipped.
`Transcript.source = "manual"`.

**Configuration:**
```
WHISPER_MODEL     = base | small | medium     (env var)
WHISPER_LANGUAGE  = en                         (env var, default English)
```

**Note:** Whisper model selection is PROPOSED. The team must verify install on all
machines before TASK-021 begins. See §31.

---

## 12. Alignment Architecture

### Primary method (PROPOSED, install-dependent): WhisperX

WhisperX performs forced alignment using wav2vec2 to produce word-level timestamps
more accurate than Whisper's built-in word timestamps.

### Fallback method: Whisper word timestamps

If WhisperX cannot be installed or fails at runtime, the alignment service falls back
to Whisper's `word_timestamps=True` output. Timestamps are less accurate but preserve
the same `AlignedTranscript` interface.

### Uniform interface (ACCEPTED — not install-dependent)

```
AlignedTranscript:
  words:             list[{word, start_s, end_s, confidence}]
  alignment_method:  "whisperx" | "whisper_word_timestamps" | "manual"
  total_coverage_pct: float
```

All downstream services use `AlignedTranscript` exclusively.
No downstream service branches on `alignment_method`.
This means the pipeline degrades gracefully without WhisperX.

### Alignment validation

After alignment:
- Verify `total_coverage_pct >= MIN_COVERAGE_PCT` (config, proposed 0.80)
- Log a warning if coverage is low; do not abort (low coverage means sparse features)
- Maximum snap distance for boundary refinement: `MAX_SNAP_S = 0.3` s (config)

---

## 13. Feature Architecture

All features implemented in `backend/app/services/features/`.
Each feature has exactly one implementation file.
No feature is implemented anywhere else.

### 13.1 F0 / Pitch

| Property | Value |
|---|---|
| Algorithm | `librosa.pyin` (Probabilistic YIN) |
| Library | librosa (PROPOSED — install unverified) |
| hop_length | `F0_HOP_LENGTH` (config, proposed 160 samples = 10 ms at 16 kHz) |
| fmin | `F0_FMIN_HZ` (config, proposed 75 Hz) |
| fmax | `F0_FMAX_HZ` (config, proposed 500 Hz) |
| voiced_threshold | `F0_VOICED_PROB_THRESHOLD` (config, proposed 0.85) |
| Output | frame-level Hz (NaN for unvoiced), voiced boolean, voiced probability |
| Normalization | z-score on voiced frames using baseline `f0_voiced_hz_mean`, `f0_voiced_hz_std` |
| Baseline comparison | participant z-score vs. 0 (baseline mean) |
| Detection role | Flat Pitch (P0), Pitch Instability (P1) |
| Evidence fields | `f0_mean_hz`, `f0_std_hz`, `f0_baseline_mean_hz`, `f0_z_mean`, `f0_z_peak` |
| Failure condition | If >80% of frames are unvoiced, skip pitch analysis; log warning |

### 13.2 MFCC

| Property | Value |
|---|---|
| Algorithm | `librosa.feature.mfcc` |
| n_mfcc | `MFCC_N_COEFFS` (config, proposed 13) |
| hop_length | `MFCC_HOP_LENGTH` (config, same as F0) |
| n_fft | `MFCC_N_FFT` (config, proposed 512) |
| Output | frame matrix (n_frames × 13) |
| Primary use | Word-segment cosine distance for Reduced Clarity evidence (P1) |
| Detection role | Reduced Clarity (P1 only) |
| P0 use | Summary statistics only (`mfcc_summary` in response): mean and std per coefficient |
| Evidence fields | `mfcc_cosine_distance` (P1) |
| Failure condition | Not used for flaw detection at P0; no failure blocks pipeline |

### 13.3 Energy

| Property | Value |
|---|---|
| Algorithm | `librosa.feature.rms` converted to dBFS |
| Formula | `energy_db = 20 * log10(max(rms, 1e-9))` |
| hop_length | `ENERGY_HOP_LENGTH` (config, same as F0) |
| Output | frame-level dBFS values |
| Normalization | z-score using baseline `energy_db_mean`, `energy_db_std` |
| Baseline comparison | participant z-score vs. 0 |
| Detection role | Low Energy, High Energy (P0); VAD for pause detection |
| Evidence fields | `energy_mean_db`, `energy_baseline_mean_db`, `energy_z_mean`, `energy_z_peak` |
| Failure condition | Very quiet audio (< −70 dBFS mean) → low reliability; log warning |

### 13.4 Speech Rate

| Property | Value |
|---|---|
| Algorithm | Rolling-window WPM over `AlignedTranscript.words` |
| Window size | `RATE_WINDOW_S` (config, proposed 8 s) |
| Step size | `RATE_STEP_S` (config, proposed 4 s) |
| Min words/window | `RATE_MIN_WORDS` (config, proposed 5) |
| Formula | `rate_wpm = (n_words_in_window / effective_duration_s) * 60` |
| Effective duration | `last_word.end_s − first_word.start_s` within window |
| Output | WPM value at each step (windows with < MIN_WORDS are skipped) |
| Normalization | z-score using baseline `rate_wpm_mean`, `rate_wpm_std` |
| Detection role | Too Fast, Too Slow (P0) |
| Evidence fields | `rate_participant_wpm`, `rate_baseline_mean_wpm`, `rate_baseline_std_wpm`, `rate_delta_wpm`, `rate_delta_pct`, `rate_z_score`, `peak_z_score`, `word_count_in_window` |
| Failure condition | If fewer than `RATE_MIN_WINDOWS` (config, proposed 2) valid windows exist, skip rate analysis |

**Note:** Speech rate is NOT computed as inverse individual word duration.
That approach produces fragmented, noisy estimates and is explicitly forbidden.

### 13.5 Pause Detection

Pause detection uses two independent signals. Their results are combined, not
required to agree. The architecture resolves the inconsistency from the proposal.

**Signal A — Energy VAD:**
- Mark frame as unvoiced if `energy_db < VAD_ENERGY_THRESHOLD_DBFS` (config, proposed −50 dBFS)
- A VAD pause candidate is a contiguous unvoiced region >= `VAD_MIN_PAUSE_S` (config, proposed 0.2 s)

**Signal B — Alignment gap:**
- An alignment gap candidate is an inter-word gap from `AlignedTranscript` >= `ALIGN_MIN_GAP_S` (config, proposed 0.15 s)

**Combination logic (resolves Issue 2):**
```
For each candidate window (from either signal):
  If both signals agree (overlap > 50%):
    detection_source = "both"
    confidence_boost = True
  If only VAD:
    detection_source = "vad"
    (included — VAD is sufficient evidence)
  If only alignment gap:
    detection_source = "alignment"
    (included — alignment gap is sufficient evidence)
  If neither:
    (not a pause)
```

The system does NOT require both signals to agree. Either signal alone is sufficient
to generate a pause candidate. Agreement increases reliability.

**Pause classification:**
```
if pause occurs between sentences (punctuation in transcript: ". " | "? " | "! "):
  boundary_type = "cross_sentence"
  compare against: baseline_pause_cross_sentence_mean_s
else:
  boundary_type = "within_phrase"
  compare against: baseline_pause_within_phrase_mean_s
```

**Flaw condition (Excessive Pause):**
```
if pause.duration_s > baseline_mean_for_type + Z_PAUSE * baseline_std_for_type:
  -> flaw candidate
```
Where `Z_PAUSE` is configurable. Cross-sentence pauses use a higher threshold
than within-phrase pauses to reduce false positives.

**Evidence fields:** `pause_duration_s`, `pause_baseline_mean_s`, `pause_baseline_std_s`,
`pause_delta_s`, `pause_z_score`, `boundary_type`, `detection_source`

### 13.6 Acoustic Clarity Proxy (P1)

**STATUS: P1 — does not block P0 delivery.**

The clarity proxy is an acoustic measurement. It is not a perceptual intelligibility measure.
It is affected by microphone quality, room acoustics, speaker characteristics, and
recording conditions independent of delivery intent.

It MUST be presented to users as an "acoustic clarity proxy," not as an intelligibility score.

**Primary proxy — HF energy ratio:**
```
hf_ratio(frame) = power(freq > HF_CUTOFF_HZ) / total_power(frame)
HF_CUTOFF_HZ = 3000   (config)
```

**Normalization:** z-score using baseline `hf_ratio_mean`, `hf_ratio_std`

**Secondary signal — MFCC word-segment distance (P1):**
- For each word segment, compute mean MFCC vector
- Compare to the same word's mean MFCC in baseline recordings (requires baseline MFCC stats)
- Distance metric: cosine distance
- Used as supplementary evidence, not standalone detection

**Flaw condition (Reduced Clarity — P1):**
```
if hf_ratio_z < -Z_CLARITY AND window_duration >= MIN_DURATION:
  -> flaw candidate (Reduced Clarity)
```

Clarity is assigned the lowest weight in scoring (see §20).
If clarity proves unreliable in practice, its weight can be reduced to 0 via config
without any code change.

---

## 14. Baseline Architecture

### 14.1 Core principle

The baseline represents effective delivery of the **same speech content** — not a
universal human speaking average. All normalization is relative to this baseline.

### 14.2 Normalization strategy

**What the baseline normalization does:**
Normalizes participant features relative to the baseline recordings' distribution.
A participant with a naturally lower voice than the baseline speaker will show
a negative F0 z-score even when delivering effectively.

**What the baseline normalization does NOT do:**
It does not perform speaker adaptation or speaker embedding. It does not "correct"
for a participant's habitual pitch range against a gender-typical norm.

**Limitation (explicitly documented):**
If the participant's habitual pitch or energy range is far outside the baseline
recording(s), the normalization will report apparent deviations even for correct delivery.
This is a known limitation of single- or few-reference systems.
It is mitigated by:
- Using multiple baseline recordings from different speakers (multi-reference, P1)
- Wider deviation thresholds that require larger z-scores before flagging flaws
- Reliability scores that reflect uncertainty

### 14.3 Normalization formula

For each feature `x` with baseline `mean_x` and `std_x`:
```
z(t) = (x_participant(t) - mean_x) / std_x
```

Baseline is z=0. Deviations are expressed in standard deviations.
Contrastive delta is the participant's z-score (since baseline is zero).

For pitch: computed only on voiced frames (voiced_prob >= `F0_VOICED_PROB_THRESHOLD`).

### 14.4 Optional participant calibration (P1)

A short neutral segment of the participant's speech (before or after the target passage)
can be used to estimate the participant's habitual F0 median and energy median.

If available:
```
participant_f0_offset = participant_f0_median - baseline_f0_median
participant_energy_offset = participant_energy_median - baseline_energy_median

z_f0_adjusted(t) = (f0_participant(t) - participant_f0_offset - baseline_f0_mean)
                   / baseline_f0_std
```

This is P1 and optional. The API accepts `speaker_calibration_audio` as an optional
additional upload. If absent, standard normalization (P0) is used.

### 14.5 BaselineProvider abstraction

All pipeline stages that need baseline statistics call:
```python
baseline_stats: BaselineStats = BaselineProvider.get(passage_id)
```

The `BaselineProvider` returns a `BaselineStats` object regardless of whether
one or multiple baseline recordings contributed to it.
The rest of the pipeline never knows how many recordings were pooled.

**P0:** Acceptable to build `BaselineStats` from a single recording.
**P1:** Build `BaselineStats` from all effective baseline recordings for the passage.

Baseline statistics are precomputed by `scripts/dataset/build_baseline_stats.py`
and stored as JSON in `data/processed/`. They are not recomputed on every request.

---

## 15. Normalization Architecture

Normalization is owned by `services/grounding/` (first stage).
It transforms `FeatureBundle` + `BaselineStats` into `NormalizedFeatureBundle`.

```
for each feature timeline:
  z_values = (participant_values - baseline_mean) / baseline_std
```

Special cases:
- F0: only voiced frames are z-scored; unvoiced frames remain NaN in `f0_z`
- Pauses: compared event-by-event to type-specific baseline (within_phrase vs. cross_sentence)
- Speech rate: each rolling-window value z-scored against baseline rate stats

---

## 16. Contrastive Analysis

Contrastive comparison is also owned by `services/grounding/` (second stage).
After normalization, baseline is z=0 for all features.
The participant's z-score is directly the deviation from baseline.

**Frame-level (pitch, energy, clarity):**
```
delta(t) = z_participant(t)    # directly equals deviation from baseline mean
```

**Window-level (speech rate):**
```
delta_rate(w) = rate_z(w)      # z-score of rolling-window WPM
```

**Event-level (pauses):**
```
delta_pause(e) = (pause.duration_s - baseline_mean_for_type) / baseline_std_for_type
```

**Segment-level (MFCC, P1):**
```
delta_mfcc(word_i) = cosine_distance(participant_mfcc_mean[i], baseline_mfcc_mean[i])
```

---

## 17. Temporal Grounding

Temporal grounding is the core differentiator of this system.
Owned by `services/grounding/` (stages 3–9 of the grounding service).

### Step-by-step pipeline

```
Raw contrastive signal
  -> [1] Candidate window generation (threshold on delta)
  -> [2] Minimum duration filter
  -> [3] Window merging
  -> [4] Smoothing (P1: median filter)
  -> [5] Hysteresis (P1)
  -> [6] Boundary refinement (P1: snap to word boundaries)
  -> [7] Evidence extraction
  -> Final GroundedFlaw[]
```

**P0 minimum:** Steps 1, 2, 3, 7 are sufficient for a working system.
Steps 4, 5, 6 are P1 quality improvements.

### Step 1: Candidate generation

Detection rules per flaw type:

| Flaw Type | Feature | Rule | Priority |
|---|---|---|---|
| Too Fast | rate_z | `rate_z > Z_RATE_FAST` for `>= MIN_DURATION_S` | P0 |
| Too Slow | rate_z | `rate_z < -Z_RATE_SLOW` for `>= MIN_DURATION_S` | P0 |
| Excessive Pause | pause_z by type | `pause_z > Z_PAUSE_EXCESS` | P0 |
| Flat Pitch | f0_std_z (per segment) | `f0_std_z < -Z_FLAT` in voiced segment `>= MIN_DURATION_S` | P0 |
| Low Energy | energy_z | `energy_z < -Z_ENERGY` for `>= MIN_DURATION_S` | P0 |
| High Energy | energy_z | `energy_z > Z_ENERGY` for `>= MIN_DURATION_S` | P0 |
| Pitch Instability | f0_var_z (per segment) | `f0_var_z > Z_INSTAB` in segment `>= MIN_DURATION_S` | P1 |
| Reduced Clarity | clarity_z | `clarity_z < -Z_CLARITY` for `>= MIN_DURATION_S` | P1 |

All Z thresholds and MIN_DURATION_S values are configurable constants in `config.py`.
Initial values are PROPOSED (see §31). They must be calibrated on the dev split.

### Step 2: Minimum duration filter

Discard any candidate window where `(end_s - start_s) < MIN_FLAW_DURATION_S`.
Proposed initial value: `MIN_FLAW_DURATION_S = 0.5` (configurable per flaw type).

### Step 3: Window merging

For each flaw type, merge any two windows of the same type where the gap between them
is < `MERGE_GAP_S` (config, proposed 0.5 s).

### Step 4: Smoothing (P1)

Before thresholding, apply a median filter to the contrastive signal:
- Kernel size: `SMOOTHING_FRAMES` (config, proposed 3)
- Applied per feature independently
- Reduces single-frame spike false positives

### Step 5: Hysteresis (P1)

After smoothing, use upper/lower threshold for state-machine flaw detection:
- Enter FLAW state: signal crosses `UPPER_THRESHOLD = Z_THRESHOLD`
- Exit FLAW state: signal drops below `LOWER_THRESHOLD = Z_THRESHOLD * HYSTERESIS_RATIO`
- `HYSTERESIS_RATIO` (config, proposed 0.75)
- Prevents rapid on/off toggling during borderline signals

### Step 6: Boundary refinement (P1)

Snap flaw start and end to the nearest word boundary in `AlignedTranscript`:
- Maximum snap distance: `MAX_SNAP_S` (config, proposed 0.3 s)
- If no word boundary within `MAX_SNAP_S`, leave boundary unchanged
- Snap direction: nearest word boundary regardless of direction

### Step 7: Evidence extraction

For each final flaw window, extract and attach to `GroundedFlaw.evidence`:
- All feature-specific evidence fields (see §13 per feature)
- `window_duration_s`
- `word_count_in_window` (for rate-based flaws)

**Rule:** Evidence object must be fully populated before the flaw is returned.
No downstream service may add evidence fields. No LLM may add evidence fields.

---

## 18. Severity

Severity is a deterministic value in [0.0, 1.0] per `GroundedFlaw`.

**Formula (PROPOSED — two options, team must select before TASK-052):**

**Option A — Linear product (simpler, preferred for P0):**
```
magnitude_component = clip((mean_z - Z_MIN) / (Z_SEVERE - Z_MIN), 0.0, 1.0)
duration_component  = clip(duration_s / DURATION_SEVERE, 0.0, 1.0)
severity            = magnitude_component * duration_component
```

**Option B — Sigmoid (smoother curve):**
```
magnitude_score = |peak_z| / Z_SEVERE
duration_score  = clip(duration_s / DURATION_SEVERE, 0.0, 1.0)
raw             = W_MAGNITUDE * magnitude_score + W_DURATION * duration_score
severity        = 1 / (1 + exp(-(raw - SIGMOID_BIAS)))
```

Constants (all configurable in `config.py`, all PROPOSED values):
- `Z_MIN = 1.0` (below this z-score, no flaw is detected)
- `Z_SEVERE = 4.0` (at this z-score, maximum magnitude severity)
- `DURATION_SEVERE = 5.0` (at this duration, maximum duration severity)
- Option B: `W_MAGNITUDE = 0.6`, `W_DURATION = 0.4`, `SIGMOID_BIAS = 0.0`

Same formula applied to all flaw types. Per-type tuning is possible via per-type
constant overrides in config if needed after calibration.

---

## 19. Reliability

Reliability is a deterministic value in [0.0, 1.0] per `GroundedFlaw`.
It represents confidence in the detection, not the severity.

**STATUS: P1 — at P0, reliability defaults to 1.0 for all flaws.**

**P1 formula:**
```
alignment_conf  = mean(word.confidence for words in flaw window)
feature_conf    = feature-specific (see below)
signal_quality  = clip((mean_energy_db - MIN_RELIABLE_DB) / ENERGY_RANGE_DB, 0, 1)
duration_factor = clip(duration_s / MIN_RELIABLE_DURATION_S, 0, 1)

reliability = (alignment_conf * feature_conf * signal_quality * duration_factor) ** 0.25
```

Feature-specific confidence:
- Pitch flaws: mean PYIN voiced probability in window
- Energy flaws: always 1.0 (energy measurement is direct)
- Rate flaws: `min(word_count_in_window / MIN_WORDS_FOR_FULL_CONF, 1.0)`
- Pause flaws: 1.0 if `detection_source == "both"`, 0.75 if single source

Flaws with `reliability < RELIABILITY_THRESHOLD` (config, proposed 0.4):
- Included in response
- `low_confidence = true`
- Penalty in scoring scaled by `reliability` (not full penalty)

---

## 20. Deterministic Scoring

Scoring is owned exclusively by `services/scoring/`. It is deterministic.

### Per-feature sub-score

```
sub_score = max(0.0, 100.0 - total_penalty)

For each flaw of this feature type:
  flaw_penalty = BASE_PENALTY * severity * duration_weight * reliability

  duration_weight = clip(flaw.duration_s / DURATION_NORM_S, 0.0, 1.0)
```

Constants (all configurable, all PROPOSED values):
- `BASE_PENALTY = 30.0` — maximum penalty for a single fully severe flaw
- `DURATION_NORM_S = 4.0` — duration that counts as "full weight"

### Composite score

```
composite = sum(sub_score[feature] * weight[feature] for feature in features)
```

**Proposed initial weights (PROPOSED — must be calibrated on dev set before freezing):**

| Feature | P0 Weight | Rationale |
|---|---|---|
| speech_rate | 0.30 | Primary delivery dimension |
| pitch | 0.25 | Monotone is clearly perceptible |
| pauses | 0.25 | Directly affects engagement |
| energy | 0.20 | Clearly perceptible |
| mfcc | 0.00 | P1 — excluded from P0 composite |
| clarity | 0.00 | P1 — excluded from P0 composite |

P0 weights sum to 1.0 across P0 features.
When P1 features are activated, weights are rebalanced via config.

**Weight lifecycle:**
1. Initial configuration: above values (PROPOSED)
2. After dev-set calibration: weights adjusted
3. Before test evaluation: weights frozen in `config_version` bump
4. Test evaluation: weights unchanged

Weights live in `config.py` and are included in the cache key via `config_version`.

### Scoring version

Every `ScoredResult` includes `scoring_version` (same as `config_version`).
Scores computed under different `config_version` are not directly comparable.

---

## 21. Evidence Model

Every `GroundedFlaw` must carry a fully populated `evidence` dict before it is
returned by `services/grounding/`. This is a hard invariant.

The `services/explanation/` service receives the evidence as a read-only input.
It may not add, modify, or remove any field in `evidence`.

**Rules:**
- All numerical values in `evidence` originate from the analytical pipeline
- All string values in `evidence` are deterministic descriptions (flaw type, boundary type, etc.)
- `explanation` and `recommendation` are the only fields produced by LLM or template
- The presence of `explanation` is not required for the evidence to be valid

**Minimum required evidence fields per flaw type:**

| Flaw Type | Required Evidence Fields |
|---|---|
| too_fast | rate_participant_wpm, rate_baseline_mean_wpm, rate_baseline_std_wpm, rate_delta_wpm, rate_delta_pct, rate_z_score, peak_z_score, window_duration_s, word_count_in_window |
| too_slow | (same as too_fast) |
| excessive_pause | pause_duration_s, pause_baseline_mean_s, pause_baseline_std_s, pause_delta_s, pause_z_score, boundary_type, detection_source |
| flat_pitch | f0_std_hz_in_window, f0_std_baseline_hz, f0_std_z, f0_voiced_fraction, window_duration_s |
| low_energy | energy_mean_db, energy_baseline_mean_db, energy_baseline_std_db, energy_delta_db, energy_z_score, window_duration_s |
| high_energy | (same fields as low_energy) |
| pitch_instability (P1) | f0_var_hz_in_window, f0_var_baseline_hz, f0_var_z, window_duration_s |
| reduced_clarity (P1) | hf_ratio_mean, hf_ratio_baseline_mean, hf_ratio_z, window_duration_s |

---

## 22. Explanation and LLM Boundary

### Permitted LLM operations

| Input to LLM | Output |
|---|---|
| Pre-computed `evidence` dict | Natural language explanation of the flaw |
| `flaw_type` + `evidence` + `severity` | Actionable coaching recommendation |
| All flaws (structured) | Optional overall delivery summary |

### Prohibited LLM operations

The LLM must NEVER produce or invent:
- Any timestamp (`start_s`, `end_s`)
- Any numerical value in `evidence`
- `severity`
- `reliability`
- Any feature sub-score or composite score
- Whether a flaw exists (flaw existence is decided by the grounding pipeline)

### Implementation guard

1. `ScoredResult` is fully populated (all numbers present)
2. Explanation service sends structured prompt with evidence dict (no blank fields)
3. LLM returns text
4. Only string fields (`explanation`, `recommendation`) are extracted from LLM output
5. Any numerical content in LLM output is silently ignored
6. A post-call validation asserts all evidence fields in response match `ScoredResult`

### Template fallback (always implemented)

Template-based explanations must be implemented independently of any LLM.
The system must be fully functional with `EXPLANATION_PROVIDER=template`.

Template format per flaw type (example):
```
too_fast:
  "Between {start_s:.1f}–{end_s:.1f} s, speech rate was {rate_delta_pct:.1f}%
  above the baseline average ({rate_participant_wpm:.0f} vs.
  {rate_baseline_mean_wpm:.0f} WPM, z = {rate_z_score:.2f})."
```

### LLM provider selection

Configurable via `EXPLANATION_PROVIDER` environment variable:
- `template` — template only (deterministic, no API key needed)
- `gemini` — Google Gemini API (requires `GEMINI_API_KEY`)

No other providers for P0. Additional providers are P2.

---

## 23. API Architecture

### Endpoints

```
POST /api/v1/analyze
  Request:  multipart/form-data
  Response: ExplanationResult JSON (sync for short audio; see below)
  Errors:   400 (invalid input), 404 (baseline not found), 422 (validation), 500

GET /api/v1/health
  Response: { "status": "ok", "config_version": "...", "pipeline_version": "..." }

GET /api/v1/result/{analysis_id}
  Response: ExplanationResult JSON if cached, 404 if not found

GET /api/v1/status/{analysis_id}
  Response: { "status": "done" | "not_found" }
```

### Synchronous vs asynchronous

**P0 default: synchronous.**

For demo audio (< 60 seconds), synchronous processing is acceptable.
The POST request blocks until analysis is complete and returns the full result.

If processing takes > 30 seconds on the demo machine:
- Upgrade path: add a task ID to the POST response, add a poll endpoint
- Do NOT introduce Celery or Redis for P0
- A simple in-process background task with FastAPI's `BackgroundTasks` is the
  recommended upgrade path if needed

Decision: measure actual processing time on Day 1 (Whisper speed benchmark, see §31).

### Request validation

- Audio format: check MIME type and file extension (WAV or MP3)
- Audio size: reject if > `MAX_UPLOAD_BYTES`
- Audio duration: reject if > `MAX_DURATION_S` (checked after preprocessing)
- `baseline_id`: verify existence in baseline stats directory
- `config_version`: reject if mismatch with server config (optional for P0)

### Error format

```json
{
  "error": "VALIDATION_ERROR | BASELINE_NOT_FOUND | PROCESSING_ERROR | ...",
  "detail": "human-readable description",
  "analysis_id": null
}
```

### Result persistence

Analysis results are stored in the file-based cache (see §7.10).
`GET /api/v1/result/{analysis_id}` reads from this cache.
Results persist across server restarts.

---

## 24. Dataset Architecture

### Dataset directory structure

```
data/
  raw/                          — original audio files (WAV preferred)
  processed/
    alignments/                 — per-recording alignment JSON files
    baseline_stats/             — precomputed BaselineStats JSON per passage
    cache/                      — analysis result cache
  metadata/
    manifest.json               — canonical dataset manifest
    speakers.json               — speaker metadata
    passages.json               — passage text and metadata
  annotations/                  — flaw annotations per flawed recording
```

### Recording categories

| Category | Description | Evaluation role |
|---|---|---|
| `baseline_effective` | Human-delivered effective speech | Source of baseline statistics |
| `flawed_human_controlled` | Human-performed specific delivery flaw | Primary detection ground truth |
| `flawed_synthetic` | Speed/pitch-shifted variants | Supplementary, not primary |
| `clean_control` | Normal speech, no introduced flaws | False-positive measurement |

Human-controlled flawed recordings are the primary source for evaluation.
Synthetic flaws are supplementary and labeled as such in the manifest.

### Recording metadata schema

Each recording is one entry in `manifest.json`:

```json
{
  "recording_id":       "rec_p001_spk02_baseline_01",
  "passage_id":         "p001",
  "speaker_id":         "spk_02",
  "category":           "baseline_effective",
  "flaw_category":      null,
  "flaw_start_s":       null,
  "flaw_end_s":         null,
  "flaw_severity_label": null,
  "transcript":         "...",
  "audio_file":         "data/raw/rec_p001_spk02_baseline_01.wav",
  "alignment_file":     "data/processed/alignments/rec_p001_spk02_baseline_01.json",
  "sha256_audio":       "...",
  "sha256_alignment":   "...",
  "sample_rate_hz":     44100,
  "duration_s":         47.3,
  "recording_conditions": "quiet_room",
  "microphone":         "headset_usb_logitech",
  "split":              "dev",
  "dataset_version":    "1.0.0",
  "created_at":         "2026-10-07"
}
```

### Split assignment rule (enforced, non-negotiable)

**No speaker may appear in both `dev` and `test` splits.**

- `dev` — used for threshold calibration and feature validation
- `test` — used exactly once for final evaluation; never used for tuning

If only 2-3 speakers are available, reserve at least 1 speaker for `test`.

### Dataset construction procedure

1. Write passage texts and commit to `data/metadata/passages.json`
2. Record baseline effective speeches
3. Record human-controlled flaw variants (prioritize P0 flaw types first)
4. Generate synthetic variants if time permits
5. Record clean control recordings
6. Compute SHA-256 for all audio files
7. Run alignment on all recordings; store in `data/processed/alignments/`
8. Compute SHA-256 for all alignment files
9. Build `manifest.json`
10. Run `scripts/dataset/validate_dataset.py` — verify all checksums
11. Run `scripts/dataset/build_baseline_stats.py` — build `BaselineStats` per passage
12. Assign splits (speaker-separated)
13. Tag `dataset_version` in manifest

### Dataset version

`manifest.json` contains a `"dataset_version"` field.
Incrementing dataset version must trigger cache invalidation
(because `baseline_sha256` will change).

---

## 25. Evaluation Architecture

### 25.1 Calibration vs. evaluation

| Stage | Data | Purpose | Rules |
|---|---|---|---|
| Calibration | dev split | Tune thresholds, weights, window sizes | May inspect dev results freely |
| Evaluation | test split | Final reported metrics | Touch once; no tuning afterward |

No threshold or weight may be adjusted after inspecting test results.

### 25.2 Feature-level evaluation

For each feature (F0, energy, rate):
- Mean z-score deviation for known-flaw recordings vs. known-good recordings
- Distribution overlap plot (not a pass/fail metric; informational for calibration)

### 25.3 Event-level evaluation

**True Positive definition:** Predicted flaw window overlaps >= 50% of annotated flaw window.

Metrics per flaw category:
- Precision = TP / (TP + FP)
- Recall = TP / (TP + FN)
- F1 = harmonic mean of Precision and Recall
- Mean temporal boundary error (MAE on start_s and end_s)

**Target (PROPOSED, not calibrated):** F1 > 0.65 per P0 flaw category on held-out speakers.
This target is aspirational for an 8-day system. It is not a hard block on submission.

### 25.4 System-level evaluation

| Test | Method | Proposed Criterion |
|---|---|---|
| False positives on clean speech | clean_control recordings | < 10% of clean recordings trigger any flaw |
| Score stability (gain change) | ±6 dB applied | Score change < 5 points |
| Resampling | 44100→22050→16000 Hz chain | Score change < 2 points |
| Compression | MP3 128 kbps encode/decode | F1 drop < 5% |
| Background noise | Pink noise SNR 20 dB | F1 drop < 15% |
| Repeated-run determinism | Same input × 3 runs | Scores must be bit-identical |
| Speaker variation | Two different effective baseline speakers | Both score > 75 |
| Rate stress | Recordings at 80%, 120%, 150% baseline WPM | Detection recall > 80% |

All criteria are PROPOSED targets. None have been experimentally validated.
They represent the intended behavior, not confirmed results.

### 25.5 Robustness priority

P0: repeated-run determinism, false positive on clean speech
P1: gain, resampling, noise, microphone variation
P2: compression, rate stress (if time permits)

---

## 26. Reproducibility

### 26.1 What must be reproducible

Same input audio + same baseline + same configuration = same output, always.

### 26.2 Configuration versioning

- `CONFIG_VERSION` in `core/config.py` — incremented on any analytical parameter change
- `PIPELINE_VERSION` — incremented on structural pipeline changes
- Both included in every API response
- Both included in cache key

### 26.3 Input provenance

Recorded in every response:
- `participant_audio_sha256` — SHA-256 of preprocessed audio bytes
- `baseline_id` — dataset baseline identifier
- `baseline_sha256` — SHA-256 of baseline stats JSON file
- `alignment_method` — which aligner was used
- `whisper_model` — model name

### 26.4 Cache key

```
cache_key = sha256(
  participant_audio_sha256 +
  baseline_id +
  baseline_sha256 +
  config_version +
  pipeline_version
)
```

Any change to configuration increments `config_version` → new cache key → cache miss → recompute.
This guarantees the cache can never return a stale result silently.

### 26.5 Library version pinning

All analytical libraries pinned to exact versions in `requirements.txt`.
Different library versions may produce different floating-point results.

### 26.6 Cross-machine reproducibility

**Guaranteed:** Feature extraction from identical preprocessed audio bytes and identical
library versions running on the same or compatible hardware.

**Not fully guaranteed:** Whisper transcription may vary slightly across GPU/CPU hardware
due to floating-point implementation differences. Alignment timestamps may differ by
< 50 ms cross-machine.

**Mitigation:** For official evaluation, run on a single machine.
Document cross-machine tolerance as < 50 ms alignment variation.

---

## 27. Security

Appropriate to hackathon scope. No production security hardening is required.

- API keys must NEVER be committed to the repository
- `.env` file is gitignored; `.env.example` is committed with placeholder values
- Audio uploads validated (format, size, duration) before processing
- Upload directory must be protected against path traversal:
  - Use `os.path.basename` on any user-supplied filename
  - Do not trust filenames from form uploads
- Temporary files cleaned up after each request
- Maximum upload size enforced before reading file bytes (`MAX_UPLOAD_BYTES`)
- No audio recordings committed to the repository (except explicitly designated dataset files)
- Audio files in `data/` are not served by the API; they are processed server-side only

---

## 28. Frontend / Backend Boundary

### Frontend may

- Upload participant audio and select a baseline
- Display processing progress
- Show the composite score and per-feature sub-scores (received from backend)
- Show the temporal flaw timeline with backend-computed timestamps
- Show feature charts (F0, energy, rate timelines received from backend)
- Show per-flaw evidence panels (all values received from backend)
- Control audio playback with flaw markers at backend-computed timestamps
- Display explanations and recommendations (received from backend)
- Jump to a specific timestamp when a flaw is clicked

### Frontend must never

- Compute pitch, MFCC, energy, speech rate, pause detection, clarity
- Detect flaws or generate flaw candidates
- Compute severity, reliability, or scores
- Modify any evidence field
- Accept LLM responses and display them as evidence
- Make any analytical decision about the recording

Frontend receives `ExplanationResult` from the backend and renders it.
It has no other source of analytical truth.

---

## 29. P0 / P1 / P2 Scope

### P0 — Core demo (must work before anything else)

**Flaw types:** Too Fast, Too Slow, Excessive Pause, Flat Pitch, Low Energy, High Energy

**Backend P0:**
- Audio preprocessing (resample, mono, normalize, SHA-256)
- Transcription (Whisper base, or manual transcript)
- Alignment (WhisperX primary, whisper_word_timestamps fallback)
- F0 extraction (librosa.pyin)
- Energy extraction (librosa.feature.rms → dBFS)
- Speech rate (rolling-window WPM)
- Pause detection (VAD + alignment gap, either-or combination)
- Baseline normalization (z-score, single reference acceptable)
- Contrastive comparison
- Temporal flaw detection for all 6 P0 flaw types
- Minimum duration filter + window merging
- Evidence extraction (all required fields per flaw type)
- Linear severity formula
- Scoring: penalty-based sub-scores + P0-weighted composite
- Template-based explanation
- FastAPI skeleton + all endpoints
- Pydantic schemas for all contracts
- Config versioning (config_version in every response)
- Input SHA-256
- File-based cache
- Repeated-run determinism test (manual)

**Frontend P0:**
- Audio upload UI
- Baseline selection
- Overall score card
- Temporal flaw timeline
- Flaw detail panel with evidence
- Audio playback with flaw markers

**Dataset P0:**
- At least 1 passage with transcript
- At least 1 baseline effective recording per passage
- At least 1 labeled flawed recording per P0 flaw type (for verification)
- SHA-256 checksums computed

### P1 — Quality (after P0 is working end-to-end)

**New flaw types:** Pitch Instability, Reduced Clarity

**Backend P1:**
- Multi-reference baseline (pooled stats from multiple recordings)
- MFCC word-segment cosine distance
- Clarity proxy (HF ratio + MFCC distance)
- Smoothing (median filter on contrastive signal)
- Hysteresis (upper/lower threshold)
- Boundary refinement (snap to word boundaries)
- Reliability per flaw
- LLM explanation (Gemini API)
- Optional participant calibration segment
- Alignment quality validation
- Dataset validation script
- Build-baseline-stats script
- Held-out evaluation script

**Frontend P1:**
- Feature timelines visualization (F0, energy, rate charts)
- Reliability indicator per flaw
- Low-confidence flaw highlighting

**Dataset P1:**
- Multiple baseline recordings per passage
- Controlled recordings for all 8 flaw types
- Speaker-separated test split
- Manifest with full SHA-256 checksums

### P2 — Polish (only after P0 + P1 are stable)

- Docker Compose
- PDF export
- Interactive transcript (click word → flaw)
- Additional LLM providers
- Advanced sentence-boundary pause analysis
- Demo video production

---

## 30. Architecture Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| WhisperX install fails | Medium | High | Fallback to whisper_word_timestamps; interface preserved |
| Whisper CPU too slow for demo | High | Medium | Precompute demo results; use base model |
| Baseline-relative normalization fails for atypical participant | Medium | Medium | Lower thresholds; document limitation; multi-reference at P1 |
| High false positive rate from natural variation | High | High | Calibrate conservatively; minimum duration filter |
| Clarity proxy unreliable | High | Medium | P1 placement; weight = 0.0 at P0; configurable to 0 |
| API contract drift between frontend and backend | Medium | High | Define Pydantic schemas before frontend begins |
| Scoring uncalibrated before demo | Medium | High | Calibrate on dev set by Day 5; test set untouched until then |
| Dataset too small for robust evaluation | High | Medium | Record P0 flaws first; synthetic only supplementary |
| LLM unavailable during demo | Medium | Low | Template fallback always tested and working |
| Pause detection fragmentation | Medium | Medium | Either-or combination logic (not AND) reduces brittleness |
| Speaker variation exceeds normalization range | Medium | Medium | Multiple baseline speakers; document limitation |

---

## 31. Open Technical Experiments

These experiments MUST be run before the corresponding tasks begin.
Results must not be fabricated. If an experiment has not been run, the choice remains PROPOSED.

| Experiment | Purpose | Blocking | When |
|---|---|---|---|
| Whisper speed benchmark (base model, 60s audio, CPU) | Decide sync vs async API | TASK-010 | Day 1 |
| WhisperX install test on all team machines | Confirm primary alignment method | TASK-022 | Day 1 |
| Alignment quality test (2 baseline recordings, manual annotation) | Confirm WhisperX or fall to fallback | TASK-022 | Day 1-2 |
| Speech rate window size sweep (W=5s, 8s, 10s on controlled recordings) | Select window size | TASK-033 | Day 2-3 |
| Baseline normalization speaker test (2 effective speakers same passage) | Validate normalization handles variation | TASK-041 | Day 2-3 |
| Threshold sweep on dev set (Z from 1.5 to 3.0) | Calibrate detection thresholds | TASK-043 | Day 3-5 |
| Severity formula sanity check (mild vs severe flaw inputs) | Select Option A or B | TASK-052 | Day 3 |
| False positive rate on clean speech (before threshold freeze) | Validate threshold conservatism | TASK-050 | Day 4-5 |
| LLM guardrail integration test | Verify no numerical LLM output reaches response | TASK-072 | Day 4 |

---

## 32. Architecture Change Procedure

1. Any agent or team member identifying a needed architectural change must STOP and report.
2. Report must include: current situation, options, recommendation, trade-offs, affected files.
3. The team leader approves or rejects the change.
4. If approved: update this file (ARCHITECTURE.md), record in DECISIONS.md, update PROJECT_STATE.md.
5. If the change affects the API contract: update TASKS.md and coordinate with frontend.
6. No agent may implement a change before it is approved and documented here.
7. AI agents must never silently modify: canonical pipeline, API contracts, scoring methodology,
   flaw vocabulary, or dataset schema.

---

## Module Ownership Summary

| Concern | Canonical Owner |
|---|---|
| All analytical feature extraction | `backend/app/services/features/` |
| Normalization | `backend/app/services/grounding/` |
| Contrastive comparison | `backend/app/services/grounding/` |
| Flaw detection | `backend/app/services/grounding/` |
| Severity | `backend/app/services/grounding/` |
| Reliability | `backend/app/services/grounding/` |
| Scoring | `backend/app/services/scoring/` |
| Explanation / recommendations | `backend/app/services/explanation/` |
| API contracts (Pydantic) | `backend/app/schemas/` |
| All analytical configuration | `backend/app/core/config.py` |
| BaselineStats (computation) | `scripts/dataset/build_baseline_stats.py` |
| BaselineStats (serving) | `backend/app/core/` (BaselineProvider) |
| Cache | `backend/app/core/cache.py` |
| Frontend analytical truth | NONE — frontend only renders |
