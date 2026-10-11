# The dataset in plain words: what to do, step by step

This is the short, friendly version of [`recording-protocol.md`](recording-protocol.md). If the two ever disagree, the protocol wins
and this page should be fixed. Read this page first; open the protocol when you want the reason behind a number.

---

## 1. What we are building (60 seconds)

The system compares a person's reading of a text with a **good reading of the same text**, and points at the moments where the
delivery went wrong. To check that it works, we need an **answer key**: recordings where we know exactly what was done and when.

So we record people reading the same short texts (about 50 seconds each) in three ways:

| Kind of recording | What the speaker does | What it is used for |
|---|---|---|
| **Baseline take** | Reads the text clearly, at a natural steady pace | Teaches the system what good delivery looks like |
| **Flawed take** | Reads normally, except **one planned sentence** where they make one planned mistake (too fast, too slow, a long silence, too quiet, too loud) | The answer key: did the system find that mistake, in that place? |
| **Clean take** | Reads normally again | Checks the system stays quiet when nothing is wrong |

Everything else (file names, labels, statistics) is paperwork around those recordings. **I automate the paperwork. Only people can
speak and listen.**

---

## 2. Words you will meet

| Word | Meaning |
|---|---|
| **Passage** | The text everyone reads. We have two ready: "Project talk" (`p001`) and "Morning market" (`p002`) in `data/plan/passages_v1.json` |
| **Take** | One recording of the whole passage |
| **Speaker** | A person who reads. Each gets an anonymous id such as `spk_dev_01` |
| **dev / test** | Two groups of speakers. **dev** speakers' takes are used to build the baseline and to tune the system. **test** speakers are different people, kept sealed until the very end, so the final score is honest |
| **WAV** | The audio file type we use (uncompressed). Phone apps often make `.m4a`, which has to be converted |
| **Clipping** | The recording was too loud and the top of the sound was cut off. It cannot be repaired, so we record again |
| **Noise floor** | How loud the room is when nobody speaks. We need it very quiet |
| **Label / annotation** | A small file saying "in this recording, a too-fast flaw happened from second 14.6 to 20.3" |

---

## 3. What you need

* **A quiet room** and **one microphone** for everybody (a USB headset is best).
* **Audacity** (free, Windows/macOS/Linux, audacityteam.org) to record and export. Use Audacity for dataset takes, **not** the dashboard's
  "Record now" button: that recorder is handy for demos but has not been tried with a real microphone yet.
* **A web browser** to open the prompter pages.
* **One computer with Python 3.10 to 3.13** for the data owner, who runs the three small commands below. The speakers need nothing else.
* **A shared drive or external disk** for the audio, and a private folder for the signed consent forms.
* Later, for step 6: a computer that can run the speech models (about 3 GB of downloads; a graphics card helps but is not required).

Keep exported recordings in a folder **outside the repository**, or in `data/incoming/` (git ignores that folder and `data/raw/`, so voices
cannot be committed by accident).

---

## 4. The plan at a glance

| Step | What happens | Who | Time |
|---|---|---|---|
| 1 | Decide: who records, which mic, where files live | **You** | 15 min |
| 2 | Prepare the kit: passages, plan sheet, on-screen prompter, quality checker | **Me** (done, in this repository) | done |
| 3 | Set up the room and microphone | Each speaker | 15 min each |
| 4 | **Pilot:** one person records 9 takes | One speaker | about 45 min |
| 5 | Check the pilot files with the checker | You, then send me the result | 10 min |
| 6 | Turn recordings into dataset files (list, hashes, word timing, labels) | **Me** (I write the tools right after your pilot) | |
| 7 | Everybody records the rest | Speakers | see step 1 (tiers) |
| 8 | Build the baseline, run the system, measure, tune on dev, freeze, test once | **Me**, with you listening and deciding | |

Why a pilot first: the real speech models have never run on a real recording here. I want to see what they do with nine real
takes before anyone records a hundred.

---

## 5. Step by step

### Step 1: Decide (you)

Write the answers down; I will turn them into the plan.

1. **How many speakers?** Best: **4** (2 dev + 2 test). With **3**: 2 dev + 1 test (works; the test result then rests on one voice).
   With 2: 1 dev + 1 test (only a smoke test). Put the two clearest, steadiest speakers in **dev**, and never move anyone between
   groups.
