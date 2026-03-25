"""
Voice Service — always-on Deepgram streaming STT with "Hey Lumi" wake word detection.

Pipeline:
  1. Mic streams continuously to Deepgram via WebSocket (always-on)
  2. Deepgram returns real-time transcripts with keyword boost for "Lumi"
  3. When transcript contains "Hey Lumi" (or similar) → capture the command after it
  4. Command transcript → POST to Lumi Server /api/sensing/event {type:"voice", message: transcript}
  5. Lumi Go → chat.send → OpenClaw → AI responds → Go captures response → POST /voice/speak
  6. tts_service plays the response through the speaker

No openwakeword needed — Deepgram handles everything via streaming STT.
"""

import logging
import re
import struct
import threading
import time
from typing import Optional

import requests

logger = logging.getLogger("lelamp.voice")

LUMI_SENSING_URL = "http://127.0.0.1:5000/api/sensing/event"

# Deepgram streaming config
DEEPGRAM_SAMPLE_RATE = 16000
DEEPGRAM_CHANNELS = 1
DEEPGRAM_ENCODING = "linear16"
DEEPGRAM_FRAME_SIZE = 1024  # samples per frame

# Wake word pattern — matches "hey lumi", "hei lumi", "hey lummy", etc.
WAKE_WORD_PATTERN = re.compile(r"\bhey?\s+lumi\b", re.IGNORECASE)

# After wake word detected, wait for speech_final to get the full command
COMMAND_TIMEOUT_S = 10.0


class VoiceService:
    """Always-on Deepgram streaming voice pipeline with wake word detection."""

    def __init__(
        self,
        deepgram_api_key: str,
        input_device: Optional[int] = None,
    ):
        self._deepgram_api_key = deepgram_api_key
        self._input_device = input_device
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._listening = False  # True when wake word detected, capturing command

        # Lazy imports
        self._sd = None
        self._np = None
        self._deepgram = None

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
            from deepgram import DeepgramClient
            self._deepgram = DeepgramClient
            logger.info("Deepgram SDK loaded")
        except ImportError:
            logger.warning("deepgram-sdk not available — STT disabled")

    @property
    def available(self) -> bool:
        return (
            self._sd is not None
            and self._np is not None
            and self._deepgram is not None
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
        logger.info("VoiceService started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("VoiceService stopped")

    def _loop(self):
        """Main loop: connect to Deepgram, stream mic, detect wake word."""
        time.sleep(3)  # Wait for hardware init

        while self._running:
            try:
                self._run_stream()
            except Exception as e:
                logger.error("Voice stream error: %s", e)
                time.sleep(5)  # Reconnect after error

    def _run_stream(self):
        """Single streaming session — reconnects on error."""
        from deepgram import DeepgramClient, LiveTranscriptEvents, LiveOptions

        client = DeepgramClient(self._deepgram_api_key)
        dg_connection = client.listen.live.v("1")

        # State for wake word detection
        wake_detected = False
        command_parts = []
        wake_time = 0.0
        lock = threading.Lock()

        def on_message(_self, result, **kwargs):
            nonlocal wake_detected, command_parts, wake_time

            transcript = result.channel.alternatives[0].transcript
            if not transcript or not transcript.strip():
                return

            is_final = result.is_final
            is_speech_final = result.speech_final

            with lock:
                if not wake_detected:
                    # Look for wake word in transcript
                    match = WAKE_WORD_PATTERN.search(transcript)
                    if match and is_final:
                        wake_detected = True
                        wake_time = time.time()
                        self._listening = True
                        # Extract command part after wake word
                        command_after = transcript[match.end():].strip()
                        if command_after:
                            command_parts.append(command_after)
                        logger.info("Wake word detected: '%s'", transcript)
                else:
                    # Capturing command after wake word
                    if is_final and transcript.strip():
                        command_parts.append(transcript.strip())

                    # Command complete when speech_final or timeout
                    if is_speech_final or (time.time() - wake_time) > COMMAND_TIMEOUT_S:
                        full_command = " ".join(command_parts).strip()
                        if full_command:
                            logger.info("Command: '%s'", full_command)
                            self._send_to_lumi(full_command)
                        else:
                            logger.info("Wake word detected but no command followed")

                        # Reset state
                        wake_detected = False
                        command_parts = []
                        wake_time = 0.0
                        self._listening = False

        def on_error(_self, error, **kwargs):
            logger.error("Deepgram error: %s", error)

        def on_close(_self, close, **kwargs):
            logger.info("Deepgram connection closed")

        dg_connection.on(LiveTranscriptEvents.Transcript, on_message)
        dg_connection.on(LiveTranscriptEvents.Error, on_error)
        dg_connection.on(LiveTranscriptEvents.Close, on_close)

        options = LiveOptions(
            model="nova-2",
            language="vi",
            smart_format=True,
            encoding=DEEPGRAM_ENCODING,
            channels=DEEPGRAM_CHANNELS,
            sample_rate=DEEPGRAM_SAMPLE_RATE,
            interim_results=True,
            endpointing=300,
            vad_events=True,
            keywords=["lumi:3"],
        )

        if not dg_connection.start(options):
            logger.error("Failed to start Deepgram connection")
            return

        logger.info("Deepgram streaming connected (always-on, keyword boost: lumi)")

        # Stream mic audio to Deepgram
        sd = self._sd
        np = self._np

        try:
            with sd.InputStream(
                samplerate=DEEPGRAM_SAMPLE_RATE,
                channels=DEEPGRAM_CHANNELS,
                dtype="int16",
                blocksize=DEEPGRAM_FRAME_SIZE,
                device=self._input_device,
            ) as stream:
                while self._running:
                    data, overflowed = stream.read(DEEPGRAM_FRAME_SIZE)
                    if overflowed:
                        logger.debug("Audio buffer overflowed")
                    audio_bytes = data.tobytes()
                    dg_connection.send(audio_bytes)

                    # Timeout check for stuck wake word state
                    with lock:
                        if wake_detected and (time.time() - wake_time) > COMMAND_TIMEOUT_S:
                            full_command = " ".join(command_parts).strip()
                            if full_command:
                                self._send_to_lumi(full_command)
                            wake_detected = False
                            command_parts = []
                            self._listening = False

        except Exception as e:
            logger.error("Mic stream error: %s", e)
        finally:
            dg_connection.finish()

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
        except requests.RequestException as e:
            logger.warning("Failed to send voice event to Lumi: %s", e)
