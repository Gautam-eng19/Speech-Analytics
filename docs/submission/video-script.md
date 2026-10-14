# Demo video script — VAANI (about 9 minutes)

**How to use this page.** Everything after a `>` is what you say, word for word. Everything under **On screen** is what the viewer sees at that moment.
Read it aloud once before recording; wherever a sentence feels stiff in your mouth, change it to how you would say it to a friend. The facts and numbers
are real (they come from our own evaluation run on the team's recordings), so keep those exactly as written.

**Length.** About 1,390 spoken words: roughly 9 minutes at a steady 155 words a minute, about 9½ with the three short audio clips from the demo takes. The hackathon allows 3 to 10 minutes,
so time yourself once; if you are over 9:45, the cuts are listed in section 10.

**The one idea the whole video serves:** *a score tells you nothing you can act on; a time, a measurement, a reason and a suggestion does.*

---

## 0. Before you press record

| Do this | Why |
|---|---|
| Start the site: `python -m uvicorn app.main:app --app-dir backend`, open http://127.0.0.1:8000, browser zoom 110 %, dark or light theme (pick one and keep it) | The judges must **see the project running** |
| Have these three takes ready to upload (they are the strongest in our evaluation) — see section 7 for what each one shows | Clear, large, correctly located flaws; no confusing extras |
| `rec_p001_spk_dev_01_flaw_fast_02.wav` (too fast) | |
| `rec_p001_spk_dev_01_flaw_pause_02.wav` (excessive pause) | |
| `rec_p001_spk_dev_02_flaw_loud_02.wav` (too loud, a different speaker) | |
| Run each of the three analyses **once before recording** and keep the result pages open in tabs (the result is stored, opening it again is instant) | The real analysis takes a while; do not make viewers wait on camera |
| Make the five visuals in section 8 (simple boxes and arrows; PowerPoint, Canva or Excalidraw is fine) | The video is carried by these |
| Record the voice in a quiet room, same microphone for the whole video; speak slightly slower than normal conversation | Clear English audio is a requirement of the submission |
| After uploading to YouTube (**Unlisted**, not Private) turn on English subtitles; correct the automatic ones with the text below | English audio or subtitles is a requirement |

---

## 1. Hook — 0:00 to 0:50

**On screen:** Black, then the title *VAANI — where exactly did the delivery drift, and by how much?* Cut to a recording's waveform playing; at the end of the section
a single finding card slides in over the waveform (use the "too fast" card from section 7).

> Imagine you rehearse a talk, and someone tells you: "You need to speak more clearly."
>
> That's it. Which part? By how much? What should you change? Nothing you can act on.
>
> Most speech tools give you one number, or a paragraph of advice from an AI that never actually measured anything.
>
> We built something different. Our system listens to how you delivered a passage, compares it with a good delivery of the *same words*, and tells you things like:
> "Between twenty-three and twenty-six seconds, you were speaking at two hundred and ninety-six words a minute. Your baseline is one hundred and seventy-five."
>
> A time. A measurement. A reason. And what to do about it. I'm **[your name]**, and this is VAANI, our entry for Track C.

---

## 2. The idea in one picture — 0:50 to 1:40

**On screen:** Visual A, "Same words, two readings" (section 8). Build it in three steps as you speak: first the three baseline strips, then the participant strip, then the
highlighted run of words that is slower.

> The idea fits in one sentence: *compare like with like.*
>
> Different text is read differently. A long word takes longer. A comma invites a pause. If you compare a speaker with some "average human", you end up judging the text and the voice, not the delivery.
>
> So in our system, the baseline is a few good readings of the *same passage*. We measure how every single word is normally read — how long it takes, how loud it is, how much the pitch moves — and
> then we ask one question: where did *this* reading drift away from that?
>
> And we only judge delivery. Not what you said, not whether the speech is any good. Delivery.

---

## 3. The pipeline — 1:40 to 5:00

**On screen:** Visual B, the pipeline (section 8). Keep it up for the whole section and light up one box at a time as you name it. Small labels on the arrows show *what data flows
between the boxes* — read them out; that is exactly what the judges asked to understand.

### 3a. From audio to timed words — 1:40 to 2:35

> Here is the journey of one recording.
>
> The audio comes in as a WAV or MP3 file. Step one is preprocessing: we convert it to one standard format, and we scale it to a typical speech level — so a quiet microphone doesn't look like a quiet speaker.
>
> Step two is transcription. Whisper writes down what was actually said. That lets us warn you if the reader wandered away from the passage.
>
> Step three is the one that makes everything else possible: forced alignment. WhisperX takes that transcript and places every single word on the timeline — a start time and an end time for each word.
>
> Why does that matter? Without word times, we could only say "somewhere in the recording". With them, we can say "words forty-one to sixty-two, from twenty-three point four seconds."

### 3b. Features and the baseline — 2:35 to 3:30

**On screen:** Zoom into the middle of Visual B: a small chart of the five features on one time axis (pitch, energy, speed, pauses, MFCC), then the baseline file as a small card:
"for every word: expected duration, expected loudness, expected pitch movement, normal variation".

> On that timed audio we measure five things: pitch, energy — which is loudness — speech rate, pauses, and MFCCs, which describe the voice's sound.
>
> Each one is written once, in one place, in the backend. The website never calculates anything. It only draws what the backend sends. That rule is written into our project constitution, and the dashboard code follows it.
>
> The baseline goes through exactly the same steps, using the good readings. What we keep is a small statistics file: for every word of the passage, how long it normally takes, how loud it is, how much the pitch moves — and, just as important, *how much good readers normally differ from each other*.
>
> That variation is our tolerance. Two good readings are never identical, so a flaw has to be bigger than normal variation to count.

### 3c. From numbers to flaws — 3:30 to 4:30

**On screen:** Visual A again, now animated: the participant's strip is lined up on the baseline's band; a run of words that sticks out of the band lights up, with its numbers
("+69 % pace", "z = 10.9") appearing beside it. Then the severity bar.

> Now the contrast. We lay your words on top of the baseline's words. First we remove your overall habits — some people just speak a bit faster or louder, and that's not a flaw.
>
> Then we scan for runs of at least ten words that drift further than chance allows, *and* by an amount that matters: at least fifteen percent in pace, at least three decibels in loudness.
> Pauses are judged against how long a pause of that kind normally lasts.
>
> Every run that passes becomes a flaw, with a start, an end, a type, and the measurements behind it. Then severity, from zero to one, based on how big the change is and how long it lasts.
>
> And all of this is deterministic. Same recording, same settings, same result — every time. The result's id is even a fingerprint of everything that went in.

### 3d. Evidence first, words second — 4:30 to 5:00

**On screen:** Visual C, the evidence chain (section 8): *timestamp → measurement → flaw type → explanation → recommendation*, filled with the real numbers of the "too fast" finding.

> Only now do words appear. The explanation is written *from the evidence*, and a separate guard checks that every number in the sentence exists in the evidence.
>
> An AI model is allowed to phrase things, but never to invent a timestamp, a percentage or a score. Today our explanations come from templates, so there's no language model in the loop at all.
>
> Then the API returns one structured result, and the dashboard shows it. Let's see it.

---

## 4. The site — upload and first look — 5:00 to 5:40

**On screen:** Terminal for three seconds showing the server running (`uvicorn ... Application startup complete`), then the browser on the VAANI **home page**. Let the headline and the instrument sit for two seconds, move the pointer slowly along the trace (the readout under it changes),
click the first finding's label so the clip plays. Then press **Analyse a recording** (the page scrolls to the analysis flow), pick the baseline, drop in the "too fast" take, press **Analyse recording**. Show the progress text, then cut to the finished result.

> This is the real system running on my machine.
>
> The first thing you see is a real analysis of one of our demo recordings, a synthetic voice. Under the pointer, every number is read from the result — the pace, the loudness, the pitch at that exact moment — and the copper marks are the places the system found a deviation. Click one and you hear it.
>
> Now my own recording. I choose the baseline — here, a passage we recorded readings of — and upload it. The audio is analysed in memory and isn't saved; only the result is.
>
> The server transcribes, aligns, measures and compares. I've run these in advance, so let's jump to the result.

---

## 5. Flaw one — too fast — 5:40 to 6:30

**On screen:** Overview page (a quick two seconds), then the **Timeline**: click the red "too fast" band, the playhead jumps to it; press play for the **clip of about eight seconds** around it; then the **Flaws** page with the
evidence panel open.

> Take one. The timeline shows the whole recording, and here, one finding. Let me play it.
>
> *[play about 8 seconds of the flagged stretch; let the viewer hear the speed]*
>
> You can hear it — it rushes. (Scroll the Overview for five seconds: the **score profile** shows each dimension against the reference ring, with what the finding cost in copper.) Now the evidence. Twenty-three point four to twenty-six point six seconds. The speaker averaged **two hundred and ninety-six words a minute**. For these same words, the baseline readers averaged **one hundred and seventy-five**.
> That is ten point nine standard deviations away — far outside normal variation. And the page says why that counts as a delivery flaw, and what to try: slow down in this stretch, aim for about one hundred and seventy-five words a minute, and keep the pauses between phrases.
>
> We planted this flaw at twenty-three point four to twenty-six point nine. The system found it from twenty-three point four to twenty-six point six. That is the whole idea: a place, a measurement, a reason.

---

## 6. Flaw two — an excessive pause, and flaw three — too loud, a different speaker — 6:30 to 8:00

### Flaw two (6:30 to 7:10)

**On screen:** Open the pause take. On the timeline the pause band; evidence panel showing the pause numbers.

> Take two is a different kind of flaw: a pause. A pause is judged on its own scale — against how long pauses of this kind normally last in the baseline.
>
> Here the speaker stopped for **three point five seconds** between two sentences. In the baseline, a pause between sentences lasts about **six tenths of a second**. That's over twenty standard deviations away. And it's exact: the finding runs from thirty-two point seven to thirty-six point three seconds, the same as what we planned. The advice: keep the pause close to point six seconds, as in the baseline.

### Flaw three (7:10 to 8:00)

**On screen:** Open the loud take (a different speaker). Timeline band, evidence panel: level numbers; briefly the Signals page with the loudness curve.

> Take three is a different speaker, and a different flaw: too loud. The loudness curve on the Signals page shows the jump.
>
> The speaker's level in this stretch is **minus twenty-four decibels**, where the baseline readers are at **minus thirty-three and a half**. About nine decibels louder, over exactly the six seconds we planned.
>
> The advice that comes with it: ease the volume back, and let emphasis come from pace and pitch variation instead of loudness.
>
> Same system, different voice, different kind of flaw — and the same answer: where, how much, why, and what to do.

---

## 7. What the three demo takes show (for you, not to read out)

| Take | Flaw | What the system found | Why this take |
|---|---|---|---|
| `rec_p001_spk_dev_01_flaw_fast_02` | too fast | 23.4–26.6 s (planned 23.4–26.9); 296 vs 175 words/min; z 10.9; overlap 94 % | the one most people understand at once; nothing else was flagged in this take |
| `rec_p001_spk_dev_01_flaw_pause_02` | excessive pause | 32.7–36.3 s (planned 32.7–36.3, exact); pause 3.52 s vs 0.60 s usual; z 22.9 | a flaw that is not about speed: shows a different rule; exact boundaries |
| `rec_p001_spk_dev_02_flaw_loud_02` | too loud | 30.9–36.9 s (planned 30.9–36.9, exact); −24.3 dBFS vs −33.5 expected; z 11.0 | a second speaker; shows it is not tuned to one voice |

Backup, if you want a fourth or one of the above misbehaves: `rec_p001_spk_dev_01_flaw_slow_02` (too slow: 94 vs 190 words/min, z −14.6, found 30.4–42.3 s, overlap 98 %). On that take
the system also flags a "high energy" finding on the same stretch — a real side effect (the speaker got louder while slowing down). It is a good place to say, honestly, *"people never change one thing at a time"*.

The composite score of these takes is high (about 94 to 96 out of 100) because it only subtracts for the flawed seconds. Do **not** present it as a grade. Say nothing about it, or say:
*"The score is deliberately gentle. The findings are the product."* (Calibrating the score is on our task list.)

---

## 8. Custom passage, and the honest numbers — 8:00 to 8:45

**On screen (first half):** Sidebar → **Custom passage**. Show the three steps with real text typed in, two or three recordings listed, and the "Baseline ready" card. (Do not make the
baseline live on camera; it takes about a minute per recording. Show a finished one.)
**On screen (second half):** Visual E, a simple bar chart: found per flaw type, out of 8 each — pauses 8, slow 8, loud 7, fast 6, quiet 5 — and the line "clean takes flagged: 1 of 8".

> One more thing. Anyone can bring their own text. On this page you paste a passage, add two or three recordings of a good reading to make your own baseline, and then analyse your reading against it. Only statistics are stored, never your audio.
>
> And now, honestly, how well does it work? We tested on forty-eight recordings from two speakers: forty with a planned flaw, eight clean. The system found **thirty-four of the forty** planned flaws — all eight pauses, all eight slow stretches, seven of eight loud, six of eight fast, five of eight quiet.
> Starts and ends land within about half a second. Only one of the eight clean recordings was flagged.
>
> The six misses were all from one speaker, and most were takes where the flaw was milder than planned — our evaluation tool tells us by how much. We are not claiming calibrated accuracy: these are development speakers, and the annotations are still being confirmed by ear.

---

## 9. Close — 8:45 to 9:10

**On screen:** Back to Visual C (the evidence chain), then the title card with the repository address and your names.

> So that is VAANI. Audio goes in. Every word is timed. Delivery is compared with the same words read well. And what comes out is not a score, but a time, a measurement, a reason and a suggestion — all computed by deterministic code, with the evidence checked before any explanation is written.
>
> There are nearly fourteen hundred backend tests and nearly four hundred dashboard tests behind it, and every claim here can be re-run from our repository.
>
> Thank you for watching. The code, the setup instructions and the documentation are in the repository linked below.

---

## 10. If you run long, cut in this order

1. Section 3b, the sentence about MFCCs (10 s).
2. The Custom passage paragraph in section 8 (25 s) — it is a bonus, the core is the three flaws.
3. The Overview-page glance and the terminal shot in section 4 (10 s).
4. Flaw three (50 s). Keep it if you can: a second speaker is your proof that it is not tuned to one voice.

If you run **short**, add the backup take `flaw_slow_02` and tell the side-effect story from section 7.

---

## 11. The five visuals (make these before recording)

Keep them simple: boxes, arrows, one accent colour for "the finding", the same fonts as the site. One idea per slide.

**Visual A — "Same words, two readings".** A passage of about 20 words across the top. Under it, three thin grey strips (the baseline readings): each word is a rectangle whose width is how long the
word took; the strips line up almost exactly (that is "normal variation": show it as a light band). Under them, one blue strip, the participant: most words line up, but words 41 to 62 are narrower (faster) and
fall outside the band; colour that run red and label it "+69 % pace, z = 10.9". *(The 69 % is 296 versus 175 words a minute.)*

**Visual B — the pipeline, left to right, with the data on the arrows.**
`Audio (WAV/MP3)` →(*samples, 16 kHz, scaled to speech level*)→ `Preprocessing` →(*clean audio*)→ `Whisper: transcription` →(*what was said*)→ `WhisperX: forced alignment` →(*every word with start and end*)→
`Features: pitch · energy · rate · pauses · MFCC` →(*numbers per word and per frame*)→ `Compare with baseline statistics` →(*runs of words that drift: size and z-score*)→ `Severity and score` →(*flaw: start, end, type, severity, evidence*)→
`Explanation templates + number guard` →(*text built from evidence*)→ `API (one JSON result)` → `Dashboard (draws only)`.
Underneath, a second row: `Good readings of the same passage` → (same steps) → `Baseline statistics file` feeding into "Compare". A thin bracket over the last two boxes: "the frontend never calculates".

**Visual C — the evidence chain.** One card, five rows linked by arrows: **When** 23.4–26.6 s → **Measured** 296 vs 175 words/min, z 10.9 → **Flaw** too fast → **Why** "the pace of this run of words was far above the baseline's pace for the same words" → **Try** "Slow down in this stretch: aim for about 175 words/min … and keep the pauses between phrases." (These are the site's own words; copy them from the Flaws page.)

**Visual D (optional, 10 s) — who owns what.** Two columns: *Backend owns:* validation, alignment, features, baseline comparison, scoring, explanation. *Frontend owns:* upload, playback, drawing, navigation.
A red line between them: "no analysis in the browser".

**Visual E — results.** A horizontal bar per flaw type out of 8: pauses 8, slow 8, loud 7, fast 6, quiet 5. Under it: "40 planned flaws · 34 found · clean takes flagged 1 of 8". Small footer:
"2 development speakers · annotations not yet confirmed by ear".

---

## 12. Words to say the same way every time

- "baseline" = *good readings of the same passage* (never "average person").
- "delivery" = how it was said (never what was said).
- "evidence" = the measured numbers behind a finding.
- Say numbers as the viewer will read them: "two hundred and ninety-six words a minute".

---

## 13. Honest limits (have these ready in case a judge asks)

- The thresholds are starting values, not yet calibrated; every result says so in its notes.
- The in-browser recorder has been tested with a fake microphone and with the team's own files, not on every browser or phone.
- Flat pitch is implemented but has only been tested on synthetic speech and clean real takes; no real monotone recording exists yet. Unstable pitch is not detected.
- The real WhisperX / Whisper models were run on the team's computers, not in our development sandbox, so the time per recording may vary on yours.
- Custom baselines are shared by everyone using the same server (there are no user accounts).
- On the flawed takes the system also raised 17 flags nobody planned. Most are real side effects (people also get louder when they slow down, or catch up after a pause); four were away from every planned flaw and still need listening to. Say so if asked about false alarms.
