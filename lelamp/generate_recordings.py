#!/usr/bin/env python3
"""Generate expressive animation CSVs for LeLamp.

Safety constraints derived from original hardware recordings:
- Max velocity: 5 deg/frame (150 deg/s at 30 FPS)
- All positions clamped to JOINT_LIMITS
- Poses reference ranges observed in original hardware captures

Usage:
    python generate_recordings.py
"""

import csv
import math
import os

RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "recordings")
FPS = 30
HEADER = ["timestamp", "base_yaw.pos", "base_pitch.pos", "elbow_pitch.pos", "wrist_roll.pos", "wrist_pitch.pos"]
JOINTS = ["base_yaw", "base_pitch", "elbow_pitch", "wrist_roll", "wrist_pitch"]

# Max degrees change per frame — derived from original recordings (max ~7, we use 5 for safety)
MAX_VEL = 5.0

# Safe joint limits (must match animation_service.py)
JOINT_LIMITS = {
    "base_yaw":     (-78.0,  78.0),
    "base_pitch":   (-78.0,  80.0),
    "elbow_pitch":  (-25.0,  97.0),
    "wrist_roll":   (-68.0,  68.0),
    "wrist_pitch":  (-25.0,  72.0),
}

# Neutral pose (from idle recording center)
NEUTRAL = {
    "base_yaw": 0.0,
    "base_pitch": -29.0,
    "elbow_pitch": 54.0,
    "wrist_roll": 3.0,
    "wrist_pitch": 25.0,
}


def clamp_joint(joint: str, value: float) -> float:
    lo, hi = JOINT_LIMITS[joint]
    return max(lo, min(hi, value))


def velocity_limit(frames: list[dict]) -> list[dict]:
    """Enforce max velocity between consecutive frames.

    If a joint moves more than MAX_VEL per frame, insert extra frames
    to slow the transition down.
    """
    if len(frames) < 2:
        return frames

    result = [frames[0]]
    for i in range(1, len(frames)):
        prev = result[-1]
        target = frames[i]

        # Find how many frames we need for the biggest joint delta
        max_delta = 0
        for j in JOINTS:
            delta = abs(target[j] - prev[j])
            if delta > max_delta:
                max_delta = delta

        n_steps = max(1, math.ceil(max_delta / MAX_VEL))

        for step in range(1, n_steps + 1):
            t = step / n_steps
            interp = {}
            for j in JOINTS:
                interp[j] = prev[j] + (target[j] - prev[j]) * t
            result.append(interp)

    return result


def add_timestamps(frames: list[dict]) -> list[dict]:
    """Add timestamp field to each frame."""
    dt = 1.0 / FPS
    out = []
    for i, f in enumerate(frames):
        row = {"timestamp": round(i * dt, 6)}
        for j in JOINTS:
            row[f"{j}.pos"] = clamp_joint(j, f[j])
        out.append(row)
    return out


def write_csv(name: str, frames: list[dict]):
    timed = add_timestamps(frames)
    path = os.path.join(RECORDINGS_DIR, f"{name}.csv")
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writeheader()
        for frame in timed:
            writer.writerow(frame)
    duration = len(timed) / FPS
    print(f"  {name}.csv  ({len(timed)} frames, {duration:.1f}s)")


def hold(pose: dict, n_frames: int) -> list[dict]:
    """Hold a pose for n frames."""
    return [dict(pose) for _ in range(n_frames)]


def make_keyframes(keyframes: list[dict]) -> list[dict]:
    """Convert keyframes to velocity-limited frame sequence.

    Each keyframe is a joint dict. Velocity limiting auto-inserts
    intermediate frames as needed.
    """
    return velocity_limit(keyframes)


def oscillate(base: dict, mods: dict, cycles: float, frames_per_cycle: int) -> list[dict]:
    """Sine oscillation. mods = {joint: amplitude}."""
    total = int(cycles * frames_per_cycle)
    frames = []
    for i in range(total):
        t = i / frames_per_cycle
        f = {}
        for j in JOINTS:
            amp = mods.get(j, 0)
            f[j] = base[j] + amp * math.sin(2 * math.pi * t)
        frames.append(f)
    return velocity_limit(frames)


# ─── Safe poses (from original recordings) ─────────────────────────
# These are positions proven safe on real hardware

POSE_IDLE = NEUTRAL.copy()

