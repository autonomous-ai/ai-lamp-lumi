import base64
import json
import logging
import os
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

        self._last_heartbeat_ts: float = 0.0
        self._heartbeat_interval: float = config.DL_HEARTBEAT_INTERVAL_S

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
            # Consume the config_updated response so it doesn't pollute frame responses
            self._ws_session.recv()
        except Exception:
            logger.exception("Failed to connect to remote emotion recognition backend")
            self._ws_session = None

    def _img2b64(self, frame: npt.NDArray[np.uint8]) -> str:
        _, buf = cv2.imencode(".jpg", frame)
        return base64.b64encode(buf.tobytes()).decode()

    def _send_heartbeat(self) -> None:
        """Send a heartbeat if the interval has elapsed."""
        now = time.time()
        if now - self._last_heartbeat_ts < self._heartbeat_interval:
            return
        if self._ws_session is None:
            return
        try:
            self._ws_session.send(json.dumps({"type": "heartbeat", "task": "emotion"}))
            resp = json.loads(self._ws_session.recv())
            if resp.get("status") == "ok":
                self._last_heartbeat_ts = now
                logger.debug("[activity.emotion] heartbeat ok")
            else:
                logger.warning(
                    "[activity.emotion] heartbeat unexpected response: %s", resp
                )
        except ConnectionClosedError:
            logger.warning("[activity.emotion] heartbeat failed — connection lost")
            self._ws_session = None

    def update(self, frame: npt.NDArray[np.uint8]) -> list[dict] | None:
        """Send a frame for emotion inference.

        Returns list of dicts with keys: emotion, confidence, face_confidence, bbox.
        Sorted by confidence descending. Returns None if unavailable,
        [] if no faces or no emotion above threshold.
        """
        # Auto-reconnect if session was lost
        if self._ws_session is None:
            self._prepare_session()
            if self._ws_session is not None:
                logger.info(
                    "[%s] reconnected to %s", self.__class__.__name__, self._base_url
                )

        self._send_heartbeat()

        if self._ws_session is not None:
            try:
                self._ws_session.send(
                    json.dumps(
                        {
                            "type": "frame",
                            "task": "emotion",
                            "frame_b64": self._img2b64(frame),
                        }
                    )
                )
                resp = json.loads(self._ws_session.recv())
                detections = resp.get("detections", [])
                results = [
                    d for d in detections if d["confidence"] >= self._threshold
                ]
                return sorted(results, key=lambda x: x["confidence"], reverse=True)
            except ConnectionClosedError:
                logger.warning(
                    "[%s] connection lost, will retry on next tick",
                    self.__class__.__name__,
                )
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
        self._snapshot_paths: list[str] = []
        self._last_flush_ts: float = 0.0

        # Dedup: per-user cooldown + same-emotion suppression
        # - Same user within cooldown → skip (prevents FER fluctuation spam)
        # - Same user + same emotion within long window → skip (no repeat)
        self._last_sent_key: tuple[str, str] | None = None  # (user, emotion)
        self._last_sent_ts: float = 0.0
        self._cooldown_s: float = 60.0       # min gap between any emotion event for same user
        self._same_emotion_window_s: float = 300.0  # 5 min — same emotion suppression

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

            top = results[0]
            self._last_emotion = top["emotion"]
            self._emotion_buffer.append(top["emotion"])
            logger.debug(
                "[activity.emotion] detected: %s (%.2f)",
                top["emotion"],
                top["confidence"],
            )

            # Draw annotated frame and save snapshot
            snapshot_path = self._save_annotated(frame, results)
            if snapshot_path:
                self._snapshot_paths.append(snapshot_path)

        self._flush_buffer()

    def _draw_annotations(
        self, frame: npt.NDArray[np.uint8], detections: list[dict]
    ) -> npt.NDArray[np.uint8]:
        """Draw face bboxes and emotion labels on a copy of the frame."""
        vis = frame.copy()
        for det in detections:
            x, y, w, h = det["bbox"]
            emotion = det["emotion"]
            conf = det["confidence"]
            cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 255, 0), 2)
            label = f"{emotion} {conf:.2f}"
            cv2.putText(
                vis, label, (x, y - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2,
            )
        return vis

    def _save_annotated(
        self, frame: npt.NDArray[np.uint8], detections: list[dict]
    ) -> Optional[str]:
        """Draw annotations and save to snapshot dir. Rotates old files."""
        try:
            os.makedirs(config.EMOTION_SNAPSHOT_DIR, exist_ok=True)

            annotated = self._draw_annotations(frame, detections)
            filename = f"emotion_{int(time.time() * 1000)}.jpg"
            filepath = os.path.join(config.EMOTION_SNAPSHOT_DIR, filename)
            _, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
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
        if not self._emotion_buffer:
            return

        cur_ts = time.time()
        if (cur_ts - self._last_flush_ts) < self._flush_interval:
            return

        emotions = list(self._emotion_buffer)
        snapshot_paths = list(self._snapshot_paths)
        self._emotion_buffer.clear()
        self._snapshot_paths.clear()
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

        # Dedup — two layers:
        # 1) Per-user cooldown: any emotion for same user within 60s → skip
        # 2) Same emotion: same user + same emotion within 5 min → skip
        current_user = ""
        if self._face_recognizer is not None:
            try:
                current_user = self._face_recognizer.current_user() or ""
            except Exception:
                logger.exception("[activity.emotion] face_recognizer.current_user() failed")

        elapsed = cur_ts - self._last_sent_ts if self._last_sent_ts > 0 else float("inf")
        last_user = self._last_sent_key[0] if self._last_sent_key else ""
        last_emotion = self._last_sent_key[1] if self._last_sent_key else ""

        # Layer 1: cooldown per user
        if current_user == last_user and elapsed < self._cooldown_s:
            logger.debug(
                "[activity.emotion] cooldown skip: %s (%.0fs < %.0fs)",
                message, elapsed, self._cooldown_s,
            )
            return

        # Layer 2: same emotion suppression
        if current_user == last_user and dominant_emotion == last_emotion and elapsed < self._same_emotion_window_s:
            logger.info(
                "[activity.emotion] same emotion skip: %s (%.0fs ago)",
                message, elapsed,
            )
            return

        self._last_sent_key = (current_user, dominant_emotion)
        self._last_sent_ts = cur_ts

        # Attach latest snapshot path
        if snapshot_paths:
            message = f"{message}\n[snapshot: {snapshot_paths[-1]}]"

        logger.info("[activity.emotion] flushing: %s", message)
        self._send_event("emotion.detected", message)

    def to_dict(self) -> dict:
        seconds_since = (
            int(time.time() - self._last_detection_time)
            if self._last_detection_time is not None
            else None
        )
        last_sent = self._last_sent_key
        return {
            "type": "emotion",
            "connected": self._checker._ws_session is not None,
            "last_sent_emotion": last_sent[1] if last_sent else None,
            "last_sent_user": last_sent[0] if last_sent else None,
            "last_detected_emotion": self._last_emotion,
            "buffered_emotions": len(self._emotion_buffer),
            "emotion_detected": self._last_detection_time is not None,
            "seconds_since_detection": seconds_since,
        }
