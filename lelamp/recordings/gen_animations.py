#!/usr/bin/env python3
"""Generate smooth, organic animation CSVs for LeLamp.

All animations use ease-in-out curves, micro-sway during holds,
secondary motion on non-primary joints, and asymmetric timing
to feel alive and natural.

Joint limits (from animation_service.py):
  base_yaw:     -55..65    (ID 1)
  base_pitch:   -70..-15   (ID 2)
  elbow_pitch:   35..98    (ID 3)
  wrist_roll:   -50..45    (ID 4)
  wrist_pitch:  -25..72    (ID 5)

Rest position:
  base_yaw=3, base_pitch=-30, elbow_pitch=57, wrist_roll=0, wrist_pitch=18
"""

import csv
import math
import os

FPS = 30
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

REST = {
    "base_yaw.pos": 3.0,
    "base_pitch.pos": -30.0,
    "elbow_pitch.pos": 57.0,
    "wrist_roll.pos": 0.0,
    "wrist_pitch.pos": 18.0,
}
JOINTS = list(REST.keys())


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def ease_in_out(t: float) -> float:
    """Cubic ease-in-out, t in [0,1]."""
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        return 4 * t * t * t
    return 1 - (-2 * t + 2) ** 3 / 2


def ease_out(t: float) -> float:
    """Cubic ease-out (fast start, slow end)."""
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def ease_in(t: float) -> float:
    """Cubic ease-in (slow start, fast end)."""
    t = max(0.0, min(1.0, t))
    return t * t * t


def breathing(t: float, period: float, amp: float, phase: float = 0.0) -> float:
    """Organic oscillation: primary wave + harmonic for asymmetric feel."""
    p = 2 * math.pi * (t / period + phase)
    return amp * (0.7 * math.sin(p) + 0.3 * math.sin(2 * p + 0.5))


def micro_sway(t: float, seed: int = 0) -> float:
    """Subtle organic micro-movement layered from multiple frequencies."""
    s = seed * 1.7
    return (
        math.sin(0.8 * t + s) * 0.5
        + math.sin(1.9 * t + s * 0.7) * 0.3
        + math.sin(3.1 * t + s * 1.3) * 0.15
    )


def drift(t: float, seed: float = 0.0) -> float:
    """Slow wandering drift (layered sine waves)."""
    return (
        math.sin(0.13 * t + seed * 1.7) * 0.4
        + math.sin(0.31 * t + seed * 2.3) * 0.25
        + math.sin(0.71 * t + seed * 0.9) * 0.15
        + math.sin(1.17 * t + seed * 3.1) * 0.08
    )


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def clamp_joint(joint: str, val: float) -> float:
    """Clamp value to safe joint limits."""
    limits = {
        "base_yaw.pos": (-55, 65),
        "base_pitch.pos": (-70, -15),
        "elbow_pitch.pos": (35, 98),
        "wrist_roll.pos": (-50, 45),
        "wrist_pitch.pos": (-25, 72),
    }
    lo, hi = limits.get(joint, (-999, 999))
    return max(lo, min(hi, val))


def write_csv(filename: str, frames: list[dict[str, float]]):
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp"] + JOINTS)
        writer.writeheader()
        for row in frames:
            clamped = {"timestamp": round(row["timestamp"], 4)}
            for j in JOINTS:
                clamped[j] = round(clamp_joint(j, row[j]), 1)
            writer.writerow(clamped)
    print(f"  {filename}: {len(frames)} frames ({len(frames)/FPS:.1f}s)")


def pose_approach_return(
    duration: float,
    target_offset: dict[str, float],
    approach_time: float = 1.5,
    hold_sway_amp: float = 0.8,
    return_time: float = None,
    hold_extras: callable = None,
) -> list[dict[str, float]]:
    """Generic pattern: ease-in to pose, hold with micro-sway, ease-out to rest.

    Args:
        hold_extras: optional fn(joint, hold_t) -> float for extra motion during hold
    """
    if return_time is None:
        return_time = approach_time * 1.2  # slightly slower return feels natural
    hold_start = approach_time
    hold_end = duration - return_time

    n = int(duration * FPS)
    frames = []
    for i in range(n + 1):
        t = i / FPS
        row = {"timestamp": t}

        if t <= hold_start:
            p = ease_in_out(t / hold_start)
        elif t <= hold_end:
            p = 1.0
        else:
            p = 1.0 - ease_in_out((t - hold_end) / return_time)

        for j in JOINTS:
            base = REST[j] + target_offset.get(j, 0.0) * p

            # Micro-sway during hold phase — never perfectly still
            if hold_start < t <= hold_end:
                ht = t - hold_start
                base += micro_sway(ht, seed=hash(j) % 13) * hold_sway_amp
                if hold_extras:
                    base += hold_extras(j, ht)

            # Subtle secondary motion during transitions too
            if t <= hold_start or t > hold_end:
                base += micro_sway(t, seed=hash(j) % 7) * 0.2 * p

            row[j] = base
        frames.append(row)
    return frames