POSE_UP = {  # lamp extended upward (from wake_up/shock originals)
    "base_yaw": 0.0,
    "base_pitch": -42.0,
    "elbow_pitch": 72.0,
    "wrist_roll": 3.0,
    "wrist_pitch": 50.0,
}

POSE_DOWN = {  # lamp drooped (from sad original)
    "base_yaw": 3.0,
    "base_pitch": -45.0,
    "elbow_pitch": 67.0,
    "wrist_roll": 3.5,
    "wrist_pitch": 25.0,
}

POSE_FOLDED = {  # fully folded (from wake_up start)
    "base_yaw": 2.0,
    "base_pitch": -42.0,
    "elbow_pitch": 79.0,
    "wrist_roll": 9.0,
    "wrist_pitch": -5.0,
}

POSE_CURIOUS_TILT = {  # head tilted, looking (from curious original)
    "base_yaw": 25.0,
    "base_pitch": -29.0,
    "elbow_pitch": 54.0,
    "wrist_roll": 3.0,
    "wrist_pitch": 25.0,
}

POSE_LOOK_LEFT = {
    "base_yaw": -20.0,
    "base_pitch": -29.0,
    "elbow_pitch": 54.0,
    "wrist_roll": 5.0,
    "wrist_pitch": 25.0,
}

POSE_LOOK_RIGHT = {
    "base_yaw": 20.0,
    "base_pitch": -29.0,
    "elbow_pitch": 54.0,
    "wrist_roll": -5.0,
    "wrist_pitch": 25.0,
}

POSE_SHY = {  # from shy original — turned away, tucked
    "base_yaw": 12.0,
    "base_pitch": -51.0,
    "elbow_pitch": 77.0,
    "wrist_roll": 1.5,
    "wrist_pitch": 69.0,
}

POSE_EXCITED_UP = {  # from excited original — perked up
    "base_yaw": 12.0,
    "base_pitch": -51.0,
    "elbow_pitch": 72.0,
    "wrist_roll": 4.0,
    "wrist_pitch": 37.0,
}


# ─── Animation Definitions ────────────────────────────────────────────

def gen_idle():
    """Gentle breathing — subtle micro-movements around neutral."""
    return oscillate(
        NEUTRAL,
        mods={
            "base_yaw": 3.0,
            "base_pitch": 1.5,
            "elbow_pitch": 1.0,
            "wrist_roll": 2.0,
            "wrist_pitch": 2.0,
        },
        cycles=3,
        frames_per_cycle=100,  # ~3.3s per cycle, total ~10s
    )


def gen_nod():
    """Three clear nods — pitch dips with slight wrist follow."""
    frames = hold(NEUTRAL, 10)
    nod_down = {**NEUTRAL, "base_pitch": -38.0, "wrist_pitch": 18.0}
    nod_up = {**NEUTRAL, "base_pitch": -24.0, "wrist_pitch": 30.0}
    for _ in range(3):
        frames += make_keyframes([frames[-1], nod_down])
        frames += hold(nod_down, 3)
        frames += make_keyframes([nod_down, nod_up])
        frames += hold(nod_up, 3)
    frames += make_keyframes([frames[-1], NEUTRAL])
    frames += hold(NEUTRAL, 10)
    return frames


def gen_headshake():
    """Three clear 'no' turns — yaw swings with counter-roll."""
    frames = hold(NEUTRAL, 10)
    left = {**NEUTRAL, "base_yaw": -22.0, "wrist_roll": 10.0}
    right = {**NEUTRAL, "base_yaw": 22.0, "wrist_roll": -10.0}
    for i in range(3):
        target = left if i % 2 == 0 else right
        frames += make_keyframes([frames[-1], target])
        frames += hold(target, 4)
    frames += make_keyframes([frames[-1], NEUTRAL])
    frames += hold(NEUTRAL, 10)
    return frames


def gen_happy_wiggle():
    """Bouncy side-to-side dance — alternating sway."""
    frames = hold(NEUTRAL, 5)
    sway_l = {
        "base_yaw": -15.0,
        "base_pitch": -33.0,
        "elbow_pitch": 58.0,
        "wrist_roll": 10.0,
        "wrist_pitch": 22.0,
    }
    sway_r = {
        "base_yaw": 15.0,
        "base_pitch": -27.0,
        "elbow_pitch": 62.0,
        "wrist_roll": -10.0,
        "wrist_pitch": 28.0,
    }
    for i in range(4):
        target = sway_l if i % 2 == 0 else sway_r
        frames += make_keyframes([frames[-1], target])
        frames += hold(target, 3)
    frames += make_keyframes([frames[-1], NEUTRAL])
    frames += hold(NEUTRAL, 10)
    return frames


