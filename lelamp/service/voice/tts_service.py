"""
TTS Service — converts text to speech and plays through speaker.

Supports pluggable backends (OpenAI, ElevenLabs) via tts_backend.py.
Streams PCM chunks directly to the audio device — no buffering the entire response.
Runs synthesis in a background thread to avoid blocking FastAPI.
"""

import json
import logging
import math
import os
import queue
import re
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np

from lelamp.service.voice.tts_backend import TTSBackend, TTS_SAMPLE_RATE, create_backend

# Persisted device-rate cache so probe doesn't re-run on every lumi-lelamp restart.
# Schema: {"<output_device_id_or_default>": <rate_hz>}
_RATE_CACHE_PATH = Path(
    os.environ.get("LELAMP_AUDIO_RATE_CACHE", "/var/lib/lelamp/audio_rate.json")
)

logger = logging.getLogger("lelamp.voice.tts")

DEFAULT_VOICE = "alloy"
DEFAULT_MODEL = "tts-1"

TTS_CHANNELS = 1


class TTSService:
    """Text-to-speech with pluggable backend + sounddevice streaming playback."""

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
        instructions: Optional[str] = None,
        on_speak_start=None,
        on_speak_end=None,
        provider: str = "openai",
    ):
        self._sd = sound_device_module
        self._np = numpy_module
        self._output_device = output_device
        self._provider = provider
        self._voice = voice
        self._model = model
        self._speed = max(0.25, min(4.0, speed))
        self._instructions = instructions
        self._lock = threading.Lock()
        self._speaking = False
        self._interruptible = False
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

        self._device_rate = None
        self._backend: Optional[TTSBackend] = None
        try:
            self._backend = create_backend(provider=provider, api_key=api_key, base_url=base_url)
            logger.info(
                "TTS ready (provider=%s, voice=%s, model=%s)",
                provider,
                self._voice,
                self._model,
            )
        except Exception as e:
            logger.warning("TTS backend init failed: %s", e)

        # Probe device sample rate by actually opening a stream (check_output_settings
        # is unreliable on some ALSA devices like seeed-2mic wm8960, CD002-AUDIO)
        if self._sd:
            self._probe_device_rate()

        # Persistent OutputStream + silence keepalive — eliminates ~4s ALSA codec
        # warmup on every speak by keeping the stream open across speaks.
        # Silence writer prevents the codec from suspending during idle.
        self._stream = None
        self._stream_rate: Optional[int] = None
        self._stream_lock = threading.Lock()
        if self._sd and self._device_rate:
            try:
                self._ensure_stream(self._device_rate)
                threading.Thread(
                    target=self._silence_keepalive,
                    daemon=True,
                    name="tts-silence-keepalive",
                ).start()
            except Exception as e:
                logger.warning("Persistent stream init failed: %s", e)

    def _ensure_stream(self, dst_rate: int):
        """Open persistent OutputStream or return existing one. Reopens if rate
        changed or previous stream was invalidated. Caller must hold _stream_lock
        OR be sure no other thread can race (init path)."""
        if (
            self._stream is not None
            and self._stream_rate == dst_rate
        ):
            return self._stream

        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
            self._stream_rate = None

        stream = self._sd.OutputStream(
            samplerate=dst_rate,
            channels=TTS_CHANNELS,
            dtype="float32",
            device=self._output_device,
        )
        stream.start()
        self._stream = stream
        self._stream_rate = dst_rate
        logger.info("Persistent OutputStream opened at %d Hz", dst_rate)
        return stream

    def _invalidate_stream(self):
        """Force the persistent stream to be reopened on next use (after a
        write failure, e.g. ALSA underrun or codec rejecting buffer)."""
        with self._stream_lock:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
                self._stream_rate = None

    def _silence_keepalive(self):
        """Write 20ms of silence every 500ms when idle to keep the codec out of
        suspend. WM8960/Rockchip codecs power down PCM after ~1s idle, which
        forces a multi-second snd_pcm_prepare on the next write."""
        np = self._np
        while True:
            time.sleep(0.5)
            if self._speaking:
                continue
            try:
                with self._stream_lock:
                    if self._stream is None or self._stream_rate is None:
                        continue
                    if self._speaking:
                        continue
                    silence = np.zeros((self._stream_rate // 50, 1), dtype=np.float32)
                    self._stream.write(silence)
            except Exception as e:
                logger.debug("Silence keepalive write failed, invalidating: %s", e)
                # Don't call _invalidate_stream() under lock recursively.
                try:
                    if self._stream is not None:
                        self._stream.close()
                except Exception:
                    pass
                self._stream = None
                self._stream_rate = None

    def _cache_key(self) -> str:
        return str(self._output_device) if self._output_device is not None else "default"

    def _load_cached_rate(self) -> Optional[int]:
        try:
            if _RATE_CACHE_PATH.exists():
                data = json.loads(_RATE_CACHE_PATH.read_text())
                rate = data.get(self._cache_key())
                if isinstance(rate, int) and rate > 0:
                    return rate
        except Exception as e:
            logger.debug("rate cache read failed: %s", e)
        return None

    def _save_cached_rate(self, rate: int) -> None:
        try:
            _RATE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if _RATE_CACHE_PATH.exists():
                try:
                    data = json.loads(_RATE_CACHE_PATH.read_text()) or {}
                except Exception:
                    data = {}
            data[self._cache_key()] = rate
            _RATE_CACHE_PATH.write_text(json.dumps(data))
        except Exception as e:
            logger.debug("rate cache write failed: %s", e)

    def _probe_device_rate(self, force: bool = False):
        """Probe the output device to find a supported sample rate.

        Short-circuit order: in-memory `self._device_rate` -> disk cache -> loop probe.
        Pass force=True to bypass both caches — used by the retry path when playback
        fails because the cached rate is no longer valid.
        """
        # In-memory hit: already probed/cached in this process, nothing to do.
        if not force and self._device_rate:
            return

        dev_label = (
            self._output_device if self._output_device is not None else "default"
        )

        if not force:
            cached = self._load_cached_rate()
            if cached:
                self._device_rate = cached
                logger.info("Output device [%s]: using cached rate=%d Hz", dev_label, cached)
                return

        self._device_rate = None
        for rate in [44100, 48000, 16000, 32000, 24000, 22050, 8000]:
            try:
                # Write only ~5ms of silence — enough to verify the rate opens
                # without forcing a multi-second snd_pcm_drain on close (OrangePi).
                probe_frames = max(1, int(rate * 0.005))
                with self._sd.OutputStream(
                    device=self._output_device,
                    samplerate=rate,
                    channels=TTS_CHANNELS,
                    dtype="float32",
                ) as stream:
                    _ = stream.write(np.zeros(probe_frames, dtype=np.float32))
                self._device_rate = rate
                logger.info("Output device [%s]: verified rate=%d Hz", dev_label, rate)
                self._save_cached_rate(rate)
                break
            except Exception as e:
                logger.debug("Failed to play audio with rate=%d Hz due to e=%s", dev_label, e)

        if self._device_rate is None:
            logger.warning(
                "No supported sample rate found for output device [%s]", dev_label
            )

    @property
    def available(self) -> bool:
        return self._backend is not None and self._backend.available and self._sd is not None

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

    @property
    def interruptible(self) -> bool:
        """Whether the current speech can be interrupted by a new speak() call."""
        return self._interruptible

    def speak(self, text: str, interruptible: bool = False) -> bool:
        """Synthesize and play text. Returns True if started, False if busy or unavailable.
        If interruptible=True, a subsequent speak() call can stop this one."""
        if not self.available:
            logger.warning("TTS not available")
            return False

        if not self._lock.acquire(blocking=False):
            # Busy — but if current speech is interruptible, stop it and retry
            if self._interruptible:
                logger.info("TTS interrupting interruptible speech for: %s", text[:50])
                self.stop()
                # Wait briefly for lock release
                if not self._lock.acquire(blocking=True, timeout=2.0):
                    logger.warning("TTS lock not released after stop, giving up: %s", text[:50])
                    return False
            else:
                logger.info("TTS busy, skipping: %s", text[:50])
                return False

        # Clear any leftover stop signal from a previous stop() call
        self._stop_event.clear()

        # Mark speaking IMMEDIATELY so VoiceService stops streaming to Deepgram
        # before TTS API call (which can take 3-5s)
        self._speaking = True
        self._interruptible = interruptible
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
        """Yield float32 sample frames from the TTS backend's PCM stream."""
        np = self._np
        src_rate = self._backend.sample_rate
        remainder = b""
        first_audio_logged = False
        t0 = time.perf_counter()

        for chunk in self._backend.stream_pcm(
            text=text,
            voice=self._voice,
            model=self._model,
            speed=self._speed,
            instructions=self._instructions,
        ):
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
            # Boost TTS volume (provider-specific: OpenAI 2.5x, ElevenLabs 1.5x)
            samples = np.clip(samples * self._backend.volume_boost, -1.0, 1.0)
            if dst_rate != src_rate:
                samples = self._resample(samples, src_rate, dst_rate)
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
            if dst_rate != src_rate:
                samples = self._resample(samples, src_rate, dst_rate)
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
                    self._probe_device_rate(force=True)
                attempt += 1
        logger.error("TTS give up for chunk %d/%d: text='%s'", idx, total, text[:80])
        return total_samples

    def _head_producer(
        self,
        text: str,
        dst_rate: int,
        out_q: "queue.Queue[Optional[np.ndarray]]",
        idx_total: tuple[int, int],
    ) -> None:
        """Produce head chunk frames into a queue. Runs in parallel with the
        ALSA OutputStream open call so HTTP TTFB overlaps codec warmup."""
        idx, total = idx_total
        attempt = 0
        try:
            while attempt <= self._max_retries:
                try:
                    logger.info(
                        "TTS chunk %d/%d: len=%d (attempt=%d, speed=%.2f)",
                        idx, total, len(text), attempt + 1, self._speed,
                    )
                    for frame in self._iter_tts_samples(text, dst_rate, ttfb_tag="c0"):
                        if self._stop_event.is_set():
                            return
                        out_q.put(frame)
                    return
                except Exception as e:
                    logger.error(
                        "TTS head chunk failed: %s (type=%s, attempt=%d/%d)",
                        e, type(e).__name__, attempt + 1, self._max_retries + 1,
                    )
                    status = getattr(e, "status_code", None)
                    if status in (404, 503):
                        return
                    attempt += 1
        finally:
            try:
                out_q.put_nowait(None)
            except Exception:
                pass

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

        # Use cached rate from __init__. Re-probe only as fallback when playback
        # actually fails (handled by the retry loop below). Pre-probing on every
        # speak() blocked ~5s on OrangePi due to ALSA snd_pcm_drain after the 1s
        # silence write — diagnosed 2026-05-05 from server.log.
        dst_rate = self._device_rate or TTS_SAMPLE_RATE

        # Start head HTTP fetch BEFORE opening the OutputStream so ElevenLabs TTFB
        # (~1.5s through proxy) overlaps with ALSA codec open (multi-second on cold
        # OrangePi). By the time `with sd.OutputStream(...)` returns, first frames
        # are usually already in the queue.
        head_total = len(chunks)
        head_q: "queue.Queue[Optional[np.ndarray]]" = queue.Queue(maxsize=256)
        head_thread = threading.Thread(
            target=self._head_producer,
            args=(head_text, dst_rate, head_q, (1, head_total)),
            daemon=True,
            name="tts-head-producer",
        )
        head_thread.start()

        for _play_attempt in range(2):
            try:
                # Acquire the stream lock for the entire playback so the silence
                # keepalive thread doesn't interleave zeros with TTS frames.
                with self._stream_lock:
                    stream = self._ensure_stream(dst_rate)
                    # Tail producer kicks off the moment stream is ready so its HTTP
                    # TTFB overlaps with head playback.
                    tail_q: Optional["queue.Queue[Optional[np.ndarray]]"] = None
                    tail_thread: Optional[threading.Thread] = None
                    if tail_chunks:
                        tail_q = queue.Queue(maxsize=128)
                        tail_thread = threading.Thread(
                            target=self._tail_producer,
                            args=(tail_chunks, dst_rate, tail_q),
                            daemon=True,
                            name="tts-tail-producer",
                        )
                        tail_thread.start()

                    # Drain head queue. First-frame latency = max(stream open, HTTP TTFB)
                    # on cold start; ~HTTP TTFB only on warm stream (subsequent speaks).
                    while not self._stop_event.is_set():
                        try:
                            item = head_q.get(timeout=2.0)
                        except queue.Empty:
                            if not head_thread.is_alive():
                                break
                            continue
                        if item is None:
                            break
                        if not self._speak_start_fired and self._on_speak_start:
                            self._speak_start_fired = True
                            try:
                                self._on_speak_start()
                            except Exception as e:
                                logger.warning("on_speak_start callback failed: %s", e)
                        stream.write(item)
                        total_samples += len(item)

                    # Drain tail queue.
                    if tail_q is not None and tail_thread is not None:
                        while not self._stop_event.is_set():
                            if (not tail_thread.is_alive()) and tail_q.empty():
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
                # Stream is suspect -- close and reopen on retry.
                self._invalidate_stream()
                if _play_attempt == 0:
                    logger.warning("Re-probing output device rate and retrying...")
                    self._probe_device_rate(force=True)
                    dst_rate = self._device_rate or TTS_SAMPLE_RATE
                    # Old head producer is at the stale rate -- orphan it and
                    # restart at the new rate. Daemon thread will exit on its own.
                    head_q = queue.Queue(maxsize=256)
                    head_thread = threading.Thread(
                        target=self._head_producer,
                        args=(head_text, dst_rate, head_q, (1, head_total)),
                        daemon=True,
                        name="tts-head-producer-retry",
                    )
                    head_thread.start()

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
