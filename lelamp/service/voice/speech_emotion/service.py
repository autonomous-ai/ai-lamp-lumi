"""SpeechEmotionService — public orchestrator.

Receives `(user, wav_bytes, duration_s)` per utterance from voice_service,
buffers recognition results per user, periodically flushes with polarity-
bucket dedup, and POSTs `speech_emotion.detected` sensing events to Lumi.

Architecture mirrors `EmotionPerception` in the face sensing pipeline:

    submit()                            # non-blocking
        │  (queue.put_nowait)
        ▼
    worker thread  ── HTTP recognize ──▶ dlbackend /api/dl/ser/recognize
        │
        ▼
    per-user buffer[user] = [Inference, …]
        ▲
        │  (flush thread wakes every FLUSH_S)
        ▼
    flush:
        - drop neutral / empty user
        - mode label per user
        - bucket = polarity(mode)
        - TTL dedup keyed on (user, bucket) over DEDUP_WINDOW_S
        - hedged message → POST Lumi sensing event

Anti-spam guards (matched to face emotion):

    1. submit() drops audio shorter than MIN_AUDIO_S
    2. submit() drops empty user
    3. worker drops results below CONFIDENCE_THRESHOLD
    4. flush drops neutral/<unk>/other labels
    5. flush dedups by (user, bucket) over DEDUP_WINDOW_S
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import Counter
from copy import copy
from dataclasses import dataclass
from typing import Optional

import requests

from lelamp import config
from lelamp.service.voice.speech_emotion.base import (
    BaseSpeechEmotionRecognizer,
)
from lelamp.service.voice.speech_emotion.constants import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_DEDUP_WINDOW_S,
    DEFAULT_DL_SER_ENDPOINT,
    DEFAULT_FLUSH_S,
    DEFAULT_MIN_AUDIO_S,
    DEFAULT_QUEUE_MAXSIZE,
    SENSING_EVENT_TYPE,
)
from lelamp.service.voice.speech_emotion.emotion2vec import Emotion2VecRecognizer
from lelamp.service.voice.speech_emotion.utils import (
    bucket_for,
    format_message,
    is_neutral,
    normalize_label,
)

logger = logging.getLogger("lelamp.voice.speech_emotion")

# Resolve runtime knobs from lelamp.config with sensible fallbacks so the
# module imports cleanly even if the config hasn't been bumped yet.
_FLUSH_S: float = float(getattr(config, "SPEECH_EMOTION_FLUSH_S", DEFAULT_FLUSH_S))
_DEDUP_WINDOW_S: float = float(
    getattr(config, "SPEECH_EMOTION_DEDUP_WINDOW_S", DEFAULT_DEDUP_WINDOW_S)
)
_MIN_AUDIO_S: float = float(
    getattr(config, "SPEECH_EMOTION_MIN_AUDIO_S", DEFAULT_MIN_AUDIO_S)
)
_CONFIDENCE_THRESHOLD: float = float(
    getattr(config, "SPEECH_EMOTION_CONFIDENCE_THRESHOLD", DEFAULT_CONFIDENCE_THRESHOLD)
)
_API_URL: str = getattr(config, "SPEECH_EMOTION_API_URL", "") or ""
_API_KEY: str = getattr(config, "SPEECH_EMOTION_API_KEY", "") or ""
_LUMI_URL: str = config.LUMI_SENSING_URL


@dataclass(slots=True)
class _Job:
    user: str
    wav_bytes: bytes
    duration_s: float


@dataclass(slots=True)
class _Inference:
    user: str
    label: str
    confidence: float
    duration_s: float
    ts: float


def _build_default_recognizer() -> BaseSpeechEmotionRecognizer:
    """Compose URL from DL_BACKEND_URL + DL_SER_ENDPOINT if not preset."""
    url = _API_URL
    if not url and config.DL_BACKEND_URL:
        endpoint = getattr(config, "DL_SER_ENDPOINT", DEFAULT_DL_SER_ENDPOINT)
        url = (
            config.DL_BACKEND_URL.rstrip("/")
            + "/"
            + endpoint.strip("/")
        )
    return Emotion2VecRecognizer(url=url, api_key=_API_KEY or config.DL_API_KEY)


class SpeechEmotionService:
    """Init once per process; call submit() per utterance.

    Spawns two daemon threads when the recognizer is available — worker
    (drains the submission queue, runs HTTP recognize) and flush (drains
    the per-user buffer every FLUSH_S, dedups, sends to Lumi). Both shut
    down when stop() is called.
    """

    def __init__(
        self,
        recognizer: Optional[BaseSpeechEmotionRecognizer] = None,
        *,
        flush_s: float = _FLUSH_S,
        dedup_window_s: float = _DEDUP_WINDOW_S,
        min_audio_s: float = _MIN_AUDIO_S,
        confidence_threshold: float = _CONFIDENCE_THRESHOLD,
        lumi_url: str = _LUMI_URL,
        queue_maxsize: int = DEFAULT_QUEUE_MAXSIZE,
    ):
        self._recognizer: BaseSpeechEmotionRecognizer = (
            recognizer if recognizer is not None else _build_default_recognizer()
        )
        self._flush_s: float = flush_s
        self._dedup_window_s: float = dedup_window_s
        self._min_audio_s: float = min_audio_s
        self._confidence_threshold: float = confidence_threshold
        self._lumi_url: str = lumi_url

        # mutable state — guarded by _lock
        self._lock: threading.RLock = threading.RLock()
        self._buffer: dict[str, list[_Inference]] = {}
        self._last_sent_by_key: dict[tuple[str, str], float] = {}
        self._last_flush_ts: float = 0.0

        self._stop_event: threading.Event = threading.Event()
        self._jobs: queue.Queue[Optional[_Job]] = queue.Queue(maxsize=queue_maxsize)
        self._worker_thread: Optional[threading.Thread] = None
        self._flush_thread: Optional[threading.Thread] = None

        if self.available:
            self._start_workers()
            logger.info(
                "SpeechEmotionService started (flush=%.1fs, dedup=%.1fs, "
                "min_audio=%.1fs, conf>=%.2f)",
                flush_s, dedup_window_s, min_audio_s, confidence_threshold,
            )
        else:
            logger.info(
                "SpeechEmotionService idle — recognizer unavailable "
                "(missing DL_BACKEND_URL or endpoint config)"
            )

    # --- public API -------------------------------------------------------

    @property
    def available(self) -> bool:
        return self._recognizer is not None and self._recognizer.available

    def submit(self, user: str, wav_bytes: bytes, duration_s: float) -> None:
        """Non-blocking. Drops the sample (and logs) when:
          - service is disabled / recognizer unavailable
          - user is empty (no subject to attribute emotion to)
          - audio is empty or shorter than MIN_AUDIO_S
          - worker queue is full (back-pressure — caller should not retry)

        The caller passes the SAME wav_bytes used for speaker recognition;
        no defensive copy is needed because bytes are immutable in Python.
        """
        if not self.available:
            return
        norm_user = normalize_label(user)
        if not norm_user:
            return
        if not wav_bytes:
            return
        if duration_s < self._min_audio_s:
            logger.debug(
                "[speech_emotion] drop submit: duration=%.2fs < min=%.2fs",
                duration_s, self._min_audio_s,
            )
            return

        job = _Job(user=norm_user, wav_bytes=wav_bytes, duration_s=duration_s)
        try:
            self._jobs.put_nowait(job)
        except queue.Full:
            logger.warning(
                "[speech_emotion] drop submit: worker queue full (size=%d)",
                self._jobs.qsize(),
            )

    def stop(self) -> None:
        """Signal worker + flush threads to exit. Idempotent."""
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        try:
            self._jobs.put_nowait(None)
        except queue.Full:
            pass

    def to_dict(self) -> dict:
        """Diagnostic snapshot — mirrors EmotionPerception.to_dict shape."""
        with self._lock:
            return {
                "type": "speech_emotion",
                "available": self.available,
                "buffered_users": len(self._buffer),
                "dedup_keys": len(self._last_sent_by_key),
                "queue_size": self._jobs.qsize(),
                "last_flush_ts": self._last_flush_ts,
            }

    # --- worker thread ----------------------------------------------------

    def _start_workers(self) -> None:
        self._worker_thread = threading.Thread(
            target=self._worker_loop, name="speech-emotion-worker", daemon=True,
        )
        self._flush_thread = threading.Thread(
            target=self._flush_loop, name="speech-emotion-flush", daemon=True,
        )
        self._worker_thread.start()
        self._flush_thread.start()

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job = self._jobs.get(timeout=1.0)
            except queue.Empty:
                continue
            if job is None:
                break
            try:
                self._process_job(job)
            except Exception:
                logger.exception("[speech_emotion] worker loop error")

    def _process_job(self, job: _Job) -> None:
        result = self._recognizer.recognize(job.wav_bytes)
        if result is None:
            return
        if result.confidence < self._confidence_threshold:
            logger.debug(
                "[speech_emotion] skip low-conf: %s %.2f < %.2f",
                result.label, result.confidence, self._confidence_threshold,
            )
            return

        inf = _Inference(
            user=job.user,
            label=normalize_label(result.label),
            confidence=result.confidence,
            duration_s=job.duration_s,
            ts=time.time(),
        )
        with self._lock:
            self._buffer.setdefault(job.user, []).append(inf)
        logger.info(
            "[speech_emotion] buffered: %s -> %s (%.2f, %.2fs)",
            job.user, inf.label, inf.confidence, inf.duration_s,
        )

    # --- flush thread -----------------------------------------------------

    def _flush_loop(self) -> None:
        while not self._stop_event.is_set():
            # wait() returns True if the stop event fires during the wait —
            # use that as the exit signal to avoid one extra flush at shutdown.
            if self._stop_event.wait(self._flush_s):
                return
            try:
                self._flush_once()
            except Exception:
                logger.exception("[speech_emotion] flush failed")

    def _flush_once(self) -> None:
        cur_ts = time.time()
        with self._lock:
            if not self._buffer:
                return
            buf = copy(self._buffer)
            self._buffer.clear()
            self._last_flush_ts = cur_ts
            # Prune expired dedup entries (oldest TTL window).
            cutoff = cur_ts - self._dedup_window_s
            self._last_sent_by_key = {
                k: ts for k, ts in self._last_sent_by_key.items() if ts >= cutoff
            }

        for user, inferences in buf.items():
            if not user or not inferences:
                continue
            self._flush_user(user, inferences, cur_ts)

    def _flush_user(
        self, user: str, inferences: list[_Inference], cur_ts: float,
    ) -> None:
        non_neutral = [inf for inf in inferences if not is_neutral(inf.label)]
        if not non_neutral:
            logger.info(
                "[speech_emotion] %s: all neutral (%d samples) — skipping",
                user, len(inferences),
            )
            return

        counts = Counter(inf.label for inf in non_neutral)
        dominant_label, _ = counts.most_common(1)[0]
        dom_confidences = [
            inf.confidence for inf in non_neutral if inf.label == dominant_label
        ]
        avg_confidence = sum(dom_confidences) / len(dom_confidences)
        bucket = bucket_for(dominant_label)

        key = (user, bucket)
        with self._lock:
            last_ts = self._last_sent_by_key.get(key)
            if last_ts is not None and (cur_ts - last_ts) < self._dedup_window_s:
                logger.info(
                    "[speech_emotion] dedup drop: %s bucket=%s "
                    "(key seen %.1fs ago)",
                    dominant_label, bucket, cur_ts - last_ts,
                )
                return
            self._last_sent_by_key[key] = cur_ts

        message = format_message(dominant_label, avg_confidence, bucket)
        logger.info(
            "[speech_emotion] flushing %s: %s (mode of %s)",
            user, message, ", ".join(inf.label for inf in non_neutral),
        )
        self._send_to_lumi(message=message, user=user)

    # --- transport --------------------------------------------------------

    def _send_to_lumi(self, *, message: str, user: str) -> None:
        """POST sensing event to Lumi with 3x retry on connection error / 503.

        Same shape as voice_service._send_to_lumi but carries `current_user`
        explicitly so the Lumi sensing handler doesn't have to look it up.
        """
        if not self._lumi_url:
            return
        payload = {
            "type": SENSING_EVENT_TYPE,
            "message": message,
            "current_user": user,
        }
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(self._lumi_url, json=payload, timeout=5)
            except requests.ConnectionError as e:
                if attempt < max_retries:
                    logger.warning(
                        "[speech_emotion] Lumi unreachable (attempt %d/%d), "
                        "retry in 2s",
                        attempt, max_retries,
                    )
                    time.sleep(2)
                    continue
                logger.warning(
                    "[speech_emotion] Lumi unreachable after %d attempts: %s",
                    max_retries, e,
                )
                return
            except requests.RequestException as e:
                logger.warning("[speech_emotion] Lumi POST failed: %s", e)
                return

            if resp.status_code == 503 and attempt < max_retries:
                logger.warning(
                    "[speech_emotion] Lumi 503, retry %d/%d in 2s",
                    attempt, max_retries,
                )
                time.sleep(2)
                continue
            if resp.status_code != 200:
                logger.warning(
                    "[speech_emotion] Lumi returned %d: %s",
                    resp.status_code, resp.text[:200],
                )
                return
            logger.info("[speech_emotion] sent to Lumi: %s", message)
            return
