import base64
import json
import logging
import os
import time
from enum import Enum
from pathlib import Path
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

RESOURCES_DIR = Path(__file__).parent / "resources"

# Map raw Kinetics action labels to high-level activity groups.
# Lumi receives the raw labels — the agent infers the group. The mapping here
# is kept only to filter out emotional actions (handled by a separate channel).
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
        threshold: float = config.MOTION_CONFIDENCE_THRESHOLD,
    ):
        self._base_url: str = base_url
        self._api_key: str = api_key
        self._whitelist: list[str] | None = whitelist
        self._threshold: float = threshold
        self._ws_session: ClientConnection | None = None

        self._prepare_session()

        self._last_action: str | None = None
        self._last_heartbeat_ts: float = 0.0
        self._heartbeat_interval: float = config.DL_HEARTBEAT_INTERVAL_S

    def _prepare_session(self):
        if self._ws_session is not None:
            logger.info("[%s] has been started", self.__class__.__name__)
            return

        try:
            self._ws_session = connect(
                self._base_url.replace("http", "ws").replace("https", "wss"), additional_headers={"X-API-Key": self._api_key}
            )
            self._ws_session.send(
                json.dumps(
                    {
                        "type": "config",
                        "task": "action",
                        "whitelist": self._whitelist,
                        "threshold": self._threshold,
                    }
                )
            )
            # Consume the config_updated response so it doesn't pollute frame responses
            self._ws_session.recv()
        except Exception:
            logger.exception("Failed to connect to remote motion recognition backend")
            self._ws_session = None

    def _img2b64(self, frame: npt.NDArray[np.uint8]):
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
            self._ws_session.send(json.dumps({"type": "heartbeat", "task": "action"}))
            resp = json.loads(self._ws_session.recv())
            if resp.get("status") == "ok":
                self._last_heartbeat_ts = now
                logger.debug("[motion] heartbeat ok")
            else:
                logger.warning("[motion] heartbeat unexpected response: %s", resp)
        except ConnectionClosedError:
            logger.warning("[motion] heartbeat failed — connection lost")
            self._ws_session = None

    def update(self, frame: npt.NDArray[np.uint8]) -> list[dict] | None:
        """Send a frame for action recognition inference.

        Returns list of dicts with keys: class_name, conf.
        Sorted by confidence descending. Returns None if unavailable,
        [] if nothing passes the backend threshold.
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
                    json.dumps({"type": "frame", "task": "action", "frame_b64": self._img2b64(frame)})
                )
                resp = json.loads(self._ws_session.recv())
                detected_classes = sorted(
                    resp.get("detected_classes", []),
                    key=lambda x: x["conf"],
                    reverse=True,
                )
                return detected_classes
            except ConnectionClosedError:
                logger.warning(
                    "[%s] connection lost, will retry on next tick",
                    self.__class__.__name__,
                )
                self._ws_session = None

        return None

    @property
    def last_action(self) -> str | None:
        return self._last_action


class MotionPerception(Perception):
    """Detects motion via remote DL backend action recognition.

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
            threshold=config.MOTION_CONFIDENCE_THRESHOLD,
        )

        # Snapshot buffer — flushed every MOTION_FLUSH_S
        self._flush_interval: float = config.MOTION_FLUSH_S
        self._snapshot_buffer: list[npt.NDArray[np.uint8]] = []
        self._actions_buffer: list[str] = []
        self._snapshot_paths: list[str] = []
        self._last_flush_ts: float = 0.0

        # Dedup state for outbound motion.activity events.
        # Key = (current_user, frozenset(labels)) where `labels` matches what
        # actually goes into the message: bucket names for drink/break, raw
        # Kinetics labels for sedentary. So `eating burger → eating cake` is
        # the same key (both collapse to "break") and is dropped; `writing →
        # drawing` flips the key (sedentary stays raw) and passes through so
        # the agent sees the new activity. Same key within MOTION_DEDUP_WINDOW_S
        # = drop (saves Lumi tokens). User change flips the key immediately;
        # different strangers collapse to "unknown" so they don't break dedup
        # on their own.
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
            detections = self._checker.update(frame)
        except Exception:
            logger.exception("[motion] inference error")
            return

        if detections:
            self._last_motion_time = time.time()
            self._on_motion()

            stable = self._capture_stable_frame()
            image = stable if stable is not None else frame
            self._snapshot_buffer.append(image)
            self._actions_buffer.extend(d["class_name"] for d in detections)

            # Save annotated snapshot
            snapshot_path = self._save_annotated(image, detections)
            if snapshot_path:
                self._snapshot_paths.append(snapshot_path)

        self._flush_buffer()

    def _draw_annotations(
        self, frame: npt.NDArray[np.uint8], detections: list[dict]
    ) -> npt.NDArray[np.uint8]:
        """Draw detected action labels on a copy of the frame."""
        vis = frame.copy()
        y_offset = 30
        for det in detections:
            label = f"{det['class_name']} ({det['conf']:.2f})"
            cv2.putText(
                vis, label, (10, y_offset),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2,
            )
            y_offset += 30
        return vis

    def _save_annotated(
        self, frame: npt.NDArray[np.uint8], detections: list[dict]
    ) -> Optional[str]:
        """Draw annotations and save to snapshot dir. Rotates old files."""
        try:
            os.makedirs(config.MOTION_SNAPSHOT_DIR, exist_ok=True)

            annotated = self._draw_annotations(frame, detections)
            filename = f"motion_{int(time.time() * 1000)}.jpg"
            filepath = os.path.join(config.MOTION_SNAPSHOT_DIR, filename)
            _, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
            with open(filepath, "wb") as f:
                f.write(buf.tobytes())

            # Rotate: remove oldest files if over max count
            files = sorted(
                (
                    os.path.join(config.MOTION_SNAPSHOT_DIR, f)
                    for f in os.listdir(config.MOTION_SNAPSHOT_DIR)
                    if f.endswith(".jpg")
                ),
                key=os.path.getmtime,
            )
            while len(files) > config.MOTION_SNAPSHOT_MAX_COUNT:
                try:
                    os.remove(files.pop(0))
                except OSError:
                    pass

            return filepath
        except Exception as e:
            logger.debug("[motion] snapshot save failed: %s", e)
            return None

    def _flush_buffer(self) -> None:
        if not self._snapshot_buffer:
            return

        cur_ts = time.time()
        if (cur_ts - self._last_flush_ts) < self._flush_interval:
            return

        actions = list(self._actions_buffer)
        snapshot_paths = list(self._snapshot_paths)
        self._snapshot_buffer.clear()
        self._actions_buffer.clear()
        self._snapshot_paths.clear()
        self._last_flush_ts = cur_ts

        # Log raw detections in this flush window — useful for tuning
        # the whitelist / ACTIVITY_GROUP mapping and for diagnosing why a
        # particular flush did/didn't produce an event.
        if actions:
            logger.info("[motion] raw actions in window: %s", actions)

        # Hybrid output: drink/break collapse to bucket name, sedentary keeps
        # the raw Kinetics label. Bucket names are enough for hydration/break
        # timer resets — the agent doesn't need the specific food or drink.
        # Sedentary keeps the raw label so the agent can ground nudge phrasing
        # and music-genre choice in the concrete activity (writing / reading
        # book / playing controller / …).
        labels: set[str] = set()

        for a in reversed(actions):
            group = ACTIVITY_GROUP.get(a)
            if group is None:
                logger.warning("[motion] unmapped action '%s', skipping", a)
                continue
            if group == "emotional":
                # Emotional actions (laughing/crying/yawning/singing) are
                # intentionally NOT emitted via motion.activity. A dedicated
                # motion.emotional event will be added later to carry them;
                # until then emotional detections are silently ignored
                # here so motion.activity stays purely about physical actions.
                continue
            if group == "sedentary":
                labels.add(a)
            else:
                labels.add(group)

        if not labels:
            return

        from ..presence_service import PresenceState

        if self._presence.state != PresenceState.PRESENT:
            logger.info(
                "[motion] skipping event — no presence (presence=%s)",
                self._presence.state,
            )
            return

        message = f"Activity detected: {', '.join(sorted(labels))}."

        # Dedup: drop if the outbound state (user + outbound labels) hasn't
        # changed since the last send AND we're still within the dedup window.
        # A user change or a label-set change flips the key — those always
        # pass through. After 5 min the same key passes through anyway so
        # Lumi agent wakes up and reruns the threshold check.
        current_user = ""
        if self._face_recognizer is not None:
            try:
                current_user = self._face_recognizer.current_user() or ""
            except Exception:
                logger.exception("[motion] face_recognizer.current_user() failed")
        key = (
            current_user,
            frozenset(labels),
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

        # Attach latest snapshot path
        if snapshot_paths:
            message = f"{message}\n[snapshot: {snapshot_paths[-1]}]"

        logger.info("[motion] flushing: %s", message)

        self._send_event("motion.activity", message)

    def reset_dedup(self, new_user: str = "") -> None:
        """Clear the outbound dedup state only if the visible user actually
        changed. Called by SensingService on presence.enter — without this
        guard, every stranger flicker (stranger_79 → stranger_77, both
        collapsing to "unknown" via FaceRecognizer.current_user()) would wipe
        the key and bypass the 5-minute window, spamming motion.activity
        events on every presence.enter. Resetting only on an actual user
        transition (leo → unknown, unknown → chloe, chloe → leo) keeps the
        dedup window honest while still letting a new presence session see a
        fresh activity event immediately.
        """
        if self._last_sent_key is None:
            return
        last_user = self._last_sent_key[0]
        if last_user == new_user:
            logger.debug(
                "[motion] dedup reset skipped — same user %r",
                last_user,
            )
            return
        logger.info(
            "[motion] dedup reset (user %r → %r)",
            last_user, new_user,
        )
        self._last_sent_key = None
        self._last_sent_ts = 0.0

    def to_dict(self) -> dict:
        seconds_since = (
            int(time.time() - self._last_motion_time)
            if self._last_motion_time is not None
            else None
        )
        last_key = self._last_sent_key
        return {
            "type": "motion",
            "connected": self._checker._ws_session is not None,
            "last_raw_actions": sorted(last_key[1]) if last_key else [],
            "last_user": last_key[0] if last_key else None,
            "buffered_snapshots": len(self._snapshot_buffer),
            "motion_detected": self._last_motion_time is not None,
            "seconds_since_motion": seconds_since,
        }
