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

## DECISIONS FROM IMPLEMENTATION (2026-10-09)

DEC-023 was approved explicitly by the team leader. DEC-024 to DEC-027 record conventions the coding agent
chose under the authority delegated by the team leader on 2026-10-09; they are ACCEPTED so that code and
documents agree, and the team leader may revise any of them (revising one means regenerating baseline
statistics or re-running detection, not a data migration).

---

## DEC-023 — Source-Time Provenance for Trimmed Audio

Status: ACCEPTED

Decision:
PreprocessedAudio records `trim_start_s` (offset of the retained audio within the pre-trim signal) and
`source_duration_s` (pre-trim duration). All internal analysis (transcription, alignment, features,
grounding) stays in processed-audio time. Conversion to source time happens exactly once, at final response
assembly, via `PreprocessedAudio.to_source_time()`. Trimming behavior, thresholds, `audio_array` and `sha256`
are unchanged.

Reason:
Trimming discarded the start offset, so timestamps could not be mapped onto the user's original recording.

Impact:
- TASK-013A (implemented); response assembly must expose the offset (API contract MINOR bump)
- Cache key (§26.4) must include `trim_start_s` or a source-audio hash: `sha256` covers only trimmed samples
- Amends DEC-P003 and ARCHITECTURE §9.1

Approved by: Team leader (explicit approval, 2026-10-09)
Date: 2026-10-09

---

## DEC-024 — Baseline Statistics Conventions

Status: ACCEPTED (agent decision under delegated authority; leader may revise)

Decision:
- Statistics are pooled across a passage's `baseline_effective` recordings (frames, windows and events
  pooled, not averaged per recording) and stored as one `BaselineStatsRecord` JSON per passage under
  `data/processed/baseline_stats/<passage_id>.json`; `BaselineProvider.get(passage_id)` serves it (DEC-015).
- F0 statistics use voiced frames only. Energy statistics use ACTIVE frames (energy_db >= the VAD threshold,
  -50 dBFS) by default so pauses do not inflate the spread of speaking level; `--energy-frames all` is
  available. The rule and threshold are stored in the file's `config_snapshot`.
- Standard deviation is the sample std (ddof=1); percentiles are linear; floats are rounded to 6 decimals.
- A statistic with too few observations is NOT defaulted: the build fails with an explicit error (std needs
  >= 2 observations; cross-sentence pause std stays unset with one pause).
- `sha256` is the SHA-256 of the canonical JSON (sorted keys, compact, no NaN) of every other field.
- The builder requires an explicit `--splits`, checks manifest SHA-256s (rejecting all-zero placeholders) and
  expects alignment files to be `AlignedTranscript` JSON in processed-audio time.

Reason:
The architecture fixes the statistics' meaning (DEC-010) but not these computation details; they must be
fixed, recorded in the file and reproducible.

Impact:
- TASK-040, TASK-041. Open: whether test-split speakers' baselines may feed test participants' statistics;
  meaning of the API `baseline_id`.

Approved by: Team leader (delegated to coding agent)
Date: 2026-10-09

---

## DEC-025 — Normalization Semantics

Status: ACCEPTED (agent decision under delegated authority; leader may revise)

Decision:
`z = (value - baseline_mean) / baseline_std`. Missing stays missing: unvoiced F0 frames, energy frames outside the
baseline's frame rule (e.g. pauses), and pauses of unknown boundary type have NaN z-scores, never 0. A baseline
std that is not finite or not > 0 makes that feature's z-scores undefined with a reported reason (no epsilon
floor). Unprovided or skipped features are listed in `unavailable`. The baseline must pass sha256 verification and
its passage id and sha256 are carried into the result. No participant calibration (P1).

Reason:
Silence must not be scored as "low energy" against a speaking-level baseline, and a zero spread cannot express
deviation in baseline units.

Impact:
- TASK-041, TASK-042 (delta == z), TASK-050

Approved by: Team leader (delegated to coding agent)
Date: 2026-10-09

---

## DEC-026 — Flaw Candidate Detection Conventions

Status: ACCEPTED (agent decision under delegated authority; leader may revise)

Decision:
- Rules use strict inequalities on the normalized z-scores: too_fast rate_z > +Z_RATE_FAST, too_slow rate_z <
  -Z_RATE_SLOW, high/low_energy energy_z > +Z_ENERGY / < -Z_ENERGY, excessive_pause pause_z > Z_PAUSE_WITHIN or
  Z_PAUSE_CROSS by boundary type. Threshold values are the PROPOSED DEC-P005 values, now in `core/config.py`;
  they remain uncalibrated. CONFIG_VERSION is not bumped until the calibration freeze (DEC-014).
- Order is threshold -> minimum duration -> merge (gap < MERGE_GAP_S). Energy runs are formed over covered
  frames: uncovered (NaN) frames bridge a run (until the uncovered stretch reaches MERGE_GAP_S), a covered
  in-range frame breaks it; minimum duration counts flagged time, not span.
- Excessive pauses are never merged; their minimum duration defaults to 0.0 (configurable per type).
- flat_pitch is NOT detected: BaselineStats holds only the pooled global F0 std, not a statistic of F0 variation
  within a window. Implementing it requires a new baseline statistic (record-contract change).
  pitch_instability and reduced_clarity are P1.
- peak_z is the largest |z| among flagged samples; mean_z their signed mean.

Reason:
A naive per-frame run detector missed sustained quiet speech (every word gap is NaN), and chaining blips across
gaps produced false positives that grew with recording length; both were found with end-to-end tests.

Impact:
- TASK-043, TASK-050, TASK-051. Rate findings are window-resolution (several seconds).

Approved by: Team leader (delegated to coding agent)
Date: 2026-10-09

---

## DEC-027 — Feature Extraction Conventions (energy, rate, pauses)

Status: ACCEPTED (agent decision under delegated authority; leader may revise)

Decision:
- Energy: librosa RMS with pinned zero padding, 512-sample (32 ms) window, 160-sample (10 ms) hop, dBFS with a
  1e-9 floor. Values are relative loudness after the loudness scaling of preprocessing (typical speech level, DEC-036; originally peak
  normalization), not absolute levels.
- Speech rate (DEC-020): window k covers [k*step, k*step+window); a word belongs to a window by its start time
  (start inclusive, end exclusive); each value is timestamped at the midpoint of its effective span; fewer than
  min_windows valid windows -> the analysis is marked skipped with a reason.
- Pauses (DEC-011): VAD and alignment candidates "agree" when overlap > 50% of the SHORTER interval; a merged
  event spans the union; VAD runs touching the first/last frame are ignored; boundary type comes from the
  preceding word's sentence-final punctuation (cross_sentence), inside a word (within_phrase), or unknown.
  Duration thresholds are inclusive with a 1e-9 s tolerance.

Reason:
DEC-011, DEC-020 and ARCHITECTURE §13 leave these details open.

Impact:
- TASK-032, TASK-033, TASK-034. Pause type is punctuation-based (abbreviations misread as sentence ends).

Approved by: Team leader (delegated to coding agent)
Date: 2026-10-09

---

## DEC-028 — Severity Formula (resolves DEC-P006; amends DEC-014)

Status: ACCEPTED (agent decision under delegated authority; leader may revise)

Decision:
- Option A (linear product) is selected:
  severity = clip((|mean_z| - Z_MIN) / (Z_SEVERE - Z_MIN), 0, 1) * clip(flagged_duration_s / DURATION_SEVERE_S, 0, 1)
  with the PROPOSED constants Z_MIN = 1.0, Z_SEVERE = 4.0, DURATION_SEVERE_S = 5.0 (config.py, uncalibrated).
- |mean_z| is used (direction does not matter); the duration is the FLAGGED time, not the span.
- excessive_pause has NO duration component: its z-score is a function of the pause duration alone, so a separate
  factor would count the same quantity twice (and cap even a 16-sigma, 1.5 s pause at 0.3).
- Duration is counted once. DEC-014's flaw_penalty = BASE_PENALTY * severity * duration_weight * reliability is
  therefore amended to flaw_penalty = BASE_PENALTY * severity * reliability (duration_weight / DURATION_NORM_S are
  dropped; see DEC-030).
- Reliability stays a constant 1.0 at P0 (ARCHITECTURE §19); it is not a confidence measure.

Reason:
Option B (sigmoid) spans only about 0.58-0.73 with the proposed constants, so it cannot distinguish mild from severe
deviations. Applying both Option A's duration component and DEC-014's duration_weight would count duration twice.

Impact:
- TASK-052, TASK-060. Limitation: with a small-spread (single-reference) baseline most real deviations exceed
  Z_SEVERE, so magnitude saturates at 1 and severity reduces to the duration component. All constants need
  calibration on a dev split.

Approved by: Team leader (delegated to coding agent)
Date: 2026-10-09

---

## DEC-029 — API Contract 1.1.0 and the Source-Time Response Timeline

Status: ACCEPTED (agent decision under delegated authority; leader may revise)

Decision:
- The public contract gains only OPTIONAL fields (MINOR bump to 1.1.0; 1.0.0 payloads stay valid): `Flaw.rule`
  (the detection rule and threshold that flagged it), `Flaw.affected_words`, `Flaw.warnings`,
  `AudioInfo.trim_start_s` / `source_duration_s`, `AnalysisResult.notes[]` and `config_fingerprint`.