2. **How much?** Pick the tier that fits your time:

   | Tier | Passages | Takes in total (2 dev + 2 test) | Rough time, everyone together |
   |---|---|---|---|
   | **Pilot** | 1 | 9 (one speaker) | under 1 hour |
   | **Minimum** | 1 | 36 (28 with 3 speakers) | about 2 to 3 hours |
   | **Recommended** | 2 | 112 (86 with 3 speakers) | about 5 to 6 hours |

   The tiers are nested: every pilot take is also part of the minimum, and every minimum take is part of the recommended plan, with
   the same file names. Nothing is ever recorded twice.
3. **Microphone and room.** One **USB headset** for everybody is best (the same distance to the mouth every time). One phone on a stand
   also works if every take uses **the same phone in the same position**. One small quiet room for all sessions.
4. **Where the audio lives.** On a **shared drive or an external disk, not in GitHub**. These are people's voices. Each speaker signs the
   consent form ([`consent-form-template.md`](consent-form-template.md)) first.
5. **Approve one change I propose** (it needs your yes before any baseline is built): the software should scale each recording by its
   *typical speech level* instead of its *loudest point*. Today, one loud stretch can make the whole rest of the recording look quiet and
   cause false alarms. Details: protocol section 8.3. **The recording instructions do not depend on this**, so you can answer later,
   but before step 8.

### Step 2: Get the kit onto the recording computer

The speakers only need a web browser and Audacity. **One person (the "data owner") runs three small commands.**

```bash
git pull origin main
python -m pip install numpy scipy          # all the kit needs; the big speech models are not needed for recording
python scripts/dataset/make_plan.py --dev 2 --test 2 --tier pilot --out data/plan/pilot
```

(Change `--dev 2 --test 2` to your numbers and `--tier pilot` to `minimum` or `recommended`.) This writes, into the folder you named:

* `plan.csv`: every take, in recording order, with its instruction;
* `prompter_spk_dev_01.html` (one per speaker): **double-click it** to open it in a browser. It shows the passage, highlights the
  planned stretch, says what to do, shows the exact file name to save, and keeps count;
* `session_log.csv`: an empty sheet for notes about each session.

The plan is the same on every computer (same numbers in, same plan out), so teammates can generate it themselves and get identical files.

### Step 3: Set up the room and microphone (once per speaker per session)

The prompter shows this as a checklist you tick before the first take. In short:

1. Quiet room, door and windows closed, phones silent, fans and air conditioning off, chat and meeting programs closed.
2. Headset boom beside the corner of the mouth, 3 to 4 cm away, **not** in the breath. Mark the spot with tape.
3. In the computer's sound settings switch **off** audio enhancements, noise suppression, automatic gain and voice isolation.
4. **Audacity** settings: Recording channels **1 (Mono)**; Project rate **48000 Hz** (the same for every recording); sample format
   **16-bit**.
5. **Silence test:** record 10 seconds of silence. The meter should show about **-60 dB or lower** (worse than -50: fix the room).
6. **Normal voice test:** the loudest syllables should reach about **-16 dB**.
7. **Loud voice test:** peaks must stay at or below **-2 dB**, never red. If it clips, lower the input volume and test again.
8. Write the input volume setting in the session log. **Do not touch any setting again** until the session ends.

### Step 4: The pilot (one speaker, 9 takes)

Use `prompter_spk_dev_01.html`. For each take:

1. Read the instruction on the page. For a flawed take, practise the flaw once without recording.
2. Audacity: press **Record**, stay silent for about **1 second**, read the **whole** passage, stay silent about **1 second**, press **Stop**.
3. Look at the meter and waveform. Red or flat tops (clipping), a cough, a word wrong or missing? Click **Reject** (or press R) and record again.
   At most 3 attempts per take, then a break.
4. Otherwise click **Accept** (or press A). Then **File > Export > Export as WAV**, encoding **Signed 16-bit PCM**, and **use the file name
   shown on the page** (use "Copy name"). **Do not edit the recording first**: no trimming, no volume change, no noise removal.
5. Next take.

Never reject a take because of what the software does with it, only because of the checklist on the page.

### Step 5: Check the files

```bash
python scripts/dataset/check_recordings.py path/to/the/folder --passages data/plan/passages_v1.json
```

