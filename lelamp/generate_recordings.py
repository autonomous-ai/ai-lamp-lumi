#!/usr/bin/env python3
"""Generate expressive animation CSVs for LeLamp.

Each animation is defined as a sequence of keyframes that get interpolated
with smooth easing. Run once to overwrite recordings/*.csv.

Usage:
    python generate_recordings.py
"""

import csv
import math
import os

RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "recordings")
FPS = 30
HEADER = ["timestamp", "base_yaw.pos", "base_pitch.pos", "elbow_pitch.pos", "wrist_roll.pos", "wrist_pitch.pos"]

# Neutral "idle" pose (lamp upright, relaxed)
NEUTRAL = {
    "base_yaw": 0.0,
    "base_pitch": -30.0,
    "elbow_pitch": 54.0,
    "wrist_roll": 3.0,
    "wrist_pitch": 25.0,
}


def ease_in_out(t: float) -> float:
    """Smooth cubic ease in-out, t in [0,1]."""
    if t < 0.5:
        return 4 * t * t * t
    return 1 - (-2 * t + 2) ** 3 / 2


def ease_out(t: float) -> float:
    """Quick start, slow end."""
    return 1 - (1 - t) ** 3


def ease_in(t: float) -> float:
    """Slow start, quick end."""
    return t ** 3


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def interpolate_keyframes(keyframes: list[dict], fps: int = FPS) -> list[dict]:
    """Interpolate between keyframes. Each keyframe has 'duration', 'easing', and joint values."""
    frames = []
    timestamp = 0.0
    dt = 1.0 / fps

    for i in range(len(keyframes) - 1):
        kf_from = keyframes[i]
        kf_to = keyframes[i + 1]
        duration = kf_to.get("duration", 1.0)
        easing = kf_to.get("easing", ease_in_out)
        n_frames = max(1, int(duration * fps))

        for f in range(n_frames):
            t = easing(f / n_frames)
            frame = {"timestamp": round(timestamp, 6)}
            for joint in ["base_yaw", "base_pitch", "elbow_pitch", "wrist_roll", "wrist_pitch"]:
                frame[f"{joint}.pos"] = lerp(kf_from[joint], kf_to[joint], t)
            frames.append(frame)
            timestamp += dt

    # Add final keyframe
    kf_last = keyframes[-1]
    frame = {"timestamp": round(timestamp, 6)}
    for joint in ["base_yaw", "base_pitch", "elbow_pitch", "wrist_roll", "wrist_pitch"]:
        frame[f"{joint}.pos"] = kf_last[joint]
    frames.append(frame)
    return frames


def make_wave(center: float, amplitude: float, frequency: float, phase: float,
              t: float) -> float:
    """Sine wave oscillation."""
    return center + amplitude * math.sin(2 * math.pi * frequency * t + phase)


def generate_oscillation(base_pose: dict, oscillations: dict, duration: float,
                         fps: int = FPS) -> list[dict]:
    """Generate frames with sinusoidal oscillations on top of a base pose.

    oscillations: {joint: (amplitude, frequency, phase)}
    """
    frames = []
    n_frames = int(duration * fps)
    dt = 1.0 / fps
    timestamp = 0.0
    for f in range(n_frames):
        t = f * dt
        frame = {"timestamp": round(timestamp, 6)}
        for joint in ["base_yaw", "base_pitch", "elbow_pitch", "wrist_roll", "wrist_pitch"]:
            base_val = base_pose.get(joint, NEUTRAL[joint])
            if joint in oscillations:
                amp, freq, phase = oscillations[joint]
                frame[f"{joint}.pos"] = base_val + amp * math.sin(2 * math.pi * freq * t + phase)
            else:
                frame[f"{joint}.pos"] = base_val
        frames.append(frame)
        timestamp += dt
    return frames


def write_csv(name: str, frames: list[dict]):
    path = os.path.join(RECORDINGS_DIR, f"{name}.csv")
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writeheader()
        for frame in frames:
            writer.writerow(frame)
    print(f"  {name}.csv  ({len(frames)} frames, {len(frames)/FPS:.1f}s)")


# ─── Animation Definitions ────────────────────────────────────────────

