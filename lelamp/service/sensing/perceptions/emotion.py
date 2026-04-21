import base64
import json
import logging
import time
from typing import Callable, Optional, override

import cv2
import numpy as np
import numpy.typing as npt
from websockets import ConnectionClosedError
from websockets.sync.client import ClientConnection, connect

import lelamp.config as config
from .base import Perception

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

EMOTIONS = ["Angry", "Disgust", "Fear", "Happy", "Sad", "Surprise", "Neutral"]


class RemoteEmotionChecker:
    """Face emotion recognition via WebSocket to dlbackend."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        threshold: float = config.EMOTION_CONFIDENCE_THRESHOLD,
    ):
        self._base_url: str = base_url
        self._api_key: str = api_key
        self._threshold: float = threshold
        self._ws_session: ClientConnection | None = None

        self._prepare_session()

    def _prepare_session(self):
        if self._ws_session is not None:
            logger.info("[%s] has been started", self.__class__.__name__)
            return

        try:
            self._ws_session = connect(
                self._base_url,
                additional_headers={"X-API-Key": self._api_key},
            )
            self._ws_session.send(
                json.dumps(
                    {
                        "type": "config",
                        "task": "emotion",
                        "threshold": self._threshold,
                    }
                )
            )
        except Exception:
            logger.exception("Failed to connect to remote emotion recognition backend")

    def _img2b64(self, frame: npt.NDArray[np.uint8]) -> str:
        _, buf = cv2.imencode(".jpg", frame)
        return base64.b64encode(buf.tobytes()).decode()

    def update(
        self, frame: npt.NDArray[np.uint8]
    ) -> list[tuple[str, float]] | None:
        """Send a frame for emotion inference.

        Returns list of (emotion_label, confidence) for each detected face,
        sorted by confidence descending. Returns None if unavailable,
        [] if no faces or no emotion above threshold.
        """
        # Auto-reconnect if session was lost
        if self._ws_session is None:
            self._prepare_session()
            if self._ws_session is not None:
                logger.info("[%s] reconnected to %s", self.__class__.__name__, self._base_url)

        if self._ws_session is not None:
            try:
                self._ws_session.send(
                    json.dumps(
                        {"type": "frame", "task": "emotion", "frame_b64": self._img2b64(frame)}
                    )
                )
                resp = json.loads(self._ws_session.recv())
                detections = resp.get("detections", [])
                results = [
                    (d["emotion"], d["confidence"])
                    for d in detections
                    if d["confidence"] >= self._threshold
                ]
                return sorted(results, key=lambda x: x[1], reverse=True)
            except ConnectionClosedError:
                logger.warning("[%s] connection lost, will retry on next tick", self.__class__.__name__)
                self._ws_session = None

        return None


class EmotionPerception(Perception):
    """Detects facial emotions via dlbackend (YuNet + VGG-FER).

    Similar to MotionPerception: sends frames to dlbackend via WebSocket,
    buffers results, and flushes aggregated emotion events periodically.
    """

    def __init__(
        self,
        send_event: Callable,
        on_motion: Callable,
        capture_stable_frame: Callable,
        presence_service,
        face_recognizer=None,
        base_url: str = config.DL_EMOTION_BACKEND_URL,
        api_key: str = config.DL_API_KEY,
    ):
        super().__init__(send_event)
        self._on_motion = on_motion
        self._capture_stable_frame = capture_stable_frame
        self._presence = presence_service
        self._face_recognizer = face_recognizer
        self._last_detection_time: Optional[float] = None
        self._last_emotion: Optional[str] = None

        self._checker = RemoteEmotionChecker(
            base_url=base_url,
            api_key=api_key,
            threshold=config.EMOTION_CONFIDENCE_THRESHOLD,
        )

        # Buffer — flushed every EMOTION_FLUSH_S
        self._flush_interval: float = config.EMOTION_FLUSH_S
        self._emotion_buffer: list[str] = []
        self._last_flush_ts: float = 0.0

        # Dedup: same (user, dominant_emotion) within window → drop
        self._last_sent_key: tuple[str, str] | None = None
        self._last_sent_ts: float = 0.0
        self._dedup_window_s: float = 300.0  # 5 min

    @override
    def _check_impl(self, frame: npt.NDArray[np.uint8]) -> None:
        if frame is None:
            return

        try:
            results = self._checker.update(frame)
        except Exception:
            logger.exception("[activity.emotion] inference error")
            return

        if results:
            self._last_detection_time = time.time()
            self._on_motion()

            top_emotion, top_conf = results[0]
            self._last_emotion = top_emotion
            self._emotion_buffer.append(top_emotion)
            logger.debug("[activity.emotion] detected: %s (%.2f)", top_emotion, top_conf)

        self._flush_buffer()

    def _flush_buffer(self) -> None:
        if not self._emotion_buffer:
            return

        cur_ts = time.time()
        if (cur_ts - self._last_flush_ts) < self._flush_interval:
            return

        emotions = list(self._emotion_buffer)
        self._emotion_buffer.clear()
        self._last_flush_ts = cur_ts

        if emotions:
            logger.info("[activity.emotion] raw detections in window: %s", emotions)

        # Find dominant emotion (most frequent in buffer)
        from collections import Counter

        counts = Counter(emotions)
        dominant_emotion, count = counts.most_common(1)[0]

        # Skip Neutral — not actionable
        if dominant_emotion == "Neutral":
            return

        from ..presence_service import PresenceState

        if self._presence.state != PresenceState.PRESENT:
            logger.info(
                "[activity.emotion] skipping event — no presence (presence=%s)",
                self._presence.state,
            )
            return

        message = f"Emotion detected: {dominant_emotion}."

        # Dedup
        current_user = ""
        if self._face_recognizer is not None:
            try:
                current_user = self._face_recognizer.current_user() or ""
            except Exception:
                logger.exception("[activity.emotion] face_recognizer.current_user() failed")
        key = (current_user, dominant_emotion)
        if (
            self._last_sent_key == key
            and (cur_ts - self._last_sent_ts) < self._dedup_window_s
        ):
            logger.info(
                "[activity.emotion] dedup drop: %s (same as last send %.1fs ago)",
                message,
                cur_ts - self._last_sent_ts,
            )
            return
        self._last_sent_key = key
        self._last_sent_ts = cur_ts

        logger.info("[activity.emotion] flushing: %s", message)
        self._send_event("emotion.detected", message)

    def to_dict(self) -> dict:
        seconds_since = (
            int(time.time() - self._last_detection_time)
            if self._last_detection_time is not None
            else None
        )
        return {
            "type": "emotion",
            "connected": self._checker._ws_session is not None,
            "last_emotion": self._last_emotion,
            "buffered_emotions": len(self._emotion_buffer),
            "emotion_detected": self._last_detection_time is not None,
            "seconds_since_detection": seconds_since,
        }
