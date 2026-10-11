"""Central analytical and server configuration (ARCHITECTURE.md §7.9, §10, §23).

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

        # Versioning tags (ARCHITECTURE.md §26.2, api-contract.md)
        self.CONFIG_VERSION: str = os.getenv("CONFIG_VERSION", "1.0.0")
        self.PIPELINE_VERSION: str = os.getenv("PIPELINE_VERSION", "1.0.0")

        # Model and Provider defaults (DEC-009, DEC-018, DEC-P001, DEC-P002, DEC-P008)
        self.WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "base")
        self.WHISPER_LANGUAGE: str = os.getenv("WHISPER_LANGUAGE", "en")
        self.ALIGNMENT_DEVICE: str = os.getenv("ALIGNMENT_DEVICE", "cpu")
        self.ALIGNMENT_LANGUAGE: str = os.getenv("ALIGNMENT_LANGUAGE", "en")
        self.ALIGNMENT_MODEL_DIR: Optional[str] = os.getenv("ALIGNMENT_MODEL_DIR", None)
        self.MIN_COVERAGE_PCT: float = float(os.getenv("MIN_COVERAGE_PCT", "0.80"))
        self.EXPLANATION_PROVIDER: str = os.getenv("EXPLANATION_PROVIDER", "template")
        self.GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

        # Storage and Cache directories (ARCHITECTURE.md §10, §24)
        self.CACHE_DIR: Path = Path(os.getenv("CACHE_DIR", "data/processed/cache"))
        self.DATA_DIR: Path = Path(os.getenv("DATA_DIR", "data"))

        # Dashboard serving (DEC-033): browser origins allowed to call the API, and the built dashboard to serve at "/".
        self.CORS_ORIGINS: list[str] = [
            origin.strip()
            for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
            if origin.strip()
        ]
        self.FRONTEND_DIST_DIR: Path = Path(os.getenv("FRONTEND_DIST_DIR", "frontend/dist"))

        # Audio limits (ARCHITECTURE.md §10, §23)
        self.MAX_UPLOAD_BYTES: int = int(os.getenv("MAX_UPLOAD_BYTES", "10485760"))  # 10 MB
        self.MAX_DURATION_S: float = float(os.getenv("MAX_DURATION_S", "300.0"))  # 5 minutes
        self.TARGET_SAMPLE_RATE: int = int(os.getenv("TARGET_SAMPLE_RATE", "16000"))
        # Loudness scaling (DEC-036): every recording is scaled so the median loudness of its speaking frames is the target level.
        # Speaking frames are those within SPEECH_LEVEL_WINDOW_DB of the 95th-percentile frame loudness; the gain is capped so the
        # loudest sample never exceeds MAX_PEAK_DBFS. PROPOSED starting values (the target is the level the thresholds below were
        # explored at); changing them changes every energy value, so they are part of the analysis fingerprint.
        self.TARGET_SPEECH_LEVEL_DBFS: float = float(os.getenv("TARGET_SPEECH_LEVEL_DBFS", "-26.0"))
        self.SPEECH_LEVEL_WINDOW_DB: float = float(os.getenv("SPEECH_LEVEL_WINDOW_DB", "30.0"))
        self.MAX_PEAK_DBFS: float = float(os.getenv("MAX_PEAK_DBFS", "-1.0"))
        self.VAD_ENERGY_THRESHOLD_DBFS: float = float(os.getenv("VAD_ENERGY_THRESHOLD_DBFS", "-50.0"))

        # Flaw-detection thresholds (DEC-P005, ARCHITECTURE.md §17). PROPOSED starting values:
        # NOT calibrated on a dev split and not empirically validated (no recordings exist yet).
        # They must be calibrated, then frozen with a CONFIG_VERSION bump (DEC-014).
        self.Z_RATE_FAST: float = float(os.getenv("Z_RATE_FAST", "2.0"))
        self.Z_RATE_SLOW: float = float(os.getenv("Z_RATE_SLOW", "2.0"))
        self.Z_ENERGY: float = float(os.getenv("Z_ENERGY", "2.0"))
        self.Z_PAUSE_WITHIN: float = float(os.getenv("Z_PAUSE_WITHIN", "2.0"))
        self.Z_PAUSE_CROSS: float = float(os.getenv("Z_PAUSE_CROSS", "2.5"))
        self.MIN_FLAW_DURATION_S: float = float(os.getenv("MIN_FLAW_DURATION_S", "0.5"))
        self.MERGE_GAP_S: float = float(os.getenv("MERGE_GAP_S", "0.5"))

        # Severity (DEC-P006 Option A as amended by DEC-028). PROPOSED, uncalibrated.
        self.SEVERITY_Z_MIN: float = float(os.getenv("SEVERITY_Z_MIN", "1.0"))
        self.SEVERITY_Z_SEVERE: float = float(os.getenv("SEVERITY_Z_SEVERE", "4.0"))
        self.SEVERITY_DURATION_SEVERE_S: float = float(os.getenv("SEVERITY_DURATION_SEVERE_S", "5.0"))

        # Pipeline honesty flags and baseline/content checks (DEC-032). PROPOSED, uncalibrated.
        self.THRESHOLDS_CALIBRATED: bool = os.getenv("THRESHOLDS_CALIBRATED", "false").strip().lower() in ("1", "true", "yes")
        self.PASSAGE_MATCH_MIN_RATIO: float = float(os.getenv("PASSAGE_MATCH_MIN_RATIO", "0.6"))
        self.BASELINE_THIN_RATE_WINDOWS: int = int(os.getenv("BASELINE_THIN_RATE_WINDOWS", "5"))
        self.BASELINE_THIN_PAUSES: int = int(os.getenv("BASELINE_THIN_PAUSES", "3"))

        # Scoring (DEC-014 as amended by DEC-030; weights DEC-P007). PROPOSED, uncalibrated.
        self.BASE_PENALTY: float = float(os.getenv("BASE_PENALTY", "30.0"))
        self.SCORE_WEIGHT_SPEECH_RATE: float = float(os.getenv("SCORE_WEIGHT_SPEECH_RATE", "0.30"))
        self.SCORE_WEIGHT_PITCH: float = float(os.getenv("SCORE_WEIGHT_PITCH", "0.25"))
        self.SCORE_WEIGHT_PAUSES: float = float(os.getenv("SCORE_WEIGHT_PAUSES", "0.25"))
        self.SCORE_WEIGHT_ENERGY: float = float(os.getenv("SCORE_WEIGHT_ENERGY", "0.20"))
        self.SCORE_WEIGHT_MFCC: float = float(os.getenv("SCORE_WEIGHT_MFCC", "0.0"))
        self.SCORE_WEIGHT_CLARITY: float = float(os.getenv("SCORE_WEIGHT_CLARITY", "0.0"))


settings = Settings()
