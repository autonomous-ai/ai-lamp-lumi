"""
Presence Service — state machine for automatic light on/off based on motion detection.

States:
  PRESENT  — someone is here, lights on (last scene or default)
  IDLE     — no motion for IDLE_TIMEOUT_S, dim to IDLE_BRIGHTNESS
  AWAY     — no motion for AWAY_TIMEOUT_S, lights off

Transitions:
  motion detected → PRESENT (turn on / restore)
  no motion for IDLE_TIMEOUT_S → IDLE (dim)
  no motion for AWAY_TIMEOUT_S → AWAY (off)

Calls LeLamp LED endpoints directly (same process, via rgb_service reference).
"""

import logging
import time
from enum import Enum
from typing import Optional

logger = logging.getLogger("lelamp.presence")

# Timeouts (seconds)
IDLE_TIMEOUT_S = 5 * 60      # 5 min → dim
AWAY_TIMEOUT_S = 15 * 60     # 15 min → off

# Dim level as fraction of last scene brightness
IDLE_BRIGHTNESS = 0.20


class PresenceState(str, Enum):
    PRESENT = "present"
    IDLE = "idle"
    AWAY = "away"
    DISABLED = "disabled"


class PresenceService:
    """Tracks presence state based on motion events. Controls LED via rgb_service."""

    def __init__(self, rgb_service=None):
        self._rgb_service = rgb_service
        self._state = PresenceState.PRESENT
        self._last_motion_time: float = time.time()
        self._enabled = True

        # Last known scene color (before dimming/off) so we can restore
        self._last_color: tuple = (255, 180, 100)  # default warm white

    @property
    def state(self) -> PresenceState:
        return self._state

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self):
        self._enabled = True
        self._state = PresenceState.PRESENT
        self._last_motion_time = time.time()
        logger.info("Presence auto-control enabled")

    def disable(self):
        self._enabled = False
        self._state = PresenceState.DISABLED
        logger.info("Presence auto-control disabled")

    def set_last_color(self, color: tuple):
        """Called whenever LED color is set (from scene or manual), so we know what to restore."""
        self._last_color = color

    def on_motion(self):
        """Called by SensingService when motion is detected."""
        if not self._enabled:
            return

        self._last_motion_time = time.time()
        prev_state = self._state

        if prev_state in (PresenceState.IDLE, PresenceState.AWAY):
            self._state = PresenceState.PRESENT
            logger.info("Presence: %s → PRESENT (motion detected, restoring light)", prev_state)
            self._restore_light()

    def tick(self):
        """Called periodically by sensing loop to check timeouts."""
        if not self._enabled or self._state == PresenceState.DISABLED:
            return

        elapsed = time.time() - self._last_motion_time

        if self._state == PresenceState.PRESENT and elapsed >= IDLE_TIMEOUT_S:
            self._state = PresenceState.IDLE
            logger.info("Presence: PRESENT → IDLE (no motion for %ds)", int(elapsed))
            self._dim_light()

        elif self._state == PresenceState.IDLE and elapsed >= AWAY_TIMEOUT_S:
            self._state = PresenceState.AWAY
            logger.info("Presence: IDLE → AWAY (no motion for %ds)", int(elapsed))
            self._turn_off_light()

    def _restore_light(self):
        """Restore last known color at full brightness."""
        if not self._rgb_service:
            return
        try:
            self._rgb_service.dispatch("solid", self._last_color)
        except Exception as e:
            logger.warning("Presence: failed to restore light: %s", e)

    def _dim_light(self):
        """Dim to IDLE_BRIGHTNESS of last color."""
        if not self._rgb_service:
            return
        try:
            dimmed = tuple(int(c * IDLE_BRIGHTNESS) for c in self._last_color)
            self._rgb_service.dispatch("solid", dimmed)
        except Exception as e:
            logger.warning("Presence: failed to dim light: %s", e)

    def _turn_off_light(self):
        """Turn off LEDs."""
        if not self._rgb_service:
            return
        try:
            self._rgb_service.clear()
        except Exception as e:
            logger.warning("Presence: failed to turn off light: %s", e)

    def to_dict(self) -> dict:
        return {
            "state": self._state.value,
            "enabled": self._enabled,
            "seconds_since_motion": int(time.time() - self._last_motion_time),
            "idle_timeout": IDLE_TIMEOUT_S,
            "away_timeout": AWAY_TIMEOUT_S,
        }
