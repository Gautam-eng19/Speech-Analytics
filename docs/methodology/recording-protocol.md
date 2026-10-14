# Recording Protocol — Building the Track C Dataset by Hand

**Status:** Recording protocol for the team's dataset (decisions in §1).
The dataset schema (`docs/methodology/dataset-schema.md`) is the reference for file formats.

**Audience:** the people who will record, label and use the data.

**Plain-language version:** [`dataset-guide.md`](dataset-guide.md) (read it first). **Consent form:** [`consent-form-template.md`](consent-form-template.md).
**Update 2026-10-11:** the plan generator with an on-screen prompter (`scripts/dataset/make_plan.py`) and the recording checker
(`scripts/dataset/check_recordings.py`) now exist and are tested on synthetic audio only; the final passages are in `data/plan/passages_v1.json`.

**Tool status key:** `[exists]` works today · `[manual]` done by people.

**Evidence status:** everything below that describes what the software does was checked against the code on 2026-10-10.
The loudness experiments in §8 were run on *synthetic* speech only. The real Whisper/WhisperX models and real recordings have
never been run through the pipeline, so numbers marked *(proposed)* are starting points to be confirmed by the pilot (§5.3).

---

## 0. What the dataset is for, and the five rules that matter most

The system judges **delivery**, not content: it compares a recording with a baseline of the **same text**, finds where the delivery
deviates, and says when, by how much and why. The recordings serve four purposes:

| Purpose | Recordings used | Question it answers |
|---|---|---|
| Baseline statistics | `baseline_effective` of the **dev** speakers | What does effective delivery of this text look like (pace, pauses, loudness)? |
| Detection ground truth | `flawed_human_controlled` | Does the system find the flaw we deliberately made, and where? |
| False alarms | `clean_control` | Does it stay quiet on normal speech? |
| Tuning vs. final test | `dev` split / `test` split | Tune on dev as often as needed; measure on test **once**. |

The five rules:

1. **Same text.** Everyone reads the exact passage text, word for word (no extra words, fillers or skipped words).
2. **Record raw.** No normalising, compression, noise reduction, EQ, trimming or editing of any kind. The software processes every
   file in the same way; manual processing only creates differences between files that the software would then mistake for delivery.
3. **One deliberate flaw per flawed take**, in a planned stretch; everything else in the take is normal delivery.
4. **Dev and test speakers are different people**, fixed *before* the first recording. Test recordings are not analysed
   by the system until the thresholds are frozen.
5. **Accept or reject a take by the checklist in §7, before looking at any system output.** Never retake because the system got a
   take wrong; that would tune the data to the system.

---

## 1. Decisions to confirm before anyone records

| # | Decision | Recommendation | Why |
|---|---|---|---|
| 1 | Speakers and split | 4 speakers: 2 dev + 2 test. With 3: 2 dev + 1 test (§2) | Baseline needs more than one voice; test must be unseen voices |
| 2 | Passages | Pilot with 1, then 2 passages of 100–130 words (§4) | Variety without exploding the workload |
| 3 | Where the audio lives | **Outside git** (shared drive); git keeps metadata, annotations, alignments, baseline statistics | Size (about 5 MB per take) and consent; `data/raw/` is *not* git-ignored today |
| 4 | Loudness normalisation in the software | **Approved and implemented 2026-10-11**, see §8.3 | Peak scaling made a loud stretch look normal and pushed the rest of the take down |
| 5 | Who annotates test takes | Someone who did not perform the take | Avoids the performer marking what they meant instead of what is audible |
| 6 | `flat_pitch` takes | Optional now | The detector exists but has only been tried on synthetic speech; two real monotone takes per speaker (one sentence, one whole passage) are what it needs to be checked and calibrated |
| 7 | Consent and sharing | Written consent from every speaker (§13) | Voices are personal data |

---

## 2. People and splits

### 2.1 Roles (one person can hold several)
- **Speakers** — read the passages.
- **Session lead** — runs the plan sheet, checks levels, names and saves files, applies the accept/reject checklist.
- **Annotator** — verifies or creates the flaw labels (§9).
- **Data owner** — runs the scripts (§10–§12) and keeps the dataset folder consistent.

### 2.2 Allocation

| Speakers available | `dev` (baseline + calibration) | `test` (held out) | Consequence |
|---|---|---|---|
| **4** | S1, S2 | S3, S4 | Recommended. Two baseline voices, two unseen test voices |
| **3** | S1, S2 | S3 | Test results rest on one voice: report them as indicative. Record more clean takes and use 2 passages to get more events |
| 2 | S1 | S2 | Works, but the baseline is one voice, so expect more false alarms and treat the numbers as a smoke test |

Rules:
- **Fix the assignment before recording and never change it.** Put the two clearest, steadiest presenters in `dev`: their takes define
  "effective delivery".
