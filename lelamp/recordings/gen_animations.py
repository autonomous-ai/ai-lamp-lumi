#!/usr/bin/env python3
"""Generate smooth, organic animation CSVs for LeLamp.

Joint limits (from animation_service.py):
  base_yaw:     -55..65    (ID 1)
  base_pitch:   -70..-15   (ID 2)
  elbow_pitch:   35..98    (ID 3)
  wrist_roll:   -50..45    (ID 4)
  wrist_pitch:  -25..72    (ID 5)

Startup/rest position:
  base_pitch = -30, elbow_pitch = 57
  base_yaw ~ 3..5, wrist_roll ~ 0..2, wrist_pitch ~ 18..21
"""

import csv
import math
import os

FPS = 30
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# Rest pose (center of idle range)
REST = {
    "base_yaw.pos": 3.0,
    "base_pitch.pos": -30.0,
    "elbow_pitch.pos": 57.0,
    "wrist_roll.pos": 0.0,
    "wrist_pitch.pos": 18.0,
}

JOINTS = list(REST.keys())


def ease_in_out(t: float) -> float:
    """Smooth ease-in-out (cubic)."""
    if t < 0.5:
        return 4 * t * t * t
    return 1 - (-2 * t + 2) ** 3 / 2


def breathing(t: float, period: float, amplitude: float, phase: float = 0.0) -> float:
    """Organic breathing-like oscillation using combined sinusoids."""
    # Primary wave + harmonic for asymmetric inhale/exhale feel
    p = 2 * math.pi * (t / period + phase)
    return amplitude * (0.7 * math.sin(p) + 0.3 * math.sin(2 * p + 0.5))


def drift(t: float, seed: float = 0.0) -> float:
    """Slow wandering drift using layered sine waves (poor man's Perlin)."""
    return (
        math.sin(0.13 * t + seed * 1.7) * 0.4
        + math.sin(0.31 * t + seed * 2.3) * 0.25
        + math.sin(0.71 * t + seed * 0.9) * 0.15
        + math.sin(1.17 * t + seed * 3.1) * 0.08
    )


def write_csv(filename: str, frames: list[dict[str, float]]):
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp"] + JOINTS)
        writer.writeheader()
        for row in frames:
            writer.writerow({k: round(v, 1) for k, v in row.items()})
    print(f"  {filename}: {len(frames)} frames ({len(frames)/FPS:.1f}s)")


# ---------------------------------------------------------------------------
# IDLE — 60s loop with organic "breathing" + slow drift
# ---------------------------------------------------------------------------
def gen_idle():
    duration = 60.0
    n = int(duration * FPS)
    frames = []

    # Breathing parameters per joint (period, amplitude, phase_offset)
    breath = {
        "base_yaw.pos":     (8.0,  2.5, 0.0),
        "base_pitch.pos":   (6.0,  1.8, 0.3),
        "elbow_pitch.pos":  (7.0,  2.0, 0.6),
        "wrist_roll.pos":   (9.0,  1.5, 0.1),
        "wrist_pitch.pos":  (5.5,  2.0, 0.8),
    }

    # Drift amplitude per joint
    drift_amp = {
        "base_yaw.pos":     3.0,
        "base_pitch.pos":   1.5,
        "elbow_pitch.pos":  2.5,
        "wrist_roll.pos":   2.0,
        "wrist_pitch.pos":  1.8,
    }

    for i in range(n):
        t = i / FPS
        row = {"timestamp": t}

        # Fade in/out at boundaries for seamless loop
        fade = 1.0
        fade_time = 2.0  # seconds
        if t < fade_time:
            fade = ease_in_out(t / fade_time)
        elif t > duration - fade_time:
            fade = ease_in_out((duration - t) / fade_time)

        for j in JOINTS:
            period, amp, phase = breath[j]
            b = breathing(t, period, amp, phase)
            d = drift(t, seed=hash(j) % 17) * drift_amp[j]

            # Occasional "look around" — slow head turns layered on top
            look = 0.0
            if j == "base_yaw.pos":
                look = 4.0 * math.sin(0.05 * t * 2 * math.pi / 20.0)
            elif j == "wrist_pitch.pos":
                look = 2.0 * math.sin(0.05 * t * 2 * math.pi / 15.0 + 1.0)

            row[j] = REST[j] + (b + d + look) * fade

        frames.append(row)

    write_csv("idle.csv", frames)


# ---------------------------------------------------------------------------
# CURIOUS — 6s: gentle lean-in with head tilt, hold with micro-sway, smooth return
# ---------------------------------------------------------------------------
def gen_curious():
    duration = 6.0
    n = int(duration * FPS)
    frames = []

    # Target "curious" pose: lean forward + tilt head
    curious_offset = {
        "base_yaw.pos":     18.0,   # turn to look
        "base_pitch.pos":    3.0,   # lean forward slightly (still within -70..-15)
        "elbow_pitch.pos":  -5.0,   # elbow adjusts
        "wrist_roll.pos":   14.0,   # head tilt
        "wrist_pitch.pos":  -8.0,   # head down (looking closer)
    }

    # Phases: approach (0-1.8s), hold+sway (1.8-4.2s), return (4.2-6.0s)
    t_approach = 1.8
    t_hold_end = 4.2
    t_return = duration

    for i in range(n):
        t = i / FPS
        row = {"timestamp": t}

        if t <= t_approach:
            # Ease in to curious pose
            p = ease_in_out(t / t_approach)
        elif t <= t_hold_end:
            # Hold at curious pose with organic micro-sway
            p = 1.0
        else:
            # Ease out back to rest
            p = 1.0 - ease_in_out((t - t_hold_end) / (t_return - t_hold_end))

        for j in JOINTS:
            base = REST[j] + curious_offset[j] * p

            # Add micro-sway during hold phase
            if t_approach < t <= t_hold_end:
                hold_t = t - t_approach
                sway = breathing(hold_t, 1.8, 0.8, hash(j) % 7 * 0.3)
                # Slight "scanning" on yaw during curiosity
                if j == "base_yaw.pos":
                    sway += 2.0 * math.sin(hold_t * 2 * math.pi / 2.5)
                base += sway

            row[j] = base

        frames.append(row)

    write_csv("curious.csv", frames)


if __name__ == "__main__":
    print("Generating animations...")
    gen_idle()
    gen_curious()
    print("Done.")
