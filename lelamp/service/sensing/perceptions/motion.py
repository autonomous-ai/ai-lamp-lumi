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

# Map raw Kinetics action labels to high-level activity groups.
# Lumi receives only the group name, not the raw label.
ACTIVITY_GROUP: dict[str, str] = {
    # drink — reset hydration timer
    "drinking": "drink",
    "drinking beer": "drink",
    "drinking shots": "drink",
    "tasting beer": "drink",
    "opening bottle": "drink",
    "making tea": "drink",
    # break — reset break timer (eating, stretching, movement)
    "tasting food": "break",
    "stretching arm": "break",
    "stretching leg": "break",
    "dining": "break",
    "eating burger": "break",
    "eating cake": "break",
    "eating carrots": "break",
    "eating chips": "break",
    "eating doughnuts": "break",
    "eating hotdog": "break",
    "eating ice cream": "break",
    "eating spaghetti": "break",
    "eating watermelon": "break",
    "applauding": "break",
    "clapping": "break",
    "celebrating": "break",
    "sneezing": "break",
    "sniffing": "break",
    "hugging": "break",
    "kissing": "break",
    "headbanging": "break",
    "sticking tongue out": "break",
    # sedentary — create wellbeing/music crons if missing
    "using computer": "sedentary",
    "writing": "sedentary",
    "texting": "sedentary",
    "reading book": "sedentary",
    "reading newspaper": "sedentary",
    "drawing": "sedentary",
    "playing controller": "sedentary",
    # emotional — always speak, log mood
    "laughing": "emotional",
    "crying": "emotional",
    "yawning": "emotional",
    "singing": "emotional",
}


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

    def update(self, frame: npt.NDArray[np.uint8]) -> list[str] | None:
        """Send a frame for X3D inference and return all detected action names.

        Returns every detected whitelist action (sorted by confidence desc),
        or None if the connection is unavailable. Returns [] if nothing
        passes the backend threshold for this frame.
        """

        # Auto-reconnect if session was lost
        if self._ws_session is None:
            self._prepare_session()
            if self._ws_session is not None:
                logger.info("[%s] reconnected to %s", self.__class__.__name__, self._base_url)

        if self._ws_session is not None:
            try:
                self._ws_session.send(
                    json.dumps({"type": "frame", "frame_b64": self._img2b64(frame)})
                )
                resp = json.loads(self._ws_session.recv())
                detected_classes = sorted(
                    resp.get("detected_classes", []), key=lambda x: x[1], reverse=True
                )
                return [name for name, _score in detected_classes]
            except ConnectionClosedError:
                logger.warning("[%s] connection lost, will retry on next tick", self.__class__.__name__)
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
        base_url: str = config.DL_MOTION_BACKEND_URL,
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

        # Dedup state for outbound motion.activity events.
        # Key = (current_user, frozenset(activity_groups)).
        # Same key within MOTION_DEDUP_WINDOW_S = drop (saves Lumi tokens). User
        # change flips the key immediately; different strangers collapse to
        # "unknown" so they don't break dedup on their own.
        self._last_sent_key: tuple[str, frozenset[str]] | None = None
        self._last_sent_ts: float = 0.0
        self._dedup_window_s: float = 300.0  # 5 min

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
            actions = self._checker.update(frame)
        except Exception:
            logger.exception("[motion] X3D inference error")
            return

        if actions:
            self._last_motion_time = time.time()
            self._on_motion()

            stable = self._capture_stable_frame()
            image = stable if stable is not None else frame
            self._snapshot_buffer.append(image)
            self._actions_buffer.extend(actions)

        self._flush_buffer()

    def _flush_buffer(self) -> None:
        if not self._snapshot_buffer:
            return

        cur_ts = time.time()
        if (cur_ts - self._last_flush_ts) < self._flush_interval:
            return

        actions = list(self._actions_buffer)
        self._snapshot_buffer.clear()
        self._actions_buffer.clear()
        self._last_flush_ts = cur_ts

        # Log raw X3D detections in this flush window — useful for tuning
        # the whitelist / ACTIVITY_GROUP mapping and for diagnosing why a
        # particular flush did/didn't produce an event.
        if actions:
            logger.info("[motion] raw X3D actions in window: %s", actions)

        activity_groups: set[str] = set()

        for a in reversed(actions):
            group = ACTIVITY_GROUP.get(a)
            if group is None:
                logger.warning("[motion] unmapped action '%s', skipping", a)
                continue
            if group == "emotional":
                # Emotional actions (laughing/crying/yawning/singing) are
                # intentionally NOT emitted via motion.activity. A dedicated
                # motion.emotional event will be added later to carry them;
                # until then emotional X3D detections are silently ignored
                # here so motion.activity stays purely about physical groups.
                continue
            activity_groups.add(group)

        if not activity_groups:
            return

        from ..presence_service import PresenceState

        if self._presence.state != PresenceState.PRESENT:
            logger.info(
                "[motion] skipping event — no presence (presence=%s)",
                self._presence.state,
            )
            return

        message = (
            f"Activity detected: {', '.join(sorted(activity_groups))}. "
            "If nothing noteworthy, reply NO_REPLY."
        )

        # Dedup: drop if the outbound state (user + activity groups) hasn't
        # changed since the last send AND we're still within the dedup window.
        # A user change or an activity group change flips the key — those
        # always pass through. After 5 min the same key passes through anyway
        # so Lumi agent wakes up and reruns the threshold check.
        current_user = ""
        if self._face_recognizer is not None:
            try:
                current_user = self._face_recognizer.current_user() or ""
            except Exception:
                logger.exception("[motion] face_recognizer.current_user() failed")
        key = (
            current_user,
            frozenset(activity_groups),
        )
        if (
            self._last_sent_key == key
            and (cur_ts - self._last_sent_ts) < self._dedup_window_s
        ):
            logger.info(
                "[motion] dedup drop: %s (same as last send %.1fs ago)",
                message,
                cur_ts - self._last_sent_ts,
            )
            return
        self._last_sent_key = key
        self._last_sent_ts = cur_ts

        logger.info("[motion] flushing: %s", message)

        self._send_event("motion.activity", message)

    def reset_dedup(self) -> None:
        """Clear the outbound dedup state so the next motion.activity will
        send regardless of whether the state (user + activity groups) matches
        the previous send. Called by SensingService on presence.enter so the
        agent sees a fresh sedentary event right after a new session starts,
        instead of waiting out the 5-minute wake-up window.
        """
        if self._last_sent_key is not None:
            logger.info("[motion] dedup reset (new presence session)")
            self._last_sent_key = None
            self._last_sent_ts = 0.0

    def to_dict(self) -> dict:
        seconds_since = (
            int(time.time() - self._last_motion_time)
            if self._last_motion_time is not None
            else None
        )
        return {
            "type": "motion",
            "connected": self._checker._ws_session is not None,
            "last_action": self._checker.last_action,
            "buffered_snapshots": len(self._snapshot_buffer),
            "motion_detected": self._last_motion_time is not None,
            "seconds_since_motion": seconds_since,
        }
