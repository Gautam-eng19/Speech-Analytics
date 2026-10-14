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
* For step 6: a computer that can run the speech models (about 3 GB of downloads; a graphics card helps but is not required). Your own Windows computer is fine.

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
| 6 | Turn recordings into dataset files (list, hashes, word timing, labels) and try them on the site | **You run one command; I wrote it** (`prepare_recordings.py`) | 30 to 60 min the first time |
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
5. **Loudness (approved by you on 2026-10-11, now in the software):** the software scales each recording by its *typical speech level*
   instead of its *loudest point*. Before, one loud stretch made the whole rest of the recording look quieter (by up to 12 dB in my test).
   Details: decision DEC-036 and protocol section 8.3. **The recording instructions do not depend on this.** Since 2026-10-13 (DEC-040) the
   loudness detector compares every word with how the baseline readers read the same word, which finds a sentence that is about 5 dB louder
   or quieter; the loud and quiet takes are still recorded in an exaggerated way (+8 / +14 dB) so that a take is clearly a flaw.

### Step 2: Get the kit onto the recording computer

The speakers only need a web browser and Audacity. **The plan for your team (2 dev + 2 test speakers) is already in the repository**, so after
`git pull origin main` you can open the pages directly. The data owner needs Python only for the checker:

```bash
git pull origin main
python -m pip install numpy scipy          # all the kit needs; the big speech models are not needed for recording
```

* `data/plan/pilot/` is the **pilot** (9 takes, speaker `spk_dev_01`): open `prompter_spk_dev_01.html`.
* `data/plan/v1/` is the **whole plan** (112 takes, four speakers, two passages): `prompter_spk_dev_01.html` ... `prompter_spk_test_02.html`.

If your numbers change (3 speakers, only one passage), make a new plan with the same tool, for example:

```bash
python scripts/dataset/make_plan.py --dev 2 --test 1 --tier minimum --out data/plan/mine
```

**After the pilot**, make a personal plan that skips the nine recorded takes (the files must keep the names the prompter showed):

```bash
python scripts/dataset/make_plan.py --dev 2 --test 2 --tier recommended --done path/to/pilot/folder --out data/plan/local
```

Each plan folder contains:

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

### Step 6: Register the files and try them on the site (you run it on your own computer)

This turns the folder of WAV files into dataset files and builds the **baseline** the site compares against. It uses the real speech models, so
the first run downloads about 1 GB and takes a while; after that it is quick. Run the commands in **PowerShell**, one at a time.

**6a. Get the newest kit**

```powershell
cd "C:\Users\<you>\...\speechdummy"      # the folder that contains backend, frontend and scripts
git pull origin main
```

**6b. Install the packages once** (10 to 30 minutes; the environment goes in your home folder, outside OneDrive, which would try to sync thousands of files)

