"""Pose estimation + ergonomic assessment perception via dlbackend WS.

Follows the same pattern as MotionPerception (RemoteMotionChecker):
- Maintains a WS connection to dlbackend /api/dl/pose-estimation/ws
- Sends camera frames, receives pose_2d + optional pose_3d + optional ergo
- When ergo risk is above threshold, sends pose.ergo_risk events to Lumi
- Dedup by risk level with cooldown window
"""

import base64
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, override

import cv2
import numpy as np
import numpy.typing as npt
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect

import lelamp.config as config
from lelamp.service.sensing.perceptions.typing import SendEventCallable
from lelamp.service.sensing.perceptions.utils import PerceptionStateObservers
from lelamp.service.sensing.presence_service import PresenceState, PresenseService

from .base import Perception

logger: logging.Logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# ---------------------------------------------------------------------------
# COCO 17-joint skeleton for visualization
# ---------------------------------------------------------------------------

_COCO_SKELETON: list[tuple[int, int]] = [
    (15, 13), (13, 11), (16, 14), (14, 12),
    (11, 12), (5, 11), (6, 12), (5, 6),
    (5, 7), (6, 8), (7, 9), (8, 10),
    (1, 2), (0, 1), (0, 2), (1, 3), (2, 4), (3, 5), (4, 6),
]

# Bone colors: left side = cyan, right side = orange, center = green
_BONE_COLORS: list[tuple[int, int, int]] = [
    (255, 200, 0), (255, 200, 0),           # left leg
    (0, 100, 255), (0, 100, 255),           # right leg
    (0, 220, 0),                             # hip bridge
    (255, 200, 0), (0, 100, 255),           # hip to shoulder
    (0, 220, 0),                             # shoulder bridge
    (255, 200, 0), (0, 100, 255),           # shoulders to elbows
    (255, 200, 0), (0, 100, 255),           # elbows to wrists
    (0, 220, 0), (0, 220, 0), (0, 220, 0), # nose to eyes
    (255, 200, 0), (0, 100, 255),           # eyes to ears
    (255, 200, 0), (0, 100, 255),           # ears to shoulders
]

_RISK_COLORS: dict[int, tuple[int, int, int]] = {
    1: (0, 200, 0),     # negligible — green
    2: (0, 200, 200),   # low — yellow
    3: (0, 140, 255),   # medium — orange
    4: (0, 0, 255),     # high — red
}

_CONF_THRESHOLD: float = 0.3


