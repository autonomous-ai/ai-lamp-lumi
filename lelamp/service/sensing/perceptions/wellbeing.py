"""
Wellbeing Perception — periodic music mood suggestion via LLM vision.

Hydration and break reminders are now handled by the AI agent via OpenClaw
cron jobs (scheduled on presence.enter, cancelled on presence.leave).
Only the music timer remains here as it requires multi-session broadcast
coordination that the cron system doesn't support.
"""

import logging
import time
from typing import Callable, Optional, override

import numpy as np
import numpy.typing as npt

import lelamp.config as config
from .base import Perception

logger = logging.getLogger(__name__)


class WellbeingPerception(Perception):
    """Sends periodic music mood events with a camera snapshot while someone is present."""

    def __init__(
        self,
        cv2,
        send_event: Callable,
        presence_service,
        capture_stable_frame: Callable,
        music_interval_s: float = config.WELLBEING_MUSIC_S,
        # Keep old params for backwards compat (ignored)
        hydration_interval_s: float = 0,
        break_interval_s: float = 0,
    ):
        super().__init__(send_event)
        self._cv2 = cv2
        self._presence = presence_service
        self._capture_stable_frame = capture_stable_frame
        self._music_interval_s = music_interval_s

        self._present_since: Optional[float] = None
        self._last_music_time: float = 0.0
        self._was_present: bool = False

    @override
    def check(self, frame: npt.NDArray[np.uint8]) -> None:
        if frame is None:
            return

        from ..presence_service import PresenceState

        is_present = self._presence.state == PresenceState.PRESENT

        # Track when presence started
        if is_present and not self._was_present:
            now = time.time()
            self._present_since = now
            self._last_music_time = now
            logger.debug("Wellbeing: presence started, music timer begins")

        if not is_present:
            if self._was_present:
                logger.debug("Wellbeing: presence ended, music timer reset")
            self._present_since = None
            self._last_music_time = 0.0

        self._was_present = is_present

        if not is_present or self._present_since is None:
            return

        now = time.time()
        elapsed_since_arrive = now - self._present_since

        # --- Music suggestion check ---
        if (
            elapsed_since_arrive >= self._music_interval_s
            and (now - self._last_music_time) >= self._music_interval_s
        ):
            self._last_music_time = now
            minutes = int(elapsed_since_arrive / 60)
            captured = self._capture_stable_frame()
            stable = captured if captured is not None else frame
            logger.info("Wellbeing: music suggestion check after %d min", minutes)
            self._send_event(
                "music.mood",
                f"User has been here for {minutes} minute(s). "
                f"Look at the attached image — assess their mood and suggest "
                f"1-2 songs that match their current state (do NOT auto-play). "
                f"Relaxed → chill/acoustic. Stressed → calming music. "
                f"Focused/working → lo-fi/ambient. Tired → gentle piano. "
                f"In a meeting → reply NO_REPLY. No user visible → reply NO_REPLY.",
                image=stable,
                cooldown=self._music_interval_s,
            )

    def to_dict(self) -> dict:
        return {
            "type": "wellbeing",
            "present_since": self._present_since,
            "last_music_time": self._last_music_time,
            "music_interval_s": self._music_interval_s,
        }
