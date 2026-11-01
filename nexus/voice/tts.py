"""Text-to-Speech (TTS) Engine for NEXUS Voice Output."""

from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger("nexus.voice.tts")

# SAPI flags
# SVSFlagsAsync = 1
# SVSFPurgeBeforeSpeak = 2


class TextToSpeechEngine:
    """Local text-to-speech engine using Windows SAPI with interrupt support.
    
    Guarantees:
    - Zero external cloud latency or bandwidth consumption.
    - Asynchronous speech playback without blocking UI or orchestrator.
    - Immediate playback interruption on user demand.
    """

    def __init__(self, rate: int = 1, volume: int = 100) -> None:
        self.rate = rate
        self.volume = volume
        self._voice = None
        self._is_speaking = False
        self._lock = threading.Lock()
        self._init_sapi()

    def _init_sapi(self) -> None:
        """Initialize Windows SAPI voice."""
        try:
            import win32com.client
            self._voice = win32com.client.Dispatch("SAPI.SpVoice")
            self._voice.Rate = self.rate
            self._voice.Volume = self.volume
            logger.info("Windows SAPI SpVoice initialized successfully.")
        except Exception as e:
            logger.warning("Windows SAPI initialization failed (%s). TTS will operate in fallback mode.", e)
            self._voice = None

    def is_available(self) -> bool:
        """Check if TTS engine is ready."""
        return self._voice is not None

    def speak(self, text: str, async_mode: bool = True) -> bool:
        """Speak text aloud."""
        if not text.strip():
            return False

        if not self._voice:
            logger.debug("TTS requested but SAPI voice is unavailable.")
            return False

        def _do_speak():
            with self._lock:
                self._is_speaking = True
            try:
                # 1 = SVSFlagsAsync, 2 = SVSFPurgeBeforeSpeak
                # Flags: 1 | 2 = 3
                self._voice.Speak(text, 0 if not async_mode else 3)
            except Exception as e:
                logger.error("TTS execution error: %s", e)
            finally:
                with self._lock:
                    self._is_speaking = False

        if async_mode:
            thread = threading.Thread(target=_do_speak, daemon=True, name="nexus-tts-worker")
            thread.start()
            return True
        else:
            _do_speak()
            return True

    def stop(self) -> None:
        """Interrupt and stop speech playback immediately."""
        if self._voice:
            try:
                # Speak empty string with SVSFPurgeBeforeSpeak (2) to stop current utterance
                self._voice.Speak("", 2)
            except Exception as e:
                logger.debug("Error stopping speech: %s", e)
        with self._lock:
            self._is_speaking = False

    @property
    def is_speaking(self) -> bool:
        """Return whether voice is currently outputting speech."""
        return self._is_speaking