def oscillation_pattern(
    duration: float,
    joint_waves: dict[str, list[tuple[float, float, float]]],
    fade_time: float = 1.0,
) -> list[dict[str, float]]:
    """Generic oscillation pattern with fade in/out.

    joint_waves: {joint: [(period, amplitude, phase), ...]}
    Multiple waves per joint are summed.
    """
    n = int(duration * FPS)
    frames = []
    for i in range(n + 1):
        t = i / FPS
        row = {"timestamp": t}

        # Fade envelope
        fade = 1.0
        if t < fade_time:
            fade = ease_in_out(t / fade_time)
        elif t > duration - fade_time:
            fade = ease_in_out((duration - t) / fade_time)

        for j in JOINTS:
            val = REST[j]
            waves = joint_waves.get(j, [])
            for period, amp, phase in waves:
                val += amp * math.sin(2 * math.pi * t / period + phase) * fade
            # Always add subtle micro-movement
            val += micro_sway(t, seed=hash(j) % 11) * 0.3 * fade
            row[j] = val
        frames.append(row)
    return frames


# ===========================================================================
# Animation generators
# ===========================================================================

def gen_idle():
    """60s loop: breathing + drift + occasional look-arounds."""
    duration = 60.0
    n = int(duration * FPS)
    frames = []

    breath = {
        "base_yaw.pos":     (8.0, 6.0, 0.0),
        "base_pitch.pos":   (6.0, 4.0, 0.3),
        "elbow_pitch.pos":  (7.0, 5.0, 0.6),
        "wrist_roll.pos":   (9.0, 4.0, 0.1),
        "wrist_pitch.pos":  (5.5, 5.0, 0.8),
    }
    drift_amp = {
        "base_yaw.pos": 6.0, "base_pitch.pos": 3.0,
        "elbow_pitch.pos": 5.0, "wrist_roll.pos": 4.0, "wrist_pitch.pos": 4.0,
    }

    for i in range(n):
        t = i / FPS
        row = {"timestamp": t}
        fade = 1.0
        ft = 2.0
        if t < ft:
            fade = ease_in_out(t / ft)
        elif t > duration - ft:
            fade = ease_in_out((duration - t) / ft)

        for j in JOINTS:
            period, amp, phase = breath[j]
            b = breathing(t, period, amp, phase)
            d = drift(t, seed=hash(j) % 17) * drift_amp[j]
            look = 0.0
            if j == "base_yaw.pos":
                look = 8.0 * math.sin(2 * math.pi * t / 20.0)
            elif j == "wrist_pitch.pos":
                look = 5.0 * math.sin(2 * math.pi * t / 15.0 + 1.0)
            elif j == "elbow_pitch.pos":
                look = 3.0 * math.sin(2 * math.pi * t / 18.0 + 0.5)
            row[j] = REST[j] + (b + d + look) * fade
        frames.append(row)

    write_csv("idle.csv", frames)


def gen_curious():
    """6s: lean-in + head tilt, scanning micro-sway, smooth return."""
    offset = {
        "base_yaw.pos": 18.0, "base_pitch.pos": 3.0,
        "elbow_pitch.pos": -5.0, "wrist_roll.pos": 14.0, "wrist_pitch.pos": -8.0,
    }

    def extras(j, ht):
        if j == "base_yaw.pos":
            return 2.5 * math.sin(2 * math.pi * ht / 2.5)
        return 0.0

    frames = pose_approach_return(6.0, offset, approach_time=1.8,
                                   hold_sway_amp=0.8, hold_extras=extras)
    write_csv("curious.csv", frames)


