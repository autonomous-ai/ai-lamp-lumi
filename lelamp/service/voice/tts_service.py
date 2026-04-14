"""
TTS Service — converts text to speech via OpenAI TTS API and plays through speaker.

Uses OpenAI-compatible API (same base_url and api_key as the LLM provider).
Streams PCM chunks directly to the audio device — no buffering the entire response.
Runs synthesis in a background thread to avoid blocking FastAPI.
"""

import logging
import math
import queue
import re
import threading
import time
from typing import Optional

import numpy as np

logger = logging.getLogger("lelamp.voice.tts")
logger.setLevel(logging.DEBUG)

AVAILABLE_VOICES = ("alloy", "ash", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer")
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
        speed: float = 1.0,
        on_speak_start=None,
        on_speak_end=None,
    ):
        self._sd = sound_device_module
        self._np = numpy_module
        self._output_device = output_device
        if voice not in AVAILABLE_VOICES:
            logger.warning("Unknown TTS voice '%s', falling back to '%s'", voice, DEFAULT_VOICE)
            voice = DEFAULT_VOICE
        self._voice = voice
        self._model = model
        self._speed = max(0.25, min(4.0, speed))
        self._lock = threading.Lock()
        self._speaking = False
        self._max_retries = max_retries
        self._stop_event = threading.Event()

        # Optional callbacks for LED speaking effect.
        # on_speak_start(): called when TTS playback begins (before audio streams).
        # on_speak_end():   called when TTS playback finishes or is interrupted.
        self._on_speak_start = on_speak_start
        self._on_speak_end = on_speak_end

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
        for rate in [44100, 48000, 16000, 32000, 24000, 22050, 8000]:
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

    def _split_text_into_growing_sentence_chunks(
        self,
        text: str,
        base_chars: int = 120,
        growth_factor: float = 2.0,
        max_chunk_chars: int = 520,
        max_chunks: int = 12,
    ) -> list[str]:
        """Split text into sentence-aligned chunks with growing size."""
        normalized = re.sub(r"\s+", " ", (text or "").strip())
        if not normalized:
            return []

        parts = re.findall(r"[^.!?;:]+[.!?;:]*", normalized)
        parts = [p.strip() for p in parts if p and p.strip()]
        if not parts:
            return [normalized]

        chunks: list[str] = []
        idx = 0
        chunk_i = 0
        while idx < len(parts) and len(chunks) < max_chunks:
            target = int(base_chars * (growth_factor ** chunk_i))
            target = min(max(target, base_chars), max_chunk_chars)
            current: list[str] = []
            while idx < len(parts):
                s = parts[idx]
                candidate = " ".join(current + [s]).strip() if current else s
                if current and len(candidate) > target:
                    break
                current.append(s)
                idx += 1
                if len(" ".join(current)) >= target:
                    break
            if current:
                chunks.append(" ".join(current).strip())
                chunk_i += 1
            else:
                chunks.append(parts[idx])
                idx += 1

        if idx < len(parts) and chunks:
            remainder = " ".join(parts[idx:]).strip()
            if remainder:
                chunks[-1] = f"{chunks[-1]} {remainder}".strip()
        return [c for c in chunks if c]

    def _iter_tts_samples(self, text: str, dst_rate: int, ttfb_tag: Optional[str] = None):
        """Yield float32 samples chunks from OpenAI-compatible streaming response."""
        np = self._np
        remainder = b""
        first_audio_logged = False
        t0 = time.perf_counter()
        with self._client.audio.speech.with_streaming_response.create(
            model=self._model,
            voice=self._voice,
            input=text,
            response_format="pcm",
            speed=self._speed,
        ) as response:
            for chunk in response.iter_bytes(STREAM_CHUNK_SIZE):
                if self._stop_event.is_set():
                    return
                raw = remainder + chunk
                usable = len(raw) - (len(raw) % 2)
                remainder = raw[usable:]
                if usable == 0:
                    continue
                samples = (
                    np.frombuffer(raw[:usable], dtype=np.int16).astype(np.float32)
                    / 32768.0
                )
                if dst_rate != TTS_SAMPLE_RATE:
                    samples = self._resample(samples, TTS_SAMPLE_RATE, dst_rate)
                if ttfb_tag and not first_audio_logged:
                    first_audio_logged = True
                    logger.info(
                        "TTS %s first audio frame: %.0fms",
                        ttfb_tag,
                        (time.perf_counter() - t0) * 1000.0,
                    )
                yield samples.reshape(-1, 1)

            if not self._stop_event.is_set() and len(remainder) >= 2:
                usable = len(remainder) - (len(remainder) % 2)
                samples = (
                    np.frombuffer(remainder[:usable], dtype=np.int16).astype(np.float32)
                    / 32768.0
                )
                if dst_rate != TTS_SAMPLE_RATE:
                    samples = self._resample(samples, TTS_SAMPLE_RATE, dst_rate)
                yield samples.reshape(-1, 1)

    def _stream_chunk_with_retry(self, stream, text: str, dst_rate: int, idx: int, total: int, ttfb_tag: Optional[str] = None) -> int:
        """Stream one text chunk with retry; return written sample count."""
        total_samples = 0
        attempt = 0
        while attempt <= self._max_retries:
            try:
                logger.info(
                    "TTS chunk %d/%d: len=%d (attempt=%d, speed=%.2f)",
                    idx,
                    total,
                    len(text),
                    attempt + 1,
                    self._speed,
                )
                for frame in self._iter_tts_samples(text, dst_rate, ttfb_tag=ttfb_tag):
                    if self._stop_event.is_set():
                        return total_samples
                    # Fire on_speak_start on first audio frame — syncs LED effect
                    # with actual audio output, not with TTS API call
                    if not self._speak_start_fired and self._on_speak_start:
                        self._speak_start_fired = True
                        try:
                            self._on_speak_start()
                        except Exception as e:
                            logger.warning("on_speak_start callback failed: %s", e)
                    stream.write(frame)
                    total_samples += len(frame)
                return total_samples
            except Exception as e:
                logger.error(
                    "TTS chunk failed: %s (type=%s, chunk=%d/%d, attempt=%d/%d)",
                    e,
                    type(e).__name__,
                    idx,
                    total,
                    attempt + 1,
                    self._max_retries + 1,
                )
                # Server-side errors (404, 503) — no point retrying or probing device
                status = getattr(e, "status_code", None)
                if status in (404, 503):
                    logger.warning("TTS server error %s — skipping retries", status)
                    break
                if attempt < self._max_retries:
                    self._probe_device_rate()
                attempt += 1
        logger.error("TTS give up for chunk %d/%d: text='%s'", idx, total, text[:80])
        return total_samples

    def _tail_producer(
        self,
        tail_chunks: list[str],
        dst_rate: int,
        out_q: "queue.Queue[Optional[np.ndarray]]",
    ) -> None:
        """Produce tail frames sequentially into one shared queue."""
        total = len(tail_chunks) + 1
        try:
            for i, chunk_text in enumerate(tail_chunks, start=2):
                if self._stop_event.is_set():
                    break
                attempt = 0
                while attempt <= self._max_retries:
                    try:
                        logger.info("Tail producer start c%d/%d len=%d", i, total, len(chunk_text))
                        for frame in self._iter_tts_samples(chunk_text, dst_rate):
                            if self._stop_event.is_set():
                                return
                            out_q.put(frame)
                        logger.info("Tail producer done  c%d/%d", i, total)
                        break
                    except Exception as e:
                        logger.error(
                            "Tail producer failed: %s (type=%s, chunk=%d/%d, attempt=%d/%d)",
                            e,
                            type(e).__name__,
                            i,
                            total,
                            attempt + 1,
                            self._max_retries + 1,
                        )
                        status = getattr(e, "status_code", None)
                        if status in (404, 503):
                            logger.warning("TTS server error %s — skipping retries", status)
                            return
                        if attempt < self._max_retries:
                            self._probe_device_rate()
                        attempt += 1
                    if attempt > self._max_retries:
                        break
        finally:
            try:
                out_q.put_nowait(None)
            except Exception:
                pass

    def _speak_sync(self, text: str):
        """Head chunk direct playback + parallel tail producer queue."""
        sd = self._sd
        dst_rate = self._device_rate or TTS_SAMPLE_RATE
        chunks = self._split_text_into_growing_sentence_chunks(text)
        for i, c in enumerate(chunks):
            preview = c[:140] + ("..." if len(c) > 140 else "")
            logger.info("[chunk-split] c%d/%d len=%d text='%s'", i, len(chunks) - 1, len(c), preview)

        if not chunks:
            self._speaking = False
            self._last_spoken_time = time.time()
            self._lock.release()
            return

        # _on_speak_start fires on first audio frame, not here — see _stream_chunk_with_retry
        self._speak_start_fired = False

        head_text = chunks[0]
        tail_chunks = chunks[1:]
        total_samples = 0

        # Re-probe before opening stream — device can reset between TTS calls (WM8960/PA).
        self._probe_device_rate()
        dst_rate = self._device_rate or TTS_SAMPLE_RATE

        for _play_attempt in range(2):
            try:
                with sd.OutputStream(
                    samplerate=dst_rate,
                    channels=TTS_CHANNELS,
                    dtype="float32",
                    device=self._output_device,
                ) as stream:
                    # Short text: one request stream then done.
                    if not tail_chunks:
                        total_samples += self._stream_chunk_with_retry(
                            stream, head_text, dst_rate, 1, 1, ttfb_tag="c0"
                        )
                    else:
                        # Start one tail producer (c1..cN) in parallel while c0 is playing.
                        tail_q: "queue.Queue[Optional[np.ndarray]]" = queue.Queue(maxsize=128)
                        producer = threading.Thread(
                            target=self._tail_producer,
                            args=(tail_chunks, dst_rate, tail_q),
                            daemon=True,
                            name="tts-tail-producer",
                        )
                        producer.start()

                        # Head path: play c0 directly as soon as first bytes arrive.
                        total_samples += self._stream_chunk_with_retry(
                            stream, head_text, dst_rate, 1, len(chunks), ttfb_tag="c0"
                        )

                        # Tail path: consume queue until sentinel or producer done + queue empty.
                        while not self._stop_event.is_set():
                            if (not producer.is_alive()) and tail_q.empty():
                                break
                            try:
                                item = tail_q.get(timeout=0.3)
                            except queue.Empty:
                                continue
                            if item is None:
                                break
                            stream.write(item)
                            total_samples += len(item)
                break  # playback succeeded, exit retry loop
            except Exception as e:
                logger.error("TTS playback setup failed: %s (type=%s)", e, type(e).__name__)
                if _play_attempt == 0:
                    logger.warning("Re-probing output device rate and retrying...")
                    self._probe_device_rate()
                    dst_rate = self._device_rate or TTS_SAMPLE_RATE

        logger.info(
            "TTS playback complete (%d samples @ %d Hz, chunks=%d)",
            total_samples,
            dst_rate,
            len(chunks),
        )

        self._speaking = False
        self._last_spoken_time = time.time()

        # Notify LED speaking effect — stop wave and restore previous LED state
        if self._on_speak_end:
            try:
                self._on_speak_end()
            except Exception as e:
                logger.warning("on_speak_end callback failed: %s", e)

        self._lock.release()