- A speaker is in exactly one split (the validator rejects overlap).
- Dev results are optimistic (a dev speaker's own baseline takes are part of the baseline). Test results are the honest ones.
- Speaker ids are anonymous: `spk_dev_01`, `spk_dev_02`, `spk_test_01`, `spk_test_02`. The mapping to real names is kept in a private
  file **outside the repository**.

`data/metadata/speakers.json` entry (schema §3.2; the committed file is a fixture and gets replaced):
```json
{ "speaker_id": "spk_dev_01", "split": "dev", "gender": "female", "native_language": "en", "notes": "Dev baseline and controlled-flaw speaker" }
```

---

## 3. Software and equipment

### 3.1 Hardware
| Item | Recommendation | Notes |
|---|---|---|
| Microphone | One **USB headset** (boom mic) for everybody | Fixed mouth-to-mic distance (3–4 cm, beside the mouth, not in the airstream) keeps loudness comparable across takes. A phone or earbud mic works if **the same device and position** is used for all takes |
| Room | Small, quiet, soft furnishings | Switch off fans/AC, close windows, phones on silent, no typing during a take. Use **one room** for all sessions if possible |
| Screen | Passage displayed large, sentence numbers visible | Printed paper also works. Do not read from a window that scrolls |
| Stopwatch | Phone stopwatch | Timing pauses and flawed sentences |

### 3.2 Software
| Purpose | Tool (free) | Use |
|---|---|---|
| Record, inspect, label | **Audacity** (Windows/macOS/Linux) | Recording, waveform and spectrogram check, label track for flaws, export WAV and label files |
| Convert / inspect files | **ffmpeg** (optional) | Only if a recording arrives as M4A/MP3/AAC; `ffprobe` shows sample rate and channels |
| Run the project tools | **Python 3.10–3.13** and the repo environment (`docs/setup.md`) | Validator, baseline builder, planned tools. Alignment needs Whisper and **WhisperX** installed (large downloads; GPU optional) |
| Plan sheet, label sheet | Excel / Google Sheets / any CSV editor | Appendix A |
| Metadata and annotations | **Git** | Small text files only |
| Audio storage | Shared drive (Google Drive/OneDrive) or external disk | Audio stays out of git (decision 3) |
| Optional pitch check | **Praat** | Look at the pitch contour to confirm a monotone (`flat_pitch`) stretch |

---

## 4. The passages

### 4.1 Rules for a good passage
- **100–130 words, 8–10 sentences, about 45–55 seconds** at a natural pace. Why: the speech-rate analysis looks at 8-second windows
  (step 4 s), so a flaw needs a few seconds of normal speech on each side to stand out; a 15-second passage leaves no room.
- Plain vocabulary everyone can read fluently; a mix of short and long sentences; commas where a speaker would breathe.
- **Spell numbers out** ("seven o'clock"). No digits, symbols, hyphenated codes, acronyms or abbreviations such as "Dr." — the aligner
  typically leaves digits and symbols without timestamps (not verified with the real model here), and the pause classifier treats a word
  ending in "." as a sentence end.
- Every sentence ends with `.`, `?` or `!`. Sentences are numbered S1, S2, … in the plan sheet.
- Content should sound like a presentation or talk, not a list.

### 4.2 How many
**Pilot: 1 passage. Recommended: 2. Extended: 3.** The baseline is built *per passage*, so every extra passage multiplies the work by
the number of speakers and takes. Two different passages are enough to avoid tuning to one text.

### 4.3 Two draft passages (replace freely, keep the rules)
**Passage A — a project talk (123 words, 8 sentences)**
> S1 Good morning, everyone, and thank you for joining us today. S2 Over the past year our team has built a tool that helps people improve the way they speak. S3 It listens to a recording, compares it with a clear example of the same message, and shows exactly where the delivery changed. S4 For instance, you might speak too quickly during a key point, or pause for too long before an answer. S5 The tool marks those moments on a timeline, explains what it measured, and suggests one simple change. S6 We tested it with students, teachers, and engineers, and most of them improved within a single week. S7 Today I will show you how it works, step by step. S8 Please feel free to ask questions at any time.

**Passage B — a personal story (118 words, 8 sentences)**
> S1 Every morning, the market in our town opens before sunrise. S2 Farmers arrive with baskets of fresh vegetables, bakers carry warm bread across the square, and children follow behind, still half asleep. S3 By seven o'clock the noise is overwhelming, yet everyone somehow manages to hear a friendly greeting. S4 My grandmother taught me that a good conversation needs patience, curiosity, and a little humor. S5 She would listen carefully, wait for the right moment, and then speak slowly so that each word mattered. S6 I have never forgotten those lessons. S7 When I stand in front of a crowd now, I remember her voice and I try to speak the same way, calmly and clearly. S8 That is how a message becomes a memory.

The sentence numbers are for the plan sheet only; they are **not** read aloud and are not part of the stored text.

The final texts are `data/plan/passages_v1.json` (ids `p001` "Project talk" and `p002` "Morning market"; passage B's title was shortened). The plan tools check
every passage against the rules above (no digits, symbols, acronyms or abbreviations, at least six sentences, each ending in . ? or !) and refuse a passage that breaks them.

### 4.4 Registering the passages
`data/metadata/passages.json` (schema §3.1). The committed `p001`/`p002` are schema fixtures with a different, shorter text and are
replaced when the real dataset is committed (§10).
```json
{ "passage_id": "p001", "title": "Project talk", "text": "Good morning, everyone, and thank you for joining us today. ...",
  "target_word_count": 123, "domain": "presentation", "dataset_version": "1.0.0", "created_at": "2026-10-10" }
```

---

## 5. What to record — the take plan

### 5.1 The four kinds of recording
| `category` | What the speaker does | Annotation file |
|---|---|---|
| `baseline_effective` | Reads the passage clearly, at a natural steady pace, with natural pauses at punctuation, expressive but not monotone | none |
| `clean_control` | Reads the passage normally again (not copied from the baseline; no extra effort to be perfect) | none |
| `flawed_human_controlled` | Reads normally **except one planned stretch** where the planned flaw is performed (§5.4) | required |
| `flawed_synthetic` | *(optional, later)* software-altered copy of a baseline/clean take; exact labels by construction; reported separately | required |

Baseline takes are recorded by **dev speakers only** and are the *only* recordings that feed the baseline statistics.

### 5.2 Takes per speaker and passage
| Block | Dev speaker | Test speaker | Purpose |
|---|---|---|---|
| Baseline (`base_01`–`03`) | 3 | 0 | Pooled baseline statistics (the standard deviation needs at least 2 observations; 3 takes × 2 speakers clears the thin-baseline warnings comfortably) |
| Clean (`clean_01`…) | 2 | 3 | False-alarm measurement; speaker-variation check on test speakers |
| Flawed | 10 | 10 | 5 flaw types × 2 takes |
| **Reads of the passage** | **15** | **13** | |
| Optional `flat_pitch` | +2 | +2 | Recommended now: one monotone sentence, one monotone whole passage (needs real examples to be calibrated) |

The 10 flawed takes per passage:

| Take id part | Flaw | Take 01 | Take 02 |
|---|---|---|---|
| `flaw_fast` | `too_fast` | moderate | strong |
| `flaw_slow` | `too_slow` | moderate | strong |
| `flaw_pause` | `excessive_pause` | inside a phrase, 1.5–2 s | at a sentence boundary, 3–4 s |
| `flaw_quiet` | `low_energy` | moderate | strong |
| `flaw_loud` | `high_energy` | moderate | strong |

### 5.3 Tiers and totals
| Tier | Scope | 2 dev + 2 test | 2 dev + 1 test |
|---|---|---|---|
| **Pilot** | 1 passage, 1 dev speaker: 3 base + 1 clean + 5 flawed (strong only) = **9 takes** | 9 | 9 |
| **Minimum** | 1 passage; dev: 3 base + 2 clean + 5 flawed; test: 3 clean + 5 flawed | **36** | **28** |
| **Recommended** | 2 passages, full blocks | **112** (80 flawed, 20 clean, 12 base) | **86** (60 flawed, 14 clean, 12 base) |
| Extended | 3 passages | 168 | 129 |

Per speaker in the Recommended tier: a dev speaker reads 30 times, a test speaker 26 times. As a rough planning figure (not
measured) allow 1.5–2 minutes per take including resets and retakes, and a break after 45–60 minutes.

The tiers are nested: `make_plan.py --tier pilot|minimum|recommended` gives every smaller tier's takes the same take ids as the larger tier (the pilot takes are the
*strong* flawed takes `_02`, so they are also part of the minimum and the recommended plan). Pilot, minimum and recommended give 9, 36 (28) and 112 (86) takes for
2 dev + 2 test (2 dev + 1 test) speakers, as in the table above.

**Always do the pilot first.** It proves the whole chain (recording → files → alignment → baseline → analysis) on a handful of takes,
and the real Whisper/WhisperX models have not run yet, so surprises are likely. Fix them before recording 100 takes.

### 5.4 How to perform each flaw
"Normal" means the speaker's own baseline delivery. The plan sheet gives, per speaker, the normal duration of each flawed sentence
(measured from their baseline takes) and the target durations below.

| Flaw | What to do | Moderate | Strong | Do **not** |
|---|---|---|---|---|
| `too_fast` | Read the planned sentence faster, every word still said | about 1.3× speed (sentence takes about 75 % of its normal time) | about 1.8× (about 55 %) | Skip or slur words; get louder at the same time |
| `too_slow` | Read the planned sentence slowly, stretching the words, no extra silence | about 0.75× speed (about 135 % of normal time) | about 0.55× (about 180 %) | Add long pauses (that is another flaw) |
| `excessive_pause` | Stop at the planned word, stay **silent**, continue | take 01: 1.5–2 s inside a phrase | take 02: 3–4 s at a sentence end | Say "um/uh"; breathe loudly; count aloud |
| `low_energy` | Read the planned sentence in a clearly softer voice, same mic distance | about −8 dB (meter peaks 8 dB lower) | about −14 dB | Whisper; lean away from the mic; trail off |
| `high_energy` | Read the planned sentence louder, projecting | about +8 dB | about +14 dB, **without clipping** | Shout into distortion; lean into the mic |
| `flat_pitch` *(optional)* | Monotone: minimal pitch movement, normal pace | reduced intonation | robot-like | Slow down at the same time |

Why the loud and quiet takes are exaggerated: real speech varies a lot from syllable to syllable and from word to word, and a change that
nobody could hear is not a flaw. The system compares every word with how the baseline readers read **the same word** and reports
a run of at least 10 words that is louder or quieter by at least about 3 dB and clearly beyond the natural variation (in simulation a change of
5 dB over a sentence is found in about 9 of 10 cases, 8 dB in practically every case). The planned +8 / +14 dB and −8 / −14 dB are kept so
that a take is clearly a flaw even if the performer reaches only part of it; a performer who reaches only +2 to +4 dB did not perform the flaw
and the registration says "weak example". The two intensities double as the `severity_label` (`medium`, `high`).

Rehearse the flaw once, unrecorded, before each flawed take. Keep everything outside the planned stretch normal.

### 5.5 Where to put the flaw
- Flaws go in **S3–S6** only (never S1, S2, S7, S8), so there is normal speech before and after.
- The two takes of a flaw type use **different sentences**.
- The plan sheet is shuffled so that no flaw type is recorded twice in a row.

Worked example for passage A (sentence word counts: S3 22, S4 19, S5 17, S6 17):

| Take | Stretch | Instruction |
|---|---|---|
| `flaw_fast_01` | S3 (whole sentence) | about 1.3× speed |
| `flaw_fast_02` | S5 | about 1.8× speed |
| `flaw_slow_01` | S4 | about 0.75× speed |
| `flaw_slow_02` | S6 | about 0.55× speed |
| `flaw_pause_01` | S4, silence after the word "quickly" (before "during") | 1.5–2 s |
| `flaw_pause_02` | silence after the last word of S5 (before S6) | 3–4 s |
| `flaw_quiet_01` | S5 | about −8 dB |
| `flaw_quiet_02` | S3 | about −14 dB |
| `flaw_loud_01` | S4 | about +8 dB |
| `flaw_loud_02` | S6 | about +14 dB |

For passage B use the same pattern on S3–S6, except that a sentence too short for the flaw is replaced (sentence 6 of passage B has only six words, so no speed or
loudness flaw goes there; the replacement is the least-used suitable sentence). `python scripts/dataset/make_plan.py --dev 2 --test 2 --tier recommended --out data/plan/v1`
generates this sheet (`plan.csv`) and one on-screen prompter per speaker for any passage file, deterministically.

### 5.6 Normal delivery (baseline and clean takes)
Pace about 130–160 words per minute, steady; short natural pauses at commas and sentence ends; moderate, even volume; natural
intonation. Do not recite robotically and do not try to repeat the previous take: natural take-to-take variation is what gives the
baseline its realistic spread.

### 5.7 Optional: showcase takes for the demo
One or two takes with **two or three** flaws at least 10 seconds apart, recorded after the thresholds are frozen, are good for the demo
video. They are not used for calibration or for the reported metrics.

---

## 6. Room, microphone and level setup (before the first take of each session)

Do this once per speaker per session; **do not change any setting afterwards.**

1. **Room.** Close the door and windows, silence phones, stop fans/AC, close chat and conferencing apps (they can grab the microphone
   or apply their own processing).
2. **Mic position.** Boom beside the corner of the mouth, 3–4 cm away, outside the breath stream; foam cover on. Mark the position
   (tape) so each speaker repeats it. Phone: fixed stand, same distance every time.
3. **Switch off processing in the operating system.** In the sound settings of the microphone (and any headset software) turn off
   "audio enhancements", "noise suppression", "automatic gain control", "voice isolation" and "mic boost" (or keep boost at its minimum).
   Automatic gain makes loudness drift *within* a take, which would look like a flaw. Set the input volume to a fixed value and
   leave it (on most systems Audacity's recording-volume slider is the same control as the operating system's input volume).
4. **Audacity settings** (menu names vary slightly by version):
   - Preferences → Audio Settings (older versions: Devices): choose the microphone; **Recording channels: 1 (Mono)**.
   - Project rate (bottom left): **48000 Hz or 44100 Hz — the same for every recording.**
   - Preferences → Quality: **Default sample format 16-bit**; dither: none.
   - Transport: software playthrough **off**; overdub **off**.
5. **Noise-floor check.** Press Record, stay silent for 10 seconds, stop. The meter should read **about −60 dB or lower**. If it shows
   −50 dB or higher: move somewhere quieter, lower the input volume, remove mic boost. *(Why: the software treats frames quieter than
   −50 dBFS as silence after scaling the take so its loudest point is at −3 dBFS; that is 47 dB below the peak, so the room noise must
   sit about 47 dB or more below your loudest speech, otherwise pauses are not detected.)*
6. **Normal level.** Read S3 in your normal voice. Adjust the input volume (Audacity's recording slider) so the **loudest syllables
   reach about −16 dB** on the meter (acceptable −18…−14).
7. **Loud test.** Read S3 in the *strong* loud voice (+14 dB). Peaks must stay **at or below −2 dB**: no red meter, no flat-topped
   waveform. If it clips, lower the input by 3 dB and repeat steps 6–7. **Clipped audio cannot be repaired.**
8. **Quiet test.** Read S3 in the *strong* quiet voice (−14 dB). It must sit clearly above the silence reading (at least 25 dB).
9. **Write down** the input volume setting in the session log. Delete the test recordings.
10. Look at the **spectrogram** of the silence test (track menu → Spectrogram): there should be no steady horizontal lines (mains hum)
    and no periodic noise.

---

## 7. Running a recording session

### 7.1 Order of work
1. Setup and level calibration (§6).
2. Warm-up: read the passage aloud once, unrecorded.
3. Dev speakers: `base_01`–`03`, then `clean_01`–`02`. Test speakers: `clean_01`–`03`.
4. Flawed takes in the shuffled order of the plan sheet.
5. Back up the files (copy to the shared drive) before leaving the room.

### 7.2 One take
1. Read the plan-sheet row: take id, passage, instruction, planned stretch, target duration.
2. Look at the passage with the stretch highlighted. Rehearse the flaw once, unrecorded (flawed takes).
3. Press Record. **Stay silent for about 1 second**, read the whole passage, **stay silent for about 1 second**, press Stop.
4. Check the waveform/meter: any clipping (red, flat tops)? Any noise event (cough, door, phone)? If yes, reject (retake).
5. Apply the checklist in 7.4. Accept or reject **now**.
6. Accepted: add the label for the flaw (Ctrl+B on the selected stretch; text `too_fast|high`) *or* leave it to the planned tool (§9.4).
7. **File → Export → Export as WAV**, encoding **Signed 16-bit PCM**, file name = take id (7.3). Do **not** edit the track before
   exporting (no trimming, no deleting a cough): edits would shift the label times.
8. Export the labels (File → Export → Export Labels…) next to the WAV as `<take id>.labels.txt` (flawed takes).
9. Tick the row in the plan sheet.

### 7.3 Naming
`rec_<passage>_<speaker>_<kind>_<nn>.wav`, for example:
`rec_p001_spk_dev_01_base_01.wav`, `rec_p001_spk_dev_01_clean_02.wav`, `rec_p001_spk_dev_01_flaw_fast_01.wav`,
`rec_p001_spk_test_02_flaw_pause_02.wav`. Kinds: `base`, `clean`, `flaw_fast`, `flaw_slow`, `flaw_pause`, `flaw_quiet`, `flaw_loud`,
`flaw_flat`. Never rename a file after it is registered (the id is the key, and the file hash is recorded).

### 7.4 Accept / reject checklist (decided at recording time, before any system output)
Reject and retake if **any** applies:
1. A word is missing, added, repeated or badly mispronounced (the transcript would not match the passage).
2. Clipping anywhere.
3. A noise event (cough, door, notification, chair) in the take — especially inside or next to the flawed stretch.
4. The flaw was not performed as planned: weaker than "moderate", in the wrong place, or combined with another flaw (for example
   getting louder while going faster).
5. A false start, or the take was interrupted.
6. The setup changed (headset moved, volume touched).

At most **3 attempts per slot**, then take a break. Never reject a take because of what the system does with it.

### 7.5 The test split stays sealed
Test-speaker audio is checked for format and clipping only (§11). **Do not run the analysis on test takes** until the thresholds are
frozen (§12.5). Whoever tunes the system should not listen to test takes either.

### 7.6 Session log (one line per session)
Date, speaker id, microphone, room, input volume setting, noise-floor reading, normal-peak reading, problems.
The microphone and conditions also go into the manifest (`microphone`, `recording_conditions`).

---

## 8. Loudness — what you do, what the software does, and the problem that was measured

### 8.1 What you do: nothing
**Do not normalise loudness by hand.** Keep the recording exactly as captured, at a healthy level (§6) and without clipping.
- A constant gain change of a whole file (Audacity "Amplify"/"Normalize") is harmless but pointless.
- "Loudness normalisation" to a target (LUFS), a compressor, a limiter, noise reduction or per-segment normalising **destroys the very
  differences the flaws consist of** (a quiet stretch or a loud stretch) and must never be applied.
- The software scales every file, baseline and participant alike, in its preprocessing step. That is the only place loudness is
  adjusted, so that the baseline and the participant are always treated identically.

### 8.2 What the software did until 2026-10-11, and what was measured (synthetic speech)
Until 2026-10-11 each recording was scaled so that its **loudest sample is −3 dBFS**. Consequences, measured on synthetic speech with one stretch
of six words changed (baseline built the same way):

| Scenario | Today: peak scaled to −3 dBFS | Proposed: median speech level scaled to −26 dBFS |
|---|---|---|
| Whole take 20 dB quieter | no flaw reported (invisible by design: only changes *within* a take are detectable) | no flaw reported |
| Quiet stretch (−12 dB) | found at 6.8–10.0 s (actual 6.8–9.7 s) | found, same |
| Loud stretch +6 dB | **not found**, and **5 false "low energy" flags** on normal speech | no false flags; the stretch's z-score is +2.6 but it is **not flagged** |
| Loud stretch +9.5 dB | not found, false flags | z-score +4.2, not flagged |
| Loud stretch +12 dB | not found, false flags | z-score +5.3, flagged but only 6.8–8.2 s of the actual 6.8–9.7 s |
| Loud stretch +18 dB | not found, false flags | z-score +6.9, flagged over the whole stretch |

Reading: scaling by the **peak** makes a loud stretch define the scale, so everything else looks quiet and the loud stretch itself looks
normal. Scaling by the **typical speech level** fixes that: the loud stretch gets the right (high) z-scores and the false flags vanish.
But the current frame-by-frame energy rule still only fires for large changes, because the baseline spread of single frames is wide and
any in-range frame breaks a run.

### 8.3 The change (implemented on 2026-10-11)

**Status 2026-10-11:** implemented as described, with the cap added. Measured end to end on synthetic voice (has the table), the new scaling
keeps the rest of a take within about 1 dB of the baseline while a loud sentence gets a z-score that grows with its loudness (the old scaling gave every
loud sentence the same z and pushed the rest down by 3 to 12 dB). It does **not** make the current frame-level energy rule detect moderate loudness
flaws: that needs a windowed energy rule and calibration. The exaggerated loud and quiet takes of §5.4 therefore remain the right plan.
**Update 2026-10-13:** the frame-level energy rule is now only the fallback; loudness is compared word by word with the baseline, which finds a
sentence that is about 5 dB louder or quieter. The first real replay (0 of 12 loud and quiet flaws found) is what motivated it; the thresholds still
have to be calibrated on the real dev takes (`evaluate_takes.py --sweep`).
Replace "scale so the peak is −3 dBFS" by "scale so the typical speech level is −26 dBFS":
1. Decode, make mono, resample to 16 kHz, trim leading/trailing silence — unchanged.
2. Compute the loudness (dBFS RMS) of every 32 ms frame, hop 10 ms (the frames the energy feature uses).
3. Keep the frames within 30 dB of the 95th-percentile frame loudness; these are the speaking frames.
4. Reference level = the **median** loudness of the speaking frames (robust: up to roughly half of the take can be unusually loud or
   quiet without moving it).
5. Gain = −26 dBFS − reference level; apply it to the whole signal; cap the gain so the loudest sample never exceeds −1 dBFS
   (the cap is a safety design, it was not part of the prototype).
6. The same step runs for baseline recordings and participant recordings.

Effects: baseline statistics must be rebuilt (none exist yet, so this is cheap now and expensive later); the audio hash changes;
`peak_dbfs` is no longer −3; the preprocessing tests change; the audio given to Whisper/WhisperX changes level (expected to be harmless,
**not checked with the real models**).

Remaining limits, which real data will have to resolve: (a) if most of a take is loud or quiet, it looks like a recording at another gain
and the flaw is invisible; (b) the frame-level energy rule probably needs smoothing over about 0.5–1 s windows before moderate loudness
flaws are detected reliably (resolved by : runs of words are compared with the baseline's level for the same words). That is why §5.4 asks for exaggerated loud and quiet takes first.

**The recording instructions in this protocol do not depend on this decision.**

---

## 9. Labelling

### 9.1 What gets labelled
| Label | Applies to | Made by |
|---|---|---|
| A. File metadata (manifest entry) | every recording | `prepare_recordings.py` (§10) or by hand |
| B. Flaw annotations (type, start, end, severity, words) | flawed takes | planned stretch → proposed automatically, verified by a person |
| C. Word alignment (each word with start/end) | every recording | **automatic** (WhisperX); nobody labels words by hand; a person spot-checks |
| D. Speaker and passage records | once | by hand |

### 9.2 Timelines — the one thing to get right
- **Annotations are in the time of the original WAV file** (second 0 = start of the exported file). That is also the time the API
  reports (it converts back from the trimmed audio), so predictions and annotations are directly comparable.
- Alignment files are stored in *trimmed-audio* time (after the software cut the leading silence). The tools convert; people only ever
  use file time.
- Never edit an exported file after labelling it.

### 9.3 Manifest entry (`data/metadata/manifest.json`)
Required by the validator: `recording_id`, `passage_id` (must exist), `speaker_id` (must exist; `split` must equal the speaker's split),
`category`, `is_synthetic` (boolean), `duration_s` (> 0), `sha256_audio` (64 hex characters), `audio_file`; `annotation_file` for flawed
takes. The baseline builder additionally needs `alignment_file` and `sha256_alignment` for baseline recordings and one shared
`dataset_version`.
```json
{
  "recording_id": "rec_p001_spk_dev_01_flaw_fast_01",
  "passage_id": "p001", "speaker_id": "spk_dev_01", "category": "flawed_human_controlled", "split": "dev",
  "audio_file": "data/raw/rec_p001_spk_dev_01_flaw_fast_01.wav", "duration_s": 52.31, "sample_rate_hz": 48000, "channels": 1,
  "sha256_audio": "<64 hex characters>",
  "alignment_file": "data/processed/alignments/rec_p001_spk_dev_01_flaw_fast_01.alignment.json", "sha256_alignment": "<64 hex characters>",
  "annotation_file": "data/annotations/rec_p001_spk_dev_01_flaw_fast_01.flaws.json",
  "recording_conditions": "quiet_room", "microphone": "usb_headset_<model>", "is_synthetic": false, "synthesis_technique": null,
  "dataset_version": "1.0.0", "created_at": "2026-10-10"
}
```
By hand: `sha256sum file.wav` (Linux/macOS) or `Get-FileHash file.wav -Algorithm SHA256` (PowerShell); `ffprobe` for duration and rate.

### 9.4 Flaw annotations (`data/annotations/<recording_id>.flaws.json`)
What the interval means:

| `flaw_type` | `start_s` → `end_s` | `target_words` |
|---|---|---|
| `too_fast`, `too_slow`, `low_energy`, `high_energy`, `flat_pitch` | start of the first word → end of the last word of the performed stretch | the words of the stretch |
| `excessive_pause` | the **silence itself**: end of the word before → start of the word after | the two bounding words |

`severity_label`: `medium` for the moderate take, `high` for the strong take.
```json
{ "recording_id": "rec_p001_spk_dev_01_flaw_fast_01", "passage_id": "p001", "dataset_version": "1.0.0",
  "flaws": [ { "flaw_id": "ann_flaw_p001_dev01_fast01", "flaw_type": "too_fast", "start_s": 14.62, "end_s": 20.31,
               "severity_label": "medium", "target_words": ["It", "listens", "to", "a", "recording", "..."],
               "annotator_notes": "performer aimed for 1.3x; sentence S3 took 5.7 s, normally 7.6 s" } ] }
```
The validator checks: type is in the canonical vocabulary, `0 <= start_s < end_s`, and `end_s <= duration_s + 0.5`.

`prepare_recordings.py` writes one extra top-level field, `annotation_status`: `"proposed"` (made from the plan and the alignment, not yet heard by a
person) or, after a person has listened and corrected the numbers, `"confirmed"` (set by editing the file). A re-run regenerates a `proposed` annotation
(it follows a changed plan) but never touches a `confirmed` one, nor one written by hand without the field. The evaluation tools must score
the **test** split with `confirmed` annotations only. The `annotator_notes` of a proposed annotation also carry the "was the flaw really performed" check
(§9.4a); `flaw_id` is `ann_<recording_id>_01`.

**Workflow A — planned stretch, proposed automatically, verified by a person (recommended; `prepare_recordings.py` does steps 1 and 2):**
1. The plan sheet already says which words carry the flaw.
2. After alignment, the tool turns those words into `start_s`/`end_s` (file time) and writes the annotation file plus Audacity
   label files (`data/processed/labels/<take>.words.txt` with every word and `<take>.flaw.txt` with the proposed stretch).
3. The annotator opens the WAV in Audacity, imports the labels (File → Import → Labels…), listens to the flawed stretch and checks
   that the interval starts and ends where the flaw is actually audible. If the performer began early/late or the aligner is off,
   correct `start_s`/`end_s` in the annotation file and set `"annotation_status": "confirmed"`.
4. For the **test** split, the person verifying is not the performer.

*Honest caveat:* the interval then comes from the same aligner that the system uses, so a systematic alignment error would be in both
the label and the prediction. This is why a person must listen to every test label.

**Workflow B — fully manual in Audacity (fallback or cross-check):**
1. Open the WAV. Drag-select the flawed stretch (or the silence for a pause); the selection start/end are shown at the bottom.
2. Tracks → Add Label at Selection (Ctrl+B); type `<flaw_type>|<severity_label>`, for example `excessive_pause|high`; press Enter.
3. File → Export → Export Labels… The text file has three tab-separated columns: start (s), end (s), text.
4. The planned converter turns it into the JSON above, filling `target_words` from the alignment. By hand: copy the numbers into the
   JSON and list the words.

### 9.4a Was the planned flaw really performed? (checked automatically, advice only)
A "weak example" of a flaw would make the answer key dishonest, so `prepare_recordings.py` compares each flawed take with the **same speaker's own baseline takes**
of the passage (when there are any) and writes the verdict into the annotation notes and the report. A take counts as a clear example from **half way** to the planned
change; below that the take is still registered, but it is marked "weak example" and should be recorded again or left out of the evaluation. These limits are
proposed, not calibrated (`PerformedGates` in `scripts/dataset/take_checks.py`).

| Flaw | Measured | Clear example when |
|---|---|---|
| `too_fast` / `too_slow` | time the stretch takes, divided by the mean time of the same words in the baseline takes | at least half way from 1 to the planned factor (take 1: 0.75 or 1.35; take 2: 0.55 or 1.8) |
| `high_energy` / `low_energy` | speech level of the stretch minus the speech level of the rest of the take, minus the same difference in the baseline takes | at least half of the planned 8 dB (take 1) or 14 dB (take 2), in the right direction |
| `excessive_pause` | length of the silence between the two bounding words | at least 70 % of the planned minimum (take 1: 1.5 s; take 2: 3 s) |

### 9.5 Alignment files and the quick visual check
`data/processed/alignments/<recording_id>.alignment.json` holds the aligned words in trimmed-audio time (the `AlignedTranscript`
format). It is produced **with the passage text as the transcript**, so the word sequence and punctuation are exactly the script and
the flaw words can be found by position. Spot-check: for 3 recordings per speaker, import the word labels into Audacity and confirm that
words land on the audio. A visibly wrong alignment (words shifted by a second or more) → fix the cause, do not hand-edit timings.
`prepare_recordings.py` also flags an implausible alignment on its own (wrong word count, words without a time, a low average alignment score, words covering
under half of the audio, a first or last word far from the ends); a take that cannot be tied to the passage words is **not registered**, the others are
registered with a warning for a person to look at (`AlignmentGates` in `scripts/dataset/take_checks.py`, proposed limits).

### 9.6 Clean and baseline takes
No annotation file (`annotation_file: null`).

---

## 10. Registering and processing the files

Sequence once the WAVs exist (run from the repository root with the environment active):

| Step | Command / action | Status |
|---|---|---|
| 1. Audio quality check of every WAV (§11) | `python scripts/dataset/check_recordings.py <folder> --passages data/plan/passages_v1.json` | `[exists]` |
| 2. Environment check, once per computer (installs nothing; `--download-models` fetches the speech models) | `python scripts/check_environment.py --download-models` | `[exists]` |
| 3. Register: quality check again, copy to `data/raw/` (not committed, decision 3), hash, measure, preprocess, align with the passage text (WhisperX), plausibility checks, `alignment.json`, manifest/speaker/passage entries, proposed flaw annotations with the "was it performed" check, Audacity label files, dataset validation | `python scripts/dataset/prepare_recordings.py data/incoming` | `[exists]` (tested with a stand-in aligner; the real WhisperX run is the first real test) |
| 4. A person listens to the proposed flaws with the label files and sets `"annotation_status": "confirmed"` (§9.4) | Audacity + a text editor | `[manual]` |
| 5. Check schema, speaker separation, hashes | `python scripts/dataset/validate_dataset.py --check-files` (step 3 already runs it) | `[exists]` |
| 6. Build the baseline from dev baseline takes | add `--build-baseline` to step 3, or `python scripts/dataset/build_baseline_stats.py --passage-id p001 p002 --splits dev --overwrite` | `[exists]` |

Step 3 can be repeated safely: an unchanged take keeps its alignment and its confirmed annotation and nothing is written twice; a take recorded again needs
`--replace`. Use `--plan` / `--passages` when the plan or the passages live elsewhere, `--microphone` / `--conditions` for the values stored with new takes, and
`--realign` to align again. Without WhisperX, steps 3 can be done by hand with the examples in §9 (hash, duration, alignment script).

`data/` in the repository holds no recordings: `passages.json` has the two real passages, `speakers.json` the four anonymous speakers (details to be filled in),
`manifest.json` is empty until takes are registered (the schema fixtures were retired with).

`--splits dev` is deliberate: the baseline statistics come from **dev** speakers only, so test speakers never influence the baseline they
are measured against. (Whether test-speaker baselines may ever contribute is an open question recorded in .)

---

## 11. Quality gates (a recording counts only if it passes)

`scripts/dataset/check_recordings.py` reports these checks per file (all thresholds are in its `Gates` class). Definitions it uses: *room noise* is the 2nd percentile of the
32 ms frame levels (10 ms hop), so a take needs a little silence to be measured; *speech* starts at the first frame clearly above the noise (and not more than 40 dB below the
loudest point); *hum* is the strongest 50/60 Hz line (or harmonic up to 180 Hz) in the quietest parts. It was exercised on synthetic audio only; its limits are
starting points that the pilot must confirm.

| Check | Pass | Why |
|---|---|---|
| Format | WAV, mono, 16-bit PCM, 44.1 or 48 kHz (16 kHz acceptable) | Schema; stereo doubles the size |
| Size / length | under 10 MB (about 109 s of mono 16-bit at 48 kHz, 119 s at 44.1 kHz) | API upload limit is 10 MB; the length limit is 300 s. A 52 s take is about 5 MB |
| Clipping | no run of 3 or more full-scale samples | Clipped audio is unusable |
| Peak level | normal takes −18…−6 dBFS; loud takes up to −2 dBFS | Headroom and a usable signal |
| Noise floor | silent parts at or below −60 dBFS (warn above −55, fail above −50) | Pause detection (§6 step 5) |
| Lead / tail silence | 0.3–2 s each | Trimming works and nothing is cut off |
| Duration | within about ±25 % of the passage's expected duration | Catches missing/extra text |
| Mains hum / tones | no strong narrow line in the spectrum | Hum biases energy and pitch |
| Manual listen | each accepted take listened to once, by someone | Catches what numbers miss |

Test-split files get these checks only. A failed file is re-recorded, not repaired.

---

## 12. Using the dataset

### 12.1 Build the baseline
`python scripts/dataset/build_baseline_stats.py --passage-id p001 p002 --splits dev` writes `data/processed/baseline_stats/<passage>.json`.
It fails loudly if a statistic cannot be computed. Read the result: the analysis will warn (`baseline_thin_*` notes) if the baseline rests
on fewer than 5 rate windows or fewer than 3 within-phrase pauses.

### 12.2 Analyse
Start the API (`docs/setup.md`) or call the pipeline in-process. For every dev flawed and clean take: `baseline_id` = the passage id,
`passage_id` = the passage. Use the real transcription for the realistic case; passing the passage text as `manual_transcript` removes
transcription errors and isolates the delivery analysis. Do both and compare.

### 12.3 Evaluate
- **True positive:** a predicted flaw of the right type whose interval overlaps at least **50 % of an annotated flaw window**; each annotation
  matches at most one prediction. Unmatched prediction = false positive; unmatched annotation = false negative.
- **Per flaw type:** precision, recall, F1, and the mean absolute error of start and end times. Always report the number of events (n).
- **False-alarm rate:** share of `clean_control` takes with any predicted flaw (proposed target < 10 %).
- **Speaker variation:** clean takes of every speaker scored against the dev baseline (proposed: composite above 75).
- **Determinism:** run each take three times; `deterministic_json()` must be identical.
- A flaw type the system does not implement (`pitch_instability`) is reported as "not implemented", not as a failure of the others.
- Report **dev and test separately** and **human and synthetic separately**. The F1 > 0.65 target is aspirational, not a gate.

### 12.4 Calibrate on dev only
Tunable constants (all in `backend/app/core/config.py`, currently uncalibrated starting values): `Z_RATE_FAST`, `Z_RATE_SLOW`, `Z_ENERGY`,
`Z_PAUSE_WITHIN`, `Z_PAUSE_CROSS`, `MIN_FLAW_DURATION_S`, `MERGE_GAP_S`, the severity constants, `BASE_PENALTY` and the score weights.
Method: change one constant at a time, re-run the dev evaluation, keep a table of (value → F1 per type, false-alarm rate); choose the
value that maximises F1 while keeping false alarms on clean dev takes under 10 %. Record the choices in.

### 12.5 Freeze, then test once
1. Freeze: set `THRESHOLDS_CALIBRATED=true`, bump `CONFIG_VERSION`, commit.
2. Run the test split **once**. No constant may be changed after looking at test results.
3. Publish dev and test numbers side by side with their sample sizes. If a result is poor, say so; a documented limitation is better than a
   tuned-to-test number.

---

## 13. Storage, versioning and consent

- **Git** holds: `manifest.json`, `speakers.json`, `passages.json`, annotation JSON, alignment JSON, baseline statistics, this protocol.
  Since 2026-10-11 `.gitignore` excludes `data/raw/*` and `data/incoming/`, so recordings cannot be committed by accident.
  **Shared drive** holds the WAV files (decision 3). The manifest hashes let anyone verify their copy (`--check-files`).
- `dataset_version` is `1.0.0` for the first complete release; any later change to audio or annotations after the freeze is a new version
  (a version change invalidates cached analyses).
- **Consent:** each speaker agrees in writing that their recordings may be used for the hackathon project and shared as stated (repo /
  dataset / demo video), may be deleted on request, and are identified only by an anonymous id. Keep the signed consents and the
  id-to-name mapping **outside the repository**.
- Do not commit audio you do not have the right to share. Recordings of other people, including public videos, are not part of this
  dataset.

---

## 14. Automation map

| Item | Who | Status |
|---|---|---|
| Recording itself, consent, listening checks, judging "natural" delivery, verifying test labels | people | `[manual]` |
| Schema / split / hash validation | tool | `[exists]` `validate_dataset.py` |
| Baseline statistics from dev baseline takes | tool | `[exists]` `build_baseline_stats.py` |
| Analysis of a recording (API or in-process) | tool | `[exists]` |
| Recording plan sheet (take list, shuffled order, stretches, target durations, on-screen prompter page) | tool | `[exists]` `make_plan.py` (target durations are estimates at 150 words a minute until a speaker's own baseline takes are measured) |
| Audio quality check (format, clipping, noise floor, silence, duration, hum) | tool | `[exists]` `check_recordings.py` |
| Hashing, metadata, alignment with the passage text, manifest and `speakers.json`/`passages.json` handling | tool | `[exists]` `prepare_recordings.py` (WhisperX must run on your machine; first real run pending) |
| Planned stretch → annotation JSON (proposed), "was the flaw performed" check, word and flaw labels for Audacity | tool | `[exists]` `prepare_recordings.py` + `take_checks.py`; Audacity-label → JSON conversion (workflow B) is not built |
| Environment check and model download | tool | `[exists]` `scripts/check_environment.py` |
| Loudness normalisation change (§8.3) | tool | `[exists]` since 2026-10-11 |
| Retire the schema fixtures when real data arrives; `.gitignore` for audio | tool | `[exists]` (2026-10-13) |

---

## Appendix A — Plan sheet columns (one row per take)
`order, take_id, speaker_id, split, passage_id, category, flaw_type, intensity, severity_label, stretch (text), stretch_first_word, stretch_last_word (1-based word numbers
in the passage; for a pause, the two words either side of the silence), pause_after_word, instruction, normal_duration_s_est, target_duration_s_est, status
(todo/accepted/rejected), attempts, accepted_by, notes, recorded_at` (as written by `make_plan.py`)

## Appendix B — Troubleshooting
| Symptom | Likely cause | Fix |
|---|---|---|
| Noise floor above −55 dB | Mic boost, fan, laptop mic, hum | Lower the input volume, remove boost, move, switch off fans, use a headset |
| Steady line in the spectrogram | Mains hum / ground loop | Other USB port, unplug chargers, move away from power cables |
| Flat-topped waveform, red meter | Clipping | Lower the input gain by 3 dB; re-do §6 steps 6–7 |
| Loudness drifts within a take | Automatic gain control on | Switch it off (§6 step 3) |
| Popping on "p" and "b" | Mic in the breath stream | Move the mic beside the mouth; foam cover |
| Words missing in the alignment | Digits/symbols in the text, mumbling, noise | Spell numbers out; re-record |
| Flaw label does not match the audio | Track was edited after labelling, or file re-exported shifted | Re-label from the exported file; never edit after labelling |
| Validator: split mismatch | Speaker listed in the wrong split | Fix `speakers.json`/manifest; a speaker can be in one split only |
| Validator: annotation end beyond duration | Label made on a different version of the file | Re-export labels from the final WAV |