def _draw_pose_2d(
    frame: cv2.typing.MatLike,
    pose_2d: dict[str, Any],
    ergo: dict[str, Any] | None = None,
) -> cv2.typing.MatLike:
    """Draw 2D skeleton and optional ergo score on frame. Returns a copy."""
    vis: npt.NDArray[np.uint8] = frame.copy()
    joints: list[list[float]] = pose_2d.get("joints", [])
    confs: list[float] = pose_2d.get("confs", [])

    if not joints:
        return vis

    kps: npt.NDArray[np.int32] = np.array(joints, dtype=np.int32)

    # Draw bones
    for idx, (u, v) in enumerate(_COCO_SKELETON):
        if max(u, v) >= len(kps):
            continue
        if confs[u] < _CONF_THRESHOLD or confs[v] < _CONF_THRESHOLD:
            continue
        color: tuple[int, int, int] = _BONE_COLORS[idx] if idx < len(_BONE_COLORS) else (0, 220, 0)
        cv2.line(vis, tuple(kps[u]), tuple(kps[v]), color, 2)

    # Draw joints
    for i, kp in enumerate(kps):
        if confs[i] < _CONF_THRESHOLD:
            continue
        cv2.circle(vis, tuple(kp), 4, (255, 255, 255), -1)

    # Draw ergo score label
    if ergo is not None:
        score: int = ergo.get("score", 0)
        risk_level: int = ergo.get("risk_level", 0)
        risk_names: dict[int, str] = {1: "negligible", 2: "low", 3: "medium", 4: "high"}
        label: str = f"RULA: {score} ({risk_names.get(risk_level, '?')})"
        color = _RISK_COLORS.get(risk_level, (200, 200, 200))
        cv2.putText(vis, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

    return vis


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PoseResult:
    pose_2d: dict[str, Any] | None = None
    pose_3d: dict[str, Any] | None = None
    ergo: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Remote WS client (same pattern as RemoteMotionChecker)
# ---------------------------------------------------------------------------


class RemotePoseEstimator:
    """WS client to dlbackend /api/dl/pose-estimation/ws."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
    ):
        self._base_url: str = base_url
        self._api_key: str = api_key
        self._ws_session: ClientConnection | None = None
        self._last_heartbeat_ts: float = 0.0
        self._heartbeat_interval: float = config.DL_HEARTBEAT_INTERVAL_S

        self._prepare_session()

    def _prepare_session(self) -> None:
        if self._ws_session is not None:
            return

        try:
            ws_url: str = self._base_url.replace("http", "ws").replace("https", "wss")
            logger.info("[%s] connecting to %s", self.__class__.__name__, ws_url)
            self._ws_session = connect(
                ws_url, additional_headers={"X-API-Key": self._api_key}
            )
        except Exception:
            logger.exception("[%s] failed to connect", self.__class__.__name__)
            self._ws_session = None

    def _img2b64(self, frame: cv2.typing.MatLike) -> str:
        _, buf = cv2.imencode(".jpg", frame)
        return base64.b64encode(buf.tobytes()).decode()

    def _send_heartbeat(self) -> None:
        now: float = time.time()
        if now - self._last_heartbeat_ts < self._heartbeat_interval:
            return
        self._last_heartbeat_ts = now

        if self._ws_session is None:
            return
        try:
            self._ws_session.send(json.dumps({"type": "heartbeat", "task": "pose"}))
            resp: dict = json.loads(self._ws_session.recv())
            if resp.get("status") == "ok":
                logger.debug("[pose] heartbeat ok")
            else:
                logger.warning("[pose] heartbeat unexpected: %s", resp)
        except ConnectionClosed:
            logger.warning("[pose] heartbeat failed — connection lost")
            self._ws_session = None

    def update(self, frame: cv2.typing.MatLike) -> PoseResult | None:
        """Send a frame and return the pose result, or None if unavailable."""
        if self._ws_session is None:
            self._prepare_session()
            if self._ws_session is not None:
                logger.info("[%s] reconnected", self.__class__.__name__)

        self._send_heartbeat()

        if self._ws_session is None:
            return None

        try:
            self._ws_session.send(
                json.dumps(
                    {
                        "type": "frame",
                        "task": "pose",
                        "frame_b64": self._img2b64(frame),
                    }
                )
            )
            resp: dict = json.loads(self._ws_session.recv())

            if "error" in resp:
                logger.warning("[pose] backend error: %s", resp["error"])
                return None

            return PoseResult(
                pose_2d=resp.get("pose_2d"),
                pose_3d=resp.get("pose_3d"),
                ergo=resp.get("ergo"),
            )
        except ConnectionClosed:
            logger.warning(
                "[%s] connection lost, will retry on next tick", self.__class__.__name__
            )
            self._ws_session = None
            return None

    def ready(self) -> bool:
        return self._ws_session is not None

    def close(self) -> None:
        if self._ws_session is not None:
            try:
                self._ws_session.close()
            except Exception:
                pass
            self._ws_session = None


# ---------------------------------------------------------------------------
# Perception processor
# ---------------------------------------------------------------------------


class PosePerception(Perception[cv2.typing.MatLike]):
    """Pose estimation + ergonomic assessment via dlbackend WS.

    On each frame tick:
    1. Sends frame to dlbackend pose-estimation WS
    2. If ergo result present and risk >= threshold, sends pose.ergo_risk event
    3. Dedup by risk level with cooldown to avoid spamming the agent
    """

    def __init__(
        self,
        perception_state: PerceptionStateObservers,
        send_event: SendEventCallable,
        presense_service: PresenseService | None,
        base_url: str = config.DL_POSE_BACKEND_URL,
        api_key: str = config.DL_API_KEY,
    ):
        super().__init__(perception_state, send_event)
        self._presence_service: PresenseService | None = presense_service
        self._estimator: RemotePoseEstimator = RemotePoseEstimator(
            base_url=base_url,
            api_key=api_key,
        )
        self._last_result: PoseResult | None = None
        self._last_ergo_event_ts: float = 0.0
        self._last_risk_level: int | None = None
        self._cooldown_s: float = config.POSE_ERGO_COOLDOWN_S
        self._risk_threshold: int = config.POSE_ERGO_HIGH_RISK_THRESHOLD

    @override
    def _check_impl(self, data: cv2.typing.MatLike) -> None:
        if data is None:
            return

        result: PoseResult | None = self._estimator.update(data)
        if result is None:
            return

        self._last_result = result

        # Send ergo event if risk is high enough
        ergo: dict[str, Any] | None = result.ergo
        if ergo is None:
            return

        score: int = ergo.get("score", 0)
        risk_level: int = ergo.get("risk_level", 0)

        if score < self._risk_threshold:
            return

        # Skip if no one is present
        if (
            self._presence_service is not None
            and self._presence_service.state != PresenceState.PRESENT
        ):
            return

        # Dedup: cooldown per risk level change
        now: float = time.time()
        if (
            self._last_risk_level == risk_level
            and (now - self._last_ergo_event_ts) < self._cooldown_s
        ):
            return

        self._last_ergo_event_ts = now
        self._last_risk_level = risk_level

        risk_names: dict[int, str] = {1: "negligible", 2: "low", 3: "medium", 4: "high"}
        risk_name: str = risk_names.get(risk_level, "unknown")

        # Build detailed message with all body-part scores for the agent
        left: dict[str, Any] = ergo.get("left", {})
        right: dict[str, Any] = ergo.get("right", {})
        left_body: dict[str, int] = left.get("body_scores", {})
        right_body: dict[str, int] = right.get("body_scores", {})
        left_skipped: list[str] = left.get("skipped_joints", [])
        right_skipped: list[str] = right.get("skipped_joints", [])

        def _side_detail(
            side_name: str,
            side_data: dict[str, Any],
            body: dict[str, int],
            skipped: list[str],
        ) -> str:
            parts: list[str] = [
                f"{side_name} (score={side_data.get('score', '?')}, ",
                f"risk={risk_names.get(side_data.get('risk_level', 0), '?')}): ",
                f"upper_arm={body.get('upper_arm', '?')} ({body.get('upper_arm_angle', '?')}°), ",
                f"lower_arm={body.get('lower_arm', '?')} ({body.get('lower_arm_angle', '?')}°), ",
                f"wrist={body.get('wrist', '?')}, ",
                f"neck={body.get('neck', '?')} ({body.get('neck_angle', '?')}°), ",
                f"trunk={body.get('trunk', '?')} ({body.get('trunk_angle', '?')}°)",
            ]
            if skipped:
                parts.append(f" [skipped: {', '.join(skipped)}]")
            return "".join(parts)

        left_detail: str = _side_detail("Left", left, left_body, left_skipped)
        right_detail: str = _side_detail("Right", right, right_body, right_skipped)

        message: str = (
            f"Ergonomic risk detected: RULA score {score} ({risk_name} risk). "
            f"{left_detail}. {right_detail}. "
            f"(camera-based posture assessment; treat as a gentle nudge, not a diagnosis.)"
        )

        # Draw annotated snapshot with 2D skeleton + ergo score
        snapshot: cv2.typing.MatLike = _draw_pose_2d(data, result.pose_2d, ergo)

        logger.info("[pose.ergo] %s", message)
        self._send_event("pose.ergo_risk", message, "pose", [snapshot], None)

    @override
    def cleanup(self) -> None:
        self._estimator.close()

    def to_dict(self) -> dict[str, Any]:
        ergo_score: int | None = None
        ergo_risk: int | None = None
        has_pose_2d: bool = False
        has_pose_3d: bool = False

        if self._last_result is not None:
            has_pose_2d = self._last_result.pose_2d is not None
            has_pose_3d = self._last_result.pose_3d is not None
            if self._last_result.ergo is not None:
                ergo_score = self._last_result.ergo.get("score")
                ergo_risk = self._last_result.ergo.get("risk_level")

        seconds_since_ergo: float | None = None
        if self._last_ergo_event_ts > 0:
            seconds_since_ergo = time.time() - self._last_ergo_event_ts

        return {
            "type": "pose",
            "connected": self._estimator.ready(),
            "has_pose_2d": has_pose_2d,
            "has_pose_3d": has_pose_3d,
            "ergo_score": ergo_score,
            "ergo_risk_level": ergo_risk,
            "seconds_since_ergo_event": int(seconds_since_ergo)
            if seconds_since_ergo is not None
            else None,
        }
