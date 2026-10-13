# Dataset Methodology and Schema Specification

## Track C — Contrastive Speech Analytics & Temporal Flaw Grounding
**Document Type:** Methodology & Specification  
**Status:** Canonical Dataset Schema  
**Associated Task:** TASK-003 — Dataset Schema  
**Related Documents:** `ARCHITECTURE.md` (§24), `DECISIONS.md` (DEC-010, DEC-013, DEC-015, DEC-017, DEC-022)  

---

## 1. Overview and Core Dataset Principles

The Track C analytical pipeline evaluates **speech delivery** through contrastive analysis: comparing participant speech against an effective, same-content baseline audio recording. To validate and calibrate this pipeline, the dataset schema must rigorously structure paired baseline and test speech, precise word alignments, and ground-truth temporal flaw annotations.

### 1.1 Core Principles
1. **Same-Content Contrastive Relationship:** Recordings are grouped by `passage_id`. Every participant recording is contrasted against an effective baseline recording associated with the identical passage text.
2. **Strict Speaker Separation:** No `speaker_id` may appear in both the `dev` (development/calibration) split and the `test` (held-out evaluation) split. This guarantees held-out speaker evaluation and prevents tuning thresholds to individual vocal quirks.
3. **Primary Evaluation on Human Flaws:** Human-performed, controlled delivery flaws are the primary ground truth (`flawed_human_controlled`). Synthetic flaw manipulations (`flawed_synthetic`) are supplementary and explicitly flagged in metadata.
4. **Clean Negative Controls:** Clean speech with effective delivery (`clean_control`) is included to evaluate system false positive rates.
5. **Exact Temporal Grounding:** Flaw annotations strictly bind start/end timestamps, flaw categories from the canonical vocabulary, and severity markers.
6. **Immutable Provenance and Traceability:** Every audio file and alignment artifact is tracked with SHA-256 hashes, sample rates, recording conditions, and dataset version tags.

---

## 2. Directory Structure and Manifest Layout

The dataset lives under the top-level `data/` directory:

```
data/
  raw/                              # Original audio files (.wav, 16-bit PCM, 44.1kHz or 16kHz)
  processed/
    alignments/                     # Word-level alignment JSON files (WhisperX / fallback)
    baseline_stats/                 # Precomputed BaselineStats JSON files per passage
  metadata/
    manifest.json                   # Master dataset manifest (array of all recordings)
    passages.json                   # Passage definitions (texts, target word counts)
    speakers.json                   # Speaker profiles (anonymized metadata, split assignment)
  annotations/
    <recording_id>.flaws.json       # Granular temporal flaw annotations for flawed recordings
```

> **NOTE ON SCHEMA FIXTURES:**
> The initial files under `data/metadata/` and `data/annotations/` are **schema validation fixtures only**.
> They contain placeholder file paths, dummy zeroed hashes (`"0000..."`), and fixture speaker IDs to validate
> JSON schema parsing, relational consistency, and integrity tooling. They do **not** represent collected audio data.
> Actual audio recording and alignment occur in subsequent project milestones (e.g., TASK-122).

---

## 3. Data Entities and Schemas

### 3.1 Passage Schema (`data/metadata/passages.json`)
Passages represent the fixed speech scripts.

```json
[
  {
    "passage_id": "p001",
    "title": "Opening Keynote Excerpt",
    "text": "Welcome everyone. Today we are launching a transformative capability in speech analytics...",
    "target_word_count": 82,
    "domain": "presentation",
    "created_at": "2026-10-07"
  }
]
```

### 3.2 Speaker Schema (`data/metadata/speakers.json`)
Tracks speaker characteristics for variability analysis without leaking speaker identity into the held-out test split.

```json
[
  {
    "speaker_id": "spk_01",
    "split": "dev",
    "gender": "female",
    "native_language": "en",
    "notes": "Dev participant"
  },
  {
    "speaker_id": "spk_test_01",
    "split": "test",
    "gender": "male",
    "native_language": "en",
    "notes": "Held-out test speaker - never seen in dev"
  }
]
```

### 3.3 Recording Manifest Schema (`data/metadata/manifest.json`)
The canonical registry of all recordings. Every entry describes a single audio file and its relationship to passages, baselines, and annotations.

