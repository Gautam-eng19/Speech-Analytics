# Project State

Last updated:
2026-10-09

Updated by:
Coding agent (control-file synchronization with verified code state, delegated by the team leader)

All statements below were checked against the repository and a full test run on 2026-10-09
(487 tests passed, 0 failed, real pytest/scipy/librosa/av/openai-whisper; see section 9).

---

# 1. CURRENT PHASE

Core analytical services — implemented through flaw-candidate detection.

Pipeline status (ARCHITECTURE.md §4):
preprocessing ✅ → transcription ✅ → forced alignment ✅ → feature extraction ✅ (F0, MFCC, energy,
rate, pauses; clarity P1 ❌) → baseline statistics ✅ → normalization ✅ → contrastive comparison ✅
(delta = z) → flaw candidates ✅ (flat pitch ❌) → severity ❌ → scoring ❌ → evidence ❌ →
explanation ❌ → API orchestration ❌ → dashboard ❌.

There is no end-to-end analysis yet: POST /api/v1/analyze still only validates the upload.

---

# 2. PROJECT HEALTH

Overall:
🟡 Good engineering base, no end-to-end demo and no real data

Repository:
🟢 main is current; all work is merged through pull requests

Architecture:
🟢 ARCHITECTURE.md canonical (updated 2026-10-09 for the audio provenance and baseline contracts)

Backend:
🟡 Services implemented and tested; orchestration, severity, scoring, explanation, cache missing

Frontend:
⚪ Not started (placeholder directory)

Dataset:
🔴 No recordings. data/ holds schema fixtures only (zero SHA-256 hashes, no audio); the baseline
builder correctly refuses them. This is the main blocker for any real result.

Analysis pipeline:
🟡 7 of 12 stages implemented (see section 1)

Testing:
🟢 487 tests pass. Real-model smoke tests (`-m smoke`: Whisper base, WhisperX) have not been run.

Demo:
⚪ Not started

---

# 3. CURRENT OBJECTIVE

Make one genuine end-to-end analysis possible: severity → scoring → evidence → explanation →
orchestrated /api/v1/analyze, while recordings are collected so thresholds and weights can be calibrated.

---

# 4. CURRENT MILESTONE

Milestone M0 — Foundation: complete except the three-machine environment check.
Milestone M1 — Analytical core: in progress (features, baseline, normalization, candidates done).

M1 success criteria:

- [x] audio preprocessing with source-time provenance
- [x] transcription, alignment, alignment validation
- [x] F0, MFCC, energy, speech rate, pauses
- [x] baseline statistics (record, builder, provider)
- [x] baseline-relative normalization
- [x] flaw candidates for rate, energy, pauses
- [ ] flat pitch detection (needs a within-window F0-variation baseline statistic)
- [ ] severity (DEC-P006 undecided), reliability, evidence payloads
- [ ] deterministic scoring
- [ ] explanation (template first)
- [ ] orchestrated /api/v1/analyze + /status + /result + cache
- [ ] real baseline + participant recordings and an evaluation

---

# 5. COMPLETED (commits on main)

Foundation: repository, control files, ARCHITECTURE.md, API contract (a7ac334), dataset schema and
validator (e3c2697), dev environment (7e2d061), FastAPI skeleton + health (0a24470), upload validation (a1b8048).

Services: preprocessing (f1a0836), F0 (dfbe1f5), MFCC (e2a440c), Whisper transcription (29e6e39),
WhisperX alignment (52ded6e), alignment validation (c3b5bbb).

Added 2026-10-09: trim provenance (33e9330), energy (468a01b), speech rate (2a7247a), pauses (88b608d),
BaselineStatsRecord / BaselineProvider / build_baseline_stats.py (834c08f, cc28792, 14aa3d5),
normalization (8777964), flaw candidates (d1268c5).

---

# 6. IN PROGRESS

None.

---

# 7. BLOCKED / NEEDS A DECISION

- Recordings do not exist. Calibration (DEC-P005, P007), evaluation and any real demo are blocked on TASK-122.
- DEC-P006 (severity Option A vs B) must be settled before TASK-052.
- Flat pitch: BaselineStats has only the pooled global F0 std; a valid detector needs a baseline statistic of
  F0 variation within a window (record-contract change).
