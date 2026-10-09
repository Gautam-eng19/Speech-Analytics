# Project State

Last updated:
2026-10-09

Updated by:
Coding agent (control-file synchronization with verified code state, delegated by the team leader)

All statements below were checked against the repository and a full test run on 2026-10-09
(810 tests passed, 0 failed, 2 smoke tests deselected; real pytest/scipy/librosa/av/openai-whisper; see section 9).
The real Whisper and WhisperX models were NOT run (see section 11).

---

# 1. CURRENT PHASE

Analytical core and orchestration complete on synthetic speech; waiting for real data.

Pipeline status (ARCHITECTURE.md §4):
preprocessing ✅ → transcription ✅ → forced alignment ✅ → feature extraction ✅ (F0, MFCC, energy,
rate, pauses; clarity P1 ❌) → baseline statistics ✅ → normalization ✅ → contrastive comparison ✅
(delta = z) → flaw candidates ✅ (flat pitch ❌) → severity ✅ → evidence ✅ → scoring ✅ →
explanation ✅ (templates + number guard; no LLM) → API orchestration ✅ → dashboard ❌.

`POST /api/v1/analyze` now runs the whole pipeline and returns the contract-valid `AnalysisResult` (API contract 1.1.0);
`GET /api/v1/status/{id}` and `GET /api/v1/result/{id}` read the stored result. This is verified end to end
over HTTP on SYNTHETIC speech with injected flaws at known times, with Whisper and WhisperX replaced by exact-timing
stand-ins. It has never run on a real recording or with the real models.

---

# 2. PROJECT HEALTH

Overall:
🟡 Complete backend chain on synthetic data; no real recordings, no frontend, no real-model run

Repository:
🟢 main is current; all work is merged through pull requests

Architecture:
🟢 ARCHITECTURE.md canonical (notes added for DEC-023, 028, 030, 031, 032)

Backend:
🟢 All 11 backend stages, the cache and the three analysis endpoints are implemented and tested

Frontend:
⚪ Not started (placeholder directory)

Dataset:
🔴 No recordings. data/ holds schema fixtures only (zero SHA-256 hashes, no audio); the baseline
builder correctly refuses them, and /analyze answers BASELINE_NOT_FOUND until a baseline file exists.
This is the main blocker for any real result.

Analysis pipeline:
🟢 11 of 12 stages implemented; flat_pitch and the dashboard are missing

Testing:
🟢 810 tests pass. Real-model smoke tests (`-m smoke`: Whisper base, WhisperX) have not been run.

Demo:
⚪ Not started

---

# 3. CURRENT OBJECTIVE

Turn the synthetic-speech proof into a real one: record the controlled dataset, build a baseline, run the real
models (`pytest -m smoke`), calibrate thresholds and weights on the injected flaws, then build the dashboard.

---

# 4. CURRENT MILESTONE

Milestone M0 — Foundation: complete except the three-machine environment check.
Milestone M1 — Analytical core: complete on synthetic data; calibration and real data outstanding.

M1 success criteria:

- [x] audio preprocessing with source-time provenance
- [x] transcription, alignment, alignment validation
- [x] F0, MFCC, energy, speech rate, pauses
- [x] baseline statistics (record, builder, provider)
- [x] baseline-relative normalization
- [x] flaw candidates for rate, energy, pauses
- [x] severity (DEC-028), typed evidence, final flaw schema (API contract 1.1.0)
- [x] deterministic scoring with explicit missing-feature handling (DEC-030)
- [x] template explanations with a number-grounding guard (DEC-031)
- [x] orchestrated /api/v1/analyze + /status + /result + cache (DEC-032)
- [ ] flat pitch detection (needs a within-window F0-variation baseline statistic)
- [ ] real baseline + participant recordings, the real-model run and an evaluation

---

# 5. COMPLETED (commits on main)

Foundation: repository, control files, ARCHITECTURE.md, API contract (a7ac334), dataset schema and
validator (e3c2697), dev environment (7e2d061), FastAPI skeleton + health (0a24470), upload validation (a1b8048).

Services: preprocessing (f1a0836), F0 (dfbe1f5), MFCC (e2a440c), Whisper transcription (29e6e39),
WhisperX alignment (52ded6e), alignment validation (c3b5bbb).

Added 2026-10-09: trim provenance (33e9330), energy (468a01b), speech rate (2a7247a), pauses (88b608d),
BaselineStatsRecord / BaselineProvider / build_baseline_stats.py (834c08f, cc28792, 14aa3d5),
normalization (8777964), flaw candidates (d1268c5), control-document sync (0e1d03d), severity (c0e351b),
evidence + final flaw schema / API contract 1.1.0 (c0b53d2), scoring (8ab467a), explanations + guard (d79feb8),
pipeline orchestration + result cache + /status + /result (the pull request that updated this file).

---

# 6. IN PROGRESS

None.

---

# 7. BLOCKED / NEEDS A DECISION

- Recordings do not exist. Calibration (DEC-P005, P007), evaluation and any real demo are blocked on TASK-122.
- The real Whisper/WhisperX path has never been run by the agent (model downloads are not possible in its sandbox); it needs a
  machine with the models: `python -m pytest -m smoke`, then one real recording through /analyze.
- Flat pitch: BaselineStats has only the pooled global F0 std; a valid detector needs a baseline statistic of
  F0 variation within a window (record-contract change). Until then pitch is reported as "not scored".
- Team-leader confirmation requested for the agent decisions DEC-024 to DEC-032 (all made under delegated authority).

---

