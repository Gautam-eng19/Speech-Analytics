# Project State

Last updated:
2026-10-13

Updated by:
Coding agent (registration and labelling tools delivered; control files synchronised, delegated by the team leader)

All statements below were checked against the repository and full test runs on 2026-10-13
(1076 backend tests passed, 2 smoke tests deselected; 290 dashboard tests passed; see section 9).
The real Whisper and WhisperX models were NOT run (see section 11).

---

# 1. CURRENT PHASE

Analytical core, orchestration and dashboard complete on synthetic speech; waiting for real data.

Pipeline status (ARCHITECTURE.md §4):
preprocessing ✅ → transcription ✅ → forced alignment ✅ → feature extraction ✅ (F0, MFCC, energy,
rate, pauses; clarity P1 ❌) → baseline statistics ✅ → normalization ✅ → contrastive comparison ✅
(delta = z) → flaw candidates ✅ (flat pitch ❌) → severity ✅ → evidence ✅ → scoring ✅ →
explanation ✅ (templates + number guard; no LLM) → API orchestration ✅ → dashboard ✅ (demo samples; never run on a real recording).

`POST /api/v1/analyze` now runs the whole pipeline and returns the contract-valid `AnalysisResult` (API contract 1.1.0);
`GET /api/v1/status/{id}` and `GET /api/v1/result/{id}` read the stored result. This is verified end to end
over HTTP on SYNTHETIC speech with injected flaws at known times, with Whisper and WhisperX replaced by exact-timing
stand-ins. It has never run on a real recording or with the real models.

The dashboard (`frontend/`, DEC-033) is served by the API at `/` and renders only backend output: upload or in-browser recording (DEC-035), overview and score,
timeline, findings with evidence (exportable as CSV), signals, transcript, baseline and method, printable report, library, settings, help, light and dark
themes. Four synthetic demo samples (DEC-034) open without a baseline. `GET /api/v1/baselines` (API contract 1.2.0) feeds the upload form.

---

# 2. PROJECT HEALTH

Overall:
🟡 Complete backend chain and dashboard on synthetic data; no real recordings, no real-model run

Repository:
🟢 main is current; all work is merged through pull requests. PR #14 fixed a `.gitignore` rule that had kept `frontend/src/lib/` out of PR #13:
main now installs, type-checks, tests and builds from a fresh clone (verified)

Architecture:
🟢 ARCHITECTURE.md canonical (notes added for DEC-023, 028, 030, 031, 032)

Backend:
🟢 All 11 backend stages, the cache and the three analysis endpoints are implemented and tested

Frontend:
🟢 Dashboard implemented and tested (290 tests; 50 injected bugs all caught); never run against the real models or a real recording; the recorder
has only met Chromium's fake microphone

Dataset:
🟡 The first 15 real takes exist (speaker spk_dev_01, passage p001: 3 baseline, 2 clean, 10 flawed) and passed the quality check, but only on the team's computer. The registration tool
(TASK-126) is built and tested with a stand-in aligner; nothing real is registered yet, so the repository's manifest is empty (the schema fixtures were retired) and /analyze answers
BASELINE_NOT_FOUND until a baseline is built from real takes. Running it with the real WhisperX is the next step and the main blocker for any real result.

Analysis pipeline:
🟢 12 of 12 stages implemented; flat_pitch detection is missing

Testing:
🟢 1076 backend + 290 dashboard tests pass. Real-model smoke tests (`-m smoke`: Whisper base, WhisperX) have not been run.

Demo:
🟡 Dashboard with four labelled synthetic samples works end to end; a real demo needs recordings and a baseline (TASK-122)

---

# 3. CURRENT OBJECTIVE

Turn the synthetic-speech proof into a real one (the recording kit is ready; the next step is the team leader's decisions and the nine-take pilot, see
`docs/methodology/dataset-guide.md`): record the controlled dataset, build a baseline, run the real
models (`pytest -m smoke`), calibrate thresholds and weights on the injected flaws, and show the real results in the dashboard.

---

# 4. CURRENT MILESTONE

Milestone M0 — Foundation: complete except the three-machine environment check.
Milestone M1 — Analytical core: complete on synthetic data; calibration and real data outstanding.
Milestone M2 — Dashboard: complete on synthetic data (demo samples); real data outstanding.

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