def gen_curious():
    """Lean forward + head tilt — "what's that?" """
    frames = hold(NEUTRAL, 10)

    # Tilt and lean
    look = {
        "base_yaw": 20.0,
        "base_pitch": -40.0,
        "elbow_pitch": 62.0,
        "wrist_roll": -12.0,
        "wrist_pitch": 45.0,
    }
    # Lean closer
    closer = {
        "base_yaw": 18.0,
        "base_pitch": -45.0,
        "elbow_pitch": 66.0,
        "wrist_roll": -15.0,
        "wrist_pitch": 52.0,
    }
    # Straighten slightly
    hold_gaze = {
        "base_yaw": 12.0,
        "base_pitch": -42.0,
        "elbow_pitch": 63.0,
        "wrist_roll": -8.0,
        "wrist_pitch": 48.0,
    }

    frames += make_keyframes([NEUTRAL, look])
    frames += hold(look, 15)
    frames += make_keyframes([look, closer])
    frames += hold(closer, 20)
    frames += make_keyframes([closer, hold_gaze])
    frames += hold(hold_gaze, 30)
    frames += make_keyframes([hold_gaze, NEUTRAL])
    frames += hold(NEUTRAL, 10)
    return frames


def gen_excited():
    """Quick bouncy oscillations — energy!"""
    frames = hold(NEUTRAL, 5)
    bounce_up = {
        "base_yaw": 10.0,
        "base_pitch": -24.0,
        "elbow_pitch": 65.0,
        "wrist_roll": 12.0,
        "wrist_pitch": 35.0,
    }
    bounce_down = {
        "base_yaw": -10.0,
        "base_pitch": -35.0,
        "elbow_pitch": 48.0,
        "wrist_roll": -12.0,
        "wrist_pitch": 18.0,
    }
    for i in range(5):
        target = bounce_up if i % 2 == 0 else bounce_down
        frames += make_keyframes([frames[-1], target])
        frames += hold(target, 2)
    frames += make_keyframes([frames[-1], NEUTRAL])
    frames += hold(NEUTRAL, 15)
    return frames


def gen_sad():
    """Slow droop — lamp wilts, holds, sighs."""
    frames = hold(NEUTRAL, 15)

    droop1 = {
        "base_yaw": -3.0,
        "base_pitch": -40.0,
        "elbow_pitch": 45.0,
        "wrist_roll": -3.0,
        "wrist_pitch": 12.0,
    }
    droop2 = {
        "base_yaw": -6.0,
        "base_pitch": -50.0,
        "elbow_pitch": 35.0,
        "wrist_roll": -6.0,
        "wrist_pitch": 3.0,
    }
    # Small sigh lift
    sigh = {
        "base_yaw": -4.0,
        "base_pitch": -46.0,
        "elbow_pitch": 40.0,
        "wrist_roll": -4.0,
        "wrist_pitch": 8.0,
    }

    frames += make_keyframes([NEUTRAL, droop1])
    frames += hold(droop1, 20)
    frames += make_keyframes([droop1, droop2])
    frames += hold(droop2, 45)
    frames += make_keyframes([droop2, sigh])
    frames += hold(sigh, 15)
    frames += make_keyframes([sigh, droop2])
    frames += hold(droop2, 30)
    return frames


def gen_shock():
    """Quick pull-back + freeze — startled."""
    frames = hold(NEUTRAL, 5)

    # Pull back (velocity limiter will auto-slow this)
    shocked = {
        "base_yaw": 2.0,
        "base_pitch": -20.0,
        "elbow_pitch": 78.0,
        "wrist_roll": 5.0,
        "wrist_pitch": 58.0,
    }
    # Settle slightly
    frozen = {
        "base_yaw": 1.0,
        "base_pitch": -22.0,
        "elbow_pitch": 75.0,
        "wrist_roll": 3.0,
        "wrist_pitch": 55.0,
    }

    frames += make_keyframes([NEUTRAL, shocked])
    frames += hold(shocked, 5)
    frames += make_keyframes([shocked, frozen])
    frames += hold(frozen, 50)  # freeze
    frames += make_keyframes([frozen, NEUTRAL])
    frames += hold(NEUTRAL, 10)
    return frames