# 8. ACTIVE TASKS

None. Candidates: collect recordings (TASK-122), calibration and evaluation (TASK-100 to TASK-107 on real data),
the frontend (TASK-080+), flat pitch (after the baseline-statistic decision).

---

# 9. RECENT CHANGES

2026-10-09:
- TASK-013A, 032, 033, 034, 040, 041, 043/050/051 implemented and merged (see section 5).
- TASK-052/053/054 (severity, evidence, final flaw schema), TASK-060/061/062 (scoring), TASK-070/071/072
  (explanations and guard) and the pipeline orchestration with cache and result endpoints implemented and merged.
- Found and fixed by the orchestration tests: a flaw touching the first frame of a recording had a negative start time
  and failed the contract (energy runs are now clipped to the audio, amending DEC-026); error details leaked decoder text and a
  server path (details are now fixed or built from validated identifiers only).
- Verification environment: `av` and `openai-whisper` installed. Full suite: 810 passed, 2 smoke tests deselected.
- DECISIONS.md gained DEC-023 to DEC-032; ARCHITECTURE.md, the API contract (1.1.0), TASKS.md, README.md and
  docs/setup.md were updated.

---

# 10. CURRENT TECHNICAL DECISIONS

Accepted decisions DEC-001 to DEC-022 are unchanged. Added 2026-10-09 (DEC-023 to DEC-032 are agent decisions under delegated
authority and await team-leader confirmation):

- Source-time provenance of trimming; conversion applied once at response assembly (DEC-023)
- Baseline statistics conventions: active-frame energy, sample std, rounding, sha256, passage_id key (DEC-024)
- Normalization semantics: missing stays NaN, unusable spread is explicit, energy rule read from the baseline (DEC-025)
- Candidate-detection conventions: strict thresholds, covered-frame runs, unmerged pauses, flat pitch deferred (DEC-026)
- Feature-extraction conventions: energy window, rate window membership/time axis, pause agreement rule (DEC-027)
- Severity = deviation magnitude x flagged duration, no duration term for pauses (DEC-028)
- API contract 1.1.0 and the source-time response timeline (DEC-029)
- Scoring: penalty = 30 x severity x reliability; unevaluated features are omitted and weights renormalised (DEC-030)
- Explanations from a fact sheet, checked by an independent number guard; minimal fallback (DEC-031)
- Orchestrator, analysis identity covering every input, result store, error mapping, notes (DEC-032)

Still PROPOSED and in use as starting values only: thresholds (DEC-P005), weights (DEC-P007). Results say so
(`thresholds_uncalibrated` note) until `THRESHOLDS_CALIBRATED=true` is set after calibration.

---

# 11. KNOWN RISKS

- No data: every threshold and weight is an uncalibrated starting value; false-positive/recall rates are unmeasured.
  Only synthetic-tone tests exist; behaviour on real speech (pYIN on voiced speech, VAD at −50 dBFS,
  WhisperX alignment quality) is unvalidated.
- The real Whisper/WhisperX models were never run in the verification environment; the model loading time of the first
  request, memory use and the accuracy of real word timings are unknown. The manual-transcript path relies on WhisperX
  wrapping text without segments into one segment (read from the code, not run).
- Single-reference baselines: the rate (and pause) spread rests on very few observations and can be tiny,
  making z-scores hypersensitive; results carry `baseline_thin_*` notes. Cross-sentence pauses need a baseline with at
  least two such pauses to be comparable (otherwise `pauses_not_comparable`).
- Rate flaws are window-resolution: with 8 s windows a `too_fast` interval can begin several seconds before the fast words
  (about 4 s in the synthetic test) and overlapping flagged windows merge. Temporal precision for rate is therefore coarse.
- `reliability` is the constant 1.0 and `low_confidence` is always false at P0; neither is a measured confidence.
- Baseline-relative normalization is not speaker adaptation (pitch/loudness offsets of the participant remain).
- Test-split leakage question: whether test-speaker baselines may feed statistics for test participants is undecided
  (the builder requires an explicit --splits).
- One analysis runs at a time and stored results are never evicted (no retention policy); there is no authentication and no CORS
  configuration yet (the frontend will need CORS).
- MP3 decoder delay is not measured; MP3 timestamps may be offset by a few tens of ms.
- Dependencies are `>=` ranges without a lockfile; WhisperX is not installed in the verification environment. Library
  versions are part of the analysis identity, so a changed environment produces new ids rather than stale results.
- Stored alignment files are assumed to be AlignedTranscript JSON in processed-audio time (not specified by the dataset schema).
- AGENTS.md §27 still says "Initialization / implementation not started" (protected file; not edited).
- CONFIG_VERSION has not been bumped for the new detection, severity and scoring constants; bump at the calibration freeze (DEC-014).
  Meanwhile `config_fingerprint` changes whenever any analytical constant changes, so the cache cannot go stale.

---

# 12. NEXT PRIORITIES

1. Collect a small controlled recording set (TASK-122), build a real baseline, and run the real-model smoke tests and
   one real recording through /analyze; fix whatever the real models reveal.
2. Calibrate thresholds, severity and weights on the controlled flaws (TASK-100 to TASK-107 on real data), then set
   `THRESHOLDS_CALIBRATED=true`, bump CONFIG_VERSION and freeze.
3. Decide the within-window F0-variation baseline statistic and implement flat pitch.
4. Frontend (TASK-080+) against the real API output (add CORS).
5. Optional: an LLM explanation provider that receives only the fact sheet and passes the existing guard.

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
