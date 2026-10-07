# Architecture Decisions
## Track C — Contrastive Speech Analytics & Temporal Flaw Grounding

This file records important decisions that affect the structure,
methodology, reproducibility, or scope of the project.

AI agents may propose decisions.

Only the team leader/team may approve them.

---

## STATUS DEFINITIONS

ACCEPTED  — Approved by team; agents must follow this decision.
PROPOSED  — Recommended by investigation; requires team approval before implementation.
REJECTED  — Considered and rejected; do not reopen without new evidence.
SUPERSEDED — Replaced by a newer decision.

---

## ACCEPTED DECISIONS (from project initialization)

---

## DEC-001 — Single Repository

Status: ACCEPTED

Decision:
Use one GitHub repository for the entire project.

Reason:
All three teammates and all AI agents need one shared source of truth.

---

## DEC-002 — Frontend Stack

Status: ACCEPTED

Decision:
React + Vite + TypeScript.

Reason:
Suitable for rapid development of an interactive dashboard.

---

## DEC-003 — Backend Stack

Status: ACCEPTED

Decision:
Python + FastAPI.

Reason:
The project contains a Python-heavy audio/speech analysis pipeline
and requires a lightweight API layer.

---

## DEC-004 — Backend-Owned Analysis

Status: ACCEPTED

Decision:
All analytical calculations are owned exclusively by the backend.
The frontend renders backend-produced results only.
The frontend must never calculate pitch, MFCC, speech rate, pauses,
flaw severity, or scores.

Reason:
Prevents duplicated logic and keeps the frontend focused on
visualization and interaction.

---

## DEC-005 — Deterministic Scoring

Status: ACCEPTED

Decision:
Numerical scoring is deterministic.
Same input + same configuration must produce the same result.
LLMs are not the source of numerical truth.
LLMs may only produce natural language from pre-computed evidence.

Reason:
The project must provide reproducible, evidence-grounded evaluation results.

---

## DEC-006 — Task-Based Team Workflow

Status: ACCEPTED

Decision:
The team will not use permanent backend/frontend/ML silos.
Instead, work is organized as small tasks with temporary ownership
and peer review.

Reason:
The system is tightly coupled and the team has three members.

---

## DEC-007 — Antigravity as Coding Environment

Status: ACCEPTED

Decision:
All teammates may use Antigravity as the primary coding environment.
Model choice depends on task complexity.

Reason:
The repository remains identical even when different AI models are used.

---

## DECISIONS FROM ARCHITECTURE REVIEW (2026-10-07)

---

## DEC-008 — Canonical Pipeline

Status: ACCEPTED

Decision:
The canonical pipeline is:
Audio → Preprocessing → Transcription → Forced Alignment →
Feature Extraction → Baseline Normalization → Contrastive Comparison →
Temporal Flaw Detection → Severity Estimation → Deterministic Scoring →
Evidence-backed Explanation → API Response → Dashboard Visualization

This pipeline must not be silently replaced, reordered, or extended
without team approval and documentation in this file.

Reason:
Defined in AGENTS.md as the project's core design contract.

Approved by: Team (architecture review)
Date: 2026-10-07

---

## DEC-009 — Alignment Fallback Interface

Status: ACCEPTED

Decision:
The alignment service exposes a uniform `AlignedTranscript` interface
regardless of which alignment method is used.

Primary method (PROPOSED, install-dependent): WhisperX
Fallback method (accepted baseline): Whisper word_timestamps=True

The `alignment_method` field records which was used.
No downstream service branches on `alignment_method`.
The pipeline degrades gracefully if WhisperX cannot be installed.

Reason:
Eliminates the risk of two parallel analytical pipelines.
Guarantees that a working fallback always exists.

Alternatives considered:
- Separate pipelines for each aligner: rejected (duplicates logic, creates maintenance burden)
- Require WhisperX with no fallback: rejected (too brittle for hackathon)

Trade-offs:
- WhisperX produces more accurate word boundaries (~50–100 ms improvement)
- The fallback is less accurate but functionally complete
- Using the fallback degrades temporal boundary quality but not correctness

