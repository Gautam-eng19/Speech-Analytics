# Devpost project page — draft text

Paste each block into the matching Devpost field. Replace the **[brackets]**. Keep the numbers as they are (they come from the team's own evaluation run).

---

## Project name

VAANI

## Tagline (one line)

Not a score: the exact seconds where your delivery drifted from a good reading of the same words, with the measurement, the reason and what to try.

---

## About the project

### The problem

"Speak more clearly." "You rushed that part." Feedback on speech is usually vague, subjective or a single number. A speaker can't act on it: *which* part, *how much*, *compared with what*? Generic
"speech quality" scores also compare people with an imaginary average voice, so they punish the text and the speaker instead of the delivery.

### What it does

VAANI compares a recording of a passage with a **baseline made of good readings of the same passage**, finds where the delivery deviates, measures how much, and pins each finding to a time interval with the numbers that support it.

For every finding you get: **when** (start and end in seconds, on word boundaries), **what was measured** (for example *296 words/min against 175 for the same words*), **the flaw type** (too fast, too slow, excessive pause, low energy, high energy, flat pitch), **why it counts as a flaw**, and **what to try**.
It evaluates delivery only: not content, wording or quality of the speech.

A web dashboard shows the result on a timeline with the audio, pitch, loudness, speed and pauses on one time axis, with playback, the evidence for each finding, the transcript, the baseline, a score profile (a radar of the dimensions against the reference) and a printable report. Its home page is an instrument that draws a real analysis of a demo recording: hover to read any moment from the result, click a finding to hear it.
Anyone can also **bring their own passage**: paste a text, add two or three recordings of a good reading to make a personal baseline, then analyse their own reading against it.

### How it works

Audio → preprocessing (one standard format, loudness scaled to a typical speech level) → transcription (Whisper) → **forced alignment** (WhisperX: a start and end time for every word) → feature extraction
(pitch, energy, speech rate, pauses, MFCCs) → comparison with the baseline → flaw detection → severity → score → evidence-backed explanation → API → dashboard.

The baseline file keeps, **for every word of the passage**, how long it normally takes, how loud it is and how much the pitch moves, and how much good readers normally differ from each other. A flaw is a run of at least ten words that
drifts further than that normal variation allows *and* by an amount that matters (at least 15 % in pace, 3 dB in loudness); pauses are judged against how long pauses of the same kind normally last. Your overall habits (some people simply
speak faster or louder) are removed first, so only the drift counts.

**Design rules we held ourselves to:**
- **Deterministic analysis.** Features, comparison, detection, severity and score are plain code: the same recording and settings always give the same result (the result id is a fingerprint of all inputs).
- **Evidence before explanation.** Every sentence shown to the user is built from measured evidence, and a guard checks that every number in it exists in that evidence. A language model may only phrase findings, never invent a timestamp, percentage or score; today the explanations come from templates.
- **One implementation per concept.** Each feature is computed in one place in the backend; the dashboard computes nothing.
- **Honesty.** Everything not evaluated or not calibrated is listed in the result's `notes`.

### Results so far

We evaluated on **48 recordings from two speakers**: 40 with a planned flaw and 8 clean readings. The system found **34 of the 40** planned flaws (all 8 pauses, all 8 slow stretches, 7 of 8 loud, 6 of 8 fast, 5 of 8 quiet); start and end times fall
within about half a second on average; **1 of the 8 clean readings** was flagged. The six misses all came from one speaker and mostly from takes where the flaw was performed more mildly than planned (the evaluation tool reports the real size of the change for every miss).
These are development speakers and the planned flaws are not yet all confirmed by ear, so we do **not** claim calibrated accuracy.

### How we built it

Python (FastAPI) backend with Whisper, WhisperX, librosa (pYIN pitch, MFCC, energy) and NumPy/SciPy; a React + TypeScript + Vite dashboard with no charting or UI library (the timeline is drawn by us);
a dataset toolkit (recording plan, on-screen prompter, quality checker, registration and evaluation tools). Nearly 1,400 backend tests and nearly 400 dashboard tests, a mutation check of the newest code, and accessibility audits (axe) of every page.

### Challenges

- Comparing words with words: our first version compared a recording with overall averages, which missed whole flawed sentences on real recordings. Moving to a per-word baseline took us from missing every loud and quiet stretch (0 of 12) on the team's recordings to finding 34 of 40 planned flaws overall.
- Real voices are not synthetic voices: a pitch tracker that worked perfectly on test audio marked only 5 % of a real voice as voiced, so we found and fixed that against real recordings.
- Telling a real side effect (people get louder when they slow down) from a false alarm, so the evaluation tool classifies every unplanned flag as on, next to or away from a planned flaw.

### Accomplishments we are proud of

Every finding has a time, a measurement, a reason and a suggestion, all from deterministic code; the evaluation shows where it works and where it doesn't; anyone can try their own passage.

### What we learned

Good feedback is specific and checkable. The baseline must be the *same content*, and "normal variation" has to be measured, not guessed.

### What's next

Confirm the annotations by ear and calibrate the thresholds and the score on more speakers; record real monotone and unstable-pitch examples (flat pitch is implemented, unstable pitch is not yet); optional language-model phrasing behind the same number guard.

### Built with

python, fastapi, whisper, whisperx, librosa, numpy, scipy, pytorch, react, typescript, vite

### Try it out

[GitHub repository link] — setup instructions in the README (the dashboard opens four demo samples without any model; "Custom passage" lets you analyse your own text and voice).

### Video demo

[YouTube link — Unlisted, English audio]

### Team

[Full real names of every team member; each must have a Devpost account and be added to the submission.]
