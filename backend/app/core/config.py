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

        # Model and Provider defaults (DEC-018, DEC-P001, DEC-P008)
        self.WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "base")
        self.WHISPER_LANGUAGE: str = os.getenv("WHISPER_LANGUAGE", "en")
        self.EXPLANATION_PROVIDER: str = os.getenv("EXPLANATION_PROVIDER", "template")
        self.GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

        # Storage and Cache directories (ARCHITECTURE.md §10, §24)
        self.CACHE_DIR: Path = Path(os.getenv("CACHE_DIR", "data/processed/cache"))
        self.DATA_DIR: Path = Path(os.getenv("DATA_DIR", "data"))

        # Audio limits (ARCHITECTURE.md §10, §23)
        self.MAX_UPLOAD_BYTES: int = int(os.getenv("MAX_UPLOAD_BYTES", "10485760"))  # 10 MB
        self.MAX_DURATION_S: float = float(os.getenv("MAX_DURATION_S", "300.0"))  # 5 minutes
        self.TARGET_SAMPLE_RATE: int = int(os.getenv("TARGET_SAMPLE_RATE", "16000"))
        self.TARGET_PEAK_DBFS: float = float(os.getenv("TARGET_PEAK_DBFS", "-3.0"))
        self.VAD_ENERGY_THRESHOLD_DBFS: float = float(os.getenv("VAD_ENERGY_THRESHOLD_DBFS", "-50.0"))


settings = Settings()
