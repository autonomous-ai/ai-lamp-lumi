"""
Wellbeing Perception — periodic hydration, posture/break, and music reminders via LLM vision.

Three independent timers run while someone is present:
  - Hydration:  every WELLBEING_HYDRATION_S (default 30 min) — remind to drink water
  - Break:      every WELLBEING_BREAK_S (default 45 min) — remind to stand up and stretch
  - Music:      every WELLBEING_MUSIC_S (default 60 min) — suggest music based on mood

Each timer sends a camera snapshot so the LLM can visually assess the user
and decide whether to speak or reply NO_REPLY.
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
    """Sends periodic wellbeing events with a camera snapshot while someone is present."""

    def __init__(
        self,
        cv2,
        send_event: Callable,
        presence_service,
        capture_stable_frame: Callable,
        hydration_interval_s: float = config.WELLBEING_HYDRATION_S,
        break_interval_s: float = config.WELLBEING_BREAK_S,
        music_interval_s: float = config.WELLBEING_MUSIC_S,
    ):
        super().__init__(send_event)
        self._cv2 = cv2
        self._presence = presence_service
        self._capture_stable_frame = capture_stable_frame
        self._hydration_interval_s = hydration_interval_s
        self._break_interval_s = break_interval_s
        self._music_interval_s = music_interval_s

        self._present_since: Optional[float] = None
        self._last_hydration_time: float = 0.0
        self._last_break_time: float = 0.0
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
            self._last_hydration_time = now
            self._last_break_time = now
            self._last_music_time = now
            logger.debug("Wellbeing: presence started, timers begin")

        if not is_present:
            if self._was_present:
                logger.debug("Wellbeing: presence ended, timers reset")
            self._present_since = None
            self._last_hydration_time = 0.0
            self._last_break_time = 0.0
            self._last_music_time = 0.0

        self._was_present = is_present

        if not is_present or self._present_since is None:
            return

        now = time.time()
        elapsed_since_arrive = now - self._present_since

        # --- Hydration check ---
        if (
            elapsed_since_arrive >= self._hydration_interval_s
            and (now - self._last_hydration_time) >= self._hydration_interval_s
        ):
            self._last_hydration_time = now
            minutes = int(elapsed_since_arrive / 60)
            captured = self._capture_stable_frame()
            stable = captured if captured is not None else frame
            logger.info("Wellbeing: hydration check after %d min", minutes)
            self._send_event(
                "wellbeing.hydration",
                f"User has been sitting for {minutes} minute(s) without a water break. "
                f"Look at the attached image — if they seem busy or focused, "
                f"gently remind them to drink some water. "
                f"If they already have a drink or seem fine, reply NO_REPLY.",
                image=stable,
                cooldown=self._hydration_interval_s,
            )

        # --- Break / posture check ---
        if (
            elapsed_since_arrive >= self._break_interval_s
            and (now - self._last_break_time) >= self._break_interval_s
        ):
            self._last_break_time = now
            minutes = int(elapsed_since_arrive / 60)
            captured = self._capture_stable_frame()
            stable = captured if captured is not None else frame
            logger.info("Wellbeing: break check after %d min", minutes)
            self._send_event(
                "wellbeing.break",
                f"User has been sitting continuously for {minutes} minute(s). "
                f"Look at the attached image — check their posture and whether they look tired. "
                f"If they seem fatigued, slouching, or have been sitting too long, "
                f"gently remind them to stand up, stretch, and take a short break. "
                f"If they look fine and energetic, reply NO_REPLY.",
                image=stable,
                cooldown=self._break_interval_s,
            )

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
                "wellbeing.music",
                f"User has been here for {minutes} minute(s). "
                f"Look at the attached image — assess their mood and whether "
                f"this is a good moment to suggest music. "
                f"If they look relaxed, tired, or could use a mood lift, "
                f"suggest 1-2 songs that match their current vibe (do NOT auto-play). "
                f"If they look busy, in a meeting, or deeply focused, reply NO_REPLY.",
                image=stable,
                cooldown=self._music_interval_s,
            )

    def to_dict(self) -> dict:
        return {
            "type": "wellbeing",
            "present_since": self._present_since,
            "last_hydration_time": self._last_hydration_time,
            "last_break_time": self._last_break_time,
            "last_music_time": self._last_music_time,
            "hydration_interval_s": self._hydration_interval_s,
            "break_interval_s": self._break_interval_s,
            "music_interval_s": self._music_interval_s,
        }