Added 2026-10-10: dashboard (TASK-080 to TASK-089), API contract 1.2.0 with `GET /api/v1/baselines`, CORS and static serving of
`frontend/dist`, OpenAPI snapshot with a drift test, synthetic demo samples (DEC-033, DEC-034); in-browser recording and CSV export of findings
(DEC-035, TASK-090, TASK-092); `frontend/src/lib/` finally tracked in git (PR #14, TASK-093).

---

# 6. IN PROGRESS

None.

---

# 7. BLOCKED / NEEDS A DECISION

- Recordings are not registered. The first 15 takes (one speaker) exist on the team's computer only; the registration with the real alignment model has not run, so no real baseline exists.
  Calibration (DEC-P005, P007), evaluation and any real demo are blocked on TASK-122 and on that run.
- The real Whisper/WhisperX path has never been run by the agent (model downloads are not possible in its sandbox); it needs a
  machine with the models: `python -m pytest -m smoke`, then one real recording through /analyze.
- Flat pitch: BaselineStats has only the pooled global F0 std; a valid detector needs a baseline statistic of
  F0 variation within a window (record-contract change). Until then pitch is reported as "not scored".
- Team-leader confirmation requested for the agent decisions DEC-024 to DEC-038 (all made under delegated authority, except DEC-036 and DEC-037, which the leader approved). DEC-033 also
  supersedes the proposed DEC-P009 (no chart / HTTP / waveform / CSS-framework library).
- Energy rule too coarse (TASK-128): loudness scaling now uses the typical speech level (DEC-036, approved and implemented 2026-10-11), which keeps
  the rest of a take at the baseline level and gives a loud sentence a z-score that grows with its loudness, but the single-frame energy rule
  (z > 2 on 10 ms frames, baseline std about 9 dB) still flags none of +6 to +18 dB or -12 to -20 dB changes. Windowed levels (0.5 to 1 s) and
  calibration on real recordings are needed; the energy rule is an analytical change for the leader to approve.

---

# 8. ACTIVE TASKS

The team leader decided speakers (2 dev + 2 test), equipment (USB headset) and loudness scaling on 2026-10-11 (DEC-036, DEC-037). The first 15 takes of spk_dev_01 were recorded and passed the checker. Next: run `scripts/check_environment.py --download-models` and `scripts/dataset/prepare_recordings.py data/incoming --build-baseline` on the team's computer (first real run of WhisperX; TASK-126 built 2026-10-13, DEC-038), listen to the proposed flaws, then analyse a take on the site. Candidates: collect recordings (TASK-122), calibration and evaluation (TASK-100 to TASK-107 on real data), flat pitch
(after the baseline-statistic decision), a first real recording session that also tries the in-browser recorder, the loudness-normalisation decision (section 7).

---

# 9. RECENT CHANGES

2026-10-10:
- Dashboard implemented (React + Vite + TypeScript, no chart/UI library; DEC-033): application shell with a sidebar, whole-recording
  ribbon, playback bar and command palette; light and dark themes; pages for new analysis, library, overview, timeline, findings,
  signals, transcript, baseline and method, printable report, settings and help. It computes no analytics.
- Backend support: API contract 1.2.0 (`GET /api/v1/baselines`), CORS from `CORS_ORIGINS`, static serving of `frontend/dist` at `/`,
  OpenAPI snapshot (`frontend/openapi.json`) exported by `scripts/export_openapi.py` and guarded by a drift test.
- Synthetic demo samples with the real pipeline's results and ground truth (DEC-034).
- Found and fixed by the dashboard tests: a request replaced by a newer one could still overwrite the open analysis (and an aborted
  sample fetch was shown as an error); a duration of 119.6 s was written "1 min 60 s"; minute-long tick labels lacked zero padding.
- Colour tokens were adjusted to meet WCAG AA in both themes and a test now guards them; an axe-core audit of every page and interactive
  state (44 combinations, both themes) found and removed several accessibility defects and now passes (`npm run a11y`).
- In-browser recording (TASK-090, DEC-035): "Record now" on the New analysis page takes raw samples with the browser's voice processing requested off,
  converts them to a 16 kHz mono WAV with a deterministic resampler and hands the file to the upload form; level and clipping indicators are
  capture aids only. "Export CSV" of the findings and "Copy a link to this page" were added (TASK-092). `npm run smoke` (29 checks in Chromium, incl.
  a take from the fake microphone) joined `npm run a11y`, which now covers 50 combinations including the recorder states.
- Loudness scaling by typical speech level (DEC-036): replaces peak scaling to -3 dBFS; 8 tests re-based (3 in the pipeline, 1 baseline builder,
  4 demo-sample integrity), 7 new preprocessing tests replace the one peak test; demo samples regenerated; 4 dashboard tests now read their expected numbers from the sample; end-to-end experiment recorded in DEC-036.
- A mutation check of the new code (23 injected bugs in the recorder, converter, WAV writer and CSV writer) found one gap, the converted length when
  the last output sample is incomplete; a test now covers it and all are caught.
- **Repository defect found and fixed:** the Python-template rule `lib/` in `.gitignore` had hidden `frontend/src/lib/` from git, so PR #13 reached main
  without eleven modules and a fresh clone failed to type-check (234 errors) or build. The working copy that produced the PR still had the files,
  which is why local checks passed. Fixed in PR #14 (negation in `.gitignore`, modules committed). From now on a PR is verified from a fresh clone
  of its branch before it is merged.
- Full runs: 838 backend tests (2 smoke deselected) and 290 dashboard tests passed.

2026-10-13:
- Registration and labelling tools (TASK-126, DEC-038): `scripts/dataset/prepare_recordings.py` registers a folder of checked takes (copy to data/raw, SHA-256, preprocessing, WhisperX alignment with the passage text as the
  transcript, plausibility checks, alignment JSON, manifest/speaker/passage entries, proposed flaw annotations that a person confirms by ear, a "was the planned flaw really performed" check against the speaker's own
  baseline takes, Audacity label files, dataset validation, optional baseline build; idempotent; `--replace` for re-recorded takes). `scripts/dataset/take_checks.py` holds the pure checks,
  `scripts/check_environment.py` checks a computer and downloads the models once. The schema fixtures were retired (real passages, four anonymous speakers, empty manifest). 127 new tests (1076 in all),
  including the committed plan and passages end to end with synthetic takes; 74 injected bugs: all caught after the gaps found were closed. A failing alignment check that did not stop the
  take from being registered was found by the tests and fixed. Not run: the real Whisper and WhisperX models.

2026-10-11:
- Dataset recording kit (TASK-125): `scripts/dataset/make_plan.py` (deterministic plan, nested tiers pilot 9 / minimum 36 (28) / recommended 112 (86) takes, per-speaker prompter page,
  session log), `check_recordings.py` (format, size, clipping, level, room noise, silence at the ends, length, hum), shared `passage_text.py`, final passages
  `data/plan/passages_v1.json`, a plain-language guide `docs/methodology/dataset-guide.md` and a consent form template. 103 tests (949 backend/integration tests in all);
  20 injected bugs all caught (two gaps found and closed); the prompter was driven in a real Chromium. Registration/labelling (TASK-126) and evaluation tools (TASK-127) are
  not written yet: they follow the pilot on purpose.

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

Accepted decisions DEC-001 to DEC-022 are unchanged. Added 2026-10-09 and 2026-10-10 (DEC-023 to DEC-035 are agent decisions under delegated
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
- Dashboard stack, boundary (renders backend output only), contract 1.2.0, serving, honest-presentation and accessibility rules (DEC-033)
- Demo samples: synthetic voice, exact word timings, real pipeline, published selection rule, labelled everywhere (DEC-034)
- In-browser recording as raw samples with voice processing off, a deterministic 16 kHz WAV, 5-minute limit; CSV export of findings (DEC-035)
- Loudness scaled by the typical speech level (DEC-036) and the dataset plan v1 (DEC-037): approved by the team leader on 2026-10-11
- Registering recordings: alignment with the passage text, proposed then confirmed annotations, a "performed" check, retired fixtures (DEC-038, 2026-10-13)

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
- Energy detection (low/high energy) judges single 10 ms frames against a wide baseline spread and breaks a run at any in-range frame,
  so it is probably too fragile for real speech; moderate loudness changes are unlikely to be found until the rule is smoothed over
  about 0.5–1 s windows and calibrated on real data (measured on synthetic speech only).
- Rate flaws are window-resolution: with 8 s windows a `too_fast` interval can begin several seconds before the fast words
  (about 4 s in the synthetic test) and overlapping flagged windows merge. Temporal precision for rate is therefore coarse.
- `reliability` is the constant 1.0 and `low_confidence` is always false at P0; neither is a measured confidence.
- Baseline-relative normalization is not speaker adaptation (pitch/loudness offsets of the participant remain).
- Test-split leakage question: whether test-speaker baselines may feed statistics for test participants is undecided
  (the builder requires an explicit --splits).
- One analysis runs at a time and stored results are never evicted (no retention policy); there is no authentication. CORS allows only
  the origins in `CORS_ORIGINS` (default: the Vite dev server); the API serves the dashboard itself in the normal case.
- Dev tooling: `npm audit` reports advisories in the vitest 3 test runner (`tinypool`, `@vitest/mocker`; fixed only by vitest 5, which needs Node 22.12+);
  `npm audit --omit=dev` is clean, so nothing shipped is affected. Revisit when the team standardises on Node 22+.
- Dashboard: never run against the real models or a real recording; upload was tested in a real browser against a MOCKED API and in
  component tests. Charts are SVG (fine for minutes of audio after thinning, not for hours). A result opened by id has no audio.
- The registration tool (TASK-126) has only seen synthetic takes and a stand-in aligner. The real WhisperX may place words differently on deliberate slow, fast or silent stretches; the plausibility and
  "performed" limits (`AlignmentGates`, `PerformedGates`) are unvalidated; a baseline can fail to build when the baseline takes contain too few natural pauses (it then reports why); on Windows
  the install (`pip install -r requirements.txt`, torch 2.8 pinned by whisperx) and the model downloads are untried.
- The dataset kit (TASK-125) has only seen synthetic audio. The checker's thresholds (room noise, hum, silence at the ends, length) come from the protocol and are unvalidated on
  real recordings, the plan's target durations are estimates at 150 words a minute, and the prompter was tested in Chromium only. The pilot is the first real test.
- The recorder (DEC-035) has been exercised with test doubles and Chromium's fake microphone only: a real microphone, Safari, Firefox and phones are
  untested, and so is how real room noise and input gain behave with the unchanged analysis. A browser may ignore the request to disable voice
  processing; the panel warns when it reports that.
- `.gitignore` is a Python template: its generic names (`lib/`, `build/`, `parts/`, `var/`, `env/`, `eggs/`, `downloads/`, `wheels/`, `sdist/`) match a
  directory of that name anywhere in the repository and silently exclude it (this hid `frontend/src/lib/` once). Check `git status --ignored` when
  adding a folder. Since 2026-10-11 it ignores `data/raw/*` and `data/incoming/` so recordings of people are not committed by accident (AGENTS.md section 22); audio kept elsewhere in the tree
  (for example a new folder) is not covered.
- Detector findings from building the demo samples (synthetic speech; see DEC-034): the per-event pause rule (z > 2 over about twenty
  pauses) flagged 6 of 10 CLEAN takes, so the false-flag rate must be calibrated below about 10 %; the frame-level energy rule missed a
  20 dB quieter sentence in all 40 candidate takes; the absolute -50 dBFS pause threshold splits quiet speech into false pauses; peak
  normalisation makes a louder stretch hard to detect (see the loudness-normalisation item in section 7); rate findings are
  window-resolution and long pauses inflate `too_slow`. The demo samples show a miss and the false-flag diagnostic on purpose.
- MP3 decoder delay is not measured; MP3 timestamps may be offset by a few tens of ms.
- Dependencies are `>=` ranges without a lockfile; WhisperX is not installed in the verification environment. Library
  versions are part of the analysis identity, so a changed environment produces new ids rather than stale results.
- Stored alignment files are assumed to be AlignedTranscript JSON in processed-audio time (not specified by the dataset schema).
- AGENTS.md §27 still says "Initialization / implementation not started" (protected file; not edited).
- CONFIG_VERSION has not been bumped for the new detection, severity and scoring constants; bump at the calibration freeze (DEC-014).
  Meanwhile `config_fingerprint` changes whenever any analytical constant changes, so the cache cannot go stale.

---

# 12. NEXT PRIORITIES

1. Register the first 15 real takes with `prepare_recordings.py` (TASK-126; first real WhisperX run), listen to the proposed flaws, build the real baseline, run the real-model smoke tests and
   one real recording through /analyze; fix whatever the real models reveal. Then record the other speakers and passage p002 (TASK-122) and write the evaluation tools (TASK-127).
2. Calibrate thresholds, severity and weights on the controlled flaws (TASK-100 to TASK-107 on real data), then set
   `THRESHOLDS_CALIBRATED=true`, bump CONFIG_VERSION and freeze.
3. Decide the within-window F0-variation baseline statistic and implement flat pitch.
4. Run the dashboard against real API output (needs priority 1), try the in-browser recorder with a real microphone, then decide on a waveform (TASK-091).
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
