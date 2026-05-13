"""TTP223 capacitive touchpad handler (4 pads = 1 logical button).

Mirrors GPIOButtonHandler structure (lgpio + callback) so both input
devices behave identically:
- Single tap:       stop speaker / unmute mic
- Triple tap:       reboot OS
- Long touch (5s):  shutdown OS

Four pads (S1-S4) collapse into one logical button — any pad touched =
press, all pads released = release. The user doesn't need to remember
which pad maps to which action.

Action logic is shared with the GPIO button via `button_actions.py`.
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

# OrangePi sun60iw2 (4 Pro / A733): TTP223 pads on gpiochip0 lines 96-99
# (PE0-PE3 ish, verified via test_ttp223_probe_orangepi.py).
OPI_SUN60_TTP223_CHIP = 0
OPI_SUN60_TTP223_LINES = [96, 97, 98, 99]
# TTP223 is capacitive — no mechanical contact bounce — but a small
# per-line debounce filters out near-simultaneous edges when the user
# drags a fingertip across multiple pads.
OPI_SUN60_TTP223_DEBOUNCE_NS = 50_000_000  # 50 ms


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
    """Return (chip, lines, debounce_ns) or None if TTP223 isn't wired here.
    Add Pi 4/5 branches when those boards get TTP223 hardware."""
    if _is_orangepi_sun60():
        return (
            OPI_SUN60_TTP223_CHIP,
            OPI_SUN60_TTP223_LINES,
            OPI_SUN60_TTP223_DEBOUNCE_NS,
        )
    return None


class TTP223Handler:
    def __init__(self):
        self._lgpio = None
        self._handle = None
        self._callbacks = []
        self._chip = 0
        self._lines = []
        self._debounce_ns = OPI_SUN60_TTP223_DEBOUNCE_NS
        # Set of lines currently HIGH (active). Press = transition from
        # empty to non-empty; release = transition back to empty.
        self._active = set()
        self._click_count = 0
        self._click_timer = None
        self._press_start = 0.0
        self._long_press_timer = None
        self._long_press_fired = False
        # Per-line edge debounce ticks
        self._last_press_tick = {}
        self._last_release_tick = {}

    def start(self):
        config = _resolve_board_config()
        if config is None:
            logger.info(
                "TTP223 disabled: board is %s (only wired on orangepi-sun60)",
                _board_label(),
            )
            return

        import lgpio

        self._chip, self._lines, self._debounce_ns = config
        self._lgpio = lgpio
        self._last_press_tick = {l: 0 for l in self._lines}
        self._last_release_tick = {l: 0 for l in self._lines}

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
            "TTP223 ready on gpiochip%d lines %s (manual debounce %d ms)",
            self._chip,
            self._lines,
            self._debounce_ns // 1_000_000,
        )

    def _on_edge(self, chip, gpio, level, tick):
        # DEBUG: raw edge trace (remove once TTP223 hold behavior confirmed)
        logger.info("TTP223 raw edge gpio=%d level=%d tick=%d", gpio, level, tick)
        # Per-edge, per-line debounce. Mirrors gpio_button's split
        # press/release tick tracking so a quick tap (rising edge soon
        # after falling) isn't dropped, while bouncy repeats of the
        # same edge are filtered.
        # TTP223 + PULL_DOWN: level==1 = touch, level==0 = release.
        if level == 1:
            if tick - self._last_press_tick.get(gpio, 0) < self._debounce_ns:
                return
            self._last_press_tick[gpio] = tick
        elif level == 0:
            if tick - self._last_release_tick.get(gpio, 0) < self._debounce_ns:
                return
            self._last_release_tick[gpio] = tick
        else:
            return  # watchdog / no-level event, ignore

        was_active = bool(self._active)
        if level == 1:
            self._active.add(gpio)
        else:
            self._active.discard(gpio)
        now_active = bool(self._active)

        if not was_active and now_active:
            # First pad touched — surface press begins
            self._press_start = time.monotonic()
            self._long_press_fired = False
            self._long_press_timer = threading.Timer(
                LONG_PRESS_DURATION, self._on_long_press
            )
            self._long_press_timer.daemon = True
            self._long_press_timer.start()
        elif was_active and not now_active:
            # Last pad released — surface release
            if self._long_press_timer:
                self._long_press_timer.cancel()
                self._long_press_timer = None

            if self._long_press_fired:
                # Long press already fired shutdown — drop the trailing release.
                return

            held = time.monotonic() - self._press_start
            if held >= LONG_PRESS_DURATION:
                return

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
            single_click_action(source="TTP223")
        elif count == 3:
            triple_click_action(source="TTP223")
        else:
            # count == 2 → slipped/panic double-tap; count >= 4 → panic.
            # Never trigger destructive actions on ambiguous counts.
            logger.info("TTP223 %d taps -- ignored (only 1=stop, 3=reboot)", count)

    def _on_long_press(self):
        self._long_press_timer = None
        # Defensive: re-read actual pin levels before firing shutdown.
        # If all pads read LOW the user is NOT currently touching anything
        # — the timer fired because a release edge got dropped (debounce
        # race / lgpio buffer miss) and self._active leaked stale state.
        # Without this guard, two taps separated by ~5s could incorrectly
        # trigger shutdown when the first tap's release was missed.
        try:
            any_touched = any(
                self._lgpio.gpio_read(self._handle, l) == 1
                for l in self._lines
            )
        except Exception as e:
            logger.warning("TTP223 pin read at long-press guard failed: %s", e)
            any_touched = True  # fall through to normal behavior if read fails
        if not any_touched:
            logger.warning(
                "TTP223 long press timer fired but all pads LOW -- ignoring (release missed)"
            )
            self._active.clear()  # resync to real hardware state
            return
        self._long_press_fired = True
        long_press_action(source="TTP223")