def gen_idle():
    """Gentle breathing-like micro-movements, subtle life."""
    return generate_oscillation(
        base_pose=NEUTRAL,
        oscillations={
            "base_yaw":     (2.5, 0.15, 0),
            "base_pitch":   (1.5, 0.12, 1.0),
            "elbow_pitch":  (1.0, 0.10, 0.5),
            "wrist_roll":   (1.5, 0.08, 2.0),
            "wrist_pitch":  (2.0, 0.13, 1.5),
        },
        duration=10.0,
    )


def gen_nod():
    """Enthusiastic nodding — three quick bobs."""
    kf = [
        {**NEUTRAL, "duration": 0},
    ]
    for _ in range(3):
        # Dip down
        kf.append({
            **NEUTRAL,
            "base_pitch": -40.0,
            "wrist_pitch": 15.0,
            "duration": 0.25, "easing": ease_out,
        })
        # Pop back up
        kf.append({
            **NEUTRAL,
            "base_pitch": -25.0,
            "wrist_pitch": 32.0,
            "duration": 0.25, "easing": ease_in_out,
        })
    # Settle
    kf.append({**NEUTRAL, "duration": 0.5, "easing": ease_in_out})
    return interpolate_keyframes(kf)


def gen_headshake():
    """Clear 'no' — three quick turns with wrist counter-roll."""
    kf = [{**NEUTRAL, "duration": 0}]
    for i in range(3):
        sign = 1 if i % 2 == 0 else -1
        kf.append({
            **NEUTRAL,
            "base_yaw": sign * 25.0,
            "wrist_roll": -sign * 12.0,
            "duration": 0.3, "easing": ease_out,
        })
    kf.append({**NEUTRAL, "duration": 0.4, "easing": ease_in_out})
    return interpolate_keyframes(kf)


def gen_happy_wiggle():
    """Bouncy dance — side-to-side sway with rhythmic bobbing."""
    kf = [{**NEUTRAL, "duration": 0}]
    for i in range(5):
        sign = 1 if i % 2 == 0 else -1
        kf.append({
            "base_yaw": sign * 20.0,
            "base_pitch": -35.0 + (i % 2) * 8,
            "elbow_pitch": 60.0 + (i % 2) * 10,
            "wrist_roll": sign * 15.0,
            "wrist_pitch": 20.0 + (i % 2) * 12,
            "duration": 0.35, "easing": ease_in_out,
        })
    kf.append({**NEUTRAL, "duration": 0.5, "easing": ease_in_out})
    return interpolate_keyframes(kf)


def gen_curious():
    """Head tilt + lean forward — "what's that?" """
    kf = [
        {**NEUTRAL, "duration": 0},
        # Lean forward and tilt head
        {
            "base_yaw": 15.0,
            "base_pitch": -45.0,
            "elbow_pitch": 65.0,
            "wrist_roll": -18.0,
            "wrist_pitch": 45.0,
            "duration": 1.0, "easing": ease_in_out,
        },
        # Tilt further, look closer
        {
            "base_yaw": 20.0,
            "base_pitch": -50.0,
            "elbow_pitch": 70.0,
            "wrist_roll": -22.0,
            "wrist_pitch": 55.0,
            "duration": 0.8, "easing": ease_in_out,
        },
        # Small head straighten (still curious)
        {
            "base_yaw": 12.0,
            "base_pitch": -48.0,
            "elbow_pitch": 68.0,
            "wrist_roll": -10.0,
            "wrist_pitch": 50.0,
            "duration": 0.6, "easing": ease_in_out,
        },
        # Hold gaze
        {
            "base_yaw": 12.0,
            "base_pitch": -48.0,
            "elbow_pitch": 68.0,
            "wrist_roll": -10.0,
            "wrist_pitch": 50.0,
            "duration": 1.0, "easing": ease_in_out,
        },
        # Return
        {**NEUTRAL, "duration": 1.2, "easing": ease_in_out},
    ]
    return interpolate_keyframes(kf)


def gen_excited():
    """Fast bouncy excitement — rapid bobbing with wide sway."""
    kf = [{**NEUTRAL, "duration": 0}]
    for i in range(6):
        sign = 1 if i % 2 == 0 else -1
        bounce = 15.0 if i < 4 else 8.0  # calm down toward end
        kf.append({
            "base_yaw": sign * bounce,
            "base_pitch": -25.0 - (i % 2) * 15,
            "elbow_pitch": 60.0 + (i % 2) * 20,
            "wrist_roll": sign * 20.0,
            "wrist_pitch": 15.0 + (i % 2) * 25,
            "duration": 0.22, "easing": ease_out,
        })
    kf.append({**NEUTRAL, "duration": 0.6, "easing": ease_in_out})
    return interpolate_keyframes(kf)