Impact:
- TASK-022 (Forced Alignment)
- All grounding code that uses AlignedTranscript

Approved by: Team (architecture review)
Date: 2026-10-07

---

## DEC-010 — Baseline Normalization Strategy

Status: ACCEPTED

Decision:
Normalization is baseline-relative z-score normalization, not
global human-average normalization.

Formula:
  z(t) = (x_participant(t) - baseline_mean) / baseline_std

Where baseline_mean and baseline_std come from the passage's baseline recordings.

For F0: computed on voiced frames only (PYIN voiced probability >= threshold).

Limitation (explicitly accepted):
This is NOT speaker adaptation. A participant with a habitually different
voice from the baseline speaker(s) will show systematic offsets.
This limitation is documented in ARCHITECTURE.md §14 and communicated to users.

Optional participant calibration (P1, not required for P0):
A short neutral participant segment can estimate habitual F0/energy offset.
This is a P1 feature that reduces the limitation but does not eliminate it.

Reason:
Speaker adaptation requires speaker embeddings (additional model, additional
complexity). Z-score normalization relative to the baseline is simple, deterministic,
and sufficient for the hackathon.

Impact:
- TASK-041 (Baseline Representation)
- TASK-030 (F0 Feature)
- TASK-032 (Energy Feature)

Approved by: Team (architecture review)
Date: 2026-10-07

---

## DEC-011 — Pause Detection Combination Logic

Status: ACCEPTED

Decision:
Pause detection uses two independent signals: energy VAD and alignment gaps.
Either signal alone is sufficient to produce a pause candidate.
The system does NOT require both signals to agree.
When both signals agree, `detection_source = "both"` and reliability is higher.
When only one signal detects a pause, `detection_source = "vad"` or `"alignment"`.

Pause candidates are classified by boundary type:
- `within_phrase`: compared against within-phrase baseline pause statistics
- `cross_sentence`: compared against cross-sentence baseline pause statistics

Reason:
The original proposal was ambiguous (requiring both signals to agree).
That approach is too brittle: VAD and alignment gaps are independent measurements
that each have value. Requiring agreement would cause many real pauses to be missed.

Impact:
- TASK-034 (Pause Detection)
- TASK-050 (Temporal Flaw Detection)

Approved by: Team (architecture review)
Date: 2026-10-07

---

## DEC-012 — Clarity as P1 Acoustic Proxy

Status: ACCEPTED

Decision:
Acoustic clarity measurement is P1 — it does not block the P0 demo.

At P0: clarity weight = 0.0. Clarity is not included in the composite score.
At P1: clarity proxy (HF energy ratio + MFCC word-segment distance) is activated.
       Its weight is configurable and initially proposed at 0.10.

Clarity is presented to users as an "acoustic clarity proxy", not as an
intelligibility score.

The weight of clarity in the composite score may be reduced to 0.0 via config
at any time without code changes if the metric proves unreliable.

Reason:
Reduced Clarity is the most uncertain feature. Its measurement is affected by
microphone, room, speaker characteristics, and recording quality, independent
of delivery quality. Allowing it to block P0 or dominate scoring would reduce
system credibility.

Impact:
- TASK-035 (Clarity Measure)
- TASK-060 (Feature Scoring)
- P0 flaw scope

Approved by: Team (architecture review)
Date: 2026-10-07

---

## DEC-013 — P0 Flaw Scope

Status: ACCEPTED

Decision:
P0 flaw detection covers exactly six flaw types:
  - Too Fast
  - Too Slow
  - Excessive Pause
  - Flat Pitch
  - Low Energy
  - High Energy

P1 flaw types (architecture fully defined, implementation deferred):
  - Pitch Instability
  - Reduced Clarity

All eight flaw types remain defined in the flaw vocabulary.
The interface supports all eight.
P1 types are simply not activated in the P0 scoring configuration.

Reason:
Implementing all eight types in P0 is an 8-day risk.
The six P0 types are the most acoustically direct and easiest to detect reliably.
Pitch Instability and Reduced Clarity require P1 enhancements (hysteresis, MFCC
distance) to be reliable.