```powershell
python -m venv $HOME\speech-venv
Set-ExecutionPolicy -Scope Process Bypass        # only for this window; lets the next line run
& "$HOME\speech-venv\Scripts\Activate.ps1"      # the prompt now starts with (speech-venv)
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

In every new PowerShell window repeat the `Set-ExecutionPolicy` and `Activate.ps1` lines (and the `cd`) before the commands below.

**6c. Check the computer, and download the speech models once**

```powershell
python scripts\check_environment.py --download-models
```

Every line says `[OK]`, `[note]` or `[PROBLEM]`; under a problem, the line starting with `->` says what to type. Copy the output to me if a
problem stays.

**6d. Register the recordings and build the baseline**

```powershell
python scripts\dataset\prepare_recordings.py data\incoming --build-baseline
```

For each file it prints one line:

| Word | Meaning |
|---|---|
| `OK` | registered, nothing doubtful |
| `CHECK` | registered, but read the lines under it: the word timing looks doubtful, or the planned mistake was **not clear enough** ("weak example"). Record such a take again, or leave it out of the measurements |
| `FAILED` | not registered, with the reason (wrong file name, failed the recording check, the words could not be matched to the passage, ...) |

It also checks that each planned mistake really happened, by comparing the take with the same speaker's baseline takes. Run it again any time:
a take that did not change is skipped. A take you **recorded again** needs `--replace`.

At the end it says `Baseline for p001: built from 3 take(s)` and `Dataset check: valid`. If it says the baseline is **NOT built**, copy the message to me.
Under the baseline it also says `word-by-word profile: built (...)`: the site then compares every word with how the baseline readers read **the same word**, which is what makes the
findings accurate. If it says `NOT built`, the baseline has fewer than 3 takes of that text; record more baseline takes. A baseline built before this feature existed has no profile either, so
**rebuild the baseline after every update** (the same command, see 6g).

**6e. Listen to the planned mistakes (the important human step)**

The tool only *proposes* where each mistake is, from the plan and the word timing. A person must confirm it by ear.

1. In Audacity open one take, for example `data\raw\rec_p001_spk_dev_01_flaw_fast_01.wav`.
2. **File, Import, Labels...** and choose `data\processed\labels\rec_p001_spk_dev_01_flaw_fast_01.words.txt`, then import
   `...flaw.txt` the same way. Every word shows as a label on the sound, and the stretch that should hold the mistake is marked `PLANNED`.
3. Play it. Do the words sit on the sounds? Does the marked stretch start and end where the mistake is? If not, edit the numbers in
   `data\annotations\<take>.flaws.json`.
4. When you are happy, change `"annotation_status": "proposed"` to `"confirmed"` in that file. A later run never overwrites a confirmed file.

(For the test speakers this is done by someone who did **not** perform the take.)

**6f. Try a recording on the site**

```powershell
cd frontend
npm ci
npm run build
cd ..
python -m uvicorn app.main:app --app-dir backend
```

(`npm` needs Node.js 20.19 or newer; check with `node --version`. If it is missing, tell me and I will give you a ready-made dashboard instead.)
Then open <http://127.0.0.1:8000>, choose **Analyze**, pick the baseline (**Project talk**), drop in one of the flawed takes, for example
`rec_p001_spk_dev_01_flaw_fast_02.wav`, and press the run button. The first analysis takes a minute or two because the models start up.

Look for three things: (1) is the planned mistake found; (2) is it in the right place compared with the proposal in the annotation file; (3) does a **clean**
take stay quiet. Write down what is wrong and send it to me; that is exactly what we need to improve the system. If the recognised text looks wrong, open
"Advanced: supply the transcript yourself" and paste the passage text.

**6g. Measure how accurate the detection is (instead of judging by eye)**

```powershell
python scripts\dataset\prepare_recordings.py data\incoming --build-baseline     # after every update of the code: rebuilds the baseline, keeps the word timing
python scripts\dataset\evaluate_takes.py
```

It replays every dev take (not the baseline takes) through the real analysis, with no speech model and no internet, and compares what it finds with the planned flaws:

| Word | Meaning |
|---|---|
| `FOUND` | the planned flaw was found. It tells you how many seconds early or late the start and the end are (a minus means too early), how much of the detected range really was the flaw (`overlap`), and how long the detected range is compared with the plan (`1.0x` is exact, `3x` is three times too long) |
| `MISSED` | nothing of the same type covered at least half of the planned flaw. The lines under it say **why**: what the registration check said about the take (`this take is a weak example of the flaw` means the speaker did not do it clearly), how big the change really was over the planned words measured the way the analysis measures (`those 14 words were 9% faster ... z 1.8; a finding needs at least 15% with z above 4`), and whether the same kind of flaw turned up somewhere else in the take (it may have been performed in another place than planned) |
| `EXTRA` | something was flagged that nobody planned. On a clean take every `EXTRA` is a false alarm. On a take with a planned flaw the line ends with **where** it lies: `on the planned ... stretch` or `2.3 s after the planned ... stretch` is usually a side effect of how the flaw was performed (someone who speaks quietly often slows down too); `away from every planned flaw` is the kind to check by ear |

The summary at the end has one line per kind of flaw: how many were found, how far off the start and end are, how many flags of that kind nobody planned, and two scores: **precision** (of the flags of that kind, how many were planned: low means many unplanned flags)
and **F1** (one number from 0 to 1 that is high only when the flaws are found and few unplanned flags appear; the project proposes above 0.65 per kind, ARCHITECTURE.md 25.3 -- but unplanned flags next to a planned flaw are often real side effects, so judge them with the `EXTRA` lines).
It then counts the false alarms on clean takes and ends with **Listen to these first**: the places where the plan and the analysis disagree (a planned flaw that was not found, a flag on a clean take, a flag away from the plan), with the seconds.
Open that take in Audacity (`data\raw\<take>.wav`) and play the stretch: the ear decides who is right. To see the findings on the take itself, add `--labels` (`python scripts\dataset\evaluate_takes.py --labels`): it writes `data\processed\labels\<take>.detected.txt`, which you import in Audacity
(**File, Import, Labels...**) next to the word and planned-flaw labels of 6e; each label says FOUND or EXTRA, the type, the severity and the evidence.
To try another setting without changing any file, add for example `--detect z_pause_within=3 min_pause_s=1.0`, or `--detect use_profile=false` to see the old way (overall averages, 8 second windows). **Send me the whole output**: it tells me exactly what to improve.
Only the dev speakers are replayed; the test speakers stay sealed (the tool refuses them unless you add `--allow-test`, which is for the single final run).

**6h. Choose the settings from numbers (the sweep)**

```powershell
python scripts\dataset\evaluate_takes.py --sweep "z_run_rate=3,3.5,4,4.5,5" "run_min_words=8,10,12" "min_rate_change_pct=10,15,20" "min_energy_change_db=2,3,4" "min_pause_s=1,1.2,1.5"
```

(Keep the quotation marks: PowerShell would otherwise cut each list at its commas.) It prints one table. Each row changes **one** setting (the first row is the normal settings) and counts how many planned flaws were found, how many other flags appeared on the flawed takes,
how many clean takes were flagged, and the false alarms per minute of clean speech (`away` counts the extras that are not on or right next to a planned flaw). A good setting finds more and flags less. It takes a few minutes. **Send me the whole table**; I choose
the values from it. Do not choose by looking at one take: change nothing in a file, this command never does.

Still to do: the final frozen test run (TASK-127).

### Step 7: Record everyone else

* Same room, same microphone, same settings for every speaker if at all possible.
* Order: baseline takes, then clean takes, then flawed takes in the shuffled order of the plan (the prompter follows it).
* Take a break every 45 to 60 minutes. Copy the files to the shared drive **before** leaving the room.
* **Test speakers:** the files are checked for format and clipping only. Nobody runs the analysis on them and nobody who tunes the
  system listens to them, until the settings are frozen.
* The person who confirms a test speaker's flaw labels should **not** be the person who performed the take.

### Step 8: Use the dataset (I do this with you)

1. Build the **baseline** from the dev speakers' baseline takes (step 6d does it).
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
| `pip install` fails or is very slow | Large downloads, a flaky connection, or the wrong Python | Run it again (it continues); use Python 3.10 to 3.13; copy the last 20 lines to me |
| `check_environment.py` says torch "DLL" or "WinError 126" | The Microsoft Visual C++ Redistributable is missing | Install "vc_redist x64" from microsoft.com and run it again |
| `check_environment.py` says a model could not be downloaded | No internet, a VPN or school proxy | Try another network, run the command again |
| `prepare_recordings.py`: `FAILED ... returned N words but the passage has M words` | The person read different words, or the aligner split a word | Listen to the take; if the words differ, record again |
| `prepare_recordings.py`: a take is `CHECK` with "weak example" | The planned mistake was too small to count | Record that take again, a clearer mistake |
| `Baseline for p001: NOT built` | The baseline takes have too few natural pauses to measure | Copy the message to me; usually the three baseline takes are recorded again with the pauses at commas and full stops |
| `evaluate_takes.py` says a take "could not be replayed" | Its word timing is missing or no longer matches (the recording was replaced) | Run `prepare_recordings.py data\incoming --realign` first |
| `git pull` says local changes would be overwritten | The tool changed `data\metadata\*.json` on your computer | Tell me before you pull; do not delete the files |
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
| Registering files, hashes, word timing, label files | run `prepare_recordings.py` on your machine | **wrote and tested the tool** (the real speech model has not been run yet; the first run is the real test) |
| Confirming flaw labels by ear | **yes** (not the performer, for test) | prepare them |
| Baseline, measuring, tuning, frozen test run | decide and review | **run and analyse** |
| Dashboard with real results, demo video | review | build |