- Every time in a result is in SOURCE time (the uploaded recording's timeline), converted exactly once at response
  assembly with the trim offset (DEC-023). Flaw bounds are validated against `trim_start_s + duration_s`.
- Words without complete timings are not invented; they are omitted from `alignment` and reported in `notes`.

Reason:
The problem statement requires each finding to state why it was flagged, which words it covers and its limitations,
and requires missing evidence to be visible. Markers must line up with the user's own audio.

Impact:
- TASK-054, response assembly (Task 5), frontend types (derive from the Pydantic models).

Approved by: Team leader (delegated to coding agent)
Date: 2026-10-09

---

## DEC-030 — Scoring Conventions (amends DEC-014; weights from DEC-P007)

Status: ACCEPTED (agent decision under delegated authority; leader may revise)

Decision:
- Penalty per flaw = BASE_PENALTY x severity x reliability (BASE_PENALTY = 30.0). DEC-014's extra duration_weight /
  DURATION_NORM_S are dropped because severity already contains duration (DEC-028); applying both counted it twice.
- sub_score = max(0, 100 - penalty_total); composite = sum(effective_weight x sub_score) over EVALUATED features.
- A feature is evaluated only if every P0 flaw type that maps to it was actually checked. Flaw types the detector
  reports as skipped (not implemented, e.g. flat_pitch, or whose feature was unavailable) make their feature NOT
  evaluated. Such a feature is OMITTED from the scores (never 100, never 0), the remaining weights are renormalised
  and the EFFECTIVE weights are reported, with the reasons returned for `notes`. With flat_pitch not implemented the
  P0 weights 0.30 / 0.25 / 0.20 therefore become 0.4 / 0.333333 / 0.266667 and pitch is not scored.
- If no feature can be evaluated, scoring fails (no number is invented). mfcc and clarity have weight 0 at P0.
- Displayed numbers are rounded first (penalty and scores 2 dp, weights 6 dp) and the composite is computed from them,
  so it can be re-derived from the response. Flaws are summed in a fixed order.
- Meaning: the score summarises deviation from the BASELINE over the evaluated dimensions (100 = none detected). It is
  not a speech-quality or intelligibility score and it is not calibrated (all constants are proposed starting values).

Reason:
A pitch score of 100 would claim pitch was assessed when it cannot be, and counting duration twice distorts penalties.

Impact:
- TASK-060, TASK-061, TASK-062; response assembly (Task 5) must surface `excluded` reasons in `notes`.

Approved by: Team leader (delegated to coding agent)
Date: 2026-10-09

---

## DEC-031 — Explanation Layer: Fact Sheet, Number Guard, Fallback

Status: ACCEPTED (agent decision under delegated authority; leader may revise)

Decision:
- Each flaw gets a FACT SHEET (`services/explanation/facts.py`): every number that may appear in its text, formatted once
  with fixed decimals from the grounded evidence, the detection rule and the interval. Templates insert fact-sheet strings
  only; no number is typed into a template. Differences and z-scores carry no sign (direction is written as "above" /
  "below"); inherently signed levels (dBFS) keep their sign.
- An independent GUARD (`guard.py`) checks any explanation text: every numeric token must equal a fact-sheet value (sign and
  trailing zeros ignored); spelled-out quantities ("twice", "half", "three", ...) are rejected; digits are tolerated only inside
  a quoted word that is exactly one of the transcript words the flaw covers.
- If a template is missing, a fact is missing, or the guard rejects a text, a minimal fallback that states only the finding
  type and interval is used (`used_fallback`). The overall summary is guarded the same way.
- Only the template provider is implemented (`explanation_method` = "template"). A future LLM provider must receive the fact
  sheet only, must pass the same guard, and falls back to the template (DEC-018, DEC-021). TASK-072 is therefore delivered as the
  guard; the LLM call itself is not implemented.
- Wording describes a difference from the baseline recording only; it makes no claim about content, confidence, emotion or
  intelligibility (a test scans for such language).

Reason:
The LLM boundary (AGENTS §6.2) is only enforceable if there is one canonical source of numbers and a check independent of the
author of the text. Dropping the sign of a dBFS level would have turned "-28.2 dBFS" into "28.2 dBFS", the opposite statement.

Impact:
- TASK-070, TASK-071, TASK-072. The guard cannot judge whether a sentence is true (direction words are fixed by the
  templates and tested), only that no number or quantity is invented.

Approved by: Team leader (delegated to coding agent)
Date: 2026-10-09

---

## DEC-032 — Pipeline Orchestration, Analysis Identity and Result Retrieval (amends DEC-016, DEC-026)

Status: ACCEPTED (agent decision under delegated authority; leader may revise)

Decision:
- ONE orchestrator, `services/pipeline.py` (`AnalysisPipeline.analyze`), runs the canonical pipeline of AGENTS.md §2 in order:
  preprocess -> baseline lookup -> cache check -> transcribe -> align + validate -> features -> normalize -> detect -> severity /
  evidence -> score -> convert to source time -> explain -> assemble -> store. It contains no analytics; it wires stages, converts
  times once (DEC-029) and states in `notes` what was not evaluated or limited. Whisper / WhisperX are injected, or created lazily.
- BASELINE LOOKUP (resolves the open `baseline_id` / `passage_id` question; refines DEC-015). `baseline_id` is the name of a
  statistics file (`BaselineProvider.get(baseline_id, passage_id=...)`; by default the passage id, which is what the builder writes);
  the record must describe the requested `passage_id`, so several baselines (for example different baseline speakers) can exist for
  one passage but a baseline can never be applied to another passage.
- ANALYSIS IDENTITY. `analysis_id` is a UUIDv5 of the SHA-256 of the canonical JSON of every input that can change the stored
  result: the audio hash (trimmed samples only), the trim offset and the source duration (the hash does not cover them), the baseline
  id and its content hash, the passage id and the passage-text hash, the `speaker_gender` hint, the manual-transcript hash, the
  config / pipeline / API-contract versions, a fingerprint of every analytical constant in effect, and the installed versions of the
  numeric libraries. The stored result - notes included - is a pure function of this key, so a cache hit equals a fresh run.
- STORAGE. Each result is one JSON file `<CACHE_DIR>/<analysis_id>.json`, written atomically. A repeated request is answered from it
  (`processing_meta.cached = true`); `GET /status/{id}` and `GET /result/{id}` read the same store, so results survive restarts.
  A missing, unreadable, corrupt or mismatched file counts as absent and is recomputed. Ids are validated before touching the disk.
- CONCURRENCY. One analysis at a time (a lock): the models are shared and the work is CPU-bound. The endpoint stays synchronous
  (DEC-016) but runs the analysis in a worker thread so health and status requests remain responsive.
- ERRORS. Every failure becomes a public `ErrorCode`: undecodable audio -> UNSUPPORTED_AUDIO_FORMAT; too long -> AUDIO_TOO_LONG;
  silent audio, an empty transcript, speech that cannot be aligned, or a baseline that describes another passage -> VALIDATION_ERROR;
  unknown baseline -> BASELINE_NOT_FOUND; model, alignment-validation, baseline-integrity and analytical-stage failures ->
  PROCESSING_ERROR. A `detail` is built only from this project's own validation messages and the client's own identifiers; text
  raised by third-party code (decoders, models, the file system) and server paths are logged, never returned. Unexpected exceptions
  become a generic PROCESSING_ERROR. A failed analysis stores nothing. If only the final write of a SUCCESSFUL result fails, the
  result is still returned, with the note `result_not_stored`, instead of discarding the analysis.
- NOTES (machine-readable codes with a message) state: uncalibrated thresholds, a thin baseline (few rate windows / within-phrase
  pauses), a very quiet recording, a transcript that does not match the passage text (or no passage text), alignment warnings,
  unavailable or unscored features (with the reason), pauses that could not be compared, words left out for missing timing, an ignored
  `speaker_gender`, an unavailable MFCC summary, a result that could not be stored, and an explanation provider that is not
  implemented or fell back.
- AMENDS DEC-026: an energy run is clipped to the span covered by the frame centres (0 to the end of the audio). The nominal
  "half a hop before the first frame" would give a flaw touching the start of a recording a NEGATIVE start time, which the public
  contract rejects; a recording that begins loud therefore failed the whole analysis. Found by the pipeline tests.

Reason:
A judge must be able to re-open a result, and the same input must give the same result (AGENTS.md §6.1). Each key component prevents
a specific wrong answer: without the trim offset two recordings with the same speech but different leading silence would share a
result whose timestamps are wrong for one of them; without the baseline content hash a rebuilt baseline would be answered from a
stale entry; without the hint and passage text the stored notes could contradict the request. Mapping failures to documented codes
keeps the frontend free of guesswork, and withholding internals follows the security rules (AGENTS.md §22).

Impact:
- Wires the finished stages (ARCHITECTURE.md §4, §23) and adds `/status` and `/result`. Partly advances TASK-063, TASK-101,
  TASK-106 (determinism, cache and error-path tests on synthetic speech) and TASK-107 (invalid input); none of them is complete
  without real recordings.
- The real Whisper / WhisperX path is covered only by the deselected smoke tests; everything else is tested with exact-timing
  stand-ins. Detection thresholds and weights remain uncalibrated (the result says so).
- Open: a single analysis at a time limits throughput; stored results are never evicted (add a retention policy if the cache grows).

Approved by: Team leader (delegated to coding agent)
Date: 2026-10-09

---

## DEC-033 — Dashboard: Stack, Boundary and Backend Support (builds on DEC-002; supersedes DEC-P009)

Status: ACCEPTED (agent decision under delegated authority; leader may revise)

Decision:
- STACK: React 19 + Vite + strict TypeScript (DEC-002), tested with Vitest, Testing Library and jsdom. NO chart, UI-kit, HTTP-client,
  icon or CSS-framework library (this supersedes DEC-P009: recharts, wavesurfer.js, axios, tailwindcss). Charts are SVG/HTML drawn
  by project code (`frontend/src/charts/`), the icon set and the design system (`frontend/src/styles/`) are project code, and
  `fetch` / `XMLHttpRequest` (for upload progress) are used directly. Runtime dependencies: `react`, `react-dom` and three
  self-hosted font packages (`@fontsource` IBM Plex Sans, IBM Plex Mono, Newsreader; SIL Open Font License 1.1). Development only:
  `vite`, `typescript`, `vitest`, `jsdom`, `@testing-library/*`, `openapi-typescript`, `playwright-core` (screenshot and accessibility
  scripts) and `axe-core` (MPL-2.0; the accessibility audit). `npm audit --omit=dev` reports no advisory; the current `vitest` 3 line
  carries advisories in its test runner (`tinypool`, `@vitest/mocker`) whose fix is vitest 5, which needs Node 22.12 or newer, so
  it was not taken; they affect the development machine only and not the shipped bundle.
- BOUNDARY (AGENTS.md section 9): the dashboard renders the backend's `AnalysisResult` and computes no analytics. It may LOOK UP values
  (the nearest frame, the pause that contains a time, the word being spoken), order and filter lists, format numbers with fixed
  decimals, choose axis ranges and thin long series for drawing (the minimum and maximum of every pixel column are kept). Two pieces
  of drawing geometry are derived from backend numbers and are labelled as such: the baseline bands (the baseline mean plus and
  minus one and two standard deviations) and the dashed "where the rule flags" line on the evidence gauge (the mean plus the finding's
  own `rule.threshold_z` times the standard deviation). Scores, severities, reliabilities, z-scores, rates, pause lengths and
  deviations are only ever read. Tests compare displayed numbers with the result.
- CONTRACT: `frontend/src/api/schema.d.ts` is generated from `frontend/openapi.json`, which `scripts/export_openapi.py` exports from the
  FastAPI app; a backend test fails when the snapshot and the app differ. API contract 1.2.0 adds `GET /api/v1/baselines` (usable
  baselines with their passage and whether their statistics are thin; unusable files are listed with a reason code, never a path),
  which the upload form needs so the user compares a recording with a baseline of the same passage.
- SERVING: FastAPI serves `frontend/dist` at `/` (mounted last and only when `index.html` exists, so API routes win and a missing build
  never breaks the API). `CORS_ORIGINS` allows a separate dev server (GET, POST, OPTIONS; no credentials). `npm run dev` proxies `/api`.
- ROUTING AND STATE: hash routes (`#/a/<analysis id>/<view>[/<finding id>]`) so a result can be linked and no server rewrite is needed.
  State is a few small external stores; the playhead has its own store so only the overlays redraw at animation-frame rate. Settings
  and a list of opened analyses (id, title, score; never audio or results) are kept in localStorage; a result is always fetched again
  from the API or the sample files. A request that was replaced by a newer one can no longer change the state.
- HONEST PRESENTATION: synthetic samples are labelled wherever they appear (chip, banner, report); a dimension that was not scored is
  a row that says why (the backend's note), never 100 and never blank; every backend note is shown; a finding keeps its rule,
  warnings and low-confidence flag; the score is described as a deviation from the baseline, not as a grade; when audio is not
  available (a result opened by id) the page says so; the colour of a finding type is always paired with a glyph.
- ACCESSIBILITY: text and component colours meet WCAG 2.1 AA in both themes (asserted by `frontend/tests/tokens.test.ts`); everything
  is operable by keyboard with a visible focus ring and a shortcut list; reduced motion is honoured (operating-system setting or a
  switch); charts have text alternatives (labels, tables of the values); there is a skip link and landmarks. `npm run a11y` runs
  axe-core (WCAG 2.1 A and AA) in a real browser on every page and on the interactive states (palette, dialog, selection, collapsed
  sidebar, phone drawer) in both themes: 44 combinations, no violations on 2026-10-10.

Reason:
The dashboard is the judges' view of the project (AGENTS.md section 26), so the evidence trail has to be visible and exact. A chart
library would have drawn the picture but not the interaction this work needs (a shared time axis, zoom and pan on every lane, a
crosshair across lanes, a playhead that moves 60 times a second without re-rendering the page), and each added dependency is cost
that AGENTS.md section 19 asks to justify: the application code is about 100 kB gzipped (fonts excluded), has no runtime network
dependency (it works in a lab without internet) and the fonts are bundled. wavesurfer.js decodes audio to draw a waveform; a waveform is not an
analytic measurement, and the backend's loudness timeline is a better picture of the same thing. Serving the build from the API
keeps one origin (no CORS in the normal case) and one command to demonstrate.

Impact:
- TASK-080 to TASK-087 (see TASKS.md), `frontend/`, `backend/app/main.py`, `backend/app/api/routes/catalog.py`, `scripts/export_openapi.py`,
  `docs/architecture/frontend.md`.
- Limits: the dashboard has never run against the real Whisper/WhisperX models or a real recording (none exist yet); upload E2E is
  tested with a mocked API in the browser and with stand-in models on the backend. There is no waveform view and no in-browser
  recording yet. Charts are SVG, which is comfortable to roughly a few thousand points per lane after thinning; a recording of many
  minutes would call for canvas.

Approved by: Team leader (delegated to coding agent)
Date: 2026-10-10

---

## DEC-034 — Demo Samples: Synthetic Recordings and What They Claim

Status: ACCEPTED (agent decision under delegated authority; leader may revise)

Decision:
- `frontend/public/samples/` ships four recordings (`clean-delivery`, `rushed-explanation`, `hesitant-delivery`, `mixed-flaws`) with the
  `AnalysisResult` the real pipeline produced for each, and an `index.json`. `scripts/demo/build_demo_samples.py` builds them
  (`npm run samples`). The voice is a speech synthesiser (ffmpeg `libflite`, voice `slt`) reading the passage word by word, so the
  word timings are exact by construction; Whisper and WhisperX are replaced by stand-ins that return those timings
  (`processing_meta.whisper_model` says `demo-exact-timings`). Every other number comes from the real analysis code. The baseline is
  built from five synthetic takes (seeds 11 to 15).
- Flaws are injected on purpose (a rate change, an inserted silence, a level change) at known times; the index stores them as
  ground truth together with whether the pipeline detected each one, computed when the sample was built.
- Selection rule, stated in the index: each sample is the first take (seeds from 200 upward) that fits its description (the clean
  take has no finding; each flawed take has its injected findings detected, with at most two additional findings). One documented
  exception: the quiet sentence of `mixed-flaws` is NOT detected by the current frame-level energy rule and is kept as a visible miss.
- The index records a diagnostic that must stay visible in the UI: of ten clean synthetic takes, six were flagged by the current
  uncalibrated thresholds.
- The samples illustrate the interface and the evidence trail. They are not evidence of detection accuracy, they contain no human
  speech, and they say so in the index, in the dashboard banner and in the printable report.

Reason:
The dashboard has to be demonstrable before real recordings exist, and a demonstration must not pretend to be a measurement.
Choosing "the first take that fits" with the rule published, and keeping a missed flaw and the false-flag rate on screen, stops the
samples from being curated into looking better than the detector is.

Impact:
- `tests/test_demo_samples.py` checks that each committed result is a valid contract result for exactly the WAV shipped next to it, that
  ground truth lies inside the recording, that the synthetic nature is stated and that the generator is deterministic for a seed.
- Regenerate the samples after any change that alters analysis output or the contract / configuration versions (the ids are derived
  from them); a stale sample would show numbers the current backend no longer produces.
- Findings recorded while building them (open work, see PROJECT_STATE.md): per-event z > 2 over about twenty pauses flags 6 of 10 clean
  takes; the energy rule missed a 20 dB quieter sentence in every candidate take; a peak-normalised recording made a louder stretch
  hard to detect (replaced by DEC-036 on 2026-10-11, which regenerated these samples); quiet speech is split into false pauses by the absolute -50 dBFS pause threshold; rate findings are window-resolution.

Approved by: Team leader (delegated to coding agent)
Date: 2026-10-10

---

## DEC-035 — In-Browser Recording and Findings Export

Status: ACCEPTED (agent decision under delegated authority; leader may revise)

Decision:
- The New analysis page offers "Record now" beside "Upload a file". A take ends as an ordinary `File` handed to the existing upload form and
  analysed through `POST /api/v1/analyze`. There is no new endpoint, no contract change and no change to the pipeline (DEC-033 boundary).
- Capture asks for one channel with the browser's echo cancellation, noise suppression and automatic gain control switched OFF. They
  rewrite the signal the features are measured on (automatic gain erases the level changes the energy rule looks for; noise
  suppression reshapes the spectrum the MFCC and clarity proxies read). If the browser reports that it applied any of them anyway, the
  panel says so before the take is used.
- Samples are taken raw through an AudioWorklet (inline module; a ScriptProcessor fallback), not through `MediaRecorder`, which would
  hand back a lossy Opus or AAC stream whose container differs by browser and would be decoded and re-encoded before analysis.
- The take is converted from the context's native rate (usually 44.1 or 48 kHz) to 16 kHz mono by the dashboard's own windowed-sinc
  resampler (`src/recording/resample.ts`: Blackman window, eight zero crossings, cut-off at the lower Nyquist frequency) and written
  as a 16-bit PCM WAV (`wav.ts`). 16 kHz is what the backend converts to anyway (`TARGET_SAMPLE_RATE`), and it keeps a five-minute take
  at 9.6 MB, inside the default upload limit of 10 MiB; at 48 kHz the limit would be reached after about 110 seconds. A hand-written
  converter (instead of the browser's offline audio context) gives the same bytes for the same samples in every browser and can be tested
  without one.
- The longest take is 300 seconds, the API's default `MAX_DURATION_S`. The server remains the authority and answers with its own limit if
  it was configured differently.
- Boundary: the level bar and the clipping warning (a peak at or above 0.99) are capture aids for setting up the microphone. They are not
  analysis, are not sent to the backend and are not stored. Nothing is kept by the dashboard: audio leaves the browser only through the
  same upload as a chosen file. Recordings of people stay out of git (AGENTS.md section 22).
- "Export findings as CSV" (Flaws page, command palette) writes one row per finding in time order with every value exactly as the backend
  returned it (nothing rounded, evidence fields flattened as `evidence.<field>`), RFC 4180 quoting, CRLF line ends and a UTF-8 byte-order mark
  so a spreadsheet reads the typographic punctuation of the explanations. "Copy a link to this page" copies the address of the current view; it
  opens the same analysis for anyone who reaches the same server while that server still holds the result.

Alternatives rejected:
- `MediaRecorder`: lossy re-encoding before analysis, browser-dependent container and codec.
- Upload at the native rate: over the size limit after about 110 seconds of speech, and the backend would discard the extra bandwidth.
- `OfflineAudioContext` for resampling: filter and rounding differ between browsers, so the same take could analyse differently.

Impact:
- Verified with fakes (a scripted audio graph, 22 tests; the panel, 11; the converter and the WAV writer, 12; the export, 13) and in
  Chromium with its fake microphone, where a take was recorded, converted to a valid 16 kHz mono WAV and accepted by the upload form
  (`npm run smoke`). It has NOT been tried with a real microphone, in Safari or Firefox, or on a phone; the first real recording session
  is the test. Microphone access needs `https://` or `localhost`, and the panel says so when the page is served otherwise.
- The recorder adds no dependency and no stored data; browser permission is requested only when "Start" is pressed.

Approved by: Team leader (delegated to coding agent)
Date: 2026-10-10

---

## DEC-036 — Loudness Scaling by Typical Speech Level (amends DEC-P003 and DEC-027)

Status: ACCEPTED (explicit approval by the team leader, 2026-10-11)

Decision:
- Preprocessing no longer scales a recording so that its loudest sample is -3 dBFS. After trimming, it scales the recording by ONE gain so
  that the **typical speech level** is `TARGET_SPEECH_LEVEL_DBFS = -26.0` dBFS. The speech level is the median loudness of the speaking
  frames: frame loudness is the energy feature's own (`frame_energy_db`: 32 ms RMS frames, 10 ms hop; one shared definition), and the
  speaking frames are those within `SPEECH_LEVEL_WINDOW_DB = 30` dB of the 95th-percentile frame loudness.
- The gain is capped so that the loudest sample never exceeds `MAX_PEAK_DBFS = -1.0` dBFS (a safety limit). Empty or digitally silent
  audio is returned unchanged with `peak_dbfs = -100`.
- The step runs identically for baseline recordings and participant recordings. `peak_dbfs` in the response keeps its meaning (the
  measured peak after scaling); it is no longer -3. No API field changed, so the API contract version is unchanged.
- The three constants are in `app/core/config.py`, replace `TARGET_PEAK_DBFS`, and are part of the analysis fingerprint (so cached results
  and analysis ids change) and of the baseline builder's configuration snapshot. They are starting values, not calibrated.
- The energy warning shown with energy findings now says that the recording is scaled to the baseline's typical speech level and that
  energy shows louder or quieter stretches inside the recording, not how loud the speaker was overall.

Reason:
Scaling by the loudest sample lets one loud stretch define the scale. Measured end to end (synthetic voice, one sentence of 17 words
changed, baseline built the same way; `energy_db` z-score of the changed sentence, and the level of the rest of the take against the
baseline mean):

| Injected change | Old: z of the sentence / rest of take | New: z of the sentence / rest of take |
|---|---|---|
| +6 dB | +0.22 / -3.4 dB | +0.53 / -0.7 dB |
| +9.5 dB | +0.22 / -6.2 dB | +0.86 / -1.0 dB |
| +12 dB | +0.22 / -8.1 dB | +0.98 / -2.2 dB |
| +18 dB | +0.22 / -12.4 dB | +0.98 / -6.6 dB |
| -12 dB | -0.95 / -0.2 dB | -0.85 / +1.4 dB |
| -20 dB | -1.49 / -0.2 dB | -1.51 / +1.1 dB |

The old method made every loud sentence look normal (the same z whatever the loudness) and pushed the rest of the take down by up to 12 dB.
The new one gives the loud sentence a z-score that grows with its loudness and leaves the rest of the take close to the baseline. (The +12 and
+18 dB rows are limited by clipping in the synthetic file; the median also moves a little when a large part of a take is louder.)

What this does NOT do (stated so nobody relies on it): the frame-level energy rule still did not flag any of these changes, because the
baseline's frame-to-frame spread is wide (std 8.6 dB, so z > 2 needs about 17 dB) and one 10 ms frame must exceed the threshold. Detecting
moderate loudness flaws needs the energy rule to compare windowed levels (about 0.5 to 1 s) instead of single frames, and a calibration
on real recordings; that is open work (TASK-128), to be decided with the leader. The demo sample "Mixed flaws" therefore still shows the
20 dB quiet sentence as a miss. Whole-take gain differences remain invisible by design (only differences inside a recording are measured),
and a recording that is mostly loud or mostly quiet looks like a recording at another gain.

Impact:
- Backend: `speech_level_dbfs` / `speech_level_normalize` replace `peak_normalize` in `app/services/audio/preprocessor.py`; `frame_energy_db` is
  factored out of `energy.py`. Tests for preprocessing, the pipeline and the baseline builder were updated, and new tests pin the level, the
  preservation of differences inside a recording, independence of the overall gain, the cap, edge cases and determinism.
- The four demo samples were regenerated (new analysis ids, new baseline hash; the audio files are unchanged); dashboard wording that
  described peak normalisation was changed, and four dashboard tests now read their expected numbers from the sample instead of fixing them.
- Any baseline built before this change is invalid for the new analysis (none existed). Baselines must be built after it.
- The recording instructions do not depend on this decision. The recording checker's "loudest point" gates describe the raw recording
  (headroom), not the scaled one.
- Not verified: behaviour on real recordings and with the real Whisper/WhisperX models (their input level now differs).

Approved by: Team leader (explicit approval, 2026-10-11)
Date: 2026-10-11

---

## DEC-037 — Dataset Collection Plan v1

Status: ACCEPTED (the team leader's answers of 2026-10-11 to the recording protocol's open decisions; the rest follows the protocol)

Decision:
- **Speakers:** four, anonymous: `spk_dev_01` and `spk_dev_02` (dev: baseline takes and tuning) and `spk_test_01` and `spk_test_02` (test: sealed until
  the settings are frozen, DEC-017). The assignment is fixed before the first recording and never changed.
- **Passages:** `p001` "Project talk" (123 words) and `p002` "Morning market" (118 words), `data/plan/passages_v1.json`. The pilot and the minimum tier use `p001` only.
- **Equipment:** one USB headset for every speaker, Audacity, WAV mono 16-bit at the same rate (48 kHz or 44.1 kHz) for every recording, one quiet room.
- **Plan:** nested tiers generated by `scripts/dataset/make_plan.py` (pilot 9 takes of `spk_dev_01`, minimum 36, recommended 112). The pilot comes first; the tier after it
  is chosen from the time left. The generated files are `data/plan/pilot/` and `data/plan/v1/`; after the pilot a personal plan that skips the recorded takes is made with `--done`.
- **Storage and consent:** audio stays out of git (`data/raw/*` and `data/incoming/` are ignored); every speaker signs the consent form (`docs/methodology/consent-form-template.md`),
  kept with the name-to-id table outside the repository.
- **Labels:** the planned stretch is turned into exact times after alignment (TASK-126) and confirmed by ear; for test speakers by a person who did not perform the take.
- **Loudness:** DEC-036 (approved the same day).
- **People:** one data owner runs the scripts with step-by-step help; speakers need only Audacity and a web browser.

Not decided yet (asked again after the pilot): the tier after the pilot, the deadline, the recording schedule and who annotates.

Approved by: Team leader (explicit answers, 2026-10-11)
Date: 2026-10-11

---

## DEC-038 — Registering Recordings: Alignment From the Passage Text, Proposed Annotations, Retired Fixtures

Status: ACCEPTED (agent decision under delegated authority; leader may revise)

Decision:
- **Dataset recordings are aligned with the passage text as the transcript.** The speakers read a known text, so `scripts/dataset/prepare_recordings.py` hands the passage
  text to the existing WhisperX aligner as a manual transcript (the manual-transcript option of ARCHITECTURE.md §7.2 and §11). Words, punctuation (which the pause classifier
  reads) and the word numbers of the recording plan then match exactly. This is not a second pipeline: the preprocessing, the aligner and the alignment validator are the
  ones the analysis uses. Participant uploads still go through speech recognition unless a transcript is supplied.
- **Flaw annotations are proposed, then confirmed.** The planned stretch (plan sheet) is placed on the timeline by the alignment, converted to the time of the original file,
  and written with `"annotation_status": "proposed"`. Only a person sets `"confirmed"`, after listening (Audacity label files are written for that). A re-run regenerates
  proposed annotations and never overwrites a confirmed one or one written by hand. The evaluation of the test split must use confirmed annotations only. The field is an
  optional addition to the annotation file; the API contract is unchanged.
- **A flaw is checked for having been performed.** Against the same speaker's own baseline takes: the time the stretch takes (speed), the speech level of the stretch against
  the rest of the take (loudness) and the length of the silence (pause) must reach half of the planned change (70 % of the planned minimum for a pause), otherwise the take is
  marked "weak example" in the report and in the annotation notes. Advice only: the take is still registered. The limits (`PerformedGates`) and the alignment plausibility limits
  (`AlignmentGates`: wrong word count or any untimed word in a baseline take fail; low scores, drifting ends, low coverage warn) are proposed, uncalibrated, and kept in one place.
- **Idempotent and safe:** a re-run changes nothing for unchanged takes and does not align again (a stored alignment that matches its hash is kept); a take recorded again needs
  `--replace`; a take that fails any check is not registered and nothing is written for it; the quality check (`check_recordings.py`) runs again first.
- **The schema fixtures are retired.** `data/metadata/` now holds the two real passages, the four anonymous speakers and an empty manifest; the fixture annotation was removed and
  the test that asserted the fixture could not be built became a test of the empty-manifest case.
- A baseline is built only on request (`--build-baseline`), from dev baseline takes (DEC-017), by the existing `build_baseline_stats.py`.

Reason:
The first real recordings must reach the site without hand-made paperwork, and the answer key must not be made from labels nobody has heard. Using the known text removes recognition
errors from the baseline; proposing and confirming keeps the aligner (which the system itself uses) from silently grading itself.

Impact:
- New: `scripts/dataset/prepare_recordings.py`, `scripts/dataset/take_checks.py`, `scripts/check_environment.py`, tests (`tests/test_prepare_recordings.py`,
  `tests/test_dataset_take_checks.py`, helper `tests/dataset_takes.py`); docs and `.gitignore` (label files) updated. No change to the pipeline, scoring, API or flaw vocabulary.
- Not verified: the real WhisperX model on real recordings (the tools were exercised with a stand-in that finds word bursts in the audio); behaviour of the alignment on the
  deliberately slow, fast and silent stretches; every limit above. The first real run is the real test and may need changes.

Approved by: Team leader (delegated to coding agent)
Date: 2026-10-13

---

## DEC-039 — Accuracy of Rate and Pause Findings: Narrowed Rate Intervals, Long Silences, Minimum Pause Length

Status: ACCEPTED (agent decision under delegated authority; leader may revise)

Decision:
- **Rate findings are narrowed to the words that deviate.** Detection stays window-based (DEC-020: 8 s windows, z against the baseline). Each too_fast / too_slow
  region is then narrowed (`grounding/candidates.py: refine_rate_candidates`): every word gets a slot (start to the next word's start); a word counts for the flaw
  by how far its slot lies beyond the HALFWAY slot between the baseline's (60 / mean rate) and the strongest window's; the finding is the run of consecutive words
  with the largest summed score (maximum-subarray; repeated on what is left, so two stretches stay two findings). A run is accepted only with at least
  `REFINE_MIN_WORDS` words (8, about 3 s), at least the minimum duration, and its own rate (words / span) beyond the same z threshold; otherwise the window
  interval is kept. The run's z-score uses the baseline's window spread scaled for the number of words: `std * sqrt(max(1, window_words / words))`, because a short
  stretch varies more than an 8 s window. The evidence of a narrowed finding (`rate_participant_wpm`, delta, `rate_z_score`, `window_duration_s`, word count) describes
  that stretch and carries a different warning; `FlawCandidate.stretch_rate_wpm` marks it. `REFINE_RATE_BOUNDARIES` / `DetectionConfig.refine_rate` switch it off.
  This implements step 6 of ARCHITECTURE.md section 17 ("boundary refinement"), which was P1.
- **A silence longer than 1.0 s counts as 1.0 s in the speech rate** (`RateConfig.max_gap_s`): a deliberate long pause is reported by pause detection and no
  longer also makes its window read as slow speech (a 3.5 s pause produced a severity-1.0 "too slow" in the experiment). The window span used to place findings is unchanged
  (`speaking_duration_s` is new). Baselines must be rebuilt after this change (the rate definition is part of their configuration snapshot); gaps up to 1 s, that is all
  natural pauses, are unchanged.
- **A pause shorter than `MIN_PAUSE_FLAW_S` (0.8 s) is never reported as excessive**, however regular the baseline's pauses are: a baseline whose pauses are all alike made
  every 0.3 to 0.5 s breath an "excessive pause" (6 of 10 clean synthetic takes were flagged, 2 of 10 after). Proposed, uncalibrated, a single setting; changes with
  `--detect min_pause_s=...` can be compared with `scripts/dataset/evaluate_takes.py`.
- **Findings are clipped to the analysed audio** (`clip_to_audio`): an aligner placing a word end a few milliseconds past the audio no longer fails the whole analysis.
- **Accuracy is measured, not judged by eye:** `scripts/dataset/evaluate_takes.py` replays registered takes (real audio, stored alignment and baseline, passage text as transcript, no
  speech model) through the real analysis and compares the findings with the annotations: found or missed, start and end error, how much of the detected range was the flaw, extra
  detections, false alarms on clean takes. The test split stays sealed (`--allow-test`), baseline takes are left out unless asked for, and `--detect NAME=VALUE` tries other settings.

Reason:
The first test on real recordings (2026-10-13) showed a fast sentence reported with an extra range and pauses that were found but not accurate. In an experiment with human-like synthetic readings
(word and gap lengths varied by about 25 %, a baseline of three takes, the real passage and the real plan; word times known exactly) the planned fast sentence was reported 6.0 s early and 6.3 s late
(24 % overlap, 4.1 times the planned length) and the slow sentence 4.7 s early and 7.1 s late (51 %, 2.0 times); after the change 0.0 s and 0.2 s (95 %) and 0.7 s and 0.0 s (95 %). Pause
intervals were already exact (0.0 s). What the change does NOT fix: ordinary variation in a three-take baseline still produces stray findings on clean takes (both clean synthetic takes still had a flag, 4 in 1.9 minutes);
that is a matter of thresholds and baseline size, to be calibrated on real dev takes with the evaluation tool.

Impact:
- Backend: `RateConfig.max_gap_s`, `RateExtractionResult.speaking_duration_s`, `NormalizedFeatureBundle.rate_max_gap_s`, `DetectionConfig.refine_rate` / `refine_min_words`, `FlawCandidate.stretch_rate_wpm`,
  `detect_candidates(..., aligned=, baseline=)`, `clip_to_audio`, settings `REFINE_RATE_BOUNDARIES`, `REFINE_MIN_WORDS`, `MIN_PAUSE_FLAW_S`. All are part of the analysis fingerprint, so cached results are not reused.
  The API contract (field names and types) is unchanged; the meaning of the rate evidence fields for a narrowed finding is described above.
- Tests: `backend/tests/test_rate_refinement.py` (32), `tests/test_evaluate_takes.py` (30), end-to-end expectations (flaw order, exact stretch) and five dashboard tests that now read their numbers from the samples.
  Demo samples regenerated; the dashboard label "Window" became "Measured over" and two texts changed.
- Existing baselines should be rebuilt: `python scripts/dataset/prepare_recordings.py data/incoming --build-baseline` (alignments are kept).
- Not verified: real recordings and the real models. `REFINE_MIN_WORDS` = 8 was chosen from the synthetic experiment (fewer stray short findings), `MIN_PAUSE_FLAW_S` = 0.8 s from how long a
  hesitation must be to be heard; both, and every z threshold, need calibration on the dev takes. The length scaling of the spread assumes word durations vary independently. A flaw whose stretch is
  not inside any flagged window is not recovered (the search stays inside the flagged region). Energy findings are untouched (TASK-128).

Approved by: Team leader (delegated to coding agent)
Date: 2026-10-13

---

## DEC-040 — Pace and Loudness Judged Word by Word Against the Baseline's Reading of the Same Words; Practical Size Guards; Severity From the Size of the Change

Status: ACCEPTED (agent decision under delegated authority; leader may revise)

Why (the first replay on the team's real recordings, 2026-10-13, 50 takes, 30 planned flaws, 8 clean takes):
excessive_pause 6 of 6 found, exact; too_fast 1 of 6; too_slow 5 of 6 but 2 s early or late on average; high_energy 0 of 6; low_energy 0 of 6; 6 of 8 clean takes flagged (8 false alarms in 5.9 minutes);
extra pauses of 0.80 to 1.25 s flagged with severity 1.00. The false alarms repeated at the same place of the passage in different takes (a stretch read at 139 words/min in three takes, the last sentences at 226 to 312
words/min in several): the baseline's overall mean and spread (8 s windows) say nothing about WHICH words are in a window, so the content of the words was measured as if it were the delivery. Loudness: single
10 ms frames against a spread of about 9 dB cannot show a sentence that is 8 dB louder (TASK-128).

Decision:
- **The baseline keeps a word profile** (`BaselineStatsRecord.word_profile`, optional; `grounding/profile.py`): for every word of the passage the expected SLOT (time from its start to the next word's start; at most
  0.25 s of the silence after it counts, `PROFILE_GAP_CAP_S`) as the geometric mean over the baseline recordings, and its expected LEVEL (median of its active frames, each recording's own overall offset removed); the spread of
  a run of n words, `sigma(n) = sqrt(drift^2 + word^2 / n)`, measured LEAVE-ONE-OUT (each baseline recording against the expectation built from the others, so it describes a recording that was not used to build it); and
  the spread of the overall pace between baseline recordings. It is built by `build_baseline_stats.py` (and so by `prepare_recordings.py --build-baseline`) from the passage text in `data/metadata/passages.json` and needs at least
  three baseline recordings that match it. A baseline without it still verifies (the hash leaves an absent profile out of the content).
- **A participant's words are matched to the passage words** (longest matching blocks, so a dropped, added or misrecognised word leaves only itself unmatched). With at least `PROFILE_MIN_COVERAGE` (0.6) of the timed words matched and
  `PROFILE_MIN_USABLE_WORDS` (16) comparable, pace and loudness are judged by `grounding/profile_detection.py`; otherwise the old rules (rolling-window pace with narrowing, DEC-039; frame loudness) run as the fallback and the
  analysis carries a note (`baseline_without_profile`, `profile_not_applicable`).
- **A finding is a run of at least `RUN_MIN_WORDS` (10) consecutive words** whose deviation, in spreads of a run of that length, is above `Z_RUN_RATE` / `Z_RUN_ENERGY` (4.0), AND whose size is practically relevant
  (`MIN_RATE_CHANGE_PCT` 15 % in pace, `MIN_ENERGY_CHANGE_DB` 3 dB in level). Every run is scored (a scan over all start words and lengths); the best z wins, its words are removed, the scan repeats (at most 8 per signal);
  fast and slow (loud and quiet) compete in one scan and never overlap. For a changed stretch the best run ends where the change ends, so boundaries are word boundaries. The spread is never taken below floors
  (`SIGMA_FLOOR_*`) so an unusually even baseline cannot make everything look huge.
- **Overall pace and level are removed first.** Pace: the reading's overall pace against the baseline (median over runs of 10 words) is divided out, so a speaker who is generally quicker or slower is compared with their own pace
  (simulated speakers 15 to 40 % off the baseline readers' pace: false alarms stayed at 4 to 8 % of clean takes, local recall at about 90 %, against 94 to 97 % false alarms with only a tolerance band). A reading that is off as
  a whole is judged on its own as one `rate_overall` finding over all comparable words, only if it differs by more than `GLOBAL_TEMPO_CHANGE_PCT` (30 %) AND by more than the spread of the overall pace between baseline readings.
  Loudness: the reading's median difference from the profile is removed (recordings are scaled to a common speech level, DEC-036, so only louder and quieter stretches within a reading are meaningful).
- **Evidence keeps its fields** (`schemas/response.py` is unchanged): `*_baseline_mean_*` is what the baseline readings had for these words (for pace, at the speaker's own overall pace; for loudness, plus the overall
  level offset) and `*_baseline_std_*` is the spread that makes the reported z-score true, |participant - baseline| / |z|, so z = (value - baseline) / spread still holds for a reader. `DetectionRule.feature` is
  `rate_run_z`, `rate_overall_z` or `energy_run_z`; explanation wording and the dashboard say "the baseline readings had for these same words".
- **Severity follows the size of the change** where a finding carries one (`FlawCandidate.effect`): `clip(|size| / scale)` with the natural-log ratio of the pace against ln 2 (twice or half as fast = 1), the level
  change against 15 dB and a pause's excess over the baseline's mean against 3.5 s (`SEVERITY_*`), times the duration component as before (none for pauses). The z-score now says how sure we are, not how serious it is: it saturates
  quickly on a very even baseline (a 1.2 s breath was 4 standard deviations from a reader whose pauses are all 0.4 s) and could no longer tell a small change from a large one. Findings of the fallback rules keep the z-score formula.
- **The shortest excessive pause is 1.2 s** (`MIN_PAUSE_FLAW_S`, was 0.8, DEC-039): every planned pause of the real takes lasted 1.39 to 3.82 s (the mildest was planned at 1.5 s), while ordinary pauses of 0.80 to 1.25 s were
  reported with severity 1.00. Pauses stay judged against the baseline's pooled mean and spread per boundary type.
- **Tools:** `evaluate_takes.py --sweep NAME=v1,v2,...` tabulates, one setting at a time, how many planned flaws are found, how many other flags there are on flawed takes, and how many clean takes are flagged
  (pitch and MFCC are computed once per recording); `--detect` accepts the new settings. `prepare_recordings.py` reports whether the profile was built.

Reason:
Simulation of human-like readings (word length decides duration, chance variation, two speakers whose pace differs by 10 %, alignment noise; the real passage): with the same data the old window rule flagged 46 % of clean takes and found
a sentence read 1.33 times as fast in 33 % of cases with ranges 2 to 3 times too long; the word-by-word comparison at the defaults flagged about 3 to 5 % of clean takes and found a 1.33 times faster sentence in 78 %, a 1.35 times slower in 82 %,
sentences 5 dB louder or quieter in 89 to 91 %, and every stronger change in 99 to 100 %, with an overlap of 92 % with the planned stretch. Through the whole system (registration, baseline, replay, stand-in aligner): all five kinds of planned flaw
found in the right words in every seed tried, one mild stray flag per six clean takes at most. Demo samples: clean probe 2 of 10 flagged before, 0 of 10 after; the quiet sentence of the mixed sample, a documented miss before, is found.

Impact:
- Backend: `grounding/profile.py`, `grounding/profile_detection.py` (new), `candidates.py` (`DetectionConfig` fields, `FlawCandidate.effect` / `run`, `CandidateDetectionResult.modes` / `profile_note`, `detect_candidates(..., observations=)`),
  `severity.py` (`effect_scale`), `flaws.py` (run evidence, rule, warnings), `explanation/templates.py` (wording), `pipeline.py` (measures the words, notes), `core/config.py` (settings), `schemas/contracts.py` (`WordProfile`, `NoiseModel`,
  `BaselineStatsRecord.word_profile`). The public API contract (field names and types) is unchanged; new `rule.feature` values and note codes are documented in `docs/architecture/api-contract.md`. All settings are in the analysis fingerprint.
- **Baselines must be rebuilt** (`python scripts/dataset/prepare_recordings.py data/incoming --build-baseline`): without it the old rules run and the result says so.
- Tests: `test_word_profile.py` (43), `test_profile_detection.py` (40), `tests/test_profile_e2e.py` (11), sweep and evidence-note tests, builder and report tests, explanation tests; demo samples regenerated (the voice keeps its loudness when stretched).
- Not verified: real recordings. The thresholds above come from simulation and must be calibrated on the real dev takes with `evaluate_takes.py --sweep` (especially `Z_RUN_*`, `RUN_MIN_WORDS`, `MIN_RATE_CHANGE_PCT`,
  `MIN_ENERGY_CHANGE_DB`, `MIN_PAUSE_FLAW_S`). Known limits: with six baseline recordings the spreads are themselves estimated; two speakers pooled in one baseline enlarge the spread of the overall pace; a stretch shorter than
  `RUN_MIN_WORDS` is reported with its neighbours; pitch findings are still not detected; the audio is the only source of the loudness of a word, so a word with fewer than three active frames has no level.

Approved by: Team leader (delegated to coding agent)
Date: 2026-10-13

---

## DEC-041 — First Check of DEC-040 on the Real Recordings: Settings Kept, and the Evaluation Tool Now Explains Its Misses and Extras

Status: ACCEPTED (agent decision under delegated authority; leader may revise)

Why (`evaluate_takes.py` and `--sweep` on the team's real dev takes after the baselines were rebuilt with the word profile, 2026-10-14; 48 takes: 40 planned flaws, 8 clean takes; two dev speakers, two passages, six baseline takes per passage):
- Planned flaws found: **34 of 40** (excessive_pause 8 of 8, too_slow 8 of 8, high_energy 7 of 8, too_fast 6 of 8, low_energy 5 of 8). Where found: start off by 0.0 to 0.4 s, end by 0.4 to 0.6 s, overlap 83 to 100 %, detected range 0.8 to 1.0
  times the plan. Before DEC-040 (30 planned flaws): 1 of 6 too_fast, 0 of 12 loud and quiet, too_slow 2 s off, pauses exact. Clean takes: **1 of 8 flagged, one false alarm in 5.9 minutes** (before: 6 of 8, eight alarms).
- By the per-category measure that ARCHITECTURE.md 25.3 proposes (F1 above 0.65 on held-out speakers; here dev speakers, annotations unconfirmed, and every flag nobody planned counted as false, side effects included), computed by hand from the printed report:
  excessive_pause 0.94, too_slow 0.80, high_energy 0.74, too_fast 0.71, low_energy 0.62. The tool now prints precision and F1 per kind itself.
- **All six missed flaws are takes of one speaker** (`spk_dev_01`: the first fast, loud and quiet take of passage 1, the first fast and quiet take of passage 2, and a quiet take whose quiet stretch turned up 14 s later than planned).
  Every one of the other speaker's 20 planned flaws was found. Five of the six misses are the first take of its kind, so the likeliest reading is a performance that was milder than planned rather than a detector that is too strict. That is a reading, not a finding:
  the next report states under each miss the change that was measured over the planned words and what the registration check said, and a person has to listen to decide.
- 14 other flags on flawed takes. Counted on the printed report with the rule the tool now applies (on a planned stretch / at most 3 s from one / further away): **7 on a planned stretch, 3 right next to one, 4 away**. People do not change one
  thing at a time: while speaking quietly the speaker also slowed down (four takes), while slowing down or speeding up they also got louder (three takes), after a loud, slow or paused stretch they relaxed or caught up. These flags state
  measured evidence, they were only not planned, so counting them as false alarms would push every threshold up and cost real flaws. The four away from every planned flaw and the one flag on a clean take (a stretch read 25 % slower, z -5.1) are what a
  person's ear has to settle.
- The sweep (one setting at a time, same takes): `z_run_rate` 3 finds one more fast flaw but adds 8 extras and flags 3 of 8 clean takes; 3.5 adds 3 extras for nothing; 4 (default) is 34 of 40, 14 extras, 1 of 8 clean flagged; 4.5 loses a real fast flaw (found with z 4.1) to
  remove 5 extras; 5 loses two. `run_min_words` 8 loses a quiet flaw and flags 2 of 8 clean takes; 12 removes two extras at no cost on these takes, which cannot show what it costs on a flaw shorter than a sentence (all planned stretches are whole sentences of 17 to 22
  words). `min_rate_change_pct` 10, 15 and 20 give identical tables (the size guard on pace never decided anything here; z did). `min_energy_change_db` 4 removes two extras, but the mildest real loud flaw found changed the level by 4.2 dB, so 4 dB is
  on the edge of the real flaws. `min_pause_s` 1.5 loses a planned pause (1.39 s) to remove one extra; 1.0 adds one.

Decision:
- **The settings of DEC-040 stay as they are** (`Z_RUN_RATE` and `Z_RUN_ENERGY` 4.0, `RUN_MIN_WORDS` 10, `MIN_RATE_CHANGE_PCT` 15, `MIN_ENERGY_CHANGE_DB` 3, `MIN_PAUSE_FLAW_S` 1.2): each is at the point where raising it loses planned flaws and lowering it adds flags faster than it finds flaws.
  `THRESHOLDS_CALIBRATED` stays false: the annotations are still only proposed from the plan, and calibrating against flaw labels that nobody has heard would measure the speakers' performance, not the detector. TASK-131 closes after the
  misses and the flags away from the plan have been listened to and the annotations confirmed or corrected, with the sweep run again.
- **The evaluation tool explains instead of only counting** (`scripts/dataset/evaluate_takes.py`; no change to any analysis result):
  - for each MISSED planned flaw: the sentence of the registration check (is the take a weak example of the flaw?), the change measured over exactly the planned words with the detection's own yardstick, set against what a finding needs
    (`those 14 words were 9% faster than the baseline readers spoke the same words (z 1.8); a finding needs a change of at least 15% with z above 4 over at least 10 words`), and whether the same kind of flaw was found elsewhere in the take;
  - for each EXTRA on a flawed take: whether it lies on a planned stretch, within 3 s of one, or away from all of them; the summary counts the three;
  - a `Listen to these first` list: planned flaws not found, flags on clean takes and flags away from the plan, with the seconds;
  - per kind of flaw: the flags of that kind nobody planned (on flawed and clean takes), precision and F1 (the metrics of ARCHITECTURE.md 25.3; the start and end errors were already there);
  - `--labels` writes what was detected as Audacity label files (`data/processed/labels/<take>.detected.txt`, ignored by git) to import next to the word and planned-flaw labels;
  - the sweep table gets an `away` column (extras that are not on or next to a planned flaw).
- **One implementation of the yardstick:** `measure_stretch` in `grounding/profile_detection.py` measures the pace and loudness of the words of a time range exactly as the findings do (overall pace and median level removed, the spread of a baseline
  reading over that many words); a test ties it to the findings of the scan. The tool captures the analysis' own word measurements while it replays a take; the pipeline is unchanged.

Reason:
A tool that only says MISSED or EXTRA cannot tell a detector that is too strict from a speaker who did not do what was planned, and the team has no other way to find out. With the measured size next to the limit, a miss reads either "the change was 5 %: perform it more clearly"
or "the change was 24 %, z 3.6: the limit may be too strict", and the second kind is what TASK-131 needs in order to move a limit with evidence. Separating the extras keeps the thresholds from being tuned to flags that are real but unplanned.

Impact:
- `backend/app/services/grounding/profile_detection.py` (`measure_stretch`, `StretchReading`, `SignalReading`; the expectation arrays of `detect_runs` moved into a helper, no behaviour change), `scripts/dataset/evaluate_takes.py`.
  No API, schema, setting or baseline change; nothing needs rebuilding.
- Tests (38 new; 1304 in all): eleven for `measure_stretch` in `backend/tests/test_profile_detection.py` (the words of a stretch are those whose middle lies in it; the size and z agree with the finding the scan reports for the same words; overall pace and level removed; unjudgeable readings give the reason),
  and in `tests/test_evaluate_takes.py` and `tests/test_profile_e2e.py` the classification of extras (limits, ties), the sentence of the registration check, the description against the limits (every boundary), the listening list, the label files, and misses explained on the synthetic takes.
- `docs/methodology/dataset-guide.md` 6g and 6h describe the new report; TASKS.md TASK-131 and PROJECT_STATE.md carry the results.
- Not verified: nobody has listened to the misses or the flags yet. The thresholds are still those chosen by simulation and checked against two speakers; scores are not calibrated either (a take with one clear flaw scored 86 to 98).

Approved by: Team leader (delegated to coding agent)
Date: 2026-10-14

## DEC-042 — Flat Pitch Is Judged With the Word Profile (Pitch Part of the Profile)

Status: ACCEPTED (agent decision under delegated authority; leader may revise)

Why:
- After DEC-040 and DEC-041 the five categories that were planned for recording were judged, but `flat_pitch`, a core category of AGENTS.md section 5 and of the problem definition, was still reported as "not implemented", and the pitch feature was left out of the score. A comparison with another team's
  project on the same track (2026-10-14; ideas only, nothing copied) showed that they do judge pitch against the reference for the same content; leaving it out was the largest visible functional gap.
- The reason it had been deferred is real (PROJECT_STATE: "BaselineStats has only the pooled global F0 std; a valid detector needs a baseline statistic of F0 variation within a window"). The word profile of DEC-040 solves exactly that: it already stores, for every word of the passage, what the same
  readers did on that word, with a noise model that says how much a reading may vary. Pitch movement fits the same machinery.
- Not adopted: pooled F0 standard deviation in Hz (depends on the speaker's register, and a speaker with a low voice would look monotone), and comparing pitch contours point by point (reading the same words with a different but natural melody would count as a flaw).

Decision:
- **Measure.** Per word: the mean over its voiced frames of clip(|semitones from the reading's own median pitch|, 6)^2, floor 0.01, only when the word has at least 5 voiced frames (otherwise the word is unusable for pitch). Semitones from the reading's own median remove the speaker's register; the clip stops a tracker's
  octave error from dominating a word. Computed once, in `grounding/profile.py` (`measure_words`), for the baseline readings and for the participant alike.
- **Profile.** `WordProfile.pitch` (`PitchProfile`: `movement_st2` per passage word, `noise` = drift/word, `scale_sd` = how much a reading's overall expressiveness varies, `min_voiced_frames`, `deviation_clip_st`), built when at least 3 readings have pitch, with the same leave-one-out noise model as pace and loudness
  (sigma(n) = sqrt(drift^2 + word^2/n), fitted by non-negative least squares). Optional and hash-compatible: the canonical JSON leaves `pitch` out when absent, so every existing baseline keeps its hash and answers "flat pitch not checked" until it is rebuilt.
- **Detection.** The same scan as pace and loudness over runs of at least 10 words, on the statistic 0.5 * ln(sum observed / (sum expected * exp(2 tau))), one-sided (only LESS movement counts; livelier speech is never a flaw), where tau is the median over 10-word runs of the participant's overall movement
  against the baseline (so a speaker who is generally more or less expressive than the baseline readers is not flagged for it). A run is a finding when z is below -`Z_RUN_PITCH` (4.5) AND the RMS movement is at least `MIN_FLAT_PITCH_CHANGE_PCT` (35 %) smaller. A whole reading that moves at least `GLOBAL_PITCH_CHANGE_PCT` (45 %)
  less AND whose overall movement is more than the threshold times max(`scale_sd`, 0.08) below the baseline's is reported as one finding over the recording (`rule.feature` `pitch_overall_z`); the best run wins, its words are removed, the scan repeats, exactly as for pace and loudness.
  Floors keep a very regular baseline from producing impossible z-scores: drift 0.05, word 0.30, scale 0.08 (`SIGMA_FLOOR_PITCH_*`).
- **Evidence and score.** The existing `FlatPitchEvidence` is reused without a contract change: `f0_std_hz_in_window` and `f0_std_baseline_hz` carry the movement as Hz above the median pitch of the reading (ref * (2^(rms_st/12) - 1)) for the participant and for the baseline readers on the same words, `f0_std_z` is negative,
  `f0_voiced_fraction` the voiced share of the run. Severity: effect size ln of the ratio of baseline to observed movement divided by ln(3) (`SEVERITY_PITCH_FLAT_SEVERE_RATIO`: a third of the baseline's movement = 1.0) times the duration component. The explanation is a template (a run variant and a whole-reading variant) over the
  fact sheet, so the number guard still applies. When flat pitch is judged by the profile, the `pitch` feature is no longer "skipped": it is evaluated and weighted like pace and loudness (`pitch_not_scored` and `f0_unavailable` no longer appear); when it is not judged the new note `pitch_not_judged` states why
  (`transcript_mismatch`, `baseline_without_pitch_profile`, `pitch_not_measured` or `too_few_pitch_words`).
- **Tools.** The baseline builder, registration report (`pitch profile: built` / `NOT built (reason)`), the evaluation tool (`flat_pitch` is measured over the planned words, explained when missed and counted in precision/F1 like the other kinds, `measure_stretch` includes pitch) and the demo builder use the same code.
  The dashboard shows the evidence (movement in Hz against the baseline, z, voiced share), the help page explains it and the limits are stated on the baseline page.
- `pitch_instability` stays "not implemented": it needs recordings of unstable pitch to calibrate against (TASK-134). No flaw category was added.

Calibration (simulation only; no real flat-pitch recording exists):
- Synthetic readings of the real passages whose pitch moves like a person's (shared intonation, each reading adds its own register, wander and word jitter; two speakers, one more reserved), analysed with the real pitch tracker (pYIN) and the stand-in aligner.
- 40 clean readings with production code: **0 of 40 flagged** at `Z_RUN_PITCH` 4.0 and at 4.5. At 4.0 a stray extra range appeared next to the real one on a monotone take, at 4.5 it does not, so 4.5 was chosen (pace and loudness use 4.0 because their first real replay supported it; pitch has no real replay yet and the tracker adds noise, so it starts more careful).
- A stretch spoken with 0.1 or 0.3 times the movement: **found 8 of 8**, at the right words (overlap at least 70 % of the planned sentence, start and end within 1.5 s); 0.5 times: 4 of 8; 0.7 times: 0 of 8. The last two are by design: the size guard says a flaw is a clearly smaller movement (35 % less), not any dip.
- A reading that is flat as a whole is reported once, over the recording. An ordinary reading by the more reserved speaker is not flagged.

Reason:
Pitch must be judged against what the same words did, in semitones and relative to the reader, or a different voice would look like a flaw. One shared profile and one scan keep a single implementation (AGENTS.md section 11); reusing the evidence record keeps the API contract, so nothing downstream changes; keeping the pitch part optional keeps every
existing baseline valid.

Impact:
- Backend: `core/config.py` and `.env.example` (9 settings), `schemas/contracts.py` (`PitchProfile`, `WordProfile.pitch`, hash-compatible canonical JSON), `grounding/profile.py`, `grounding/profile_detection.py`, `grounding/candidates.py`, `grounding/severity.py`, `grounding/flaws.py`, `explanation/facts.py`, `explanation/templates.py`, `pipeline.py`.
  No API field changed: the rule features `pitch_run_z` and `pitch_overall_z` and the note code `pitch_not_judged` are new values (documented in `docs/architecture/api-contract.md`).
- Tools: `scripts/dataset/build_baseline_stats.py`, `prepare_recordings.py`, `evaluate_takes.py`, `scripts/demo/build_demo_samples.py` (demo samples regenerated: the flawed samples' composite scores rose because pitch is now a scored feature, e.g. mixed-flaws 79.38 to 84.54; a clean probe of 10 gave no flat-pitch finding).
- Dashboard: `evidence.ts`, `flawMeta.ts`, `FlawsPage`, `HelpPage`, `BaselinePage`, `notesMeta.ts` and their tests.
- Baselines must be rebuilt to get the pitch part: `python scripts\dataset\prepare_recordings.py data\incoming --build-baseline` and look for `pitch profile: built`.
- Tests (65 new; 1369 backend and 296 dashboard in all): 49 unit tests in `backend/tests/test_pitch_detection.py` (measurement, profile, hash compatibility, detection, `measure_stretch`, candidates, severity, evidence, explanation, settings) and one in `test_profile_detection.py` (notes),
  nine end-to-end tests in `tests/test_pitch_e2e.py` (synthetic expressive readings, real pitch tracker: a monotone sentence is found where it was put, ordinary readings of both speakers are not flagged, a flat reading is one finding, the baseline without the pitch part says so, repeated runs are identical),
  and updated tool tests (evaluation tool, baseline builder, registration report). A mutation check of the new code (53 injected bugs in the measurement, profile, detection, candidates, severity, evidence, notes and tools) first left 9 alive; tests were added for each and all are now caught except one
  equivalent change (the sign of a difference that the explanation layer writes as an absolute number by design).
- Docs: ARCHITECTURE.md 14.6, `docs/architecture/api-contract.md`, dataset guide, recording protocol (flat-pitch takes now recommended), README, PROJECT_STATE, TASKS (TASK-133 delivered; TASK-134, TASK-135 new).
- Not verified: nothing was tried on a real monotone recording; pitch trackers make octave and voicing errors on real voices and room noise, so the first real replay may show flat-pitch flags on clean takes (the evaluation tool lists them under "Listen to these first"); the thresholds are from simulation; scores changed
  for takes judged for pitch and are still uncalibrated (TASK-132).

Approved by: Team leader (delegated to coding agent)
Date: 2026-10-14

## DEC-043 — Flat Pitch Needs a More Permissive Voicing Decision Than the Global Pitch Statistics (Found on the First Real Recordings)

Status: ACCEPTED (agent decision under delegated authority; leader may revise)

Why: the team ran `prepare_recordings.py --build-baseline` with DEC-042 on its 60 real dev takes and both baselines reported `pitch profile: NOT built`. With five real takes of the team leader (3 baseline, 2 clean, passage p001) the cause was reproduced: the pitch tracker (pYIN) marks a frame as voiced only if its
confidence is at least 0.85, and on real speech only about 5 % of all frames pass (188 to 268 frames in 41 to 45 s), so most words had fewer than the 5 voiced frames the movement of a word needs. Synthetic test voices are clean, so every earlier test passed.

Decision:
- `F0Config.track_prob_threshold` (0.4) and two optional fields of `F0ExtractionResult` (`track_values_hz`, `track_voiced`): a second voicing decision from the same single pYIN run (no extra run, no extra time). At 0.4 about 30 % of all frames (about half of the speech frames) pass, median pitch and the 5th to 95th percentile stay in the
  same range as at 0.85 (about 195 Hz, 157 to 258 Hz). The strict `voiced` / `values_hz` that the global pitch statistics and every existing baseline use are unchanged, so no baseline or score changes except through the pitch part.
- `profile._pitch_movement` uses the permissive track when the extractor provides it (otherwise `voiced`/`values_hz`, as before).
- A reading that is flat as a whole is now reported as one finding over the recording, without also reporting pieces of it: with the permissive track a synthetic monotone reading got the whole-reading finding plus two short runs left standing by tracker noise.

Result on the five real takes (rough word timing spread by word length over the speech, because the real aligner cannot run here): the pitch part builds from 3 baseline takes (80 to 90 of 123 words usable per take, about 10 voiced frames per word, noise per word 0.49, spread of the overall expressiveness 0.26), and the two held-out clean takes
get no flat-pitch finding (and no pace or loudness finding). Still not checked: any real monotone take (TASK-135), the second speaker and passage p002.

Impact: `backend/app/services/features/f0.py`, `backend/app/services/grounding/profile.py`, `backend/app/services/grounding/profile_detection.py`; demo samples regenerated (clean probe 0 of 10); three new tests. Baselines must be rebuilt again (`prepare_recordings.py data\incoming --build-baseline`).

Approved by: Team leader (delegated to coding agent)
Date: 2026-10-14

## DEC-044 — Custom Passages: a Baseline From the User's Own Text and Recordings

Status: ACCEPTED (agent decision under delegated authority; leader may revise)

Why: the team leader asked for a feature in which a user uploads their own passage, records two or three baseline readings of it, and then records themselves reading it, with a dashboard page for it. The analysis already compares a recording with the effective delivery of the SAME
content, so the feature is a way to make the baseline, not a second pipeline (AGENTS.md section 2): the ordinary `POST /analyze` runs unchanged on the result.

Decision:
- **One implementation of baseline building.** The per-recording features and the pooling into a `BaselineStatsRecord` moved from `scripts/dataset/build_baseline_stats.py` to `backend/app/services/baseline_builder.py` (a move, no behaviour change; the script re-exports the names and its 44 tests pass
  unchanged). The dataset tool and the new `app.services.custom` service therefore build baselines exactly alike (same preprocessing, alignment against the text as the transcript, features, word profile with its pitch part).
- **Service and store** (`backend/app/services/custom.py`): the user's text (30 to 400 words, at least two sentences, because the baseline needs a pause between sentences) and 2 to 6 recordings; each recording is preprocessed, force-aligned to the text (the text IS the transcript), refused if fewer than 85 % of the words can be timed, and, when
  the speech recogniser is available, refused if what was recognised matches the text by less than 0.5 (warned below 0.75). A baseline from two recordings works but has no word profile (the word-by-word comparison needs three) and the response and the analysis say so; one from three has it.
  The id is `custom-<12 hex>`, derived from the normalised text and the recordings, so the same input is the same baseline (idempotent, nothing recomputed). Nothing of the audio is stored: only the record (`data/custom/baseline_stats/<id>.json`, hash-verified like any baseline) and the passage text (`data/custom/passages.json`), both git-ignored.
- **Lookup** (`BaselineProvider`, `PassageCatalog`): ids starting with `custom-` are resolved only in the custom directory, all other ids only in the project directories, so neither can shadow the other and a path cannot be built from an id. A caller that names the project directory (tests, tools) gets no custom baselines.
- **API contract 1.3.0**: `POST /custom/baselines`, `DELETE /custom/baselines/{baseline_id}`, three new models and `BaselineSummary.custom`; the analysis result is unchanged apart from the version string (demo samples regenerated).
- **Dashboard**: a Custom passage page (sidebar, command palette, `g c`): passage and name with early hints, recordings by upload or in-browser recording, make the baseline (with progress and a plain refusal message), a table of what was measured per recording and the warnings, the user's own reading (upload or recording) analysed against it, a list of custom baselines with use and delete,
  and custom baselines also appear on the New analysis page. The page only sends files and shows what the backend returns; the hints under the text box (word and sentence counts) mirror the server's limits for early feedback and the server checks again.

Reason: it gives a user a way to use the system on their own content without registering a dataset, keeps analytical truth in the backend and the single baseline builder, and keeps personal recordings out of storage. The word profile requires three recordings; supporting two keeps the entry barrier low at the cost of a less precise comparison, which is stated openly.

Impact:
- Backend: `services/baseline_builder.py` (moved code, `default_config_snapshot`), `services/custom.py`, `api/routes/custom.py`, `api/deps.py`, `core/baseline.py`, `core/passages.py`, `core/config.py` (10 `CUSTOM_*` settings, `.env.example`), `schemas/response.py`, `schemas/common.py` (1.3.0), `main.py` (router, CORS `DELETE`), `.gitignore` (`data/custom/`).
- Dashboard: `features/custom/CustomPage.tsx`, `state/custom.ts`, API client (`createCustomBaseline`, `deleteCustomBaseline`), types regenerated from the OpenAPI snapshot, router, sidebar, command palette, shortcuts, help, styles.
- Tests: `tests/test_custom_passage.py` (17: baseline made from three and from two recordings, only statistics stored, idempotence, the analysis finds a fast sentence against it and not in a clean reading, every refusal, the cap, id isolation, the pace warning, the HTTP round trip with delete; a mutation check of the new code with 28 injected bugs first left two alive, both now covered and caught); dashboard `custom.test.tsx`, `custom-state.test.ts`, client and router additions
  (26 new; 322 in all); axe on the page (both themes, phone width, recorder) finds no violations. Checked in a real browser against the real server with stand-ins for Whisper and WhisperX: passage typed, three recordings uploaded, baseline made, a reading with a fast sentence analysed (finding: too fast, 4.0 s), listed on New analysis, deleted.
- Not verified: the real WhisperX alignment and Whisper recognition on a user's own recordings (they cannot run in the development sandbox); how long the real alignment takes per recording; a custom baseline from a person's own voice has not been compared with project baselines. Thresholds are the project's initial, uncalibrated values.

Approved by: Team leader (delegated to coding agent)
Date: 2026-10-14

## DEC-045 — VAANI: One Visual Identity for the Whole Dashboard, and a Landing Page on the Home Route

Status: ACCEPTED (agent decision under delegated authority; leader may revise)

Why: the team leader asked for the whole site to be turned into a distinctive, premium "acoustic intelligence instrument" under the product name VAANI: a real landing page, one visual system across every existing page, a clearer radar and purposeful signal motion. The brief forbids new pages, routes or navigation destinations, removing features, fake data or statistics,
backend or API changes for visual reasons, and new dependencies. This is presentation only (AGENTS.md section 9): the frontend still computes nothing, and nothing in the pipeline, the API or the scoring changed.

Decision:
- **Identity.** Tokens (`styles/tokens.css`, both themes, one source): obsidian `#0B0F12` and graphite `#141B20` surfaces, warm ivory `#F4F0E8` for type and the primary button, hairline rules `rgba(220,235,242,.12)`, electric cyan `#70D6FF` for signal (the delivery, live audio, interactive highlights), burnt copper `#F28C5B` for deviation, muted steel `#82919B` for the reference and quiet text.
  Dark is now the default theme (Settings still offers System and Light); the light theme is the same system on ivory. Display type is Newsreader (page titles 21 to 26 % larger through `--fs-title`, headlines up to `--fs-display`), the interface IBM Plex Sans, every measurement, timestamp and technical label IBM Plex Mono: the fonts were already shipped, none was added.
  The surfaces carry two very faint pools of light and a fine grain (an inline SVG tile); no gradient text, no glassmorphism, no purple-pink.
- **Copper is the generic deviation colour; the eight finding hues stay.** The hues tell finding types apart (always with a glyph and a name) and were tuned to the new surfaces; copper is used wherever the pipeline reported a deviation without needing the type (severity bars, the deviation marks on the instrument and the radar). `tests/tokens.test.ts` still asserts WCAG 2.1 AA for every pair in both themes.
- **The home route is the landing page.** No route or page was added: `#/` now shows a hero (one headline, "Hear the difference. Understand the why."), a live instrument, three short sections (method, evidence, journey), the existing analysis flow unchanged (upload, recording, baseline choice, demo samples, recent), and a footer. On this route a landing navigation replaces the top bar (anchors to the sections, Library, Custom passage, Help, theme,
  menu, "Analyse a recording") and the sidebar is the drawer at every width, so no destination is hidden. The first call to action scrolls to the flow and moves focus to its heading; the second opens the demo analysis on the timeline. "New analysis" asked for from inside the app (sidebar, command palette, `g n`, the library's buttons) goes to the flow rather than to the hero: the hero is for arriving. The product has no accounts, so there was no "Sign in" to remove and none was added.
- **The hero instrument draws one real result.** The demo sample `mixed-flaws` (a synthetic voice analysed by the real pipeline): the speech-rate trace over the reference corridor (the baseline's mean and one and two standard deviations), the loudness envelope, a labelled interval for every finding with the backend's own evidence line (`evidenceHeadline`), and a probe whose readout is a lookup in the result's arrays (`readAt`).
  Copper appears only inside intervals the backend reported. Geometry is in `features/landing/heroModel.ts` (pure, tested: smoothing never leaves the range of two samples, bars are copper exactly inside findings). If the sample cannot be loaded the instrument is a fixed drawing labelled "Illustration" with no numbers and no time labels. Its audio is a local element (one voice at a time: it pauses the app's own player).
- **Pointer and motion rules.** One listener on the instrument (never global), written to CSS variables and refs through `requestAnimationFrame`: a soft light and a brighter copy of the bars under the pointer, and a slight depth shift of the atmosphere (grid, glow) only; data, text and buttons never move. A decorative marker travels along the trace until the pointer or the audio takes over. Everything that moves pauses when the instrument is out of view (IntersectionObserver)
  and is off for coarse pointers and for reduced motion (system setting or Settings): the picture is then complete at once. Transforms and opacity only; no React re-render per frame.
- **Radar.** The outer ring is the reference (the baseline reading, 100), the cyan shape is this recording, copper marks what findings cost (also in the legend); it grows into its values on load and on change (`charts/useTweened.ts`, finite, none when motion is reduced), a floating tooltip sits on the pointed corner (hidden from assistive technology; the readout below and the accessible names carry the same words),
  and room for labels is computed from the labels that sit at the sides so nothing is clipped on a phone. Data model, scales and keyboard behaviour are unchanged.
- **Playback-linked signal visuals.** The part already played is washed in the plots and in the delivery ribbon, the finding being played breathes while the audio runs, traces are drawn in from the left when a plot first appears (not again on zoom or pan; not in print), and the drop area's decorative trace wakes while a file is over it.
- **The printable report is paper.** `.paper` re-applies the light tokens, so the report looks on screen in a dark theme as it prints.
- **Accessibility fixes found on the way.** A closed drawer is hidden, not only moved off screen (its links were in the keyboard's tab order, now they are not); the drawer takes focus when it opens and returns it to its button; the flags on the instrument are real buttons with full accessible names.

Alternatives considered: a landing page as a separate route (forbidden by the brief and it would have duplicated the flow); a canvas instrument (a pointer-reactive canvas redraws everything every frame; SVG with transforms keeps data static and the cost near zero); one colour per finding type in the hero (the rainbow would have broken the identity); renaming the API title to "VAANI API" (it changes the OpenAPI snapshot and generated types for no visual reason: left as it is).

Impact:
- Dashboard only: `styles/*` (new `landing.css`), `app/Shell.tsx`, `Sidebar.tsx`, `App.tsx`, `features/landing/*` (new), `features/analyze/AnalyzePage.tsx` (the flow is now inside the landing), `charts/ScoreRadar.tsx`, `charts/useTweened.ts` (new), `charts/overlays.tsx`, `TimelineStack.tsx`, `app/Ribbon.tsx`, `components/Icon.tsx` (the mark: two strokes leave one point together, the delivery drifts away and ends in the copper marker), `components/ui.tsx` (large buttons), `lib/useMotion.ts` (new), `lib/settings.ts` (dark default), `index.html` (title, favicon, theme),
  README and the submission documents (product name). Backend, API contract, OpenAPI snapshot and the analysis: unchanged.
- Tests: 53 new dashboard tests (386 in all): hero geometry (21), the landing page (16: headline and calls to action, findings as buttons with their evidence, readout at the pointer, seek and play, the audio stopping with the page, illustration fallback, reduced motion, navigation without sign-in, drawer focus, "New analysis" going to the flow), radar (8 more, including the grow animation and the tooltip), the tween (5), the played wash and the live finding (3). Ten injected bugs in the new code: nine caught at once, one (labels allowed to leave the picture on a phone) first survived and is now covered. axe: no violations on all pages and states in both themes, with six landing states added
  (settled, pointer on the instrument, a finding playing, drawer open, phone), 70 of 70 combinations; a layout audit of 12 pages at 8 widths (320 to 2560) in both themes finds no horizontal overflow; browser smoke test 42 of 42 (13 new for the landing).
- Not verified: browsers other than Chromium (Safari and Firefox lack nothing the page needs; the travelling marker is skipped where CSS motion paths are unsupported); a real user's eye on a projector; the page with a real recording's analysis as the hero (the hero is always the synthetic demo sample).

Approved by: Team leader (delegated to coding agent)
Date: 2026-10-14

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
Peak normalization: −3 dBFS (replaced by scaling to the typical speech level, DEC-036, 2026-10-11)
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

Status: RESOLVED by DEC-028 (Option A selected, with amendments)

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

Status: SUPERSEDED by DEC-033 (no chart, HTTP, audio-waveform or CSS-framework library was adopted)

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
3. Severity formula choice (A vs B) — RESOLVED by DEC-028 (constants still need calibration)
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
