import logging
import time
from enum import Enum
from typing import Callable, Optional, cast, override

import lelamp.config as config
import numpy as np
import numpy.typing as npt

from .base import Perception

logger = logging.getLogger(__name__)


class MoveEnum(Enum):
    BACKGROUND = "background"  # whole scene shifting — camera shake or very close object
    FOREGROUND = "foreground"  # localized movement — person walking, object moving
    NONE = "none"


class MotionChecker:
    """Optical flow-based motion classifier using Farneback dense flow."""

    def __init__(
        self,
        cv2,
        pixel_threshold: float = config.MOTION_PIXEL_THRESHOLD,
        moving_pixel_ratio: float = config.MOTION_BG_RATIO,
        move_threshold: float = config.MOTION_FLOW_THRESHOLD,
    ):
        self._cv2 = cv2
        self._last_frame: npt.NDArray[np.uint8] | None = None
        self._flow: npt.NDArray[np.float32] | None = None
        self._pixel_threshold = pixel_threshold
        self._moving_pixel_ratio = moving_pixel_ratio
        self._move_threshold = move_threshold

    def _classify_move(self, flow: npt.NDArray[np.float32]) -> MoveEnum:
        H, W = flow.shape[:2]
        flow_mag = np.linalg.norm(flow, axis=-1)
        mask = flow_mag > self._pixel_threshold

        if mask.sum() == 0:
            return MoveEnum.NONE

        if mask.sum() / (H * W) > self._moving_pixel_ratio:
            return MoveEnum.BACKGROUND

        mean_flow = flow_mag[mask].mean()
        if mean_flow > self._move_threshold:
            return MoveEnum.FOREGROUND

        return MoveEnum.NONE

    def update(self, rgb_frame: npt.NDArray[np.uint8]) -> MoveEnum:
        cv2 = self._cv2
        H, W = rgb_frame.shape[:2]
        frame = cv2.cvtColor(rgb_frame, cv2.COLOR_BGR2GRAY)
        frame = cv2.resize(frame, (320, 180))
        frame = cast(npt.NDArray[np.uint8], frame)

        if self._last_frame is None:
            self._last_frame = frame.copy()
            return MoveEnum.NONE

        flow = np.zeros_like(frame)
        flow = np.repeat(np.expand_dims(flow, axis=-1), repeats=2, axis=-1)
        flow = cv2.calcOpticalFlowFarneback(
            self._last_frame,
            frame,
            flow,
            pyr_scale=0.5,
            levels=3,
            winsize=15,
            iterations=3,
            poly_n=5,
            poly_sigma=1.2,
            flags=0,
        )
        flow = cv2.resize(flow, (W, H))
        flow = cv2.GaussianBlur(flow, (21, 21), -1)
        flow = cast(npt.NDArray[np.float32], flow)

        self._flow = flow
        self._last_frame = frame

        return self._classify_move(flow)

    @property
    def flow(self) -> npt.NDArray[np.float32] | None:
        return self._flow


class MotionPerception(Perception):
    """Detects foreground motion via optical flow (Farneback). Ignores background/camera shake."""

    def __init__(
        self,
        cv2,
        send_event: Callable,
        on_motion: Callable,
        capture_stable_frame: Callable,
        presence_service,
        motion_update_ts: float = config.MOTION_EVENT_COOLDOWN_S,
    ):
        super().__init__(send_event)
        self._on_motion = on_motion
        self._capture_stable_frame = capture_stable_frame
        self._presence = presence_service
        self._motion_update_ts: float = motion_update_ts
        self._last_motion_time: Optional[float] = None
        self._last_motion_event_ts: float = 0.0
        self._checker = MotionChecker(cv2)

    @override
    def check(self, frame: npt.NDArray[np.uint8]) -> None:
        if not config.MOTION_ENABLED or frame is None:
            return

        result = self._checker.update(frame)

        if result != MoveEnum.FOREGROUND:
            return

        cur_ts = time.time()
        self._last_motion_time = cur_ts
        self._on_motion()

        if (cur_ts - self._last_motion_event_ts) < self._motion_update_ts:
            return
        self._last_motion_event_ts = cur_ts

        stable = self._capture_stable_frame()
        image = stable if stable is not None else frame

        from ..presence_service import PresenceState

        if self._presence.state == PresenceState.PRESENT:
            logger.info("Motion: activity analysis while PRESENT")
            self._send_event(
                "motion.activity",
                "Movement detected while user is present. "
                "Look at the attached image — describe what the user appears to be doing "
                "(e.g. working, stretching, eating, talking, fidgeting, getting up). "
                "If nothing noteworthy, reply NO_REPLY.",
                image=image,
            )
        else:
            self._send_event(
                "motion",
                "Large movement detected in camera view — someone may have entered or left the room",
                image=image,
            )

    def to_dict(self) -> dict:
        seconds_since = (
            int(time.time() - self._last_motion_time)
            if self._last_motion_time is not None
            else None
        )
        return {
            "type": "motion",
            "has_baseline": self._checker._last_frame is not None,
            "motion_detected": self._last_motion_time is not None,
            "seconds_since_motion": seconds_since,
        }
