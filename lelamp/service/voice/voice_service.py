"""
Voice Service — wake word detection + Deepgram STT streaming.

Pipeline:
  1. openwakeword runs always-on, listens for "Hey Lumi"
  2. On wake word → start Deepgram WebSocket streaming
  3. Stream mic audio until silence detected (VAD) or timeout
  4. Get transcript → POST to Lumi Server /api/sensing/event {type:"voice", message: transcript}
  5. Lumi Go → chat.send → OpenClaw → AI responds → Go captures response → POST /voice/speak
  6. tts_service plays the response through the speaker

This service runs in a background daemon thread, similar to SensingService.
"""

import logging
import os
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

# Recording timeout after wake word (seconds)
LISTEN_TIMEOUT_S = 10.0

# Silence detection: stop recording after this many seconds of silence
SILENCE_THRESHOLD_S = 1.5
SILENCE_RMS_THRESHOLD = 500  # RMS below this = silence


class VoiceService:
    """Background voice pipeline: wake word → STT → forward to Lumi."""

    def __init__(
        self,
        deepgram_api_key: str,
        input_device: Optional[int] = None,
        wake_word_model: str = "hey_jarvis",  # openwakeword built-in, closest to "Hey Lumi"
    ):
        self._input_device = input_device
        self._deepgram_api_key = deepgram_api_key
        self._wake_word_model = wake_word_model
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._listening = False  # True when actively recording for STT

        # Lazy imports
        self._pvrecorder = None
        self._oww = None
        self._np = None
        self._deepgram = None

        try:
            import numpy as np
            self._np = np
        except ImportError:
            logger.warning("numpy not available for voice")

        try:
            from pvrecorder import PvRecorder
            self._pvrecorder = PvRecorder
        except ImportError:
            logger.warning("pvrecorder not available — wake word disabled")

        try:
            import openwakeword
            from openwakeword.model import Model as OWWModel
            self._oww = OWWModel
            openwakeword.utils.download_models()
            logger.info("openwakeword loaded")
        except ImportError:
            logger.warning("openwakeword not available")

        try:
            from deepgram import DeepgramClient
            self._deepgram = DeepgramClient
            logger.info("Deepgram SDK loaded")
        except ImportError:
            logger.warning("deepgram-sdk not available — STT disabled")

    @property
    def available(self) -> bool:
        return self._oww is not None and self._deepgram is not None and self._deepgram_api_key != ""

    @property
    def listening(self) -> bool:
        return self._listening

    def start(self):
        if self._running:
            return
        if not self.available:
            logger.warning("VoiceService not starting — missing deps or DEEPGRAM_API_KEY")
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
        """Main loop: listen for wake word, then stream to Deepgram."""
        time.sleep(3)  # Wait for hardware init

        # Initialize openwakeword model
        oww_model = self._oww(
            wakeword_models=[self._wake_word_model],
            inference_framework="onnx",
        )

        # Initialize PvRecorder for always-on mic listening
        # PvRecorder uses 512-sample frames at 16kHz
        frame_length = 512
        try:
            recorder = self._pvrecorder(
                frame_length=frame_length,
                device_index=self._input_device if self._input_device is not None else -1,
            )
        except Exception as e:
            logger.error("Failed to init PvRecorder: %s", e)
            return

        recorder.start()
        logger.info("Wake word listener active (model=%s)", self._wake_word_model)

        try:
            while self._running:
                try:
                    pcm = recorder.read()
                    # Convert to numpy int16 array
                    np_frame = self._np.array(pcm, dtype=self._np.int16)

                    # Feed to openwakeword
                    prediction = oww_model.predict(np_frame)

                    # Check if any wake word score exceeds threshold
                    for model_name, score in prediction.items():
                        if score > 0.5:
                            logger.info("Wake word detected! (%s, score=%.2f)", model_name, score)
                            oww_model.reset()
                            self._on_wake_word(recorder, frame_length)
                            break

                except Exception as e:
                    logger.error("Wake word loop error: %s", e)
                    time.sleep(1)
        finally:
            recorder.stop()
            recorder.delete()

    def _on_wake_word(self, recorder, frame_length: int):
        """Handle wake word detection: stream mic to Deepgram for STT."""
        self._listening = True
        try:
            transcript = self._stream_to_deepgram(recorder, frame_length)
            if transcript and transcript.strip():
                logger.info("Transcript: %s", transcript)
                self._send_to_lumi(transcript)
            else:
                logger.info("No speech detected after wake word")
        except Exception as e:
            logger.error("STT failed: %s", e)
        finally:
            self._listening = False

    def _stream_to_deepgram(self, recorder, frame_length: int) -> Optional[str]:
        """Stream audio to Deepgram and return the final transcript."""
        from deepgram import DeepgramClient, LiveTranscriptEvents, LiveOptions

        client = DeepgramClient(self._deepgram_api_key)
        dg_connection = client.listen.live.v("1")

        transcript_parts = []
        done_event = threading.Event()

        def on_message(self_unused, result, **kwargs):
            sentence = result.channel.alternatives[0].transcript
            if sentence:
                if result.is_final:
                    transcript_parts.append(sentence)
                    if result.speech_final:
                        done_event.set()

        def on_error(self_unused, error, **kwargs):
            logger.error("Deepgram error: %s", error)
            done_event.set()

        dg_connection.on(LiveTranscriptEvents.Transcript, on_message)
        dg_connection.on(LiveTranscriptEvents.Error, on_error)

        options = LiveOptions(
            model="nova-2",
            language="vi",  # Vietnamese
            smart_format=True,
            encoding=DEEPGRAM_ENCODING,
            channels=DEEPGRAM_CHANNELS,
            sample_rate=DEEPGRAM_SAMPLE_RATE,
            interim_results=True,
            endpointing=300,  # ms of silence to finalize
            vad_events=True,
        )

        if not dg_connection.start(options):
            logger.error("Failed to start Deepgram connection")
            return None

        try:
            start_time = time.time()
            silence_start = None
            np = self._np

            while self._running and (time.time() - start_time) < LISTEN_TIMEOUT_S:
                if done_event.is_set():
                    break

                pcm = recorder.read()
                np_frame = np.array(pcm, dtype=np.int16)

                # Check for silence (VAD)
                rms = float(np.sqrt(np.mean(np_frame.astype(np.float64) ** 2)))
                if rms < SILENCE_RMS_THRESHOLD:
                    if silence_start is None:
                        silence_start = time.time()
                    elif (time.time() - silence_start) >= SILENCE_THRESHOLD_S:
                        logger.debug("Silence timeout, ending recording")
                        break
                else:
                    silence_start = None

                # Send PCM bytes to Deepgram
                audio_bytes = np_frame.tobytes()
                dg_connection.send(audio_bytes)

        finally:
            dg_connection.finish()

        return " ".join(transcript_parts) if transcript_parts else None

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
