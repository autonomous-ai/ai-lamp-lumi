"""
TTS Service — converts text to speech via OpenAI TTS API and plays through speaker.

Uses OpenAI-compatible API (same base_url and api_key as the LLM provider).
Requests PCM format directly — no ffmpeg needed.
Runs synthesis in a background thread to avoid blocking FastAPI.
"""

import logging
import math
import threading
from typing import Optional

logger = logging.getLogger("lelamp.voice.tts")

DEFAULT_VOICE = "alloy"
DEFAULT_MODEL = "tts-1"


class TTSService:
    """Text-to-speech using OpenAI TTS API + sounddevice playback."""

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
        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=api_key, base_url=base_url)
            logger.info("OpenAI TTS ready (voice=%s, model=%s, base_url=%s)", self._voice, self._model, base_url)
        except ImportError as e:
            logger.warning("openai SDK not available: %s", e)

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

    def _speak_sync(self, text: str):
        """Run TTS synthesis and playback in a worker thread."""
        try:
            self._speaking = True
            logger.info("TTS synthesizing: model=%s, voice=%s, base_url=%s, text='%s'",
                        self._model, self._voice, self._base_url, text[:80])
            response = self._client.audio.speech.create(
                model=self._model,
                voice=self._voice,
                input=text,
                response_format="pcm",  # raw 24kHz 16-bit mono PCM
            )
            pcm_data = response.read()
            logger.info("TTS received %d bytes PCM data", len(pcm_data))
            if len(pcm_data) == 0:
                logger.error("TTS returned empty audio data")
                return
            self._play_pcm(pcm_data)
        except Exception as e:
            logger.error("TTS speak failed: %s (type=%s)", e, type(e).__name__)
        finally:
            self._speaking = False
            self._lock.release()

    def _get_device_samplerate(self) -> int:
        """Get the default sample rate for the output device."""
        try:
            info = self._sd.query_devices(self._output_device)
            return int(info["default_samplerate"])
        except Exception:
            return 48000

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

    def _play_pcm(self, pcm_data: bytes):
        """Play raw PCM int16 mono 24kHz through sounddevice, resampling if needed."""
        np = self._np
        sd = self._sd
        src_rate = 24000

        audio = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0

        dst_rate = self._get_device_samplerate()
        if dst_rate != src_rate:
            logger.info("TTS resampling %d -> %d Hz (%d samples)", src_rate, dst_rate, len(audio))
            audio = self._resample(audio, src_rate, dst_rate)

        logger.info("TTS playing %d samples @ %d Hz on device=%s", len(audio), dst_rate, self._output_device)
        try:
            sd.play(audio, samplerate=dst_rate, device=self._output_device, blocking=True)
            logger.info("TTS playback complete")
        except Exception as e:
            logger.error("TTS playback failed: %s (device=%s)", e, self._output_device)
