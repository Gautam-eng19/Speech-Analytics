# Project State

Last updated:
2026-10-14

Updated by:
Coding agent (registration tools, rounds of accuracy work, flat pitch, custom passages, then the VAANI visual identity; control files synchronised, delegated by the team leader)

All statements below were checked against the repository and full test runs on 2026-10-13
(1389 backend tests passed, 2 smoke tests deselected; 386 dashboard tests passed, 42 smoke and 70 accessibility checks passed; see section 9).
The real Whisper and WhisperX models were NOT run (see section 11).

---

# 1. CURRENT PHASE

Analytical core, orchestration and dashboard complete on synthetic speech; waiting for real data.

Pipeline status (ARCHITECTURE.md §4):
preprocessing ✅ → transcription ✅ → forced alignment ✅ → feature extraction ✅ (F0, MFCC, energy,
rate, pauses; clarity P1 ❌) → baseline statistics ✅ → normalization ✅ → contrastive comparison ✅
(delta = z) → flaw candidates ✅ (flat pitch ✅ DEC-042, pitch instability ❌) → severity ✅ → evidence ✅ → scoring ✅ →
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
🟢 Dashboard implemented and tested (293 tests; 50 injected bugs all caught); never run against the real models or a real recording; the recorder
has only met Chromium's fake microphone

Dataset:
🟡 The first 15 real takes exist (speaker spk_dev_01, passage p001: 3 baseline, 2 clean, 10 flawed) and passed the quality check, but only on the team's computer. The registration tool
(TASK-126) is built and tested with a stand-in aligner; nothing real is registered yet, so the repository's manifest is empty (the schema fixtures were retired) and /analyze answers
BASELINE_NOT_FOUND until a baseline is built from real takes. Running it with the real WhisperX is the next step and the main blocker for any real result.

Analysis pipeline:
🟢 12 of 12 stages implemented; flat_pitch is judged by the word profile's pitch part (DEC-042; synthetic speech only); pitch_instability is not detected

Testing:
🟢 1389 backend + 386 dashboard tests pass. Real-model smoke tests (`-m smoke`: Whisper base, WhisperX) have not been run.

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
- [x] flat pitch detection (DEC-042: pitch part of the word profile; calibrated by simulation only, TASK-135 checks it on real monotone takes)
- [ ] pitch instability detection (TASK-134, needs recordings)
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
- Flat pitch (DEC-042): detected with the pitch part of the word profile, calibrated on synthetic speech with the real pitch tracker only. There is no real monotone recording; the first real replay (after rebuilding the baselines) may show
  flat-pitch flags on clean takes caused by tracker errors (TASK-135). Baselines built before DEC-042 have no pitch part and say "flat pitch not checked". Pitch instability is not detected (TASK-134).
- Team-leader confirmation requested for the agent decisions DEC-024 to DEC-040 (all made under delegated authority, except DEC-036 and DEC-037, which the leader approved). DEC-033 also
  supersedes the proposed DEC-P009 (no chart / HTTP / waveform / CSS-framework library).
- Energy rule too coarse (TASK-128): the first real replay confirmed that the single-frame energy rule (z > 2 on 10 ms frames, baseline std about 9 dB) found none of the 12 planned loud and quiet stretches.
  Replaced, when the baseline has a word profile, by the word-by-word comparison (TASK-130, DEC-040; agent decision under delegated authority, leader to confirm). In simulation a sentence 5 dB louder or quieter
  is found in about 9 of 10 cases, 8 dB or more in practically every case. The frame rule remains as the fallback. Not verified on real recordings: calibrate with `evaluate_takes.py --sweep` (TASK-131).

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

2026-10-13 (later): the first test of the site on real recordings (the team leader, 4 takes): a baseline take scored 100 %, a fast take about 74 % but the fast sentence was reported with an extra range, and pauses were
  found but not accurate.
