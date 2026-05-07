"""GPIO button handler for pin 17.

Supports three actions on a single button:
- Single click: stop speaker / unmute mic
- Triple click: reboot OS
- Long press (3s): shutdown OS

Double-click and 4+ rapid clicks are intentional no-ops — destructive
actions (reboot/shutdown) need a deliberate gesture so a user panic-
clicking the button to interrupt TTS doesn't accidentally reboot.
"""

import logging
import subprocess
import threading
import time

import lelamp.app_state as state

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
# gpiochip1 on sun60iw2 reports more contact bounce than the Pi — pad to 250 ms.
OPI_SUN60_DEBOUNCE_NS = 250_000_000

DOUBLE_CLICK_WINDOW = 0.4  # seconds to wait for second click
LONG_PRESS_DURATION = 3.0  # seconds to hold for shutdown
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
        # Kernel-level debounce filter — drops edges shorter than the window at
        # the lgpio driver layer, before they reach the Python callback. The
        # manual per-edge debounce in _on_edge stays as a fallback for older
        # lgpio builds without gpio_set_debounce_micros, and as a backstop in
        # case the kernel filter behaves differently than expected.
        kernel_debounce_us = self._debounce_ns // 1000
        kernel_status = "off"
        try:
            lgpio.gpio_set_debounce_micros(self._handle, self._pin, kernel_debounce_us)
            kernel_status = f"{kernel_debounce_us // 1000}ms"
        except Exception as e:
            logger.warning("gpio_set_debounce_micros unavailable (%s)", e)
        self._callback = lgpio.callback(
            self._handle, self._pin, lgpio.BOTH_EDGES, self._on_edge
        )
        logger.info(
            "GPIO button ready on gpiochip%d line %d (kernel debounce %s, manual %d ms)",
            self._chip,
            self._pin,
            kernel_status,
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
            self._single_click()
        elif count == 3:
            self._triple_click()
        else:
            # count == 2 → likely a slipped/panic double-tap of single
            # count >= 4 → panic-click; never trigger destructive actions
            logger.info("GPIO button %d clicks -- ignored (only 1=stop, 3=reboot)", count)

    def _single_click(self):
        if state._mic_muted:
            logger.info("GPIO button single click -- unmuting mic")
            from lelamp.routes.voice import unmute_mic

            unmute_mic()
            if (
                state.tts_service
                and state.tts_service.available
                and not state._speaker_muted
            ):
                threading.Thread(
                    target=lambda: state.tts_service.speak_cached("I'm listening!"),
                    daemon=True,
                    name="unmute-tts",
                ).start()
            return
        logger.info("GPIO button single click -- stopping speaker")
        from lelamp.routes.voice import stop_tts
        from lelamp.routes.music import audio_stop

        stop_tts()
        audio_stop()

    def _triple_click(self):
        logger.info("GPIO button triple click -- rebooting OS")
        if (
            state.tts_service
            and state.tts_service.available
            and not state._speaker_muted
        ):
            state.tts_service.speak_cached("Rebooting now")
            # speak_cached is async; reboot kicks the OS before audio plays
            # without this. ~2s covers the cached "Rebooting now" clip
            # (matches the existing _on_long_press shutdown delay).
            time.sleep(5)
        subprocess.Popen(
            ["sudo", "reboot"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

    def _on_long_press(self):
        logger.info("GPIO button long press -- shutting down OS")
        self._long_press_timer = None

        # Step 1: TTS announce.
        if (
            state.tts_service
            and state.tts_service.available
            and not state._speaker_muted
        ):
            state.tts_service.speak_cached("Shutting down now")
            time.sleep(5)

        # Step 2: park servo in safe pose then cut torque, otherwise the
        # body slams down when systemd kills the process mid-pose.
        try:
            from lelamp.routes.servo import release_servos

            logger.info("GPIO long press -- releasing servo before shutdown")
            release_servos()
        except Exception as e:
            logger.warning(f"Servo release before shutdown failed: {e}")

        # Step 3: shutdown OS.
        subprocess.Popen(
            ["sudo", "shutdown", "-h", "now"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
