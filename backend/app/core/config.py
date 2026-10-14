"""Central analytical and server configuration.

Single source of truth for version strings, server defaults, and analytical constants.
Uses standard library os/dotenv without requiring extra dependencies.
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Load local .env if present
load_dotenv()


class Settings:
    """Application settings with environment variable fallbacks."""

    def __init__(self) -> None:
        # Server configuration
        self.APP_HOST: str = os.getenv("APP_HOST", "127.0.0.1")
        self.APP_PORT: int = int(os.getenv("APP_PORT", "8000"))
        self.ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
        self.LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

        # Versioning tags (api-contract.md)
        self.CONFIG_VERSION: str = os.getenv("CONFIG_VERSION", "1.0.0")
        self.PIPELINE_VERSION: str = os.getenv("PIPELINE_VERSION", "1.0.0")

        # Model and Provider defaults
        self.WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "base")
        self.WHISPER_LANGUAGE: str = os.getenv("WHISPER_LANGUAGE", "en")
        self.ALIGNMENT_DEVICE: str = os.getenv("ALIGNMENT_DEVICE", "cpu")
        self.ALIGNMENT_LANGUAGE: str = os.getenv("ALIGNMENT_LANGUAGE", "en")
        self.ALIGNMENT_MODEL_DIR: Optional[str] = os.getenv("ALIGNMENT_MODEL_DIR", None)
        self.MIN_COVERAGE_PCT: float = float(os.getenv("MIN_COVERAGE_PCT", "0.80"))
        self.EXPLANATION_PROVIDER: str = os.getenv("EXPLANATION_PROVIDER", "template")
        self.GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

        # Storage and Cache directories
        self.CACHE_DIR: Path = Path(os.getenv("CACHE_DIR", "data/processed/cache"))
        self.DATA_DIR: Path = Path(os.getenv("DATA_DIR", "data"))

        # Dashboard serving: browser origins allowed to call the API, and the built dashboard to serve at "/".
        self.CORS_ORIGINS: list[str] = [
            origin.strip()
            for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
            if origin.strip()
        ]
        self.FRONTEND_DIST_DIR: Path = Path(os.getenv("FRONTEND_DIST_DIR", "frontend/dist"))

        # Audio limits
        self.MAX_UPLOAD_BYTES: int = int(os.getenv("MAX_UPLOAD_BYTES", "10485760"))  # 10 MB
        self.MAX_DURATION_S: float = float(os.getenv("MAX_DURATION_S", "300.0"))  # 5 minutes
        self.TARGET_SAMPLE_RATE: int = int(os.getenv("TARGET_SAMPLE_RATE", "16000"))
        # Loudness scaling: every recording is scaled so the median loudness of its speaking frames is the target level.
        # Speaking frames are those within SPEECH_LEVEL_WINDOW_DB of the 95th-percentile frame loudness; the gain is capped so the
        # loudest sample never exceeds MAX_PEAK_DBFS. PROPOSED starting values (the target is the level the thresholds below were
        # explored at); changing them changes every energy value, so they are part of the analysis fingerprint.
        self.TARGET_SPEECH_LEVEL_DBFS: float = float(os.getenv("TARGET_SPEECH_LEVEL_DBFS", "-26.0"))
        self.SPEECH_LEVEL_WINDOW_DB: float = float(os.getenv("SPEECH_LEVEL_WINDOW_DB", "30.0"))
        self.MAX_PEAK_DBFS: float = float(os.getenv("MAX_PEAK_DBFS", "-1.0"))
        self.VAD_ENERGY_THRESHOLD_DBFS: float = float(os.getenv("VAD_ENERGY_THRESHOLD_DBFS", "-50.0"))

        # Flaw-detection thresholds. PROPOSED starting values:
        # NOT calibrated on a dev split and not empirically validated (no recordings exist yet).
        # They must be calibrated, then frozen with a CONFIG_VERSION bump.
        self.Z_RATE_FAST: float = float(os.getenv("Z_RATE_FAST", "2.0"))
        self.Z_RATE_SLOW: float = float(os.getenv("Z_RATE_SLOW", "2.0"))
        self.Z_ENERGY: float = float(os.getenv("Z_ENERGY", "2.0"))
        self.Z_PAUSE_WITHIN: float = float(os.getenv("Z_PAUSE_WITHIN", "2.0"))
        self.Z_PAUSE_CROSS: float = float(os.getenv("Z_PAUSE_CROSS", "2.5"))
        self.MIN_FLAW_DURATION_S: float = float(os.getenv("MIN_FLAW_DURATION_S", "0.5"))
        self.MERGE_GAP_S: float = float(os.getenv("MERGE_GAP_S", "0.5"))
        # A pause shorter than this is never reported as excessive, however regular the baseline's pauses are (raised from 0.8 to 1.2 in
        # : on real recordings every planned pause lasted 1.4 s or more, the mildest being planned at 1.5 s, while ordinary breaths of
        # 0.8 to 1.25 s were flagged with maximum severity). PROPOSED, uncalibrated.
        self.MIN_PAUSE_FLAW_S: float = float(os.getenv("MIN_PAUSE_FLAW_S", "1.2"))
        # Narrowing of rate findings to the words that deviate; the fewest words a narrowed stretch may have.
        self.REFINE_RATE_BOUNDARIES: bool = os.getenv("REFINE_RATE_BOUNDARIES", "true").strip().lower() in ("1", "true", "yes", "on")
        self.REFINE_MIN_WORDS: int = int(os.getenv("REFINE_MIN_WORDS", "8"))

        # Word-by-word comparison with the baseline. PROPOSED, uncalibrated: calibrate with `evaluate_takes.py --sweep` on dev takes.
        # A finding is a run of at least RUN_MIN_WORDS words whose deviation from the baseline's reading of the same words is more than Z_RUN_*
        # spreads AND at least MIN_RATE_CHANGE_PCT (pace) / MIN_ENERGY_CHANGE_DB (level) in size. A reading whose overall pace differs from the
        # baseline by more than GLOBAL_TEMPO_CHANGE_PCT is also reported as a whole. The profile is used only if PROFILE_MIN_COVERAGE of the
        # participant's timed words match the passage and PROFILE_MIN_USABLE_WORDS words can be compared. The SIGMA_FLOOR_* values keep a very
        # even baseline from making every deviation look huge (rate: natural-log ratio of durations; level: dB).
        self.PROFILE_ENABLED: bool = os.getenv("PROFILE_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
        # At most this much of the silence after a word counts towards the word's slot (pace is how fast the words are spoken; a pause is
        # judged by pause detection and must not also make the words around it look slow). Fixed when a baseline is built and stored in its profile.
        self.PROFILE_GAP_CAP_S: float = float(os.getenv("PROFILE_GAP_CAP_S", "0.25"))
        self.Z_RUN_RATE: float = float(os.getenv("Z_RUN_RATE", "4.0"))
        self.Z_RUN_ENERGY: float = float(os.getenv("Z_RUN_ENERGY", "4.0"))
        self.RUN_MIN_WORDS: int = int(os.getenv("RUN_MIN_WORDS", "10"))
        self.MIN_RATE_CHANGE_PCT: float = float(os.getenv("MIN_RATE_CHANGE_PCT", "15.0"))
        self.MIN_ENERGY_CHANGE_DB: float = float(os.getenv("MIN_ENERGY_CHANGE_DB", "3.0"))
        self.GLOBAL_TEMPO_CHANGE_PCT: float = float(os.getenv("GLOBAL_TEMPO_CHANGE_PCT", "30.0"))
        self.PROFILE_MIN_COVERAGE: float = float(os.getenv("PROFILE_MIN_COVERAGE", "0.6"))
        self.PROFILE_MIN_USABLE_WORDS: int = int(os.getenv("PROFILE_MIN_USABLE_WORDS", "16"))
        self.SIGMA_FLOOR_RATE_DRIFT: float = float(os.getenv("SIGMA_FLOOR_RATE_DRIFT", "0.02"))
        self.SIGMA_FLOOR_RATE_WORD: float = float(os.getenv("SIGMA_FLOOR_RATE_WORD", "0.08"))
        self.SIGMA_FLOOR_LEVEL_DRIFT_DB: float = float(os.getenv("SIGMA_FLOOR_LEVEL_DRIFT_DB", "0.3"))
        self.SIGMA_FLOOR_LEVEL_WORD_DB: float = float(os.getenv("SIGMA_FLOOR_LEVEL_WORD_DB", "1.0"))
        self.SIGMA_FLOOR_TEMPO: float = float(os.getenv("SIGMA_FLOOR_TEMPO", "0.04"))
        # Flat pitch, judged the same way: how far the pitch of the words moves around the reading's own median pitch (root mean square, in
        # semitones, per word, deviations clipped at PITCH_DEVIATION_CLIP_ST so a tracking error cannot dominate; a word needs PITCH_MIN_VOICED_FRAMES
        # voiced frames) against what the baseline readings did with the same words. A run is flat if its movement is more than Z_RUN_PITCH spreads
        # AND at least MIN_FLAT_PITCH_CHANGE_PCT below the baseline's; a whole reading that moves GLOBAL_PITCH_CHANGE_PCT less is also reported as a
        # whole. The spread is in natural-log ratio of the root-mean-square movement. PROPOSED, uncalibrated; no real flat-pitch recordings exist yet.
        self.PITCH_MIN_VOICED_FRAMES: int = int(os.getenv("PITCH_MIN_VOICED_FRAMES", "5"))
        self.PITCH_DEVIATION_CLIP_ST: float = float(os.getenv("PITCH_DEVIATION_CLIP_ST", "6.0"))
        self.Z_RUN_PITCH: float = float(os.getenv("Z_RUN_PITCH", "4.5"))
        self.MIN_FLAT_PITCH_CHANGE_PCT: float = float(os.getenv("MIN_FLAT_PITCH_CHANGE_PCT", "35.0"))
        self.GLOBAL_PITCH_CHANGE_PCT: float = float(os.getenv("GLOBAL_PITCH_CHANGE_PCT", "45.0"))
        self.SIGMA_FLOOR_PITCH_DRIFT: float = float(os.getenv("SIGMA_FLOOR_PITCH_DRIFT", "0.05"))
        self.SIGMA_FLOOR_PITCH_WORD: float = float(os.getenv("SIGMA_FLOOR_PITCH_WORD", "0.30"))
        self.SIGMA_FLOOR_PITCH_SCALE: float = float(os.getenv("SIGMA_FLOOR_PITCH_SCALE", "0.08"))

        # Severity. PROPOSED, uncalibrated.
        self.SEVERITY_Z_MIN: float = float(os.getenv("SEVERITY_Z_MIN", "1.0"))
        self.SEVERITY_Z_SEVERE: float = float(os.getenv("SEVERITY_Z_SEVERE", "4.0"))
        self.SEVERITY_DURATION_SEVERE_S: float = float(os.getenv("SEVERITY_DURATION_SEVERE_S", "5.0"))
        # Size of the change that counts as maximum severity for findings that carry a measured size: the pace changed by this factor
        # (2.0: twice as fast or half as fast), the level by this many dB, a pause exceeds the baseline's by this many seconds.
        self.SEVERITY_RATE_SEVERE_RATIO: float = float(os.getenv("SEVERITY_RATE_SEVERE_RATIO", "2.0"))
        self.SEVERITY_ENERGY_SEVERE_DB: float = float(os.getenv("SEVERITY_ENERGY_SEVERE_DB", "15.0"))
        self.SEVERITY_PAUSE_EXCESS_SEVERE_S: float = float(os.getenv("SEVERITY_PAUSE_EXCESS_SEVERE_S", "3.5"))
        # Flat pitch: the pitch moves this many times less than the baseline's (3.0: a third as much is the most serious).
        self.SEVERITY_PITCH_FLAT_SEVERE_RATIO: float = float(os.getenv("SEVERITY_PITCH_FLAT_SEVERE_RATIO", "3.0"))

        # Pipeline honesty flags and baseline/content checks. PROPOSED, uncalibrated.
        self.THRESHOLDS_CALIBRATED: bool = os.getenv("THRESHOLDS_CALIBRATED", "false").strip().lower() in ("1", "true", "yes")
        self.PASSAGE_MATCH_MIN_RATIO: float = float(os.getenv("PASSAGE_MATCH_MIN_RATIO", "0.6"))
        self.BASELINE_THIN_RATE_WINDOWS: int = int(os.getenv("BASELINE_THIN_RATE_WINDOWS", "5"))
        self.BASELINE_THIN_PAUSES: int = int(os.getenv("BASELINE_THIN_PAUSES", "3"))

        # Custom passages: a user's own passage text and 2 to 6 of their own baseline recordings become a baseline under data/custom/.
        # The passage needs enough words and at least two sentences (the baseline needs a pause between sentences to be measured); every
        # baseline recording must be aligned to the passage (at least CUSTOM_MIN_TIMED_WORD_SHARE of its words timed) and, when the speech
        # recogniser is available, must match the passage text (below CUSTOM_MIN_CONTENT_MATCH it is refused, below CUSTOM_WARN_CONTENT_MATCH
        # a warning is given). Baseline recordings whose speaking pace differs by more than CUSTOM_TAKE_RATE_SPREAD_WARN get a warning.
        self.CUSTOM_MIN_PASSAGE_WORDS: int = int(os.getenv("CUSTOM_MIN_PASSAGE_WORDS", "30"))
        self.CUSTOM_MAX_PASSAGE_WORDS: int = int(os.getenv("CUSTOM_MAX_PASSAGE_WORDS", "400"))
        self.CUSTOM_MIN_BASELINE_TAKES: int = int(os.getenv("CUSTOM_MIN_BASELINE_TAKES", "2"))
        self.CUSTOM_MAX_BASELINE_TAKES: int = int(os.getenv("CUSTOM_MAX_BASELINE_TAKES", "6"))
        self.CUSTOM_MAX_BASELINES: int = int(os.getenv("CUSTOM_MAX_BASELINES", "50"))
        self.CUSTOM_MIN_TIMED_WORD_SHARE: float = float(os.getenv("CUSTOM_MIN_TIMED_WORD_SHARE", "0.85"))
        self.CUSTOM_CHECK_CONTENT: bool = os.getenv("CUSTOM_CHECK_CONTENT", "true").strip().lower() in ("1", "true", "yes", "on")
        self.CUSTOM_MIN_CONTENT_MATCH: float = float(os.getenv("CUSTOM_MIN_CONTENT_MATCH", "0.5"))
        self.CUSTOM_WARN_CONTENT_MATCH: float = float(os.getenv("CUSTOM_WARN_CONTENT_MATCH", "0.75"))
        self.CUSTOM_TAKE_RATE_SPREAD_WARN: float = float(os.getenv("CUSTOM_TAKE_RATE_SPREAD_WARN", "0.35"))

        # Scoring (weights). PROPOSED, uncalibrated.
        self.BASE_PENALTY: float = float(os.getenv("BASE_PENALTY", "30.0"))
        self.SCORE_WEIGHT_SPEECH_RATE: float = float(os.getenv("SCORE_WEIGHT_SPEECH_RATE", "0.30"))
        self.SCORE_WEIGHT_PITCH: float = float(os.getenv("SCORE_WEIGHT_PITCH", "0.25"))
        self.SCORE_WEIGHT_PAUSES: float = float(os.getenv("SCORE_WEIGHT_PAUSES", "0.25"))
        self.SCORE_WEIGHT_ENERGY: float = float(os.getenv("SCORE_WEIGHT_ENERGY", "0.20"))
        self.SCORE_WEIGHT_MFCC: float = float(os.getenv("SCORE_WEIGHT_MFCC", "0.0"))
        self.SCORE_WEIGHT_CLARITY: float = float(os.getenv("SCORE_WEIGHT_CLARITY", "0.0"))


settings = Settings()
