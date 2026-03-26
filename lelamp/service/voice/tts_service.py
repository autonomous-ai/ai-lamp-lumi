"""
TTS Service — converts text to speech via OpenAI TTS API and plays through speaker.

Uses OpenAI-compatible API (same base_url and api_key as the LLM provider).
Streams PCM chunks directly to the audio device — no buffering the entire response.
Runs synthesis in a background thread to avoid blocking FastAPI.
"""

import logging
import math
import threading
from typing import Optional

logger = logging.getLogger("lelamp.voice.tts")

DEFAULT_VOICE = "alloy"
DEFAULT_MODEL = "tts-1"

# OpenAI TTS returns 24kHz 16-bit mono PCM
TTS_SAMPLE_RATE = 24000
TTS_CHANNELS = 1

# Stream chunk size for iter_bytes (4KB = ~85ms of audio at 24kHz 16-bit)
STREAM_CHUNK_SIZE = 4096


class TTSService:
    """Text-to-speech using OpenAI TTS API + sounddevice streaming playback."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        sound_device_module=None,
        numpy_module=None,
        output_device: Optional[int] = None,
        voice: str = DEFAULT_VOICE,
        model: str = DEFAULT_MODEL,
    ):
        self._sd = sound_device_module
        self._np = numpy_module
        self._output_device = output_device
        self._voice = voice
        self._model = model
        self._lock = threading.Lock()
        self._speaking = False

        self._client = None
        self._base_url = base_url
        self._device_rate = None
        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=api_key, base_url=base_url)
            logger.info("OpenAI TTS ready (voice=%s, model=%s, base_url=%s)", self._voice, self._model, base_url)
        except ImportError as e:
            logger.warning("openai SDK not available: %s", e)

        # Cache device sample rate
        if self._sd and self._output_device is not None:
            try:
                info = self._sd.query_devices(self._output_device)
                self._device_rate = int(info["default_samplerate"])
                logger.info("Output device %d: rate=%d Hz", self._output_device, self._device_rate)
            except Exception as e:
                logger.warning("Failed to query output device: %s", e)

    @property
    def available(self) -> bool:
        return self._client is not None and self._sd is not None

    @property
    def speaking(self) -> bool:
        return self._speaking

    def speak(self, text: str) -> bool:
        """Synthesize and play text. Returns True if started, False if busy or unavailable."""
        if not self.available:
            logger.warning("TTS not available")
            return False

        if not self._lock.acquire(blocking=False):
            logger.info("TTS busy, skipping: %s", text[:50])
            return False

        thread = threading.Thread(
            target=self._speak_sync,
            args=(text,),
            daemon=True,
            name="tts-speak",
        )
        thread.start()
        return True

    def _resample(self, audio, src_rate: int, dst_rate: int):
        """Linear interpolation resample (no scipy needed)."""
        np = self._np
        if src_rate == dst_rate:
            return audio
        ratio = dst_rate / src_rate
        n_out = math.ceil(len(audio) * ratio)
        x_old = np.linspace(0, 1, len(audio))
        x_new = np.linspace(0, 1, n_out)
        return np.interp(x_new, x_old, audio).astype(np.float32)

    def _speak_sync(self, text: str):
        """Stream TTS response directly to audio output — no full-buffer wait."""
        np = self._np
        sd = self._sd
        dst_rate = self._device_rate or 48000

        try:
            self._speaking = True
            logger.info("TTS synthesizing: text='%s'", text[:80])

            with self._client.audio.speech.with_streaming_response.create(
                model=self._model,
                voice=self._voice,
                input=text,
                response_format="pcm",
            ) as response:
                # Remainder bytes from previous chunk (PCM frames must be 2-byte aligned)
                remainder = b""
                total_samples = 0

                with sd.OutputStream(
                    samplerate=dst_rate,
                    channels=TTS_CHANNELS,
                    dtype="float32",
                    device=self._output_device,
                ) as stream:
                    for chunk in response.iter_bytes(STREAM_CHUNK_SIZE):
                        raw = remainder + chunk
                        # Ensure 2-byte alignment for int16
                        usable = len(raw) - (len(raw) % 2)
                        remainder = raw[usable:]

                        if usable == 0:
                            continue

                        samples = np.frombuffer(raw[:usable], dtype=np.int16).astype(np.float32) / 32768.0

                        if dst_rate != TTS_SAMPLE_RATE:
                            samples = self._resample(samples, TTS_SAMPLE_RATE, dst_rate)

                        stream.write(samples.reshape(-1, 1))
                        total_samples += len(samples)

                    # Flush remainder
                    if len(remainder) >= 2:
                        usable = len(remainder) - (len(remainder) % 2)
                        samples = np.frombuffer(remainder[:usable], dtype=np.int16).astype(np.float32) / 32768.0
                        if dst_rate != TTS_SAMPLE_RATE:
                            samples = self._resample(samples, TTS_SAMPLE_RATE, dst_rate)
                        stream.write(samples.reshape(-1, 1))
                        total_samples += len(samples)

                logger.info("TTS playback complete (%d samples @ %d Hz)", total_samples, dst_rate)

        except Exception as e:
            logger.error("TTS speak failed: %s (type=%s)", e, type(e).__name__)
        finally:
            self._speaking = False
            self._lock.release()