- Accuracy work (TASK-129, TASK-127a, DEC-039): rate findings are narrowed to the words that deviate (window detection is unchanged), a silence longer than 1 s counts as 1 s in the rate, a pause needs 0.8 s to be
  excessive, findings are clipped to the audio, and `scripts/dataset/evaluate_takes.py` replays registered takes through the real analysis (no speech model) and measures found/missed, start and end error, overlap and false
  alarms against the annotations. On human-like synthetic readings (real passage and plan, word times exact): fast sentence 24 % -> 95 % overlap, slow sentence 51 % -> 95 %, a deliberate 3.5 s pause no longer produces a
  severity-1.0 "too slow", the clean-take probe of the demo builder 6 of 10 -> 2 of 10. Not verified on real recordings. Baselines must be rebuilt.
- **Second accuracy round on the real replay (TASK-130, TASK-131, DEC-040).** The first `evaluate_takes.py` output on the 50 real recordings: pauses exact (6 of 6, 0.0 s), too_fast 1 of 6, too_slow 5 of 6 but 2 s off, high_energy and low_energy
  0 of 12, 6 of 8 clean takes flagged, ordinary pauses of 0.8 to 1.25 s flagged with severity 1.0, and the same passage region flagged in every take (139 words/min in three takes): the overall baseline average ignores which words a window
  holds. Now: the baseline stores a word profile (expected slot and level of every word, spread of a run of words measured leave-one-out; built from the passage text and at least three baseline takes), and pace and loudness are judged word by word
  against it: a run of at least 10 words, more than 4 spreads away and at least 15 % in pace or 3 dB in level, the reading's own overall pace and level removed first, a reading that is off as a whole judged as one finding, at most 0.25 s of
  silence counted towards a word's pace; severity follows the size of the change (the z-score saturated); a pause needs 1.2 s; `evaluate_takes.py --sweep` compares settings in one table; wording, dashboard and notes updated; demo samples regenerated (clean probe 2 of 10 -> 0 of 10, the quiet sentence of the
  mixed sample is found, the voice keeps its loudness when stretched). In simulation: clean takes flagged 46 % -> 3 to 5 %, a 1.33 times faster sentence found 33 % -> 78 % with ranges 2 to 3 times too long -> 0.9 times, 5 dB louder or quieter
  sentences 0 % -> 89 to 91 %. Not verified on real recordings; baselines must be rebuilt (`prepare_recordings.py data/incoming --build-baseline`).

