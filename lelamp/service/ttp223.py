"""TTP223 capacitive touchpad handler.

Maps four TTP223 pads (S1-S4 on gpiochip0 lines 96-99, OrangePi
sun60iw2) to the same three gestures handled by the GPIO button:
- Single tap:       stop speaker / unmute mic
- Triple tap:       reboot OS
- Long touch (5s):  shutdown OS

All four pads form one logical button surface — touching any pad
counts as a press, release happens when the last active pad lets go.
The user doesn't have to hit a specific pad, any of S1-S4 works.

Action logic is shared with the GPIO button via `button_actions.py`.
"""

import logging
import threading
import time

import gpiod
from gpiod.line import Bias, Direction, EdgeDetection

from lelamp.service.button_actions import (
    DOUBLE_CLICK_WINDOW,
    LONG_PRESS_DURATION,
    long_press_action,
    single_click_action,
    triple_click_action,
)

logger = logging.getLogger(__name__)

TTP223_CHIP = "/dev/gpiochip0"
TTP223_LINES = [96, 97, 98, 99]
TTP223_NAMES = {96: "S1", 97: "S2", 98: "S3", 99: "S4"}
# TTP223 is capacitive — no mechanical contact bounce — but a small
# per-line debounce filters out near-simultaneous edges when the user
# drags a fingertip across multiple pads.
TTP223_DEBOUNCE_NS = 50_000_000  # 50 ms


def _device_tree_model() -> str:
    """Lower-cased contents of /proc/device-tree/model, or '' if missing."""
    try:
        with open("/proc/device-tree/model", "r") as f:
            return f.read().rstrip("\x00").strip().lower()
    except OSError:
        return ""


def _is_orangepi_sun60() -> bool:
    """Allwinner sun60iw2 (OrangePi 4 Pro / A733)."""
    return "sun60iw2" in _device_tree_model()


def _is_raspberry_pi_4() -> bool:
    return "raspberry pi 4" in _device_tree_model()


def _is_raspberry_pi_5() -> bool:
    return "raspberry pi 5" in _device_tree_model()


def _board_label() -> str:
    """Short label for logs."""
    if _is_orangepi_sun60():
        return "orangepi-sun60"
    if _is_raspberry_pi_5():
        return "pi5"
    if _is_raspberry_pi_4():
        return "pi4"
    return _device_tree_model() or "unknown"


class TTP223Handler:
    def __init__(self):
        self._req = None
        self._thread = None
        # Set of line numbers currently HIGH (active). Press = transition
        # from empty to non-empty; release = transition back to empty.
        self._active: set[int] = set()
        self._click_count = 0
        self._click_timer = None
        self._press_start = 0.0
        self._long_press_timer = None
        self._long_press_fired = False
        self._last_edge_ns: dict[int, int] = {l: 0 for l in TTP223_LINES}

    def start(self):
        board = _board_label()
        if not _is_orangepi_sun60():
            # Pi 4 / Pi 5 / unknown boards don't have TTP223 wired —
            # skip entirely so the same image runs everywhere without
            # claiming unrelated GPIOs. If TTP223 gets added to Pi
            # later, branch here on _is_raspberry_pi_4/5() and override
            # TTP223_CHIP / TTP223_LINES per board (mirror gpio_button's
            # _resolve_board_config pattern).
            logger.info("ttp223 disabled: board is %s (only wired on orangepi-sun60)", board)
            return

        settings = gpiod.LineSettings(
            direction=Direction.INPUT,
            bias=Bias.PULL_DOWN,
            edge_detection=EdgeDetection.BOTH,
        )
        config = {l: settings for l in TTP223_LINES}
        try:
            self._req = gpiod.request_lines(
                TTP223_CHIP, consumer="ttp223-touchpad", config=config
            )
        except (OSError, FileNotFoundError) as e:
            # Right board but lines already claimed / kernel error —
            # log so we can investigate but don't crash the process.
            logger.warning("ttp223 line claim failed: %s", e)
            return
        self._thread = threading.Thread(
            target=self._run, name="ttp223-touchpad", daemon=True
        )
        self._thread.start()
        logger.info(
            "TTP223 ready on %s lines %s (debounce %d ms)",
            TTP223_CHIP,
            TTP223_LINES,
            TTP223_DEBOUNCE_NS // 1_000_000,
        )

    def _run(self):
        while True:
            try:
                # Block until edges arrive. Daemon thread dies on
                # process exit; no explicit stop path needed.
                if not self._req.wait_edge_events():
                    continue
                for ev in self._req.read_edge_events():
                    self._on_event(ev)
            except Exception as e:
                logger.error("ttp223 event loop error: %s", e)
                break

    def _on_event(self, ev):
        line = ev.line_offset
        ts = ev.timestamp_ns
        # Per-line debounce. Tracking ticks per line (not globally) so
        # tapping pad A then pad B in quick succession registers both
        # edges; only bouncy repeats of the same line are dropped.
        if ts - self._last_edge_ns[line] < TTP223_DEBOUNCE_NS:
            return
        self._last_edge_ns[line] = ts

        # TTP223 with pull-down bias: rising edge = touch, falling = release.
        is_press = ev.event_type == gpiod.EdgeEvent.Type.RISING_EDGE
        was_active = bool(self._active)
        if is_press:
            self._active.add(line)
        else:
            self._active.discard(line)
        now_active = bool(self._active)

        if not was_active and now_active:
            self._on_press()
        elif was_active and not now_active:
            self._on_release()

    def _on_press(self):
        self._press_start = time.monotonic()
        self._long_press_fired = False
        self._long_press_timer = threading.Timer(
            LONG_PRESS_DURATION, self._on_long_press
        )
        self._long_press_timer.daemon = True
        self._long_press_timer.start()

    def _on_release(self):
        if self._long_press_timer:
            self._long_press_timer.cancel()
            self._long_press_timer = None

        if self._long_press_fired:
            # Long press already shut down — ignore the trailing release.
            return

        held = time.monotonic() - self._press_start
        if held >= LONG_PRESS_DURATION:
            return

        # Count as a tap
        self._click_count += 1
        if self._click_timer:
            self._click_timer.cancel()
        self._click_timer = threading.Timer(
            DOUBLE_CLICK_WINDOW, self._on_click_timeout
        )
        self._click_timer.daemon = True
        self._click_timer.start()

    def _on_click_timeout(self):
        count = self._click_count
        self._click_count = 0
        if count == 1:
            single_click_action(source="ttp223")
        elif count == 3:
            triple_click_action(source="ttp223")
        else:
            # count == 2 → likely a slipped/panic double-tap of single
            # count >= 4 → panic-tap; never trigger destructive actions
            logger.info("ttp223 %d taps -- ignored (only 1=stop, 3=reboot)", count)

    def _on_long_press(self):
        self._long_press_timer = None
        self._long_press_fired = True
        long_press_action(source="ttp223")
