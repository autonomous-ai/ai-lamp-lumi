import logging
import threading
import time
from typing import Callable, Optional, override

import lelamp.config as config
import numpy as np
import requests

from .base import Perception

_MONITOR_URL = "http://127.0.0.1:5000/api/monitor/event"

logger = logging.getLogger(__name__)

_DEDUPE_INTERVAL_S = 15.0
_WINDOW_DURATION_S = 120.0
_PERSISTENT_AFTER = 3
_SUPPRESS_DURATION_S = 180.0


class SoundPerception(Perception):
    """Detects loud sounds via microphone RMS energy.

    Escalation logic (mirrors Go soundTracker):
      - occurrence 1-2: forwarded silently (agent reacts with emotion only)
      - occurrence 3+: marked persistent — agent speaks once, then suppressed for 3 min
      - 15s dedup prevents flooding between occurrences
      - 2min silence resets the window
    """

    def __init__(
        self,
        sd,
        np_module,
        send_event: Callable,
        input_device: Optional[int] = None,
        tts_service=None,
    ):
        super().__init__(send_event)
        self._sd = sd
        self._np = np_module
        self._input_device = input_device
        self._tts = tts_service

        self._count: int = 0
        self._window_start: float = 0.0
        self._last_passed: float = 0.0
        self._suppress_until: float = 0.0

    def set_tts_service(self, tts_service) -> None:
        self._tts = tts_service

    def _push_monitor(self, event_type: str, summary: str, detail: dict) -> None:
        def _send():
            try:
                requests.post(_MONITOR_URL, json={"type": event_type, "summary": summary, "detail": detail}, timeout=5)
            except Exception:
                pass
        threading.Thread(target=_send, daemon=True).start()

    def _track(self, now: float) -> tuple[bool, int, bool]:
        """Returns (send, occurrence, persistent)."""
        if now < self._suppress_until:
            return False, 0, False

        # Reset window after silence longer than window duration
        if self._last_passed and (now - self._last_passed) > _WINDOW_DURATION_S:
            self._count = 0
            self._window_start = 0.0

        # Dedup: at most one event per dedupe interval
        if self._last_passed and (now - self._last_passed) < _DEDUPE_INTERVAL_S:
            return False, 0, False

        if not self._window_start:
            self._window_start = now
        self._count += 1
        self._last_passed = now

        current = self._count
        persistent = current >= _PERSISTENT_AFTER
        if persistent:
            self._suppress_until = now + _SUPPRESS_DURATION_S
            self._count = 0
            self._window_start = 0.0

        return True, current, persistent

    @override
    def _check_impl(self, frame: np.ndarray) -> None:
        if self._input_device is None:
            return

        if self._tts is not None and (
            self._tts.speaking or time.time() - self._tts.last_spoken_time < 5.0
        ):
            return

        try:
            sample_rate = 44100
            frames = int(sample_rate * config.SOUND_SAMPLE_DURATION_S)
            recording = self._sd.rec(
                frames,
                samplerate=sample_rate,
                channels=1,
                dtype="int16",
                device=self._input_device,
                blocking=True,
            )
            rms = float(self._np.sqrt(self._np.mean(recording.astype(self._np.float64) ** 2)))
            if rms < config.SOUND_RMS_THRESHOLD:
                return

            now = time.time()
            send, occurrence, persistent = self._track(now)
            if not send:
                self._push_monitor("sound_tracker", "sound dropped (dedup/suppressed)", {"action": "drop"})
                return

            msg = f"Loud noise detected (level: {int(rms)})"
            if persistent:
                msg += f" — persistent (occurrence {occurrence})"
                self._push_monitor("sound_tracker", f"sound persistent — occurrence {occurrence} → will speak", {"action": "persistent", "occurrence": occurrence})
            else:
                msg += f" — occurrence {occurrence}"
                self._push_monitor("sound_tracker", f"sound occurrence {occurrence} → silent", {"action": "silent", "occurrence": occurrence})

            self._send_event("sound", msg)
        except Exception as e:
            logger.debug("Sound check failed: %s", e)

    def to_dict(self) -> dict:
        return {
            "type": "sound",
            "input_device": self._input_device,
            "echo_suppression": self._tts is not None,
            "occurrence_count": self._count,
            "suppressed": time.time() < self._suppress_until,
        }