def gen_nod():
    """5s: two gentle nods (elbow/wrist pitch oscillation) with secondary sway.

    A nod is primarily wrist_pitch going down then up, with elbow following.
    Two nods with slight pause between them feels natural.
    """
    duration = 5.0
    n = int(duration * FPS)
    frames = []

    # Two nods: at t=0.8s and t=2.2s, each ~0.8s long
    nod_centers = [1.2, 2.6]
    nod_width = 0.5  # half-width in seconds

    for i in range(n + 1):
        t = i / FPS
        row = {"timestamp": t}

        # Fade envelope
        fade = 1.0
        if t < 0.5:
            fade = ease_in_out(t / 0.5)
        elif t > duration - 0.8:
            fade = ease_in_out((duration - t) / 0.8)

        # Sum nod impulses (gaussian-ish)
        nod_val = 0.0
        for tc in nod_centers:
            d = (t - tc) / nod_width
            nod_val += math.exp(-d * d * 2)

        for j in JOINTS:
            val = REST[j]
            if j == "wrist_pitch.pos":
                val += 18.0 * nod_val * fade  # head dips down
            elif j == "elbow_pitch.pos":
                val += 8.0 * nod_val * fade   # elbow follows slightly
            elif j == "base_pitch.pos":
                val += 2.0 * nod_val * fade   # body leans into nod
            else:
                val += micro_sway(t, seed=hash(j) % 9) * 0.5 * fade
            row[j] = val
        frames.append(row)

    write_csv("nod.csv", frames)


def gen_headshake():
    """5s: two-and-a-half head shakes (base_yaw oscillation).

    Natural headshake: first swing wider, subsequent ones dampen.
    """
    duration = 5.0
    n = int(duration * FPS)
    frames = []

    for i in range(n + 1):
        t = i / FPS
        row = {"timestamp": t}

        fade = 1.0
        if t < 0.6:
            fade = ease_in_out(t / 0.6)
        elif t > duration - 1.0:
            fade = ease_in_out((duration - t) / 1.0)

        # Damped oscillation for headshake
        shake_period = 1.0
        decay = math.exp(-0.5 * t)  # amplitude decreases over time
        shake = math.sin(2 * math.pi * t / shake_period) * decay

        for j in JOINTS:
            val = REST[j]
            if j == "base_yaw.pos":
                val += 22.0 * shake * fade
            elif j == "wrist_roll.pos":
                # Wrist rolls opposite slightly (natural coupling)
                val += -5.0 * shake * fade
            elif j == "base_pitch.pos":
                # Slight forward lean during shake
                val += 1.5 * abs(shake) * fade
            else:
                val += micro_sway(t, seed=hash(j) % 11) * 0.4 * fade
            row[j] = val
        frames.append(row)

    write_csv("headshake.csv", frames)


def gen_happy_wiggle():
    """5s: joyful body wiggle with circular arm motion.

    Alternating yaw sway + elbow/wrist coordinated circular motion.
    Faster rhythm than idle, feels bouncy and excited.
    """
    duration = 5.0
    waves = {
        "base_yaw.pos":     [(0.7, 12.0, 0.0), (1.4, 4.0, 0.5)],     # bouncy yaw
        "base_pitch.pos":   [(0.7, 3.0, math.pi/2)],                   # bob up-down
        "elbow_pitch.pos":  [(0.7, 6.0, math.pi/4), (1.4, 3.0, 1.0)], # arm bounce
        "wrist_roll.pos":   [(0.7, 8.0, math.pi), (0.35, 3.0, 0.0)],  # wrist wiggle
        "wrist_pitch.pos":  [(0.7, 5.0, math.pi/3), (1.4, 2.0, 2.0)], # head bob
    }
    frames = oscillation_pattern(duration, waves, fade_time=0.8)
    write_csv("happy_wiggle.csv", frames)


def gen_sad():
    """6s: slow droop downward, hold with subtle breathing, slow rise back.

    Head drops, body sags, wrist goes limp — the whole body language of dejection.
    """
    offset = {
        "base_yaw.pos": -8.0,       # look slightly away
        "base_pitch.pos": -12.0,     # droop down
        "elbow_pitch.pos": -10.0,    # arm sags
        "wrist_roll.pos": -6.0,      # wrist goes limp to side
        "wrist_pitch.pos": -10.0,    # head hangs
    }
    frames = pose_approach_return(6.0, offset, approach_time=2.0,
                                   hold_sway_amp=0.4, return_time=2.0)
    write_csv("sad.csv", frames)