- Meaning of the API's `baseline_id` versus `passage_id` is unresolved (BaselineProvider is keyed by passage_id).

---

# 8. ACTIVE TASKS

None. Candidates in dependency order: severity (TASK-052), evidence (TASK-053), scoring (TASK-060–062),
explanation (TASK-070/071), orchestration + cache, then the frontend.

---

# 9. RECENT CHANGES

2026-10-09:
- TASK-013A, 032, 033, 034, 040, 041, 043/050/051 implemented and merged (see section 5).
- Verification environment fixed: `av` and `openai-whisper` installed; the 3 previously failing tests were
  environment-only (missing packages) and pass. Full suite: 487 passed.
- ARCHITECTURE.md §9.1/§9.5/§9.6 updated; DECISIONS.md gained DEC-023 to DEC-027; TASKS.md statuses
  synchronized with evidence; README.md and docs/setup.md rewritten; root pytest.ini now deselects smoke tests.

---

# 10. CURRENT TECHNICAL DECISIONS

Accepted decisions are unchanged (DEC-001 to DEC-022). Added 2026-10-09 (DEC-023 to DEC-027; DEC-024 to 027
are agent decisions under delegated authority and await team-leader confirmation):

- Source-time provenance of trimming; conversion applied once at response assembly (DEC-023)
- Baseline statistics conventions: active-frame energy, sample std, rounding, sha256, passage_id key (DEC-024)
- Normalization semantics: missing stays NaN, unusable spread is explicit, energy rule read from the baseline (DEC-025)
- Candidate-detection conventions: strict thresholds, covered-frame runs, unmerged pauses, flat pitch deferred (DEC-026)
- Feature-extraction conventions: energy window, rate window membership/time axis, pause agreement rule (DEC-027)

Still PROPOSED and in use as starting values only: thresholds (DEC-P005), severity (DEC-P006), weights (DEC-P007).

---

# 11. KNOWN RISKS

- No data: every threshold is an uncalibrated starting value; false-positive/recall rates are unmeasured.
  Only synthetic-tone tests exist; behaviour on real speech (pYIN on voiced speech, VAD at −50 dBFS,
  WhisperX alignment quality) is unvalidated.
- Single-reference baselines: the rate (and pause) spread rests on very few observations and can be tiny,
  making z-scores hypersensitive. Within-phrase pauses need at least 2 observations to build a baseline.
- Rate flaws are window-resolution (several seconds) and overlapping flagged windows merge.
- Baseline-relative normalization is not speaker adaptation (pitch/loudness offsets of the participant remain).
- Test-split leakage question: whether test-speaker baselines may feed statistics for test participants is undecided
  (the builder requires an explicit --splits).
- Cache key (ARCHITECTURE §26.4) must include trim_start_s or a source-audio hash; sha256 covers only trimmed samples.
- All-silence input yields an empty array that downstream extractors reject (no API-level error path yet).
- MP3 decoder delay is not measured; MP3 timestamps may be offset by a few tens of ms.
- Dependencies are `>=` ranges without a lockfile; WhisperX is not installed in the verification environment.
- Stored alignment files are assumed to be AlignedTranscript JSON in processed-audio time (not specified by the dataset schema).
- AGENTS.md §27 still says "Initialization / implementation not started" (protected file; not edited).
- CONFIG_VERSION has not been bumped for the new detection constants; bump at the calibration freeze (DEC-014).

---

# 12. NEXT PRIORITIES

1. Decide severity (DEC-P006) and implement TASK-052, then evidence (TASK-053) and the final flaw schema (TASK-054).
2. Scoring (TASK-060–062) with explicit missing-feature handling.
3. Template explanations (TASK-070/071) from evidence only.
4. Orchestrated /api/v1/analyze with cache, /status and /result.
5. Collect a small controlled recording set (TASK-122) and calibrate.
6. Frontend (TASK-080+) against real API output.

---

# 13. UPDATE RULE

This file reflects the current project reality.

After completing a meaningful task:

- update completed work
- update active work
- record blockers
- record important implementation changes
- identify the next priority

Do not rewrite historical information unnecessarily.

# END