Impact:
- TASK-050, TASK-052, TASK-060, TASK-062

Approved by: Team (architecture review)
Date: 2026-10-07

---

## DEC-014 — Scoring Architecture

Status: ACCEPTED

Decision:
Scoring uses a penalty-based formula:

  sub_score = max(0, 100 - total_penalty)
  flaw_penalty = BASE_PENALTY * severity * duration_weight * reliability
  composite_score = sum(sub_score[i] * weight[i])

All constants (BASE_PENALTY, weights, DURATION_NORM_S) live in config.py.
CONFIG_VERSION must be incremented when any scoring constant changes.
Score weights are configurable and must be calibrated on the dev split
before being frozen for test evaluation.

Weight lifecycle:
  1. Initial (PROPOSED) values coded in config.py
  2. Calibration on dev split → weights adjusted
  3. CONFIG_VERSION bumped → cache invalidated
  4. Test evaluation with frozen weights
  5. No tuning after test results are inspected

Reason:
Penalty-based scoring is transparent and deterministic.
The weight lifecycle ensures the test set is never used for tuning.

Impact:
- TASK-060, TASK-061, TASK-062, TASK-063

Approved by: Team (architecture review)
Date: 2026-10-07

---

## DEC-015 — BaselineProvider Abstraction

Status: ACCEPTED

Decision:
All pipeline stages that need baseline statistics call a single abstraction:
  BaselineStats = BaselineProvider.get(passage_id)

The rest of the pipeline does not know whether 1 or N baseline recordings
contributed to the BaselineStats object.

At P0: a single baseline recording per passage is acceptable.
At P1: multiple recordings are pooled to produce more robust statistics.

Reason:
This abstraction allows the multi-reference upgrade (P1) to happen without
changing any grounding, scoring, or explanation code.

Impact:
- TASK-040, TASK-041

Approved by: Team (architecture review)
Date: 2026-10-07

---

## DEC-016 — Synchronous API for P0

Status: ACCEPTED

Decision:
The POST /api/v1/analyze endpoint is synchronous at P0.
The request blocks until the full analysis is complete and returns the result.

Condition: acceptable if processing time on demo machine is < 30 seconds.

If the Whisper speed benchmark (Day 1) shows processing > 30 seconds:
  Upgrade path: return an analysis_id immediately, poll /api/v1/status/{id}
  Implementation: FastAPI BackgroundTasks (not Celery/Redis) for P0
  Celery/Redis is P2

Reason:
Synchronous is simpler and sufficient for short demo audio.
Introducing an async queue at P0 adds complexity that may not be needed.

Impact:
- TASK-010, TASK-012

Approved by: Team (architecture review)
Date: 2026-10-07

---

## DEC-017 — Speaker-Separated Dev/Test Split

Status: ACCEPTED

Decision:
No speaker may appear in both the dev and test dataset splits.
The test split is touched exactly once for final evaluation.
No threshold or weight may be adjusted after test results are inspected.

Reason:
Speaker-separated evaluation is the only way to measure genuine generalization.
Using the same speakers in dev and test would allow overfitting to their voices.

Impact:
- TASK-003, TASK-122

Approved by: Team (architecture review)
Date: 2026-10-07

---

## DEC-018 — Template Explanation Always Available

Status: ACCEPTED

Decision:
Template-based explanations must be implemented before or alongside
any LLM explanation integration.

The system must be fully functional with EXPLANATION_PROVIDER=template.

If the LLM fails or is unavailable:
  - Use template silently
  - Set explanation_method = "template" in the response
  - Do not fail the request

Reason:
LLM availability cannot be guaranteed during a live demo.
The template fallback ensures the demo works regardless of network or API status.

Impact:
- TASK-070, TASK-072

Approved by: Team (architecture review)
Date: 2026-10-07

---

## DEC-019 — Cache Key Includes Config Version

Status: ACCEPTED

Decision:
The deterministic cache key is:
  sha256(participant_audio_sha256 + baseline_id + baseline_sha256
         + config_version + pipeline_version)

