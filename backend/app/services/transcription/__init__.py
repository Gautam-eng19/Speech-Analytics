"""Transcription service package.

Public surface:
    WhisperTranscriber  — service class
    transcribe          — convenience function using the shared singleton
    get_transcriber     — retrieve/initialise the module-level singleton
"""
from .transcriber import WhisperTranscriber, get_transcriber, transcribe  # noqa: F401
