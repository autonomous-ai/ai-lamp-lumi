import base64
import logging
import os
import threading
import time
from collections import Counter
from copy import copy
from dataclasses import dataclass
from typing import Any, override

import cv2
import requests

import lelamp.config as config
from lelamp.service.sensing.perceptions.models import (
    Face,
    FaceDetectionData,
)
from lelamp.service.sensing.perceptions.typing import SendEventCallable
from lelamp.service.sensing.perceptions.utils import PerceptionStateObservers
from lelamp.service.sensing.presence_service import PresenceState, PresenseService

from .base import Perception

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

EMOTIONS = [
    "Neutral",
    "Happy",
    "Sad",
    "Surprise",
    "Fear",
    "Disgust",
    "Anger",
    "Contempt",
]


class RemoteEmotionRecognizer:
    """Calls the dlbackend HTTP emotion-recognize endpoint for a single face crop."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        threshold: float = config.EMOTION_CONFIDENCE_THRESHOLD,
        timeout: float = 10.0,
    ):
        self._url: str = (
            base_url.rstrip("/") + "/" + config.DL_EMOTION_RECOGNIZE_ENDPOINT.strip("/")
            if base_url
            else ""
        )
        self._api_key: str = api_key
        self._threshold: float = threshold
        self._timeout: float = timeout

    def _img2b64(self, frame: cv2.typing.MatLike) -> str:
        _, buf = cv2.imencode(".jpg", frame)
        return base64.b64encode(buf.tobytes()).decode()

    def recognize(self, face_crop: cv2.typing.MatLike) -> dict[str, Any] | None:
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
                return None

            detections = resp.json().get("detections", [])
            if not detections:
                return None

            # Return the top detection (highest confidence)
            top = max(detections, key=lambda d: d["confidence"])
            return top
        except requests.RequestException as e:
            logger.warning("[activity.emotion] request failed: %s", e)
            return None


@dataclass
class EmotionData:
    face: Face
    emotions: list[str]


class EmotionPerception(Perception[FaceDetectionData]):
    """Detects facial emotions via face recognizer callback + dlbackend HTTP.

    Registers a callback with FaceRecognizer. When a face is detected,
    sends the face crop to the emotion-recognize HTTP endpoint. Buffers
    results per-person and flushes aggregated emotion events periodically.
    """

    def __init__(
        self,
        perception_state: PerceptionStateObservers,
        send_event: SendEventCallable,
        presense_service: PresenseService | None,
        base_url: str = config.DL_BACKEND_URL,
        api_key: str = config.DL_API_KEY,
    ):
        super().__init__(perception_state, send_event)

        self._presence_service: PresenseService | None = presense_service
        self._base_url: str = base_url
        self._api_key: str = api_key

        self._recognizer: RemoteEmotionRecognizer = RemoteEmotionRecognizer(
            base_url=base_url,
            api_key=api_key,
            threshold=config.EMOTION_CONFIDENCE_THRESHOLD,
        )

        self._last_detection_time: float | None = None
        self._last_emotion: str | None = None

        # Lock protects all mutable state below
        self._state_lock: threading.RLock = threading.RLock()

        # Buffer per person — flushed every EMOTION_FLUSH_S
        self._flush_interval: float = config.EMOTION_FLUSH_S
        self._last_flush_ts: float = 0.0
        # {person_id: [emotion_str, ...]}
        self._emotion_buffer: dict[str, EmotionData] = {}
        self._snapshots_buffer: list[cv2.typing.MatLike] = []

        # Dedup: same (current_user, emotion) within window → drop. Mirrors
        # MotionPerception — single key + window, reset on user change.
        self._last_sent_key: tuple[str, str] | None = None  # (current_user, emotion)
        self._last_sent_ts: float = 0.0
        self._dedup_window_s: float = 300.0  # 5 min

    def _process_face(
        self,
        frame: cv2.typing.MatLike,
        face: Face,
    ) -> None:
        """Crop face, send to emotion backend, buffer result."""

        h, w = frame.shape[:2]
        # bbox is [x1, y1, x2, y2] from InsightFace
        x1, y1, x2, y2 = face.bbox

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

        if self._presence_service:
            self._presence_service.on_motion()

        # Save annotated snapshot (I/O — outside lock)
        snapshot = self._save_annotated(frame, face.bbox, emotion, confidence)

        with self._state_lock:
            self._last_detection_time = time.time()
            self._last_emotion = emotion

            if face.person_id not in self._emotion_buffer:
                self._emotion_buffer[face.person_id] = EmotionData(
                    face=face, emotions=[]
                )
            self._emotion_buffer[face.person_id].emotions.append(emotion)

            if snapshot is not None:
                self._snapshots_buffer.append(snapshot)

        logger.debug(
            "[activity.emotion] %s: %s (%.2f)", face.person_id, emotion, confidence
        )

    @override
    def _check_impl(self, data: FaceDetectionData) -> None:
        """Only used for periodic flush — actual detection is callback-driven."""
        if data.frame is not None:
            for f in data.faces:
                self._process_face(data.frame, f)

        self._flush_buffer()

    def _save_annotated(
        self,
        frame: cv2.typing.MatLike,
        bbox: list[int],
        emotion: str,
        confidence: float,
    ) -> cv2.typing.MatLike | None:
        """Draw annotation and save to snapshot dir. Rotates old files."""
        try:
            os.makedirs(config.EMOTION_SNAPSHOT_DIR, exist_ok=True)

            vis = frame.copy()
            x1, y1, x2, y2 = bbox
            _ = cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)
            label = f"{emotion} {confidence:.2f}"
            _ = cv2.putText(
                vis,
                label,
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
            )

            return vis
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

            buffer = copy(self._emotion_buffer)
            snapshots_buffer = copy(self._snapshots_buffer)
            self._emotion_buffer.clear()
            self._snapshots_buffer.clear()
            self._last_flush_ts = cur_ts

        if (
            self._presence_service is not None
            and self._presence_service.state != PresenceState.PRESENT
        ):
            logger.info(
                "[activity.emotion] skipping — no presence (presence=%s)",
                self._presence_service.state,
            )
            return

        # Dedup key uses the global current_user (same source of truth as
        # MotionPerception + reset_dedup). Per-face person_id is too noisy
        # ('?' / 'stranger_17' / 'stranger_18' all flip the key on every
        # frame and bypass dedup). current_user is normalized at presence
        # level, so all unsure/stranger faces collapse under the same user.
        current_user = self._perception_state.current_user.data or ""

        # Process each person's emotions
        for person_id, emotion_data in buffer.items():
            if emotion_data:
                logger.info("[activity.emotion] %s raw: %s", person_id, emotion_data)

            # Skip Neutral
            non_neutral = [e for e in emotion_data.emotions if e != "Neutral"]
            if not non_neutral:
                continue

            counts = Counter(non_neutral)
            dominant_emotion, _ = counts.most_common(1)[0]

            message = f"Emotion detected: {dominant_emotion}."

            # Dedup: same (current_user, emotion) within 5 min → drop. A
            # different user OR a different emotion flips the key.
            key = (current_user, dominant_emotion)
            with self._state_lock:
                if (
                    self._last_sent_key == key
                    and (cur_ts - self._last_sent_ts) < self._dedup_window_s
                ):
                    logger.info(
                        "[activity.emotion] dedup drop: %s (same as last send %.1fs ago)",
                        message,
                        cur_ts - self._last_sent_ts,
                    )
                    continue
                self._last_sent_key = key
                self._last_sent_ts = cur_ts

            logger.info("[activity.emotion] flushing: %s", message)
            self._send_event(
                "emotion.detected", message, "emotion", [snapshots_buffer[-1]], None
            )

    def reset_dedup(self, new_user: str = "") -> None:
        """Clear the outbound dedup state only if the visible user actually
        changed. Mirrors MotionPerception.reset_dedup — called by
        SensingService on presence.enter via the orchestrator. Without this
        guard, every stranger flicker would wipe the key and bypass the
        5-min window.
        """
        with self._state_lock:
            if self._last_sent_key is None:
                return
            last_user = self._last_sent_key[0]
            if last_user == new_user:
                logger.debug(
                    "[activity.emotion] dedup reset skipped — same user %r",
                    last_user,
                )
                return
            logger.info(
                "[activity.emotion] dedup reset (user %r → %r)",
                last_user,
                new_user,
            )
            self._last_sent_key = None
            self._last_sent_ts = 0.0

    def to_dict(self) -> dict[str, Any]:
        with self._state_lock:
            seconds_since = (
                int(time.time() - self._last_detection_time)
                if self._last_detection_time is not None
                else None
            )
            last_sent = self._last_sent_key
            return {
                "type": "emotion",
                "last_sent_emotion": last_sent[1] if last_sent else None,
                "last_sent_user": last_sent[0] if last_sent else None,
                "last_detected_emotion": self._last_emotion,
                "buffered_persons": len(self._emotion_buffer),
                "emotion_detected": self._last_detection_time is not None,
                "seconds_since_detection": seconds_since,
            }
