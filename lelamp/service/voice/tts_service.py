"""
TTS Service — converts text to speech via OpenAI TTS API and plays through speaker.

Uses OpenAI-compatible API (same base_url and api_key as the LLM provider).
Streams PCM chunks directly to the audio device — no buffering the entire response.
Runs synthesis in a background thread to avoid blocking FastAPI.
"""

import logging
import math
import threading
import time
from typing import Optional

import numpy as np

logger = logging.getLogger("lelamp.voice.tts")
logger.setLevel(logging.DEBUG)

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
        max_retries: int = 3,
    ):
        self._sd = sound_device_module
        self._np = numpy_module
        self._output_device = output_device
        self._voice = voice
        self._model = model
        self._lock = threading.Lock()
        self._speaking = False
        self._max_retries = max_retries
        self._stop_event = threading.Event()

        # Echo cancellation: store last spoken text for transcript self-filtering
        self._last_spoken_text: str = ""
        self._last_spoken_time: float = 0.0

        self._client = None
        self._base_url = base_url
        self._device_rate = None
        try:
            from openai import OpenAI

            self._client = OpenAI(api_key=api_key, base_url=base_url)
            logger.info(
                "OpenAI TTS ready (voice=%s, model=%s, base_url=%s)",
                self._voice,
                self._model,
                base_url,
            )
        except ImportError as e:
            logger.warning("openai SDK not available: %s", e)

        # Probe device sample rate by actually opening a stream (check_output_settings
        # is unreliable on some ALSA devices like seeed-2mic wm8960, CD002-AUDIO)
        if self._sd:
            self._probe_device_rate()

    def _probe_device_rate(self):
        """Probe the output device to find a supported sample rate."""
        dev_label = (
            self._output_device if self._output_device is not None else "default"
        )
        self._device_rate = None
        for rate in [48000, 16000, 32000, 44100, 24000, 22050, 8000]:
            try:
                with self._sd.OutputStream(
                    device=self._output_device,
                    samplerate=rate,
                    channels=TTS_CHANNELS,
                    dtype="float32",
                ) as stream:
                    _ = stream.write(np.zeros(rate, dtype=np.float32))
                self._device_rate = rate
                logger.info("Output device [%s]: verified rate=%d Hz", dev_label, rate)
                break
            except Exception as e:
                logger.debug("Failed to play audio with rate=%d Hz due to e=%s", dev_label, e)

        if self._device_rate is None:
            logger.warning(
                "No supported sample rate found for output device [%s]", dev_label
            )

    @property
    def available(self) -> bool:
        return self._client is not None and self._sd is not None

    @property
    def speaking(self) -> bool:
        return self._speaking

    @property
    def last_spoken_text(self) -> str:
        """Last text sent to TTS (for echo cancellation transcript filtering)."""
        return self._last_spoken_text

    @property
    def last_spoken_time(self) -> float:
        """Timestamp when last TTS playback finished."""
        return self._last_spoken_time

    def stop(self):
        """Interrupt active TTS playback. No-op if not speaking."""
        if self._speaking:
            logger.info("TTS stop requested — setting stop event")
            self._stop_event.set()

    def speak(self, text: str) -> bool:
        """Synthesize and play text. Returns True if started, False if busy or unavailable."""
        if not self.available:
            logger.warning("TTS not available")
            return False

        if not self._lock.acquire(blocking=False):
            logger.info("TTS busy, skipping: %s", text[:50])
            return False

        # Clear any leftover stop signal from a previous stop() call
        self._stop_event.clear()

        # Mark speaking IMMEDIATELY so VoiceService stops streaming to Deepgram
        # before TTS API call (which can take 3-5s)
        self._speaking = True
        self._last_spoken_text = text

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

        attempt = 0
        while attempt <= self._max_retries:
            dst_rate = self._device_rate or TTS_SAMPLE_RATE
            try:
                logger.info(
                    "TTS synthesizing: text='%s' (attempt=%d)", text[:80], attempt + 1
                )

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
                            if self._stop_event.is_set():
                                logger.info("TTS playback interrupted by stop()")
                                break
                            raw = remainder + chunk
                            # Ensure 2-byte alignment for int16
                            usable = len(raw) - (len(raw) % 2)
                            remainder = raw[usable:]

                            if usable == 0:
                                continue

                            samples = (
                                np.frombuffer(raw[:usable], dtype=np.int16).astype(
                                    np.float32
                                )
                                / 32768.0
                            )

                            if dst_rate != TTS_SAMPLE_RATE:
                                samples = self._resample(
                                    samples, TTS_SAMPLE_RATE, dst_rate
                                )

                            stream.write(samples.reshape(-1, 1))
                            total_samples += len(samples)

                        # Flush remainder
                        if len(remainder) >= 2:
                            usable = len(remainder) - (len(remainder) % 2)
                            samples = (
                                np.frombuffer(
                                    remainder[:usable], dtype=np.int16
                                ).astype(np.float32)
                                / 32768.0
                            )
                            if dst_rate != TTS_SAMPLE_RATE:
                                samples = self._resample(
                                    samples, TTS_SAMPLE_RATE, dst_rate
                                )
                            stream.write(samples.reshape(-1, 1))
                            total_samples += len(samples)

                    logger.info(
                        "TTS playback complete (%d samples @ %d Hz)",
                        total_samples,
                        dst_rate,
                    )
                    break  # success

            except Exception as e:
                logger.error(
                    "TTS speak failed: %s (type=%s, attempt=%d/%d)",
                    e,
                    type(e).__name__,
                    attempt + 1,
                    self._max_retries + 1,
                )
                if attempt < self._max_retries:
                    logger.info(
                        "Re-probing output device sample rate (attempt=%d/%d)",
                        attempt + 1,
                        self._max_retries,
                    )
                    self._probe_device_rate()
                attempt += 1

        else:
            logger.error(
                "TTS give up after %d attempts: text='%s'",
                self._max_retries + 1,
                text[:80],
            )

        self._speaking = False
        self._last_spoken_time = time.time()
        self._lock.release()
