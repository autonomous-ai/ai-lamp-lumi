"""TTP223 capacitive touchpad handler (4 pads = 1 logical button).

Single tap only — stop speaker / unmute mic. Destructive gestures
(reboot, shutdown) are intentionally OFF on TTP223 because:
- The IC on this board runs in FastMode (max touch ~80ms): output
  goes LOW within ~50ms of touch even with finger still on pad, so
  a true "hold 5s" is impossible without rewiring the FM pin.
- Cross-talk between adjacent pads makes one physical tap produce
  1-2 spurious software clicks, so counting "exactly 3 taps" for
  reboot is unreliable.

GPIO button still handles triple-click reboot and 5s-long-press
shutdown via its mechanical pin — destructive actions live there.

Cross-talk fix: instead of treating each rising/falling edge as a
press/release, every edge starts/extends a "touch session". The
session ends when no edges have arrived for SESSION_GAP_NS. One
session = one tap, regardless of how many edges fired inside it.
"""

import logging
import threading

from lelamp.service.button_actions import single_click_action

logger = logging.getLogger(__name__)

# OrangePi sun60iw2 (4 Pro / A733): TTP223 pads on gpiochip0 lines 96-99
# (verified via test_ttp223_probe_orangepi.py).
OPI_SUN60_TTP223_CHIP = 0
OPI_SUN60_TTP223_LINES = [96, 97, 98, 99]
# Session gap: any edge within this window of the previous edge keeps
# the session alive. 200 ms comfortably exceeds the observed burst
# duration (~30-100 ms across 4 pads) while staying well below a
# natural inter-tap gap, so two real taps register as two sessions.
SESSION_GAP_S = 0.2


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
        # Session-end timer: fires SESSION_GAP_S after the last edge,
        # signalling that the current touch is over → emit one click.
        self._session_end_timer = None
        self._session_lock = threading.Lock()

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
            "TTP223 ready on gpiochip%d lines %s (session gap %d ms, single tap only)",
            self._chip,
            self._lines,
            int(SESSION_GAP_S * 1000),
        )

    def _on_edge(self, chip, gpio, level, tick):
        # Any edge (rising or falling, any pad) keeps the session alive.
        # Cross-talk and FastMode auto-LOW produce a flurry of edges per
        # physical touch; we coalesce them by resetting the session-end
        # timer instead of trying to interpret each edge as press/release.
        with self._session_lock:
            if self._session_end_timer is not None:
                self._session_end_timer.cancel()
            self._session_end_timer = threading.Timer(
                SESSION_GAP_S, self._on_session_end
            )
            self._session_end_timer.daemon = True
            self._session_end_timer.start()

    def _on_session_end(self):
        with self._session_lock:
            self._session_end_timer = None
        single_click_action(source="TTP223")
