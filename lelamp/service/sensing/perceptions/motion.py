import base64
import json
import logging
import time
from enum import Enum
from pathlib import Path
from typing import Callable, Optional, override

import cv2
import lelamp.config as config
import numpy as np
import numpy.typing as npt
from websockets import ConnectionClosedError
from websockets.sync.client import ClientConnection, connect

from .base import Perception

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

RESOURCES_DIR = Path(__file__).parent / "resources"


class MoveEnum(Enum):
    BACKGROUND = (
        "background"  # whole scene shifting — camera shake or very close object
    )
    FOREGROUND = "foreground"  # localized movement — person walking, object moving
    NONE = "none"


class RemoteMotionChecker:
    """Video action recognition-based motion detector."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        whitelist: list[str] | None = None,
        threshold: float = config.MOTION_X3D_CONFIDENCE_THRESHOLD,
    ):
        self._base_url: str = base_url
        self._api_key: str = api_key
        self._whitelist: list[str] | None = whitelist
        self._threshold: float = threshold
        self._ws_session: ClientConnection | None = None

        self._prepare_session()

        self._last_action: str | None = None

    def _prepare_session(self):
        if self._ws_session is not None:
            logger.info("[%s] has been started", self.__class__.__name__)
            return

        try:
            print(self._base_url, self._api_key)
            self._ws_session = connect(
                self._base_url, additional_headers={"X-API-Key": self._api_key}
            )
            self._ws_session.send(
                json.dumps(
                    {
                        "type": "config",
                        "whitelist": self._whitelist,
                        "threshold": self._threshold,
                    }
                )
            )
        except Exception:
            logger.exception("Failed to connect to remote motion recognition backend")

    def _img2b64(self, frame: npt.NDArray[np.uint8]):
        _, buf = cv2.imencode(".jpg", frame)
        return base64.b64encode(buf.tobytes()).decode()

    def update(self, frame: npt.NDArray[np.uint8]) -> str | None:
        """Buffer a frame and run X3D inference when the interval elapses.

        Returns the predicted action name, or None if not enough time has passed.
        """

        if self._ws_session is not None:
            try:
                self._ws_session.send(
                    json.dumps({"type": "frame", "frame_b64": self._img2b64(frame)})
                )
                resp = json.loads(self._ws_session.recv())
                detected_classes = sorted(
                    resp.get("detected_classes", []), key=lambda x: x[1], reverse=True
                )
                try:
                    return detected_classes[0][0]
                except IndexError:
                    return None
            except ConnectionClosedError:
                logger.warning("[%s] connection closed", self.__class__.__name__)
                self._ws_session = None

        return None

    @property
    def last_action(self) -> str | None:
        return self._last_action


class MotionPerception(Perception):
    """Detects motion via X3D video action recognition (400 Kinect action classes).

    Snapshots are buffered and flushed every MOTION_FLUSH_S seconds,
    sending all accumulated snapshots together in one event.
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
        self._last_motion_time: Optional[float] = None
        whitelist = self._load_whitelist()
        self._checker = RemoteMotionChecker(
            base_url=base_url,
            api_key=api_key,
            whitelist=whitelist,
            threshold=config.MOTION_X3D_CONFIDENCE_THRESHOLD,
        )

        # Snapshot buffer — flushed every MOTION_FLUSH_S
        self._flush_interval: float = config.MOTION_FLUSH_S
        self._snapshot_buffer: list[npt.NDArray[np.uint8]] = []
        self._actions_buffer: list[str] = []
        self._last_flush_ts: float = 0.0

    @staticmethod
    def _load_whitelist() -> list[str] | None:
        whitelist_path = RESOURCES_DIR / "white_list.txt"
        if not whitelist_path.exists():
            logger.warning("[motion] whitelist file not found: %s", whitelist_path)
            return None
        lines = whitelist_path.read_text().strip().splitlines()
        whitelist = [line.strip() for line in lines if line.strip()]
        logger.info("[motion] loaded %d whitelist entries", len(whitelist))
        return whitelist

    @override
    def _check_impl(self, frame: npt.NDArray[np.uint8]) -> None:
        if frame is None:
            return

        try:
            action = self._checker.update(frame)
        except Exception:
            logger.exception("[motion] X3D inference error")
            return

        if action is not None:
            self._last_motion_time = time.time()
            self._on_motion()

            stable = self._capture_stable_frame()
            image = stable if stable is not None else frame
            self._snapshot_buffer.append(image)
            self._actions_buffer.append(action)

        self._flush_buffer()

    def _flush_buffer(self) -> None:
        if not self._snapshot_buffer:
            return

        cur_ts = time.time()
        if (cur_ts - self._last_flush_ts) < self._flush_interval:
            return

        snapshots = list(self._snapshot_buffer)
        actions = list(self._actions_buffer)
        self._snapshot_buffer.clear()
        self._actions_buffer.clear()
        self._last_flush_ts = cur_ts

        unique_actions = sorted(set(actions))
        actions_str = ", ".join(f"'{a}'" for a in unique_actions)
        logger.info(
            "[motion] flushing %d snapshot(s), actions: %s", len(snapshots), actions_str
        )

        from ..presence_service import PresenceState

        has_friend = (
            self._face_recognizer is not None
            and self._face_recognizer.has_friend_present()
        )

        if self._presence.state == PresenceState.PRESENT and has_friend:
            self._send_event(
                "motion.activity",
                f"Actions detected via video recognition: {actions_str}. "
                "If nothing noteworthy, reply NO_REPLY.",
            )
        else:
            self._send_event(
                "motion",
                f"Actions detected via video recognition: {actions_str} — someone may have entered or left the room",
                images=snapshots,
            )

    def to_dict(self) -> dict:
        seconds_since = (
            int(time.time() - self._last_motion_time)
            if self._last_motion_time is not None
            else None
        )
        return {
            "type": "motion",
            "last_action": self._checker.last_action,
            "buffered_snapshots": len(self._snapshot_buffer),
            "motion_detected": self._last_motion_time is not None,
            "seconds_since_motion": seconds_since,
        }
