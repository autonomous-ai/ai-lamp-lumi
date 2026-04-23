import base64
import logging
import os
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

import cv2
import numpy as np
import numpy.typing as npt
import requests

import lelamp.config as config

from .base import Perception

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

EMOTIONS = ["Neutral", "Happy", "Sad", "Surprise", "Fear", "Disgust", "Anger", "Contempt"]


class RemoteEmotionRecognizer:
    """Calls the dlbackend HTTP emotion-recognize endpoint for a single face crop."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        threshold: float = config.EMOTION_CONFIDENCE_THRESHOLD,
        timeout: float = 10.0,
    ):
        self._url = (
            base_url.rstrip("/") + "/" + config.DL_EMOTION_RECOGNIZE_ENDPOINT.strip("/")
            if base_url
            else ""
        )
        self._api_key = api_key
        self._threshold = threshold
        self._timeout = timeout
        self.connected = bool(base_url)

    def _img2b64(self, frame: npt.NDArray[np.uint8]) -> str:
        _, buf = cv2.imencode(".jpg", frame)
        return base64.b64encode(buf.tobytes()).decode()

    def recognize(self, face_crop: npt.NDArray[np.uint8]) -> dict | None:
        """Send a face crop to the emotion-recognize endpoint.

        Returns dict with keys: emotion, confidence, valence, arousal.
        Returns None if unavailable or no detection above threshold.
        """
        if not self._url:
            return None

        try:
            resp = requests.post(
                self._url,
                json={
                    "image_b64": self._img2b64(face_crop),
                    "threshold": self._threshold,
                },
                headers={"X-API-Key": self._api_key},
                timeout=self._timeout,
            )
            if resp.status_code != 200:
                logger.warning(
                    "[activity.emotion] HTTP %d: %s", resp.status_code, resp.text
                )
                self.connected = False
                return None

            self.connected = True
            detections = resp.json().get("detections", [])
            if not detections:
                return None

            # Return the top detection (highest confidence)
            top = max(detections, key=lambda d: d["confidence"])
            return top
        except requests.RequestException as e:
            logger.warning("[activity.emotion] request failed: %s", e)
            self.connected = False
            return None


class EmotionPerception(Perception):
    """Detects facial emotions via face recognizer callback + dlbackend HTTP.

    Registers a callback with FaceRecognizer. When a face is detected,
    sends the face crop to the emotion-recognize HTTP endpoint. Buffers
    results per-person and flushes aggregated emotion events periodically.
    """

    def __init__(
        self,
        send_event: Callable,
        on_motion: Callable,
        capture_stable_frame: Callable,
        presence_service,
        face_recognizer=None,
        base_url: str = config.DL_BACKEND_URL,
        api_key: str = config.DL_API_KEY,
    ):
        super().__init__(send_event)
        self._on_motion = on_motion
        self._capture_stable_frame = capture_stable_frame
        self._presence = presence_service
        self._face_recognizer = face_recognizer
        self._last_detection_time: Optional[float] = None
        self._last_emotion: Optional[str] = None

        self._recognizer = RemoteEmotionRecognizer(
            base_url=base_url,
            api_key=api_key,
            threshold=config.EMOTION_CONFIDENCE_THRESHOLD,
        )

        # Lock protects all mutable state below
        self._state_lock = threading.Lock()

        # Buffer per person — flushed every EMOTION_FLUSH_S
        self._flush_interval: float = config.EMOTION_FLUSH_S
        # {person_id: [emotion_str, ...]}
        self._emotion_buffer: dict[str, list[str]] = {}
        self._snapshot_paths: list[str] = []
        self._last_flush_ts: float = 0.0

        # Dedup: per-user cooldown + same-emotion suppression
        self._last_sent_key: tuple[str, str] | None = None  # (user, emotion)
        self._last_sent_ts: float = 0.0
        self._cooldown_s: float = 60.0
        self._same_emotion_window_s: float = 300.0

        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="emotion")

        # Register callback with face recognizer
        if self._face_recognizer is not None:
            self._face_recognizer.register_callback(self._on_face_detected)

    def _on_face_detected(
        self,
        frame: npt.NDArray[np.uint8],
        bbox: list[int],
        kind: str,
        person_id: str,
    ) -> None:
        """Callback from FaceRecognizer. Submits work to thread pool to avoid blocking."""
        self._pool.submit(self._process_face, frame, bbox, kind, person_id)

    def _process_face(
        self,
        frame: npt.NDArray[np.uint8],
        bbox: list[int],
        kind: str,
        person_id: str,
    ) -> None:
        """Crop face, send to emotion backend, buffer result."""
        h, w = frame.shape[:2]
        # bbox is [x1, y1, x2, y2] from InsightFace
        x1, y1, x2, y2 = bbox

        # Clamp to frame bounds
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(w, x2)
        y2 = min(h, y2)
        if x2 <= x1 or y2 <= y1:
            return

        face_crop = frame[y1:y2, x1:x2]

        try:
            result = self._recognizer.recognize(face_crop)
        except Exception:
            logger.exception("[activity.emotion] recognize error")
            return

        if result is None:
            return

        emotion = result["emotion"]
        confidence = result["confidence"]

        self._on_motion()

        # Save annotated snapshot (I/O — outside lock)
        snapshot_path = self._save_annotated(frame, bbox, emotion, confidence)

        with self._state_lock:
            self._last_detection_time = time.time()
            self._last_emotion = emotion

            if person_id not in self._emotion_buffer:
                self._emotion_buffer[person_id] = []
            self._emotion_buffer[person_id].append(emotion)

            if snapshot_path:
                self._snapshot_paths.append(snapshot_path)

        logger.debug(
            "[activity.emotion] %s: %s (%.2f)", person_id, emotion, confidence
        )

        self._flush_buffer()

    def _check_impl(self, frame: npt.NDArray[np.uint8]) -> None:
        """Only used for periodic flush — actual detection is callback-driven."""
        self._flush_buffer()

    def _save_annotated(
        self,
        frame: npt.NDArray[np.uint8],
        bbox: list[int],
        emotion: str,
        confidence: float,
    ) -> Optional[str]:
        """Draw annotation and save to snapshot dir. Rotates old files."""
        try:
            os.makedirs(config.EMOTION_SNAPSHOT_DIR, exist_ok=True)

            vis = frame.copy()
            x1, y1, x2, y2 = bbox
            cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)
            label = f"{emotion} {confidence:.2f}"
            cv2.putText(
                vis, label, (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2,
            )

            filename = f"emotion_{int(time.time() * 1000)}.jpg"
            filepath = os.path.join(config.EMOTION_SNAPSHOT_DIR, filename)
            _, buf = cv2.imencode(".jpg", vis, [cv2.IMWRITE_JPEG_QUALITY, 85])
            with open(filepath, "wb") as f:
                f.write(buf.tobytes())

            # Rotate: remove oldest files if over max count
            files = sorted(
                (
                    os.path.join(config.EMOTION_SNAPSHOT_DIR, f)
                    for f in os.listdir(config.EMOTION_SNAPSHOT_DIR)
                    if f.endswith(".jpg")
                ),
                key=os.path.getmtime,
            )
            while len(files) > config.EMOTION_SNAPSHOT_MAX_COUNT:
                try:
                    os.remove(files.pop(0))
                except OSError:
                    pass

            return filepath
        except Exception as e:
            logger.debug("[activity.emotion] snapshot save failed: %s", e)
            return None

    def _flush_buffer(self) -> None:
        with self._state_lock:
            if not self._emotion_buffer:
                return

            cur_ts = time.time()
            if (cur_ts - self._last_flush_ts) < self._flush_interval:
                return

            buffer = dict(self._emotion_buffer)
            snapshot_paths = list(self._snapshot_paths)
            self._emotion_buffer.clear()
            self._snapshot_paths.clear()
            self._last_flush_ts = cur_ts

        from ..presence_service import PresenceState

        if self._presence.state != PresenceState.PRESENT:
            logger.info(
                "[activity.emotion] skipping — no presence (presence=%s)",
                self._presence.state,
            )
            return

        # Process each person's emotions
        for person_id, emotions in buffer.items():
            if emotions:
                logger.info(
                    "[activity.emotion] %s raw: %s", person_id, emotions
                )

            # Skip Neutral
            non_neutral = [e for e in emotions if e != "Neutral"]
            if not non_neutral:
                continue

            counts = Counter(non_neutral)
            dominant_emotion, count = counts.most_common(1)[0]

            message = f"Emotion detected for {person_id}: {dominant_emotion}."

            # Dedup (lock for dedup state)
            with self._state_lock:
                elapsed = (
                    cur_ts - self._last_sent_ts
                    if self._last_sent_ts > 0
                    else float("inf")
                )
                last_user = self._last_sent_key[0] if self._last_sent_key else ""
                last_emotion = self._last_sent_key[1] if self._last_sent_key else ""

                if person_id == last_user and elapsed < self._cooldown_s:
                    logger.debug(
                        "[activity.emotion] cooldown skip: %s (%.0fs < %.0fs)",
                        message, elapsed, self._cooldown_s,
                    )
                    continue

                if (
                    person_id == last_user
                    and dominant_emotion == last_emotion
                    and elapsed < self._same_emotion_window_s
                ):
                    logger.info(
                        "[activity.emotion] same emotion skip: %s (%.0fs ago)",
                        message, elapsed,
                    )
                    continue

                self._last_sent_key = (person_id, dominant_emotion)
                self._last_sent_ts = cur_ts

            if snapshot_paths:
                message = f"{message}\n[snapshot: {snapshot_paths[-1]}]"

            logger.info("[activity.emotion] flushing: %s", message)
            self._send_event("emotion.detected", message)

    def to_dict(self) -> dict:
        with self._state_lock:
            seconds_since = (
                int(time.time() - self._last_detection_time)
                if self._last_detection_time is not None
                else None
            )
            last_sent = self._last_sent_key
            return {
                "type": "emotion",
                "connected": self._recognizer.connected,
                "last_sent_emotion": last_sent[1] if last_sent else None,
                "last_sent_user": last_sent[0] if last_sent else None,
                "last_detected_emotion": self._last_emotion,
                "buffered_persons": len(self._emotion_buffer),
                "emotion_detected": self._last_detection_time is not None,
                "seconds_since_detection": seconds_since,
            }