def gen_sad():
    """Slow droop — lamp wilts downward, holds, then slowly recovers."""
    kf = [
        {**NEUTRAL, "duration": 0},
        # Start drooping
        {
            "base_yaw": -5.0,
            "base_pitch": -45.0,
            "elbow_pitch": 40.0,
            "wrist_roll": -5.0,
            "wrist_pitch": 10.0,
            "duration": 1.5, "easing": ease_in,
        },
        # Full droop
        {
            "base_yaw": -8.0,
            "base_pitch": -55.0,
            "elbow_pitch": 30.0,
            "wrist_roll": -8.0,
            "wrist_pitch": 0.0,
            "duration": 1.2, "easing": ease_in,
        },
        # Hold sadness
        {
            "base_yaw": -10.0,
            "base_pitch": -58.0,
            "elbow_pitch": 25.0,
            "wrist_roll": -10.0,
            "wrist_pitch": -5.0,
            "duration": 2.0, "easing": ease_in_out,
        },
        # Small sigh (slight lift then drop)
        {
            "base_yaw": -8.0,
            "base_pitch": -52.0,
            "elbow_pitch": 32.0,
            "wrist_roll": -6.0,
            "wrist_pitch": 5.0,
            "duration": 0.8, "easing": ease_in_out,
        },
        {
            "base_yaw": -10.0,
            "base_pitch": -56.0,
            "elbow_pitch": 27.0,
            "wrist_roll": -9.0,
            "wrist_pitch": -3.0,
            "duration": 1.0, "easing": ease_in,
        },
    ]
    return interpolate_keyframes(kf)


def gen_shock():
    """Quick jolt back + freeze — sudden surprise."""
    kf = [
        {**NEUTRAL, "duration": 0},
        # Quick pull back (fast!)
        {
            "base_yaw": 0.0,
            "base_pitch": -15.0,
            "elbow_pitch": 80.0,
            "wrist_roll": 0.0,
            "wrist_pitch": 60.0,
            "duration": 0.15, "easing": ease_out,
        },
        # Overshoot slightly
        {
            "base_yaw": 3.0,
            "base_pitch": -12.0,
            "elbow_pitch": 85.0,
            "wrist_roll": 5.0,
            "wrist_pitch": 65.0,
            "duration": 0.1, "easing": ease_out,
        },
        # Settle into frozen shock
        {
            "base_yaw": 2.0,
            "base_pitch": -14.0,
            "elbow_pitch": 82.0,
            "wrist_roll": 3.0,
            "wrist_pitch": 62.0,
            "duration": 0.2, "easing": ease_in_out,
        },
        # Hold freeze
        {
            "base_yaw": 2.0,
            "base_pitch": -14.0,
            "elbow_pitch": 82.0,
            "wrist_roll": 3.0,
            "wrist_pitch": 62.0,
            "duration": 1.5, "easing": ease_in_out,
        },
        # Slowly relax
        {**NEUTRAL, "duration": 1.5, "easing": ease_in_out},
    ]
    return interpolate_keyframes(kf)


def gen_shy():
    """Slow turn away + tilt down — bashful hiding."""
    kf = [
        {**NEUTRAL, "duration": 0},
        # Look away
        {
            "base_yaw": -30.0,
            "base_pitch": -40.0,
            "elbow_pitch": 50.0,
            "wrist_roll": 15.0,
            "wrist_pitch": 10.0,
            "duration": 0.8, "easing": ease_in_out,
        },
        # Tuck more (hiding)
        {
            "base_yaw": -35.0,
            "base_pitch": -50.0,
            "elbow_pitch": 40.0,
            "wrist_roll": 20.0,
            "wrist_pitch": 5.0,
            "duration": 0.6, "easing": ease_in,
        },
        # Peek back slightly
        {
            "base_yaw": -20.0,
            "base_pitch": -42.0,
            "elbow_pitch": 48.0,
            "wrist_roll": 10.0,
            "wrist_pitch": 15.0,
            "duration": 0.8, "easing": ease_in_out,
        },
        # Hide again
        {
            "base_yaw": -32.0,
            "base_pitch": -48.0,
            "elbow_pitch": 42.0,
            "wrist_roll": 18.0,
            "wrist_pitch": 8.0,
            "duration": 0.5, "easing": ease_in,
        },
        # Hold
        {
            "base_yaw": -32.0,
            "base_pitch": -48.0,
            "elbow_pitch": 42.0,
            "wrist_roll": 18.0,
            "wrist_pitch": 8.0,
            "duration": 1.0, "easing": ease_in_out,
        },
    ]
    return interpolate_keyframes(kf)