Changing any analytical parameter in config.py must increment CONFIG_VERSION.
Incrementing CONFIG_VERSION invalidates all existing cached results.

Reason:
Without config version in the cache key, a stale cached result from an earlier
configuration could be returned after parameters are changed.

Impact:
- TASK-063, core/cache.py

Approved by: Team (architecture review)
Date: 2026-10-07

---

## DEC-020 — Speech Rate via Rolling Window

Status: ACCEPTED

Decision:
Speech rate is computed as a rolling-window WPM over the aligned transcript.
It is NOT computed as the inverse of individual word duration.

Formula:
  rate_wpm(window) = (n_words_in_window / effective_duration_s) * 60
  effective_duration_s = last_word.end_s - first_word.start_s (in window)

Window size and step are configurable (proposed W=8s, step=4s).
Windows with fewer than MIN_WORDS (configurable, proposed 5) are skipped.

Reason:
Per-word duration is noisy and produces fragmented, unstable estimates.
Rolling-window WPM is more stable and provides a meaningful rate timeline.

Alternatives: phrase-level segmentation (supplementary, not primary)

Impact:
- TASK-033

Approved by: Team (architecture review)
Date: 2026-10-07

---

## DEC-021 — LLM Boundary: Evidence Before Explanation

Status: ACCEPTED

Decision:
The evidence object of every flaw must be fully populated with deterministic
numerical values before the explanation service is called.

The explanation service may only produce text (explanation, recommendation).
It may not modify, add, or invent any numerical field.

Any numerical content in LLM output is silently ignored.
A post-call validation step asserts evidence fields match pre-computed values.

Reason:
Core analytical integrity principle. LLMs must not be the source of numerical truth.

Impact:
- TASK-070, TASK-072, backend/app/services/explanation/

Approved by: Team (architecture review)
Date: 2026-10-07

---

## DEC-022 — Human-Controlled Flaws Are Primary Evaluation Ground Truth

Status: ACCEPTED

Decision:
Human-performed controlled flaw recordings are the primary evaluation source.
Synthetic flaws (speed/pitch-shifted) are supplementary and labeled as such.
Evaluation metrics reported on synthetic flaws must be clearly distinguished
from metrics on human-controlled flaws.

Reason:
Synthetic flaws may not represent the full acoustic character of natural delivery flaws.
Human-controlled recordings provide more realistic evaluation targets.

Impact:
- TASK-003, TASK-122, evaluation strategy

Approved by: Team (architecture review)
Date: 2026-10-07

---

## PROPOSED DECISIONS (require team approval before implementation)

The following decisions are recommended by the architecture review but have NOT been
empirically validated. They must not be treated as accepted.

---

## DEC-P001 — Transcription Technology

Status: PROPOSED

Decision:
Use openai-whisper with model configurable via WHISPER_MODEL env var (default "base").

Alternatives:
- faster-whisper: faster CTranslate2 backend, same interface
- Cloud STT APIs: higher accuracy, but network-dependent and non-reproducible

Reason:
Free, offline, reproducible, no API key required.

Trade-offs:
- CPU inference is 2–3x real-time; may require async for long audio
- Model quality increases with size (base < small < medium < large)

Must be validated: install test on all team machines, speed benchmark on demo machine.

Approved by: Team — pending
Date: pending

---

## DEC-P002 — Primary Alignment Technology

Status: PROPOSED

Decision:
WhisperX (wav2vec2-based) as primary forced aligner.
Whisper word_timestamps=True as fallback (DEC-009 defines the interface).

Must be validated: install test on all machines before TASK-022 begins.
If install fails on demo machine, fallback is the P0 baseline.

Approved by: Team — pending
Date: pending

---

## DEC-P003 — Audio Preprocessing Specification

Status: PROPOSED

Decision:
Target sample rate: 16 000 Hz
Channels: 1 (mono)
Format: float32 PCM
Peak normalization: −3 dBFS
Silence trimming: energy VAD at −50 dBFS threshold
Libraries: librosa + soundfile (ffmpeg for MP3)

