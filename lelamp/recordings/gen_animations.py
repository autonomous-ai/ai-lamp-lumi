#!/usr/bin/env python3
"""Generate custom animation CSVs for LeLamp.

Standard animations (idle, curious, nod, headshake, happy_wiggle, sad, excited,
shock, shy, scanning, wake_up) come from upstream recordings captured via
leader-follower teleop. Only custom animations not in upstream are generated here.

Rest position: yaw=3, pitch=-30, elbow=57, roll=0, wrist_pitch=18
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


def ease_in_out(t):
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        return 4 * t * t * t
    return 1 - (-2 * t + 2) ** 3 / 2


def ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def noise(t, seed=0):
    """Deterministic pseudo-noise from layered sines with prime frequencies."""
    s = seed * 1.37
    return (
        math.sin(0.17 * t + s) * 0.35
        + math.sin(0.43 * t + s * 2.1) * 0.25
        + math.sin(0.97 * t + s * 0.6) * 0.20
        + math.sin(2.13 * t + s * 3.4) * 0.12
        + math.sin(4.31 * t + s * 1.8) * 0.08
    )


def smooth_frames(frames, passes=2, max_delta=4.0):
    """Post-process smoothing: moving average + delta capping."""
    if len(frames) < 3:
        return frames

    smoothed = frames
    kernel = [1, 2, 3, 2, 1]
    k_sum = sum(kernel)
    k_half = len(kernel) // 2

    for _ in range(passes):
        new_frames = []
        for i in range(len(smoothed)):
            row = {"timestamp": smoothed[i]["timestamp"]}
            for j in JOINTS:
                if i < k_half or i >= len(smoothed) - k_half:
                    row[j] = smoothed[i][j]
                else:
                    total = 0.0
                    for ki, kw in enumerate(kernel):
                        total += smoothed[i - k_half + ki][j] * kw
                    row[j] = total / k_sum
            new_frames.append(row)
        smoothed = new_frames

    for i in range(1, len(smoothed)):
        for j in JOINTS:
            prev = smoothed[i - 1][j]
            curr = smoothed[i][j]
            delta = curr - prev
            if abs(delta) > max_delta:
                smoothed[i][j] = prev + max_delta * (1 if delta > 0 else -1)

    return smoothed


def write_csv(filename, frames, smooth=True, max_delta=4.0):
    if smooth:
        frames = smooth_frames(frames, passes=2, max_delta=max_delta)

    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp"] + JOINTS)
        writer.writeheader()
        for row in frames:
            out = {"timestamp": round(row["timestamp"], 4)}
            for j in JOINTS:
                out[j] = round(row[j], 4)
            writer.writerow(out)
    print(f"  {filename}: {len(frames)} frames ({len(frames)/FPS:.1f}s)")


# ===========================================================================
# music_groove — custom animation, not in upstream
# ===========================================================================
def gen_music_groove():
    """10s: rhythmic grooving to music — head bobs, body sways, arm flair.

    Based on ~120 BPM. Has downbeat emphasis, syncopation, and body weight shifts.
    """
    duration = 10.0
    beat = 0.5  # 120 BPM
    n = int(duration * FPS)
    frames = []

    for i in range(n + 1):
        t = i / FPS
        row = {"timestamp": t}

        fade = 1.0
        if t < 0.8:
            fade = ease_in_out(t / 0.8)
        elif t > duration - 0.8:
            fade = ease_in_out((duration - t) / 0.8)

        # Head bob — asymmetric: quick down on beat, slow rise
        beat_phase = (t % beat) / beat
        if beat_phase < 0.25:
            bob = ease_out(beat_phase / 0.25)
        else:
            bob = 1.0 - ease_in_out((beat_phase - 0.25) / 0.75)

        # Every 4th beat: bigger bob (downbeat emphasis)
        bar_phase = (t % (beat * 4)) / (beat * 4)
        downbeat = 1.0 + 0.4 * math.exp(-((bar_phase) / 0.05) ** 2)

        # Body sway — half-time feel
        sway = math.sin(2 * math.pi * t / (beat * 4))
        sway2 = math.sin(2 * math.pi * t / (beat * 8) + 0.8) * 0.4

        # Syncopation on wrist — off-beat accents
        offbeat_phase = ((t + beat * 0.5) % beat) / beat
        if offbeat_phase < 0.2:
            synco = ease_out(offbeat_phase / 0.2)
        else:
            synco = 1.0 - ease_in_out((offbeat_phase - 0.2) / 0.8)

        for j in JOINTS:
            val = REST[j]

            if j == "base_yaw.pos":
                val += (sway * 12.0 + sway2 * 5.0) * fade
            elif j == "base_pitch.pos":
                val += bob * downbeat * 4.0 * fade
            elif j == "elbow_pitch.pos":
                val += bob * downbeat * 7.0 * fade
                val += sway * 3.0 * fade
            elif j == "wrist_roll.pos":
                val += -sway * 8.0 * fade  # counter sway
                val += synco * 5.0 * fade  # off-beat flair
            elif j == "wrist_pitch.pos":
                val += bob * downbeat * 6.0 * fade
                val += synco * 3.0 * fade

            val += noise(t, hash(j) % 13) * 0.4 * fade
            row[j] = val
        frames.append(row)

    write_csv("music_groove.csv", frames)


# ===========================================================================
ALL = {
    "music_groove": gen_music_groove,
}

if __name__ == "__main__":
    import sys
    targets = sys.argv[1:] if len(sys.argv) > 1 else list(ALL.keys())
    for name in targets:
        if name not in ALL:
            print(f"Unknown: {name}. Available: {', '.join(ALL.keys())}")
            continue
        ALL[name]()
    print("Done.")