def gen_shy():
    """Turn away + tuck, peek back, hide again."""
    frames = hold(NEUTRAL, 10)

    hide = {
        "base_yaw": -25.0,
        "base_pitch": -38.0,
        "elbow_pitch": 48.0,
        "wrist_roll": 12.0,
        "wrist_pitch": 12.0,
    }
    peek = {
        "base_yaw": -12.0,
        "base_pitch": -33.0,
        "elbow_pitch": 52.0,
        "wrist_roll": 6.0,
        "wrist_pitch": 20.0,
    }
    hide_more = {
        "base_yaw": -28.0,
        "base_pitch": -40.0,
        "elbow_pitch": 45.0,
        "wrist_roll": 15.0,
        "wrist_pitch": 8.0,
    }

    frames += make_keyframes([NEUTRAL, hide])
    frames += hold(hide, 20)
    frames += make_keyframes([hide, peek])
    frames += hold(peek, 15)
    frames += make_keyframes([peek, hide_more])
    frames += hold(hide_more, 30)
    return frames


def gen_wake_up():
    """Rise from folded sleep position, stretch, settle."""
    # Start folded
    sleeping = {
        "base_yaw": 0.0,
        "base_pitch": -55.0,
        "elbow_pitch": 30.0,
        "wrist_roll": 2.0,
        "wrist_pitch": -5.0,
    }
    stirring = {
        "base_yaw": 3.0,
        "base_pitch": -48.0,
        "elbow_pitch": 40.0,
        "wrist_roll": 5.0,
        "wrist_pitch": 5.0,
    }
    stretch = {
        "base_yaw": -3.0,
        "base_pitch": -25.0,
        "elbow_pitch": 72.0,
        "wrist_roll": -5.0,
        "wrist_pitch": 48.0,
    }
    yawn = {
        "base_yaw": 5.0,
        "base_pitch": -28.0,
        "elbow_pitch": 65.0,
        "wrist_roll": 0.0,
        "wrist_pitch": 35.0,
    }

    frames = hold(sleeping, 20)
    frames += make_keyframes([sleeping, stirring])
    frames += hold(stirring, 15)
    frames += make_keyframes([stirring, stretch])
    frames += hold(stretch, 20)
    frames += make_keyframes([stretch, yawn])
    frames += hold(yawn, 10)
    frames += make_keyframes([yawn, NEUTRAL])
    frames += hold(NEUTRAL, 10)
    return frames


def gen_scanning():
    """Slow pan left → right → center, looking around."""
    frames = hold(NEUTRAL, 10)

    look_left = {
        "base_yaw": -30.0,
        "base_pitch": -32.0,
        "elbow_pitch": 58.0,
        "wrist_roll": 6.0,
        "wrist_pitch": 32.0,
    }
    look_up_left = {
        "base_yaw": -25.0,
        "base_pitch": -26.0,
        "elbow_pitch": 65.0,
        "wrist_roll": 4.0,
        "wrist_pitch": 40.0,
    }
    look_right = {
        "base_yaw": 30.0,
        "base_pitch": -32.0,
        "elbow_pitch": 56.0,
        "wrist_roll": -6.0,
        "wrist_pitch": 28.0,
    }
    look_up_right = {
        "base_yaw": 25.0,
        "base_pitch": -27.0,
        "elbow_pitch": 63.0,
        "wrist_roll": -4.0,
        "wrist_pitch": 38.0,
    }

    frames += make_keyframes([NEUTRAL, look_left])
    frames += hold(look_left, 15)
    frames += make_keyframes([look_left, look_up_left])
    frames += hold(look_up_left, 10)
    frames += make_keyframes([look_up_left, look_right])
    frames += hold(look_right, 15)
    frames += make_keyframes([look_right, look_up_right])
    frames += hold(look_up_right, 10)
    frames += make_keyframes([look_up_right, NEUTRAL])
    frames += hold(NEUTRAL, 10)
    return frames


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
    print(f"Safety: max {MAX_VEL} deg/frame ({MAX_VEL * FPS} deg/s)")
    print()
    for name, gen_fn in ANIMATIONS.items():
        frames = gen_fn()
        write_csv(name, frames)
    print("\nDone!")
