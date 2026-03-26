"""
Voice Service — local wake word detection + on-demand Deepgram STT.

Pipeline:
  1. Mic streams locally to openwakeword (offline, zero cost)
  2. When "Hey Lumi" detected → open Deepgram WebSocket, capture command
  3. Command complete (speech_final / timeout) → close Deepgram → back to local
  4. Command transcript → POST to Lumi Server /api/sensing/event
  5. Lumi Go → chat.send → OpenClaw → AI responds → POST /voice/speak
  6. tts_service plays the response through the speaker

Cost: Deepgram only used for ~5-10s per interaction instead of 24/7.
"""

import logging
import threading
import time
from typing import Optional

import requests

logger = logging.getLogger("lelamp.voice")

LUMI_SENSING_URL = "http://127.0.0.1:5000/api/sensing/event"

# Audio config (shared between wake word and Deepgram)
SAMPLE_RATE = 16000
CHANNELS = 1
FRAME_SIZE = 1280  # 80ms at 16kHz — openwakeword expects this

# After wake word detected, capture command for up to this long
COMMAND_TIMEOUT_S = 10.0

# openwakeword threshold (0.0-1.0, higher = fewer false positives)
WAKEWORD_THRESHOLD = 0.5


class VoiceService:
    """Local wake word detection (openwakeword) + on-demand Deepgram STT."""

    def __init__(
        self,
        deepgram_api_key: str,
        input_device: Optional[int] = None,
    ):
        self._deepgram_api_key = deepgram_api_key
        self._input_device = input_device
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._listening = False  # True when capturing command via Deepgram

        # Lazy imports
        self._sd = None
        self._np = None
        self._oww = None
        self._dg_available = False

        try:
            import numpy as np
            self._np = np
        except ImportError:
            logger.warning("numpy not available for voice")

        try:
            import sounddevice as sd
            self._sd = sd
        except ImportError:
            logger.warning("sounddevice not available")

        try:
            import openwakeword
            self._oww = openwakeword
            logger.info("openwakeword loaded")
        except ImportError:
            logger.warning("openwakeword not available — wake word disabled")

        try:
            import deepgram  # noqa: F401
            self._dg_available = True
            logger.info("deepgram-sdk loaded")
        except ImportError:
            logger.warning("deepgram-sdk not available — STT disabled")

    @property
    def available(self) -> bool:
        return (
            self._sd is not None
            and self._np is not None
            and self._oww is not None
            and self._dg_available
            and self._deepgram_api_key != ""
        )

    @property
    def listening(self) -> bool:
        return self._listening

    def start(self):
        if self._running:
            return
        if not self.available:
            logger.warning("VoiceService not starting — missing deps or API key")
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="voice")
        self._thread.start()
        logger.info("VoiceService started (local wake word + on-demand Deepgram)")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("VoiceService stopped")

    def _loop(self):
        """Main loop: local wake word → Deepgram STT → back to wake word."""
        time.sleep(3)  # Wait for hardware init

        # Initialize openwakeword model
        from openwakeword.model import Model as OWWModel

        oww_model = OWWModel(
            wakeword_models=["hey_jarvis"],  # closest built-in to "hey lumi"
            inference_framework="onnx",
        )
        # List available models for logging
        logger.info("openwakeword models: %s", list(oww_model.models.keys()))

        sd = self._sd
        np = self._np

        while self._running:
            try:
                with sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="int16",
                    blocksize=FRAME_SIZE,
                    device=self._input_device,
                ) as mic:
                    logger.info("Listening for wake word (local, zero cost)...")

                    while self._running:
                        data, overflowed = mic.read(FRAME_SIZE)
                        if overflowed:
                            continue

                        # Feed audio to openwakeword
                        audio_i16 = data.flatten()
                        prediction = oww_model.predict(audio_i16)

                        # Check if any model triggered
                        for model_name, score in prediction.items():
                            if score >= WAKEWORD_THRESHOLD:
                                logger.info("Wake word detected! model=%s score=%.2f", model_name, score)
                                oww_model.reset()

                                # Capture command via Deepgram
                                self._listening = True
                                try:
                                    self._capture_command(mic)
                                finally:
                                    self._listening = False

            except Exception as e:
                logger.error("Voice loop error: %s", e)
                time.sleep(5)

    def _capture_command(self, mic_stream):
        """Open Deepgram connection, stream mic until command complete, then close."""
        from deepgram import DeepgramClient

        np = self._np

        client = DeepgramClient(self._deepgram_api_key)
        dg_connection = client.listen.live.v("1")

        # State
        command_parts = []
        command_done = threading.Event()
        start_time = time.time()

        def on_message(_self, result, **kwargs):
            transcript = result.channel.alternatives[0].transcript
            if not transcript or not transcript.strip():
                return

            is_final = result.is_final
            is_speech_final = result.speech_final

            if is_final and transcript.strip():
                command_parts.append(transcript.strip())
                logger.info("STT partial: '%s'", transcript.strip())

            if is_speech_final:
                command_done.set()

        def on_error(_self, error, **kwargs):
            logger.error("Deepgram error: %s", error)
            command_done.set()

        def on_close(_self, close, **kwargs):
            logger.info("Deepgram connection closed")
            command_done.set()

        # Register events — use string names for SDK compatibility
        dg_connection.on("Results", on_message)
        dg_connection.on("Error", on_error)
        dg_connection.on("Close", on_close)

        options = {
            "model": "nova-2",
            "language": "vi",
            "smart_format": True,
            "encoding": "linear16",
            "channels": CHANNELS,
            "sample_rate": SAMPLE_RATE,
            "interim_results": True,
            "endpointing": 300,
            "vad_events": True,
        }

        if not dg_connection.start(options):
            logger.error("Failed to start Deepgram connection")
            return

        logger.info("Deepgram connected — capturing command...")

        try:
            while self._running and not command_done.is_set():
                # Timeout check
                if (time.time() - start_time) > COMMAND_TIMEOUT_S:
                    logger.info("Command capture timeout")
                    break

                data, _ = mic_stream.read(1024)
                dg_connection.send(data.tobytes())

        except Exception as e:
            logger.error("Command capture error: %s", e)
        finally:
            try:
                dg_connection.finish()
            except Exception:
                pass

        full_command = " ".join(command_parts).strip()
        if full_command:
            logger.info("Command captured: '%s'", full_command)
            self._send_to_lumi(full_command)
        else:
            logger.info("Wake word detected but no command followed")

    def _send_to_lumi(self, transcript: str):
        """Send voice transcript to Lumi Server as a sensing event."""
        try:
            resp = requests.post(
                LUMI_SENSING_URL,
                json={"type": "voice", "message": transcript},
                timeout=5,
            )
            if resp.status_code != 200:
                logger.warning("Lumi returned %d: %s", resp.status_code, resp.text)
            else:
                logger.info("Sent to Lumi: '%s'", transcript[:80])
        except requests.RequestException as e:
            logger.warning("Failed to send voice event to Lumi: %s", e)