```json
[
  {
    "recording_id": "rec_p001_spk01_base_01",
    "passage_id": "p001",
    "speaker_id": "spk_01",
    "category": "baseline_effective",
    "split": "dev",
    "audio_file": "data/raw/rec_p001_spk01_base_01.wav",
    "duration_s": 42.15,
    "sample_rate_hz": 44100,
    "channels": 1,
    "sha256_audio": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "alignment_file": "data/processed/alignments/rec_p001_spk01_base_01.alignment.json",
    "sha256_alignment": "4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a",
    "annotation_file": null,
    "recording_conditions": "quiet_room",
    "microphone": "headset_usb_logitech",
    "is_synthetic": false,
    "synthesis_technique": null,
    "dataset_version": "1.0.0",
    "created_at": "2026-10-07"
  }
]
```

#### Category Enumeration:
- `baseline_effective`: Human-delivered model/effective speech used to calculate baseline acoustic statistics.
- `flawed_human_controlled`: Human participant performing speech with deliberate, controlled delivery flaws.
- `flawed_synthetic`: Baseline or clean audio modified via signal processing algorithms (e.g., speed stretch or pitch drop).
- `clean_control`: Effective speech tested as participant audio to measure system false-positive rates (should trigger 0 flaws).

### 3.4 Temporal Flaw Annotation Schema (`data/annotations/<recording_id>.flaws.json`)
Attached to recordings of category `flawed_human_controlled` and `flawed_synthetic`.

```json
{
  "recording_id": "rec_p001_spk02_flawed_01",
  "passage_id": "p001",
  "dataset_version": "1.0.0",
  "flaws": [
    {
      "flaw_id": "ann_flaw_001",
      "flaw_type": "too_fast",
      "start_s": 12.40,
      "end_s": 15.80,
      "severity_label": "high",
      "target_words": ["transformative", "capability", "in", "speech"],
      "annotator_notes": "Deliberately accelerated delivery exceeding 210 WPM."
    }
  ]
}
```

#### Flaw Types (Vocabulary):
Strictly constrained to the canonical vocabulary in `ARCHITECTURE.md` (§13, §29) and `AGENTS.md` (§5):

**P0 Flaws (Core Demo):**
- `too_fast`: Accelerated speaking rate over a sustained window.
- `too_slow`: Abnormally decelerated speaking rate.
- `excessive_pause`: Inappropriate, prolonged hesitation or silence.
- `flat_pitch`: Lack of intonation / monotone prosody.
- `low_energy`: Subdued vocal loudness or projection.
- `high_energy`: Excessive vocal intensity or straining.

**P1 Flaws (Quality/Extension):**
- `pitch_instability`: Erratic frequency jitter or uncontrolled pitch jumps.
- `reduced_clarity`: Muffled articulation or loss of high-frequency energy (acoustic proxy).

---

## 4. Split Management and Held-Out Speaker Evaluation

To prevent data leakage and ensure reproducible evaluation:

1. **Rule of Mutually Exclusive Speakers (DEC-017):**
   $$\text{Speakers}(\text{dev}) \cap \text{Speakers}(\text{test}) = \emptyset$$
   No speaker in `dev` may ever appear in `test`.

2. **Split Definitions:**
   - **`dev` (Development & Calibration):**
     Used for pipeline development, Whisper / aligner verification, feature extraction checks, and threshold tuning (Z-thresholds, merge windows, score weights).
   - **`test` (Held-Out Final Evaluation):**
     Kept frozen. Evaluated exactly once after thresholds and scoring weights are locked in `core/config.py`. Never used for parameter tuning.

3. **Split Assignment Validation:**
   The validation script enforces that:
   - Every recording with `split: "dev"` belongs to a speaker with `split: "dev"`.
   - Every recording with `split: "test"` belongs to a speaker with `split: "test"`.

---

## 5. Provenance and Checksums

1. **SHA-256 Checksums:**
   Both `sha256_audio` and `sha256_alignment` are mandatory in the manifest. Changing an audio file or re-running alignment changes the hash and invalidates any cached analysis results.
2. **Dataset Versioning:**
   Every manifest entry, passage, and annotation records `dataset_version: "1.0.0"`. Increments in dataset versioning invalidate cached results via the cache key mechanism defined in DEC-019.
