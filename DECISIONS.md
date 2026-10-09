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
  1e-9 floor. Values are relative loudness after peak normalization, not absolute levels.
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