2026-10-14 (after): score profile chart. The Overview page shows the score of each dimension as an interactive radar (`charts/ScoreRadar.tsx`): the outer ring is 100 (no deviation from the baseline), the shaded shape is where the delivery stands, and the stretch between a corner and the ring (what the dimension lost) lights up on hover or focus; a spoke opens the dimension's strongest finding (click, Enter or Space; arrow keys move between spokes); a dimension the backend did not score keeps a dashed spoke and no corner and is never drawn as perfect; the list beside it carries the same numbers as text and highlights in step. Presentation only: every value is the backend's. 11 new dashboard tests, axe without violations, keyboard and pointer checked in a real browser.
2026-10-14 (latest): VAANI visual identity and landing page (TASK-137, DEC-045). Presentation only: no route, page, feature, API field or backend file changed, no dependency added.
- **One visual system across the dashboard under the name VAANI**: obsidian and graphite surfaces, ivory type, cyan for signal and everything interactive, copper for deviation, steel for the reference and quiet text; dark by default (System and Light in Settings); page titles 21 to 26 % larger on one scale; the mark is two strokes that leave one point together, the delivery drifting away and ending in a copper marker.
- **The home route is a landing page**: the headline "Hear the difference. Understand the why.", a live instrument that draws the real demo analysis (`mixed-flaws`: rate trace over the reference corridor, loudness envelope, a labelled interval per finding with the backend's own evidence line; hover reads the measurement at that moment from the result, click plays it, a pointer-reactive light and depth shift only behind the data), method, evidence and journey sections,
  the analysis flow unchanged, footer. Without the sample it is a drawing labelled "Illustration". No sign-in anywhere (the product has no accounts). Everything that moves pauses off screen and is off for reduced motion and coarse pointers.
- **Also**: a redesigned score radar (reference ring, legend, copper for what findings cost, grows into its values, tooltip), playback-linked plots (played wash, the finding being played, trace reveal, ribbon wash), a printable report that is paper in either theme, a closed navigation drawer that is hidden from the keyboard and returns focus, "New analysis" from inside the app going to the flow.
- Checked: 53 new dashboard tests (386 in all; ten injected bugs, one first survived, now covered), axe on 70 page and state combinations without a violation (six new landing states), a layout audit of 12 pages at eight widths (320 to 2560 px) in both themes (no horizontal overflow), browser smoke test 42 of 42, screenshots reviewed at phone, tablet, laptop, desktop and wide sizes in both themes.
  **Not run:** browsers other than Chromium; the hero is always the synthetic demo sample, never a user's analysis; the API's own title is still "Speech Analytics API" (changing it changes the OpenAPI snapshot for no visual reason).
2026-10-14 (afterwards): custom passages (TASK-136, DEC-044).
- **A user can bring their own passage.** New dashboard page *Custom passage*: paste a text (30 to 400 words, two sentences or more), add two to six recordings of a good reading (upload or record in the browser), make the baseline, then analyse their own reading against it. Backend: `POST /api/v1/custom/baselines`, `DELETE /api/v1/custom/baselines/{id}`, API contract 1.3.0 (`BaselineSummary.custom`); the ordinary `/analyze` runs unchanged on the result.
  The baseline is built by the same code as the dataset tool (moved to `app.services.baseline_builder`); three recordings give the word profile, two fall back to the overall averages and say so; a recording that is not a reading of the text or in which too few words can be timed is refused with a plain sentence. Only statistics and the text are stored (`data/custom/`, git-ignored), never the audio.
- Checked: 17 integration tests (synthetic readings, stand-in aligner and recogniser, real everything else), a mutation check of the new code (28 injected bugs; two gaps found, covered, all caught), 26 new dashboard tests, axe without violations (both themes, phone width), and a real-browser run against the real server (passage typed, three recordings uploaded, baseline made, a reading with a fast sentence analysed and the finding shown, listed on New analysis, deleted).
  **Not run:** the real WhisperX alignment and Whisper recognition on a person's own recordings, and how long they take per recording.
2026-10-14 (later): flat pitch (TASK-133, DEC-042).
- **Flat pitch is judged.** The word profile of the baseline also keeps how much the pitch moved on every word (the pitch part: expected movement per word in semitones squared from the reading's own median, a leave-one-out noise model, the spread of a speaker's overall expressiveness),
  and the word scan finds runs of at least 10 words (or the whole reading) that moved clearly less than the baseline readers did on the same words (one-sided; 35 % less movement and z below -4.5). The finding carries the movement in Hz against the baseline's, the z-score, the voiced share and the words; the explanation is
  a template over the fact sheet. Pitch is now a scored feature when it was judged (flawed demo samples scored higher than before, e.g. 79.38 to 84.54 for mixed-flaws, because the pitch component of 100 now counts); when it was not judged the note `pitch_not_judged` says why. No API field changed. 9 new settings in `core/config.py`.
- Checked on synthetic expressive speech with the real pitch tracker: 0 of 40 clean readings flagged; a stretch with 0.1 or 0.3 times the normal movement found 8 of 8 at the right words, 0.5 times 4 of 8, 0.7 times 0 of 8 (a mild loss of intonation is deliberately not reported). **Not checked on any real recording.**
- The evaluation tool, baseline builder, registration report, demo builder and dashboard know the new part. Baselines must be rebuilt to get it (`prepare_recordings.py data\incoming --build-baseline`, look for `pitch profile: built`).
- New tasks: TASK-134 (pitch instability, needs recordings), TASK-135 (record flat-pitch examples and check the detector on them).
2026-10-14: the second real replay (the baselines rebuilt with the word profile; `evaluate_takes.py` and `--sweep` on 48 real dev takes: 40 planned flaws, 8 clean takes).
- **First real check of DEC-040 (TASK-131, DEC-041).** 34 of 40 planned flaws found (excessive_pause 8 of 8, too_slow 8 of 8, high_energy 7 of 8, too_fast 6 of 8, low_energy 5 of 8), start off by 0.0 to 0.4 s, overlap 83 to 100 %, detected range
  0.8 to 1.0 times the plan (before: 1 of 6 fast, 0 of 12 loud and quiet, slow 2 s off); 1 of 8 clean takes flagged (before 6 of 8). All six misses are takes of one speaker; the other speaker's 20 planned flaws were all found. Of the 14 other flags on flawed
  takes, 7 lie on a planned stretch and 3 right next to one (side effects of how the flaw was performed: quieter speech also slower, slow speech also louder, catching up after a pause) and 4 are away from every planned flaw. The sweep shows the DEC-040 settings at the point where
  raising a limit loses real flaws and lowering it adds flags faster than it finds flaws, so they stay; `THRESHOLDS_CALIBRATED` stays false until the misses and the flags away from the plan have been listened to and the annotations confirmed.
- The evaluation tool explains instead of only counting (DEC-041): each MISSED flaw says what the registration check said and how big the change really was over the planned words against what a finding needs (`measure_stretch`, the detection's own yardstick); each EXTRA says whether it
  lies on, next to or away from a planned flaw; a "Listen to these first" list; `--labels` writes the detections as Audacity labels; the sweep table has an `away` column. No analysis result changes.
- New task TASK-132: the scores are still the initial scale (a take with one clear flaw scores 86 to 98); calibrate with the leader's decision of what a score should mean.
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
- Accuracy of rate and pause findings: narrowed rate intervals, long silences capped in the rate, a minimum pause length, clipping to the audio, a replay evaluation tool (DEC-039, 2026-10-13)

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
- Rate findings are DETECTED over 8 s windows and then narrowed to the words that deviate (DEC-039; on synthetic human-like readings 95 % overlap with the planned sentence instead of 24 %),
  but this has not been seen on real recordings; the narrowing can be off by a word or two, a flaw outside every flagged window is not recovered, and stray findings on clean takes remain (thresholds, baseline size).
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
  window-resolution (since DEC-039 narrowed to the deviating words, since DEC-040 judged word by word) and long pauses inflated `too_slow` (since DEC-040 at most 0.25 s of silence counts towards a word's pace, and a pause under 1.2 s is not
  reported as excessive; the clean-take probe went from 6 of 10 flagged to 2 of 10 (DEC-039) to 0 of 10). The demo samples still show the false-flag diagnostic.
- MP3 decoder delay is not measured; MP3 timestamps may be offset by a few tens of ms.
- Dependencies are `>=` ranges without a lockfile; WhisperX is not installed in the verification environment. Library
  versions are part of the analysis identity, so a changed environment produces new ids rather than stale results.
- Stored alignment files are assumed to be AlignedTranscript JSON in processed-audio time (not specified by the dataset schema).
- AGENTS.md §27 still says "Initialization / implementation not started" (protected file; not edited).
- CONFIG_VERSION has not been bumped for the new detection, severity and scoring constants; bump at the calibration freeze (DEC-014).
  Meanwhile `config_fingerprint` changes whenever any analytical constant changes, so the cache cannot go stale.

---

# 12. NEXT PRIORITIES

1. Listen to the places `scripts/dataset/evaluate_takes.py` lists under "Listen to these first" (the misses, the flag on a clean take, the flags away from the plan; `--labels` shows them in Audacity), confirm or correct the annotations, re-record weak takes, run `--sweep` again
   with `--confirmed-only` and calibrate from the numbers (TASK-131); run the real-model smoke tests; fix whatever the real models reveal. Then record the other speakers and passage p002 (TASK-122) and finish the evaluation tools (TASK-127).
2. Calibrate thresholds, severity and weights on the controlled flaws (TASK-100 to TASK-107 on real data), then set
   `THRESHOLDS_CALIBRATED=true`, bump CONFIG_VERSION and freeze.
3. Record the flat-pitch examples (two monotone takes per dev speaker, TASK-135), check the flat-pitch detection on them with the real replay and decide pitch instability (TASK-134).
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