def gen_excited():
    """4s: quick rise to alert pose, energetic micro-bouncing, settle.

    Like a dog seeing its owner — head up, body alert, slight vibrating energy.
    """
    offset = {
        "base_yaw.pos": 5.0,
        "base_pitch.pos": 12.0,      # rise up
        "elbow_pitch.pos": 18.0,     # arm lifts
        "wrist_roll.pos": 3.0,
        "wrist_pitch.pos": 25.0,     # head up high
    }

    def extras(j, ht):
        # Excited micro-bouncing — faster frequency than normal sway
        bounce = math.sin(2 * math.pi * ht * 3.5) * 1.2 * math.exp(-0.3 * ht)
        if j == "elbow_pitch.pos":
            return bounce * 2.0
        if j == "wrist_pitch.pos":
            return bounce * 1.5
        if j == "base_yaw.pos":
            return bounce * 0.8
        return bounce * 0.3

    frames = pose_approach_return(4.0, offset, approach_time=0.8,
                                   hold_sway_amp=1.0, return_time=1.2,
                                   hold_extras=extras)
    write_csv("excited.csv", frames)


def gen_shock():
    """4s: fast jolt backward, freeze with tremor, slow cautious return.

    Quick recoil — head pulls back, body leans away. Holds with slight shaking.
    """
    offset = {
        "base_yaw.pos": -3.0,
        "base_pitch.pos": 8.0,       # lean back
        "elbow_pitch.pos": 12.0,     # arm pulls up
        "wrist_roll.pos": -6.0,      # wrist twists
        "wrist_pitch.pos": 15.0,     # head jerks up
    }

    def extras(j, ht):
        # Trembling during shock hold — high freq, low amp, decaying
        tremor = math.sin(2 * math.pi * ht * 8) * 0.6 * math.exp(-1.5 * ht)
        return tremor

    frames = pose_approach_return(4.0, offset, approach_time=0.4,
                                   hold_sway_amp=0.5, return_time=1.8,
                                   hold_extras=extras)
    write_csv("shock.csv", frames)


def gen_shy():
    """7s: turn away + tilt down, small peek, then slowly return.

    Like hiding face — turn away, duck head, maybe peek once during hold.
    """
    offset = {
        "base_yaw.pos": -25.0,      # turn away
        "base_pitch.pos": -8.0,      # duck down
        "elbow_pitch.pos": -8.0,     # arm curls in
        "wrist_roll.pos": -12.0,     # wrist curls
        "wrist_pitch.pos": -5.0,     # head dips
    }

    def extras(j, ht):
        # One small "peek" at ht ~1.5s — head turns slightly back
        peek = math.exp(-((ht - 1.5) / 0.4) ** 2) * 0.6
        if j == "base_yaw.pos":
            return 8.0 * peek  # peek back toward center
        if j == "wrist_pitch.pos":
            return 3.0 * peek  # lift head slightly
        return 0.0

    frames = pose_approach_return(7.0, offset, approach_time=1.5,
                                   hold_sway_amp=0.5, return_time=2.0,
                                   hold_extras=extras)
    write_csv("shy.csv", frames)


def gen_scanning():
    """7s: panoramic left-right sweep, like looking around a room.

    Smooth pan left, pause, smooth pan right, pause, return to center.
    Secondary: elbow/pitch adjust as if tracking with the head.
    """
    duration = 7.0
    n = int(duration * FPS)
    frames = []

    # Keyframes: (time, yaw_offset) with smooth interpolation
    # Rest(0) -> Left(-30) at 1.5s -> pause -> Right(+30) at 4.5s -> pause -> Rest at 7s
    key_times = [0.0, 1.5, 2.2, 4.5, 5.2, 7.0]
    key_yaws  = [0.0, -28.0, -28.0, 30.0, 30.0, 0.0]

    for i in range(n + 1):
        t = i / FPS
        row = {"timestamp": t}

        # Find keyframe segment
        yaw_offset = 0.0
        for k in range(len(key_times) - 1):
            if key_times[k] <= t <= key_times[k + 1]:
                seg_t = (t - key_times[k]) / (key_times[k + 1] - key_times[k])
                yaw_offset = lerp(key_yaws[k], key_yaws[k + 1], ease_in_out(seg_t))
                break

        fade = 1.0
        if t < 0.5:
            fade = ease_in_out(t / 0.5)
        elif t > duration - 0.5:
            fade = ease_in_out((duration - t) / 0.5)

        for j in JOINTS:
            val = REST[j]
            if j == "base_yaw.pos":
                val += yaw_offset * fade
            elif j == "base_pitch.pos":
                # Slight upward tilt when scanning (alert)
                val += 3.0 * fade
            elif j == "elbow_pitch.pos":
                # Elbow tracks with yaw slightly
                val += abs(yaw_offset) * 0.1 * fade
            elif j == "wrist_pitch.pos":
                # Head follows yaw direction slightly
                val += yaw_offset * 0.15 * fade
            val += micro_sway(t, seed=hash(j) % 13) * 0.4 * fade
            row[j] = val
        frames.append(row)

    write_csv("scanning.csv", frames)


