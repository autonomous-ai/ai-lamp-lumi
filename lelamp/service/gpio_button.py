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

BUTTON_PIN = 17
DOUBLE_CLICK_WINDOW = 0.4  # seconds to wait for second click
LONG_PRESS_DURATION = 3.0  # seconds to hold for shutdown
DEBOUNCE_US = 200_000  # microseconds


class GPIOButtonHandler:
    def __init__(self):
        self._lgpio = None
        self._handle = None
        self._callback = None
        self._click_count = 0
        self._click_timer = None
        self._press_start = 0
        self._long_press_timer = None
        self._last_tick = 0

    def start(self):
        import lgpio

        self._lgpio = lgpio
        self._handle = lgpio.gpiochip_open(0)
        lgpio.gpio_claim_alert(
            self._handle, BUTTON_PIN, lgpio.BOTH_EDGES, lgpio.SET_PULL_UP
        )
        self._callback = lgpio.callback(
            self._handle, BUTTON_PIN, lgpio.BOTH_EDGES, self._on_edge
        )
        logger.info("GPIO button ready on pin %d", BUTTON_PIN)

    def _on_edge(self, chip, gpio, level, tick):
        if level == 0:
            # Button pressed (falling edge)
            if tick - self._last_tick < DEBOUNCE_US:
                return
            self._last_tick = tick
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
                    target=lambda: state.tts_service.speak("I'm listening!"),
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
            state.tts_service.speak("Rebooting now")
        subprocess.Popen(
            ["sudo", "reboot"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

    def _on_long_press(self):
        logger.info("GPIO button long press -- shutting down OS")
        self._long_press_timer = None
        if (
            state.tts_service
            and state.tts_service.available
            and not state._speaker_muted
        ):
            state.tts_service.speak("Shutting down now")
            time.sleep(2)
        subprocess.Popen(
            ["sudo", "shutdown", "-h", "now"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