Must be validated: confirm librosa + soundfile install, confirm ffmpeg available.

Approved by: Team — pending
Date: pending

---

## DEC-P004 — Feature Extraction Libraries

Status: PROPOSED

Decision:
F0: librosa.pyin
MFCC: librosa.feature.mfcc (n_mfcc=13)
Energy: librosa.feature.rms
Rate: computed from AlignedTranscript (no external library)
Pause: librosa energy VAD + AlignedTranscript gaps

Approved by: Team — pending
Date: pending

---

## DEC-P005 — Initial Detection Thresholds

Status: PROPOSED

Decision:
Initial threshold starting points (must be calibrated on dev split):

Z_RATE_FAST / Z_RATE_SLOW = 2.0
Z_ENERGY = 2.0
Z_FLAT = 2.0 (on F0 std deviation within segment)
Z_PAUSE (within-phrase) = 2.0
Z_PAUSE (cross-sentence) = 2.5
MIN_FLAW_DURATION_S = 0.5
MERGE_GAP_S = 0.5

IMPORTANT: These are starting points only. They MUST be calibrated on the dev split
before being frozen. They must not be frozen by reading this document as if they
were empirically validated.

Approved by: Team — pending (calibration required)
Date: pending

---

## DEC-P006 — Severity Formula

Status: PROPOSED (team must select Option A or B before TASK-052)

Option A — Linear product (simpler, recommended for P0):
  magnitude = clip((mean_z - Z_MIN) / (Z_SEVERE - Z_MIN), 0, 1)
  duration  = clip(duration_s / DURATION_SEVERE, 0, 1)
  severity  = magnitude * duration

Option B — Sigmoid:
  raw = W_MAGNITUDE * (|peak_z| / Z_SEVERE) + W_DURATION * clip(duration_s / DURATION_SEVERE, 0, 1)
  severity = 1 / (1 + exp(-(raw - SIGMOID_BIAS)))

Constants (all configurable): Z_MIN=1.0, Z_SEVERE=4.0, DURATION_SEVERE=5.0

Recommendation: Option A for P0 (simpler, easier to reason about).

Approved by: Team — pending
Date: pending

---

## DEC-P007 — Initial Score Weights (P0)

Status: PROPOSED (must be calibrated on dev split before test evaluation)

P0 initial weights:
  speech_rate = 0.30
  pitch       = 0.25
  pauses      = 0.25
  energy      = 0.20
  mfcc        = 0.00  (P1)
  clarity     = 0.00  (P0 — P1 when activated)

These weights sum to 1.0 for P0 features.
They are INITIAL values only. Calibration on the dev split is required
before these weights are frozen for test evaluation.

Approved by: Team — pending (calibration required)
Date: pending

---

## DEC-P008 — LLM Provider

Status: PROPOSED

Decision:
EXPLANATION_PROVIDER=gemini (Google Gemini API, free tier)
with mandatory template fallback (DEC-018 is accepted).

Alternatives: OpenAI GPT-4o-mini, local Ollama (P2)

Requires: GEMINI_API_KEY in .env (not committed)

Approved by: Team — pending
Date: pending

---

## DEC-P009 — Frontend Libraries

Status: PROPOSED

Decision:
Charts: recharts
Audio playback/waveform: wavesurfer.js
HTTP client: axios
Styling: tailwindcss

Approved by: Team — pending
Date: pending

---

## UNRESOLVED DECISIONS

The following items from the original unresolved list are now either
accepted (above), proposed (above), or addressed by the architecture.

Items that remain requiring empirical investigation before any decision can be made:

1. Exact threshold values — must be calibrated on dev data (DEC-P005)
2. Exact score weights — must be calibrated on dev data (DEC-P007)
3. Severity formula choice (A vs B) — must be team-selected (DEC-P006)
4. WhisperX vs. fallback — depends on install success (DEC-P002)
5. Whisper model size — depends on speed benchmark (DEC-P001)

---

## DECISION FORMAT

When adding a major decision, use:

## DEC-XXX — <Decision Name>

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
<team leader/team> or "Team — pending"

Date:
<date>

---

# END
