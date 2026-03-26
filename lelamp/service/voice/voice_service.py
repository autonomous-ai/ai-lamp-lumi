"""
Voice Service — local VAD + on-demand Deepgram STT for autonomous sensing.

Pipeline:
  1. Mic always on, local RMS energy check (free, zero cost)
  2. Speech detected → connect Deepgram, stream audio
  3. Silence for SILENCE_TIMEOUT → disconnect Deepgram (stop billing)
  4. Transcripts → POST to Lumi Server /api/sensing/event
  5. Lumi Go → local intent match or OpenClaw → AI responds → POST /voice/speak

Cost: Deepgram only billed when someone is actually speaking.
"""

import logging
import threading
import time
from typing import Optional

import requests

logger = logging.getLogger("lelamp.voice")

LUMI_SENSING_URL = "http://127.0.0.1:5000/api/sensing/event"

SAMPLE_RATE = 16000
CHANNELS = 1
FRAME_SIZE = 1024  # 64ms at 16kHz

# Local VAD config
RMS_THRESHOLD = 500       # Audio energy above this = speech (tune on device)
SILENCE_TIMEOUT_S = 3.0   # Disconnect Deepgram after this much silence
SPEECH_HOLDOFF_S = 0.2    # Minimum speech duration before connecting Deepgram

# Keyword boost for wake word detection via transcript
KEYWORDS = ["lumi:3", "lu mi:2"]


class VoiceService:
    """Local VAD + on-demand Deepgram STT for autonomous sensing."""

    def __init__(
        self,
        deepgram_api_key: str,
        input_device: Optional[int] = None,
    ):
        self._deepgram_api_key = deepgram_api_key
        self._input_device = input_device
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._listening = False

        # Lazy imports
        self._sd = None
        self._np = None
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
            logger.warning(
                "VoiceService not starting — sd=%s np=%s dg=%s key=%s",
                self._sd is not None,
                self._np is not None,
                self._dg_available,
                bool(self._deepgram_api_key),
            )
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="voice")
        self._thread.start()
        logger.info("VoiceService started (local VAD + on-demand Deepgram)")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("VoiceService stopped")

    def _rms(self, audio_data) -> float:
        """Calculate RMS energy of audio frame."""
        np = self._np
        samples = audio_data.flatten().astype(np.float32)
        return float(np.sqrt(np.mean(samples ** 2)))

    def _loop(self):
        """Main loop: local VAD → Deepgram on speech → disconnect on silence."""
        time.sleep(3)  # Wait for hardware init
        sd = self._sd

        while self._running:
            try:
                with sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="int16",
                    blocksize=FRAME_SIZE,
                    device=self._input_device,
                ) as mic:
                    logger.info("Listening locally for speech (RMS threshold=%d)...", RMS_THRESHOLD)
                    self._vad_loop(mic)
            except Exception as e:
                logger.error("Voice loop error: %s", e)
                if self._running:
                    time.sleep(3)

    def _vad_loop(self, mic):
        """Monitor mic with local VAD, connect Deepgram when speech detected."""
        speech_start = None

        while self._running:
            data, overflowed = mic.read(FRAME_SIZE)
            if overflowed:
                continue

            rms = self._rms(data)

            if rms >= RMS_THRESHOLD:
                if speech_start is None:
                    speech_start = time.time()
                # Wait for holdoff before connecting Deepgram (avoid short noises)
                elif (time.time() - speech_start) >= SPEECH_HOLDOFF_S:
                    logger.info("Speech detected (RMS=%.0f), connecting Deepgram...", rms)
                    self._stream_session(mic)
                    speech_start = None
            else:
                speech_start = None

    def _stream_session(self, mic):
        """Stream to Deepgram until silence, then disconnect."""
        from deepgram import DeepgramClient

        client = DeepgramClient(api_key=self._deepgram_api_key)
        dg_connection = client.listen.live.v("1")

        session_closed = threading.Event()

        def on_message(_self, result, **kwargs):
            transcript = result.channel.alternatives[0].transcript
            if not transcript or not transcript.strip():
                return
            if not result.is_final:
                return
            text = transcript.strip()
            logger.info("STT: '%s'", text)
            self._send_to_lumi(text)

        def on_error(_self, error, **kwargs):
            logger.error("Deepgram error: %s", error)
            session_closed.set()

        def on_close(_self, close, **kwargs):
            logger.info("Deepgram connection closed")
            session_closed.set()

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
            "interim_results": False,
            "endpointing": 500,
            "vad_events": True,
            "keywords": KEYWORDS,
        }

        if not dg_connection.start(options):
            logger.error("Failed to start Deepgram connection")
            return

        self._listening = True
        logger.info("Deepgram connected — streaming speech...")

        last_speech_time = time.time()

        try:
            while self._running and not session_closed.is_set():
                data, overflowed = mic.read(FRAME_SIZE)
                if overflowed:
                    continue

                dg_connection.send(data.tobytes())

                rms = self._rms(data)
                if rms >= RMS_THRESHOLD:
                    last_speech_time = time.time()
                elif (time.time() - last_speech_time) > SILENCE_TIMEOUT_S:
                    logger.info("Silence detected, disconnecting Deepgram")
                    break
        except Exception as e:
            logger.error("Stream error: %s", e)
        finally:
            self._listening = False
            try:
                dg_connection.finish()
            except Exception:
                pass

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