Each file gets **PASS**, **WARN** or **FAIL**, with the reason and what to change in plain words. A FAIL means: record that take again
(do not repair it). A WARN is usable but worth fixing next time. **Copy the whole output and send it to me** together with a note on
anything odd in the session; I will adjust the plan before the full recording.

### Step 6: Dataset files (I do this; you run it on a machine that can run the speech models)

After the pilot I write the tools that:

* measure each file and write its entry in the dataset list (`manifest.json`), including a fingerprint (hash) so nobody can swap a file by accident;
* find the time of every word (forced alignment, WhisperX) so a flaw can be given exact seconds;
* turn "sentence 5 was the flawed one" into exact start and end times, which a person then **listens to and confirms**;
* check the whole dataset for mistakes (the validator already exists).

I wait for the pilot on purpose: I want to see how the real aligner behaves on real recordings before writing the tool around it.

### Step 7: Record everyone else

* Same room, same microphone, same settings for every speaker if at all possible.
* Order: baseline takes, then clean takes, then flawed takes in the shuffled order of the plan (the prompter follows it).
* Take a break every 45 to 60 minutes. Copy the files to the shared drive **before** leaving the room.
* **Test speakers:** the files are checked for format and clipping only. Nobody runs the analysis on them and nobody who tunes the
  system listens to them, until the settings are frozen.
* The person who confirms a test speaker's flaw labels should **not** be the person who performed the take.

### Step 8: Use the dataset (I do this with you)

1. Build the **baseline** from the dev speakers' baseline takes.
2. Run the system on the dev flawed and clean takes and **measure**: did it find each planned flaw, in the right place; how often did it
   cry wolf on clean takes?
3. **Tune** the thresholds on dev only, one setting at a time, writing down every change.
4. **Freeze** the settings.
5. Run the **test** speakers **once**. Report dev and test results side by side, with the number of cases. A poor result is reported
   as it is.
6. Show real results in the dashboard and use them in the demo video.

---

## 6. Seven rules that protect the dataset

1. **Same text, word for word.** No extra words, no skipped words, no "um".
2. **Record raw.** No normalising, compression, noise removal or trimming, ever. The software treats every file the same way; hand
   editing only creates differences it would mistake for delivery.
3. **One planned flaw per flawed take**, only where the plan says, with normal reading everywhere else.
4. **dev and test are different people**, decided before the first recording and never changed.
5. **Accept or reject a take using the checklist, before seeing any system output.**
6. **Never change the setup during a session** (mic position, input volume, room).
7. **Audio never goes into GitHub**, and every speaker has agreed in writing.

---

## 7. If something goes wrong

| Problem | Likely cause | What to do |
|---|---|---|
| Checker says "room noise" | Fan, mic boost, laptop microphone, noisy room | Switch off fans, lower input volume, remove boost, use the headset, move |
| "Clipping" or red meter | Input volume too high | Lower it by about 3 dB, repeat the loud test, record again |
| "Speech reaches the very start" | Started talking too soon | Wait a full second after pressing Record |
| "Steady tone (mains hum)" | Charger, cable or bad USB port | Try another USB port, unplug chargers, move away from power cables |
| "Length ... words are probably missing or added" | A word was dropped or repeated | Listen to the take; record again |
| The phone produced `.m4a` | Phone recorder format | Convert to WAV, mono, 16-bit (`ffmpeg -i in.m4a -ac 1 -sample_fmt s16 out.wav`), and use the same phone for every take |

More in protocol Appendix B.

---

## 8. What to send me, and when

| After | Send |
|---|---|
| Step 1 | Number of speakers, tier, microphone, deadline |
| Step 5 | The checker's output, what felt confusing, how long the nine takes took |
| Step 7 | Which speakers and takes are done; any take you doubt |

Not the audio files themselves in the chat unless you ask me to look at them: recordings of people stay out of the repository.

---

## 9. Who does what

| Task | You and the team | Me |
|---|---|---|
| Decide speakers, tier, equipment, consent | yes | advise |
| Final passages, plan sheet, prompter, quality checker | | **done** |
| Recording, listening, accepting or rejecting takes | **yes** | |
| Registering files, hashes, word timing, label files | run on your machine | **write and test the tools** |
| Confirming flaw labels by ear | **yes** (not the performer, for test) | prepare them |
| Baseline, measuring, tuning, frozen test run | decide and review | **run and analyse** |
| Dashboard with real results, demo video | review | build |
