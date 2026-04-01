import logging
import time
from typing import Callable, Optional

import lelamp.config as config
import numpy as np

from .base import Perception

logger = logging.getLogger(__name__)


class MotionPerception(Perception):
    """Detects motion via frame differencing (grayscale absdiff + contour area)."""

    def __init__(
        self,
        cv2,
        send_event: Callable,
        on_motion: Callable,
        capture_stable_frame: Callable,
        motion_update_ts: float = 180,
    ):
        super().__init__(send_event)
        self._cv2 = cv2
        self._on_motion = on_motion
        self._capture_stable_frame = capture_stable_frame
        self._last_frame: Optional[np.ndarray] = None
        self._last_motion_time: Optional[float] = None
        self._motion_update_ts: float = motion_update_ts
        self._last_motion_event_ts: dict[str, float] = {}

    def check(self, frame: np.ndarray) -> None:
        if frame is None:
            return
        cv2 = self._cv2
        moved = False
        biggest_ratio = 0.0
        change_ratio = 0.0
        total_ratio = 0.0

        if self._last_frame is not None:
            total_pixels = int(frame.shape[0] * frame.shape[1])
            prev_gray = cv2.GaussianBlur(
                cv2.cvtColor(self._last_frame, cv2.COLOR_BGR2GRAY), (21, 21), 0
            )
            cur_gray = cv2.GaussianBlur(
                cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (21, 21), 0
            )

            delta = cv2.absdiff(prev_gray, cur_gray)
            thresh = cv2.threshold(
                delta, config.MOTION_THRESHOLD, 255, cv2.THRESH_BINARY
            )[1]
            contours, _ = cv2.findContours(
                thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )

            if len(contours):
                areas = np.array([cv2.contourArea(c) for c in contours])
                k = int(np.ceil(len(areas) * config.MOTION_BIGGEST_CONTOURS_RATIO))
                biggest_contours = np.argpartition(areas, -k)[-k:]
                logger.debug("biggest contour areas: %s", areas[biggest_contours])
                biggest_ratio = areas[biggest_contours].sum() / areas.sum()
                change_ratio = areas[biggest_contours].sum() / total_pixels
                total_ratio = areas.sum() / total_pixels

            if (
                biggest_ratio >= config.MOTION_MIN_BIGGEST_COUNTOURS_TO_CONTOURS
                and change_ratio >= config.MOTION_MIN_BIGGEST_COUNTOURS_TO_TOTAL
            ):
                moved = True

        self._last_frame = frame

        if moved:
            cur_ts = time.time()
            self._last_motion_time = cur_ts
            self._on_motion()

            if total_ratio >= config.MOTION_LARGE_TOTAL_RATIO:
                msg = "Large movement detected in camera view — someone may have entered or left the room"
                motion_type = "large"
            else:
                msg = "Small movement detected in camera view"
                motion_type = "small"

            last_motion_event_ts = self._last_motion_event_ts.get(motion_type, None)
            if (
                last_motion_event_ts is None
                or (cur_ts - last_motion_event_ts) > self._motion_update_ts
            ):
                self._last_motion_event_ts[motion_type] = cur_ts

                image = None
                if motion_type == "large":
                    stable = self._capture_stable_frame()
                    image = stable if stable is not None else frame

                # TODO: re-enable small motion if agent gains intent filtering for low-signal events
                # self._send_event("motion", msg, image=image)
                if motion_type == "large":
                    self._send_event("motion", msg, image=image)

    def to_dict(self) -> dict:
        seconds_since = (
            int(time.time() - self._last_motion_time)
            if self._last_motion_time is not None
            else None
        )
        return {
            "type": "motion",
            "has_baseline": self._last_frame is not None,
            "motion_detected": self._last_motion_time is not None,
            "seconds_since_motion": seconds_since,
        }
