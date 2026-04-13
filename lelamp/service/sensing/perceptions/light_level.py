import logging
import time
from typing import Callable, Optional

import lelamp.config as config
import numpy as np

from .base import Perception

logger = logging.getLogger(__name__)


class LightLevelPerception(Perception):
    """Detects significant ambient light changes via mean frame brightness."""

    def __init__(self, cv2, np_module, send_event: Callable):
        super().__init__(send_event)
        self._cv2 = cv2
        self._np = np_module
        self._last_level: Optional[float] = None
        self._last_check: float = 0.0

    def _check_impl(self, frame: np.ndarray) -> None:
        if frame is None:
            return
        now = time.time()
        if now - self._last_check < config.LIGHT_LEVEL_INTERVAL_S:
            return
        self._last_check = now

        np = self._np
        cv2 = self._cv2

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        brightness = float(np.mean(gray))

        prev = self._last_level
        self._last_level = brightness

        if prev is not None:
            change = brightness - prev
            if abs(change) >= config.LIGHT_CHANGE_THRESHOLD:
                if change < 0:
                    msg = f"Ambient light decreased significantly (level: {brightness:.0f}/255, change: {change:.0f})"
                else:
                    msg = f"Ambient light increased significantly (level: {brightness:.0f}/255, change: {change:+.0f})"
                self._send_event(
                    "light.level", msg, cooldown=config.LIGHT_LEVEL_INTERVAL_S
                )

    def to_dict(self) -> dict:
        return {
            "type": "light_level",
            "level": round(self._last_level, 1) if self._last_level is not None else None,
            "seconds_since_check": int(time.time() - self._last_check) if self._last_check else None,
        }
