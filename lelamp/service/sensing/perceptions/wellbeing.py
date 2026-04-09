"""
Wellbeing Perception — stub.

All proactive reminders (hydration, break, music) are now handled by the
AI agent via OpenClaw cron jobs. This class remains as a no-op placeholder
in the sensing pipeline so that SensingService instantiation doesn't break.
"""

import logging
from typing import Callable, Optional, override

import numpy as np
import numpy.typing as npt

from .base import Perception

logger = logging.getLogger(__name__)


class WellbeingPerception(Perception):
    """No-op placeholder — all wellbeing logic moved to AI agent cron jobs."""

    def __init__(
        self,
        cv2,
        send_event: Callable,
        presence_service,
        capture_stable_frame: Callable,
        # Accept old params for backwards compat (all ignored)
        hydration_interval_s: float = 0,
        break_interval_s: float = 0,
        music_interval_s: float = 0,
    ):
        super().__init__(send_event)

    @override
    def check(self, frame) -> None:
        pass

    def to_dict(self) -> dict:
        return {"type": "wellbeing", "status": "ai-driven"}