def gen_wake_up():
    """Rise from sleep — folded down, slowly stretch up."""
    kf = [
        # Sleeping position (folded down)
        {
            "base_yaw": 0.0,
            "base_pitch": -60.0,
            "elbow_pitch": 20.0,
            "wrist_roll": 0.0,
            "wrist_pitch": -10.0,
            "duration": 0,
        },
        # Start stirring
        {
            "base_yaw": 3.0,
            "base_pitch": -55.0,
            "elbow_pitch": 28.0,
            "wrist_roll": 5.0,
            "wrist_pitch": -5.0,
            "duration": 1.5, "easing": ease_in,
        },
        # Stretch up!
        {
            "base_yaw": -5.0,
            "base_pitch": -20.0,
            "elbow_pitch": 75.0,
            "wrist_roll": -8.0,
            "wrist_pitch": 50.0,
            "duration": 1.2, "easing": ease_in_out,
        },
        # Big stretch (overshoot)
        {
            "base_yaw": 0.0,
            "base_pitch": -15.0,
            "elbow_pitch": 85.0,
            "wrist_roll": 10.0,
            "wrist_pitch": 60.0,
            "duration": 0.8, "easing": ease_out,
        },
        # Yawn-like wobble
        {
            "base_yaw": 8.0,
            "base_pitch": -22.0,
            "elbow_pitch": 70.0,
            "wrist_roll": -5.0,
            "wrist_pitch": 40.0,
            "duration": 0.6, "easing": ease_in_out,
        },
        # Settle into awake neutral
        {**NEUTRAL, "duration": 1.0, "easing": ease_in_out},
    ]
    return interpolate_keyframes(kf)


def gen_scanning():
    """Slow pan left to right — looking around the room."""
    kf = [
        {**NEUTRAL, "duration": 0},
        # Look left
        {
            "base_yaw": -35.0,
            "base_pitch": -35.0,
            "elbow_pitch": 60.0,
            "wrist_roll": 8.0,
            "wrist_pitch": 35.0,
            "duration": 1.2, "easing": ease_in_out,
        },
        # Pause and look up-left
        {
            "base_yaw": -30.0,
            "base_pitch": -25.0,
            "elbow_pitch": 70.0,
            "wrist_roll": 5.0,
            "wrist_pitch": 45.0,
            "duration": 0.6, "easing": ease_in_out,
        },
        # Pan right
        {
            "base_yaw": 35.0,
            "base_pitch": -35.0,
            "elbow_pitch": 58.0,
            "wrist_roll": -8.0,
            "wrist_pitch": 30.0,
            "duration": 1.8, "easing": ease_in_out,
        },
        # Pause and look up-right
        {
            "base_yaw": 30.0,
            "base_pitch": -28.0,
            "elbow_pitch": 68.0,
            "wrist_roll": -5.0,
            "wrist_pitch": 42.0,
            "duration": 0.6, "easing": ease_in_out,
        },
        # Return center
        {**NEUTRAL, "duration": 1.0, "easing": ease_in_out},
    ]
    return interpolate_keyframes(kf)


# ─── Main ─────────────────────────────────────────────────────────────

ANIMATIONS = {
    "idle":          gen_idle,
    "nod":           gen_nod,
    "headshake":     gen_headshake,
    "happy_wiggle":  gen_happy_wiggle,
    "curious":       gen_curious,
    "excited":       gen_excited,
    "sad":           gen_sad,
    "shock":         gen_shock,
    "shy":           gen_shy,
    "wake_up":       gen_wake_up,
    "scanning":      gen_scanning,
}

if __name__ == "__main__":
    os.makedirs(RECORDINGS_DIR, exist_ok=True)
    print(f"Generating recordings to {RECORDINGS_DIR}/")
    for name, gen_fn in ANIMATIONS.items():
        frames = gen_fn()
        write_csv(name, frames)
    print("Done!")
