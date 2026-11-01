"""Speech-to-Text (STT) Engine for NEXUS Voice Interaction."""

from __future__ import annotations

import io
import logging
import wave
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("nexus.voice.stt")

# Attempt importing speech_recognition
try:
    import speech_recognition as sr
except ImportError:
    sr = None


class SpeechToTextEngine:
    """Microphone and audio speech recognition engine for NEXUS.
    
    Guarantees:
    - Push-to-talk speech transcription.
    - Safe exception handling for missing microphones or recognition errors.
    - Zero background listening when recording is inactive.
    """

    def __init__(self, energy_threshold: int = 300) -> None:
        self.recognizer = sr.Recognizer() if sr else None
        if self.recognizer:
            self.recognizer.energy_threshold = energy_threshold
            self.recognizer.dynamic_energy_threshold = True

    def is_available(self) -> bool:
        """Check if speech recognition library is present."""
        return self.recognizer is not None

    def check_microphone(self) -> Tuple[bool, str]:
        """Verify microphone device availability."""
        if not sr:
            return False, "speech_recognition library not installed."
        try:
            mics = sr.Microphone.list_microphone_names()
            if not mics:
                return False, "No audio input devices detected."
            return True, f"Detected {len(mics)} microphone(s)."
        except Exception as e:
            return False, f"Microphone access error: {e}"

    def transcribe_audio_bytes(self, audio_data_bytes: bytes, sample_rate: int = 16000) -> Tuple[bool, str]:
        """Transcribe in-memory PCM or WAV audio bytes to text."""
        if not self.recognizer:
            return False, "Speech recognition engine unavailable."

        try:
            # Check if bytes have WAV header
            if audio_data_bytes.startswith(b"RIFF"):
                audio_file = io.BytesIO(audio_data_bytes)
                with sr.AudioFile(audio_file) as source:
                    audio = self.recognizer.record(source)
            else:
                # Raw PCM 16-bit mono
                audio = sr.AudioData(audio_data_bytes, sample_rate, 2)

            # Transcribe using local recognition engine or sphinx/google
            text = self.recognizer.recognize_google(audio)
            return True, text
        except sr.UnknownValueError:
            return False, "Speech was unclear; could not understand audio."
        except sr.RequestError as e:
            return False, f"Speech recognition service error: {e}"
        except Exception as e:
            return False, f"Audio processing error: {e}"

    def record_and_transcribe(self, duration_seconds: float = 4.0) -> Tuple[bool, str]:
        """Push-to-talk microphone recording and transcription."""
        if not self.recognizer or not sr:
            return False, "Speech recognition engine unavailable."

        try:
            with sr.Microphone() as source:
                logger.info("Listening for %s seconds...", duration_seconds)
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self.recognizer.record(source, duration=duration_seconds)

            text = self.recognizer.recognize_google(audio)
            return True, text
        except sr.UnknownValueError:
            return False, "Could not understand audio."
        except sr.RequestError as e:
            return False, f"Recognition service request failed: {e}"
        except Exception as e:
            return False, f"Microphone recording error: {e}"

