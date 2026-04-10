"""
LED effect loops — each function runs in a background thread until stop_event is set
or deadline is reached. All effects accept (color, speed, deadline, stop_event, svc)
except where noted (rainbow omits color; notification_flash omits deadline).
"""

import math
import random
import time
import threading
from typing import Optional


def is_done(deadline: Optional[float], stop_event: threading.Event) -> bool:
    """Return True if the effect should stop."""
    if stop_event.is_set():
        return True
    if deadline is not None and time.monotonic() >= deadline:
        return True
    return False


def hsv_to_rgb(h: float, s: float, v: float) -> tuple:
    """Convert HSV (0-1 range) to RGB (0-255 ints)."""
    if s == 0.0:
        val = int(v * 255)
        return (val, val, val)
    i = int(h * 6.0)
    f = (h * 6.0) - i
    p = int(255 * v * (1.0 - s))
    q = int(255 * v * (1.0 - s * f))
    t = int(255 * v * (1.0 - s * (1.0 - f)))
    v_int = int(255 * v)
    i %= 6
    if i == 0:
        return (v_int, t, p)
    if i == 1:
        return (q, v_int, p)
    if i == 2:
        return (p, v_int, t)
    if i == 3:
        return (p, q, v_int)
    if i == 4:
        return (t, p, v_int)
    return (v_int, p, q)


def run_effect(
    effect: str,
    color: tuple,
    speed: float,
    duration_ms: Optional[int],
    stop_event: threading.Event,
    svc,
):
    """Dispatch to the appropriate effect loop. Runs in a background thread."""
    deadline = None
    if duration_ms is not None:
        deadline = time.monotonic() + duration_ms / 1000.0

    try:
        if effect == "breathing":
            breathing(color, speed, deadline, stop_event, svc)
        elif effect == "candle":
            candle(color, speed, deadline, stop_event, svc)
        elif effect == "rainbow":
            rainbow(speed, deadline, stop_event, svc)
        elif effect == "notification_flash":
            notification_flash(color, speed, stop_event, svc)
        elif effect == "pulse":
            pulse(color, speed, deadline, stop_event, svc)
        elif effect == "blink":
            blink(color, speed, deadline, stop_event, svc)
    except Exception as e:
        import logging
        logging.getLogger("lelamp.led.effects").warning("LED effect '%s' error: %s", effect, e)


def breathing(
    color: tuple,
    speed: float,
    deadline: Optional[float],
    stop_event: threading.Event,
    svc,
):
    """Fade in/out with the given color."""
    step_delay = 0.03 / speed
    while not is_done(deadline, stop_event):
        # Full cycle: 0 -> 1 -> 0 over ~3s at speed=1
        for i in range(100):
            if is_done(deadline, stop_event):
                return
            brightness = math.sin(math.pi * i / 100.0)
            scaled = tuple(int(c * brightness) for c in color)
            svc.dispatch("solid", scaled)
            time.sleep(step_delay)


def candle(
    color: tuple,
    speed: float,
    deadline: Optional[float],
    stop_event: threading.Event,
    svc,
):
    """Warm flicker effect with randomized warm tones."""
    step_delay = 0.05 / speed
    led_count = getattr(svc, "led_count", 64)
    while not is_done(deadline, stop_event):
        pixels = []
        for _ in range(led_count):
            flicker = random.uniform(0.4, 1.0)
            # Warm tone bias: keep red high, vary green, minimal blue
            r = int(min(255, color[0] * flicker + random.randint(0, 20)))
            g = int(min(255, color[1] * flicker * random.uniform(0.6, 0.9)))
            b = int(min(255, color[2] * flicker * 0.3))
            pixels.append((r, g, b))
        svc.dispatch("paint", pixels)
        time.sleep(step_delay)


def rainbow(
    speed: float,
    deadline: Optional[float],
    stop_event: threading.Event,
    svc,
):
    """Cycle through hue spectrum across all pixels."""
    step_delay = 0.03 / speed
    led_count = getattr(svc, "led_count", 64)
    offset = 0.0
    while not is_done(deadline, stop_event):
        pixels = []
        for i in range(led_count):
            hue = (offset + i / led_count) % 1.0
            r, g, b = hsv_to_rgb(hue, 1.0, 1.0)
            pixels.append((r, g, b))
        svc.dispatch("paint", pixels)
        offset += 0.01
        time.sleep(step_delay)


def notification_flash(
    color: tuple,
    speed: float,
    stop_event: threading.Event,
    svc,
):
    """3 quick flashes then stop."""
    flash_on = 0.15 / speed
    flash_off = 0.1 / speed
    for _ in range(3):
        if stop_event.is_set():
            return
        svc.dispatch("solid", color)
        time.sleep(flash_on)
        if stop_event.is_set():
            return
        svc.dispatch("solid", (0, 0, 0))
        time.sleep(flash_off)


def blink(
    color: tuple,
    speed: float,
    deadline: Optional[float],
    stop_event: threading.Event,
    svc,
):
    """Rapid on/off blink. speed=1 → ~3 Hz, speed=2 → ~6 Hz, speed=0.5 → ~1.5 Hz."""
    half_period = 1.0 / (speed * 6.0)  # on time = off time
    while not is_done(deadline, stop_event):
        svc.dispatch("solid", color)
        time.sleep(half_period)
        if is_done(deadline, stop_event):
            return
        svc.dispatch("solid", (0, 0, 0))
        time.sleep(half_period)


def pulse(
    color: tuple,
    speed: float,
    deadline: Optional[float],
    stop_event: threading.Event,
    svc,
):
    """Single color pulse outward from center."""
    step_delay = 0.04 / speed
    led_count = getattr(svc, "led_count", 64)
    center = led_count // 2
    max_radius = center + 1
    while not is_done(deadline, stop_event):
        for radius in range(max_radius + 1):
            if is_done(deadline, stop_event):
                return
            pixels = [(0, 0, 0)] * led_count
            for i in range(led_count):
                dist = abs(i - center)
                if dist <= radius:
                    # Brightness falls off with distance from the wavefront
                    falloff = max(
                        0.0, 1.0 - abs(dist - radius) / max(max_radius * 0.3, 1)
                    )
                    pixels[i] = tuple(int(c * falloff) for c in color)
            svc.dispatch("paint", pixels)
            time.sleep(step_delay)
