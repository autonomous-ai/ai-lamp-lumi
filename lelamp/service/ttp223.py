"""TTP223 capacitive touchpad handler (4 pads = dog-head touch surface).

Two gestures:
- Single tap   → stop speaker / unmute mic (same as GPIO button single click)
- Pet / stroke → playful TTS response ("hihi nhột quá!", etc.)

Destructive gestures (reboot / shutdown) are intentionally OFF on TTP223
because the IC on this board runs in FastMode: output drops LOW within
~50ms of touch even with finger still on the pad, so a true "hold 5s"
is impossible without rewiring the FM pin. GPIO button still owns those.

Gesture detection is two-layered:

1. Session: any edge (rising or falling, any pad) keeps a 200ms window
   alive. Coalesces the burst of cross-talk + FastMode auto-LOW edges
   from one physical touch into a single "session". One session = one
   touch event from the user's POV.

2. Pet vs tap: after a session ends, wait DECISION_WINDOW (400ms) for
   more sessions. Three or more sessions in rapid succession = the user
   is stroking the head → head_pat_action. One session that's not
   followed by more = single tap → single_click_action. (Two sessions
   are treated as a single tap for tolerance — TTP223 cross-talk
   occasionally splits one physical touch.)

The 400ms decision delay is the cost of distinguishing the two gestures
on this hardware — TTP223 FastMode can't tell us "finger currently down",
so we infer continuous stroking from session frequency.
"""

import logging
import threading

from lelamp.service.button_actions import (
    head_pat_action,
    single_click_action,
)

logger = logging.getLogger(__name__)

# OrangePi sun60iw2 (4 Pro / A733): TTP223 pads on gpiochip0 lines 96-99.
OPI_SUN60_TTP223_CHIP = 0
OPI_SUN60_TTP223_LINES = [96, 97, 98, 99]

# Session gap: edges within this window of the previous edge belong to
# the same session. 200ms comfortably exceeds the observed burst length
# (~30-100ms across 4 pads) while staying below a natural inter-tap gap.
SESSION_GAP_S = 0.2

# Decision window: after a session ends, wait this long for more
# sessions before classifying. Strokes produce sessions ~100-300ms
# apart (finger sweeping retriggers IC), so 400ms catches the second
# and third bursts of a pet without making single-tap response feel
# laggy.
DECISION_WINDOW_S = 0.4

# Number of sessions within DECISION_WINDOW that triggers pet response.
PET_SESSION_THRESHOLD = 3


def _device_tree_model() -> str:
    """Lower-cased /proc/device-tree/model contents, or '' if missing."""
    try:
        with open("/proc/device-tree/model", "r") as f:
            return f.read().rstrip("\x00").strip().lower()
    except OSError:
        return ""


def _is_orangepi_sun60() -> bool:
    return "sun60iw2" in _device_tree_model()


def _is_raspberry_pi_4() -> bool:
    return "raspberry pi 4" in _device_tree_model()


def _is_raspberry_pi_5() -> bool:
    return "raspberry pi 5" in _device_tree_model()


def _board_label() -> str:
    if _is_orangepi_sun60():
        return "orangepi-sun60"
    if _is_raspberry_pi_5():
        return "pi5"
    if _is_raspberry_pi_4():
        return "pi4"
    return _device_tree_model() or "unknown"


def _resolve_board_config():
    """Return (chip, lines) or None if TTP223 isn't wired here."""
    if _is_orangepi_sun60():
        return (OPI_SUN60_TTP223_CHIP, OPI_SUN60_TTP223_LINES)
    return None


class TTP223Handler:
    def __init__(self):
        self._lgpio = None
        self._handle = None
        self._callbacks = []
        self._chip = 0
        self._lines = []
        self._lock = threading.Lock()
        # Session-end timer: fires SESSION_GAP_S after the last edge.
        self._session_end_timer = None
        # Decision timer: fires DECISION_WINDOW_S after the last session
        # ended, resolving how many sessions accumulated → tap vs pet.
        self._decision_timer = None
        self._session_count = 0

    def start(self):
        config = _resolve_board_config()
        if config is None:
            logger.info(
                "TTP223 disabled: board is %s (only wired on orangepi-sun60)",
                _board_label(),
            )
            return

        import lgpio

        self._chip, self._lines = config
        self._lgpio = lgpio

        try:
            self._handle = lgpio.gpiochip_open(self._chip)
        except Exception as e:
            logger.warning("TTP223 gpiochip_open(%d) failed: %s", self._chip, e)
            return

        for line in self._lines:
            try:
                lgpio.gpio_claim_alert(
                    self._handle, line, lgpio.BOTH_EDGES, lgpio.SET_PULL_DOWN
                )
                cb = lgpio.callback(
                    self._handle, line, lgpio.BOTH_EDGES, self._on_edge
                )
                self._callbacks.append(cb)
            except Exception as e:
                logger.warning("TTP223 claim line %d failed: %s", line, e)

        if not self._callbacks:
            logger.warning("TTP223 no lines claimed -- disabled")
            return

        logger.info(
            "TTP223 ready on gpiochip%d lines %s (session %dms, decision %dms, pet>=%d sessions)",
            self._chip,
            self._lines,
            int(SESSION_GAP_S * 1000),
            int(DECISION_WINDOW_S * 1000),
            PET_SESSION_THRESHOLD,
        )

    def _on_edge(self, chip, gpio, level, tick):
        # Any edge keeps the current session alive — cross-talk and
        # FastMode auto-LOW produce flurries of edges per physical
        # touch; coalesce them by resetting the session-end timer.
        with self._lock:
            if self._session_end_timer is not None:
                self._session_end_timer.cancel()
            self._session_end_timer = threading.Timer(
                SESSION_GAP_S, self._on_session_end
            )
            self._session_end_timer.daemon = True
            self._session_end_timer.start()

    def _on_session_end(self):
        # One physical touch ended. Accumulate; let the decision timer
        # decide tap vs pet when the user stops touching for a while.
        with self._lock:
            self._session_end_timer = None
            self._session_count += 1
            count = self._session_count
            if self._decision_timer is not None:
                self._decision_timer.cancel()
            self._decision_timer = threading.Timer(
                DECISION_WINDOW_S, self._on_decision
            )
            self._decision_timer.daemon = True
            self._decision_timer.start()
        logger.debug("TTP223 session ended (count=%d)", count)

    def _on_decision(self):
        with self._lock:
            count = self._session_count
            self._session_count = 0
            self._decision_timer = None
        if count >= PET_SESSION_THRESHOLD:
            head_pat_action(source="TTP223")
        elif count >= 1:
            # 1 or 2 sessions → single tap. 2 is tolerated because
            # TTP223 cross-talk occasionally splits one physical touch
            # into two close sessions; treating both as one tap is
            # friendlier than ignoring.
            single_click_action(source="TTP223")