def gen_wake_up():
    """8s: slow rise from sleep position to alert, stretching motion.

    Start slumped low, gradually lift with a stretch at the peak,
    then settle into rest pose. Like waking up and stretching.
    """
    duration = 8.0
    n = int(duration * FPS)
    frames = []

    # Sleep pose (lower than rest)
    sleep_offset = {
        "base_yaw.pos": -5.0,
        "base_pitch.pos": -15.0,     # slumped far down
        "elbow_pitch.pos": -15.0,    # arm hanging
        "wrist_roll.pos": -5.0,
        "wrist_pitch.pos": -12.0,    # head drooped
    }
    # Stretch pose (higher than rest)
    stretch_offset = {
        "base_yaw.pos": 2.0,
        "base_pitch.pos": 15.0,      # rise up high
        "elbow_pitch.pos": 25.0,     # arm extends up
        "wrist_roll.pos": 5.0,
        "wrist_pitch.pos": 30.0,     # head up
    }

    # Phases: sleep(0-1s), rising(1-3.5s), stretch(3.5-5s), settle(5-8s)
    for i in range(n + 1):
        t = i / FPS
        row = {"timestamp": t}

        for j in JOINTS:
            if t <= 1.0:
                # Sleeping — very subtle breathing
                val = REST[j] + sleep_offset[j]
                val += breathing(t, 3.0, 0.3, hash(j) % 5 * 0.2)
            elif t <= 3.5:
                # Rising from sleep to rest
                p = ease_in_out((t - 1.0) / 2.5)
                val = REST[j] + sleep_offset[j] * (1 - p)
                val += micro_sway(t, seed=hash(j) % 7) * 0.3 * p
            elif t <= 5.0:
                # Stretch! Rise above rest
                p = ease_in_out((t - 3.5) / 1.5)
                val = REST[j] + stretch_offset[j] * p
                val += micro_sway(t, seed=hash(j) % 9) * 0.5
            else:
                # Settle from stretch to rest
                p = 1.0 - ease_in_out((t - 5.0) / 3.0)
                val = REST[j] + stretch_offset[j] * p
                val += micro_sway(t, seed=hash(j) % 11) * 0.3 * (1 - p)

            row[j] = val
        frames.append(row)

    write_csv("wake_up.csv", frames)


def gen_music_groove():
    """10s loop: rhythmic bouncing/swaying to music.

    Bouncy rhythm on pitch/elbow (like head-bobbing), swaying yaw,
    wrist roll adding flair. Multiple rhythmic layers.
    """
    duration = 10.0
    # Musical tempo: ~120 BPM = 0.5s per beat
    beat = 0.5
    waves = {
        "base_yaw.pos":     [(beat * 4, 10.0, 0.0), (beat * 8, 5.0, 1.0)],   # sway
        "base_pitch.pos":   [(beat, 3.0, 0.0), (beat * 2, 1.5, 0.5)],         # bob
        "elbow_pitch.pos":  [(beat, 5.0, math.pi/4), (beat * 2, 3.0, 1.0)],   # arm bounce
        "wrist_roll.pos":   [(beat * 2, 6.0, math.pi/2), (beat * 4, 3.0, 0)], # wrist flair
        "wrist_pitch.pos":  [(beat, 4.0, math.pi/6), (beat * 2, 2.0, 2.0)],   # head bob
    }
    frames = oscillation_pattern(duration, waves, fade_time=1.0)
    write_csv("music_groove.csv", frames)


# ===========================================================================
# Main
# ===========================================================================

if __name__ == "__main__":
    print("Generating all animations...")
    gen_idle()
    gen_curious()
    gen_nod()
    gen_headshake()
    gen_happy_wiggle()
    gen_sad()
    gen_excited()
    gen_shock()
    gen_shy()
    gen_scanning()
    gen_wake_up()
    gen_music_groove()
    print("Done.")
