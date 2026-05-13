"""GPIO button handler for pin 17.

Supports three actions on a single button:
- Single click: stop speaker / unmute mic
- Triple click: reboot OS
- Long press (5s): shutdown OS

Double-click and 4+ rapid clicks are intentional no-ops — destructive
actions (reboot/shutdown) need a deliberate gesture so a user panic-
clicking the button to interrupt TTS doesn't accidentally reboot.

The actual action logic lives in `button_actions.py` so other input
devices (touchpad, remote) can reuse the same gestures.
"""

import logging
import threading
import time

from lelamp.service.button_actions import (
    DOUBLE_CLICK_WINDOW,
    LONG_PRESS_DURATION,
    long_press_action,
    single_click_action,
    triple_click_action,
)

logger = logging.getLogger(__name__)

# Default wiring for Raspberry Pi 4/5 (BCM 17 on gpiochip0).
PI_BUTTON_CHIP = 0
PI_BUTTON_PIN = 17
# wm8960 button on Pi 4/5: 100 ms wasn't enough (deterministic 2 callback
# edges per physical click). Bump to 200 ms — still leaves 200 ms inside
# DOUBLE_CLICK_WINDOW which is more than the typical human inter-click gap.
PI_DEBOUNCE_NS = 200_000_000

# OrangePi sun60iw2 (4 Pro / A733): button on header pin 11 = PL9 → gpiochip1 line 9.
OPI_SUN60_BUTTON_CHIP = 1
OPI_SUN60_BUTTON_PIN = 9
# Same 200 ms as Pi — 250 ms made the triple-click gap window too tight
# ([250, 400] ms) on OrangePi field-test, dropping click 2/3 when users
# clicked at natural pace. If bounce comes back at 200 ms, prefer bumping
# DOUBLE_CLICK_WINDOW over the debounce (single click is the hot path).
OPI_SUN60_DEBOUNCE_NS = 200_000_000

# lgpio.callback tick is nanoseconds. Both per-board values stay well under
# DOUBLE_CLICK_WINDOW so triple click is still detectable.


def _is_orangepi_sun60() -> bool:
    """Detect Allwinner sun60iw2 (OrangePi 4 Pro / A733) via device-tree model."""
    try:
        with open("/proc/device-tree/model", "r") as f:
            return "sun60iw2" in f.read().lower()
    except OSError:
        return False


def _resolve_board_config() -> tuple[int, int, int]:
    """Return (chip, line, debounce_ns) for the wake button on this board."""
    if _is_orangepi_sun60():
        return OPI_SUN60_BUTTON_CHIP, OPI_SUN60_BUTTON_PIN, OPI_SUN60_DEBOUNCE_NS
    return PI_BUTTON_CHIP, PI_BUTTON_PIN, PI_DEBOUNCE_NS


class GPIOButtonHandler:
    def __init__(self):
        self._lgpio = None
        self._handle = None
        self._callback = None
        self._click_count = 0
        self._click_timer = None
        self._press_start = 0
        self._long_press_timer = None
        self._chip = 0
        self._pin = 0
        self._debounce_ns = PI_DEBOUNCE_NS
        self._last_press_tick = 0
        self._last_release_tick = 0

    def start(self):
        import lgpio

        self._chip, self._pin, self._debounce_ns = _resolve_board_config()
        self._lgpio = lgpio
        self._handle = lgpio.gpiochip_open(self._chip)
        lgpio.gpio_claim_alert(
            self._handle, self._pin, lgpio.BOTH_EDGES, lgpio.SET_PULL_UP
        )
        self._callback = lgpio.callback(
            self._handle, self._pin, lgpio.BOTH_EDGES, self._on_edge
        )
        logger.info(
            "GPIO button ready on gpiochip%d line %d (manual debounce %d ms)",
            self._chip,
            self._pin,
            self._debounce_ns // 1_000_000,
        )

    def _on_edge(self, chip, gpio, level, tick):
        # Per-edge debounce. Track press/release ticks independently so a
        # quick click (rising edge soon after the falling edge) isn't
        # dropped, while bouncy repeats of the same edge are filtered out.
        # OrangePi's gpiochip1 reports more contact bounce than the Pi.
        if level == 0:
            if tick - self._last_press_tick < self._debounce_ns:
                return
            self._last_press_tick = tick
        else:
            if tick - self._last_release_tick < self._debounce_ns:
                return
            self._last_release_tick = tick

        if level == 0:
            # Button pressed (falling edge)
            self._press_start = time.monotonic()
            # Start long press detection
            self._long_press_timer = threading.Timer(
                LONG_PRESS_DURATION, self._on_long_press
            )
            self._long_press_timer.daemon = True
            self._long_press_timer.start()
        else:
            # Button released (rising edge)
            # Cancel long press detection
            if self._long_press_timer:
                self._long_press_timer.cancel()
                self._long_press_timer = None

            held = time.monotonic() - self._press_start
            if held >= LONG_PRESS_DURATION:
                # Already handled by long press timer
                return

            # Count as a click
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
            single_click_action(source="GPIO button")
        elif count == 3:
            triple_click_action(source="GPIO button")
        else:
            # count == 2 → likely a slipped/panic double-tap of single
            # count >= 4 → panic-click; never trigger destructive actions
            logger.info("GPIO button %d clicks -- ignored (only 1=stop, 3=reboot)", count)

    def _on_long_press(self):
        self._long_press_timer = None
        long_press_action(source="GPIO button")
