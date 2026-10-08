# ASR and Forced Alignment Feasibility Spike Report

**Date:** 2026-10-07  
**Task:** Track C — Feasibility Spike for Transcription and Alignment Stack  
**Status:** VALIDATED (Whisper base + WhisperX operational on CPU)

---

## 1. Environment Tested
- **OS:** Windows 11 (Build 26200, SP0, 64-bit AMD64)
- **Python:** 3.13.7
- **PyTorch:** 2.14.1 (CPU mode, `torch.cuda.is_available() == False`)
- **Virtual Environment:** `backend/.venv`

---

## 2. Whisper Installation and Import Result
- **Package:** `openai-whisper` (version `20250625`)
- **Status:** Installed cleanly on Python 3.13 with PyTorch 2.14.1 backend.
- **Import:** `import whisper` succeeded with no errors.

---

## 3. Whisper Model-Loading Result
- **Model:** `whisper.load_model("base")`
- **Download / Load Time:** 25.75s initial download (~139 MB cached at `~/.cache/whisper/base.pt`); subsequent loads are instant (<0.5s).
- **Device:** CPU (FP32 precision fallback handled automatically).
- **Memory Footprint:** ~150 MB RAM.

---

## 4. Whisper Transcription Result
- **Execution:** `whisper.transcribe(audio_array, word_timestamps=True)` executed successfully when passed float32 PCM numpy array.
- **Word Timestamps:** Native word timestamp generation (`res['segments']`) supported.
- **Key Discovery (ffmpeg dependency):** Passing audio file paths directly via `whisper.transcribe(filepath)` or calling `whisper.load_audio(filepath)` invokes `ffmpeg` via subprocess. Because `ffmpeg` is not on the Windows PATH, it raises `FileNotFoundError: [WinError 2]`. However, when float32 PCM numpy array is passed directly (preprocessed via Python libraries), transcription succeeds without `ffmpeg`.

---

## 5. WhisperX Installation and Import Result
- **Package:** `whisperx` (version `3.8.6`)
- **Status:** Installed successfully along with sub-dependencies (`pandas`, `torchaudio`, `transformers`, `nltk`).
- **Import:** `import whisperx` succeeded with no errors.
- **Dependency Note:** `whisperx` requests older pinned versions (`torch~=2.8.0`, `torchaudio~=2.8.0`), but imports and functions normally under modern PyTorch 2.14.1 on Python 3.13.

---

## 6. WhisperX Alignment Result
- **Align Model Loading:** `whisperx.load_align_model(language_code="en", device="cpu")` successfully loaded wav2vec2 aligner (`WAV2VEC2_ASR_BASE_960H`).
- **Alignment Execution:** `whisperx.align(transcript, align_model, metadata, audio, device="cpu")` completed in **2.56 seconds**.
- **Output Quality:** Returned precise word-level timing (`word`, `start`, `end`, `score`).

---

## 7. ffmpeg Availability Result
- **Status:** `ffmpeg` is **NOT installed** on the system PATH (`where.exe ffmpeg` returned exit code 1).
- **Impact:**
  - Standard WAV loading in `services/audio/` MUST use Python-native loaders (`soundfile`, `scipy.io.wavfile`, `librosa`) rather than `whisper.load_audio()`.
  - Non-WAV formats (MP3/OGG) will require `ffmpeg` or Python audio decoders.

---

## 8. Runtime and Resource Observations
- **CPU Performance:** CPU processing is fast enough for short demo clips (<30s audio aligns in ~2.5s).
- **Combined Memory:** ~400 MB RAM total for Whisper base + wav2vec2 aligner.
- **Concurrency:** Single-threaded execution per request is recommended on CPU.

---

## 9. Problems Encountered
1. `ffmpeg` absent from Windows host PATH, causing `FileNotFoundError` on `whisper.load_audio(path)`.
2. PyPI download timeout/connection reset when downloading full `whisperx` wheel tree due to large size (>250 MB). Resolved by explicit retry / installing core dependencies.

---

## 10. Recommended Implementation Path
- **Primary Stack:** Whisper base + WhisperX forced alignment.
  - `services/audio/`: Preprocess audio to float32 PCM numpy array (using `soundfile` / `scipy`).
  - `services/transcription/`: Pass float32 numpy array to `whisper.transcribe(audio_array)`.
  - `services/alignment/`: Pass transcript + audio array to `whisperx.align()`.
- **Fallback Path:** Whisper `word_timestamps=True`.
  - Enforce uniform `AlignedTranscript` interface per DEC-009 so system degrades gracefully if WhisperX fails.

---

## 11. What Remains Unvalidated
- Transcription & alignment accuracy on real human speech dataset (no audio recordings present in `data/raw` yet).
- Transcription speed on long audio (>60s).
- Robustness on noisy speech or strong accents.
