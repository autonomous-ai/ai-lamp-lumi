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

        # Build detailed message for the agent
        left_score: int = ergo.get("left", {}).get("score", 0)
        right_score: int = ergo.get("right", {}).get("score", 0)
        message: str = (
            f"Ergonomic risk detected: RULA score {score} ({risk_name} risk). "
            f"Left side: {left_score}, Right side: {right_score}. "
            f"(camera-based posture assessment; treat as a gentle nudge, not a diagnosis.)"
        )

        logger.info("[pose.ergo] %s", message)
        self._send_event("pose.ergo_risk", message, "pose", None, None)

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
