#!/usr/bin/env python3
"""Generate lifelike animation CSVs for LeLamp.

Motion principles applied:
  - Anticipation: slight opposite pull before main action
  - Overshoot + settle: go past target, bounce back
  - Staggered joints: base moves first, extremities follow with delay
  - Variable rhythm: not perfectly periodic
  - Weight: heavier joints (base) move slower, lighter (wrist) snappier
  - Micro-fidgets: small unexpected movements during holds

Joint limits:
  base_yaw: -55..65 | base_pitch: -70..-15 | elbow_pitch: 35..98
  wrist_roll: -50..45 | wrist_pitch: -25..72

Rest: yaw=3, pitch=-30, elbow=57, roll=0, wrist_pitch=18
"""

import csv
import math
import os

FPS = 30
DT = 1.0 / FPS
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

REST = {
    "base_yaw.pos": 3.0,
    "base_pitch.pos": -30.0,
    "elbow_pitch.pos": 57.0,
    "wrist_roll.pos": 0.0,
    "wrist_pitch.pos": 18.0,
}
JOINTS = list(REST.keys())

# Joint "weight" — heavier = slower response, lighter = snappier
JOINT_WEIGHT = {
    "base_yaw.pos": 1.0,       # heavy base
    "base_pitch.pos": 0.9,
    "elbow_pitch.pos": 0.7,
    "wrist_roll.pos": 0.4,     # light wrist
    "wrist_pitch.pos": 0.4,
}

# Stagger delay per joint (seconds) — base leads, wrist follows
JOINT_DELAY = {
    "base_yaw.pos": 0.0,
    "base_pitch.pos": 0.03,
    "elbow_pitch.pos": 0.07,
    "wrist_roll.pos": 0.12,
    "wrist_pitch.pos": 0.10,
}

LIMITS = {
    "base_yaw.pos": (-55, 65),
    "base_pitch.pos": (-70, -15),
    "elbow_pitch.pos": (35, 98),
    "wrist_roll.pos": (-50, 45),
    "wrist_pitch.pos": (-25, 72),
}


def clamp(joint, val):
    lo, hi = LIMITS[joint]
    return max(lo, min(hi, val))


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


def overshoot_ease(t, overshoot=0.15):
    """Ease-in-out with overshoot at the end — goes past 1.0 then settles."""
    t = max(0.0, min(1.0, t))
    if t < 0.7:
        return ease_in_out(t / 0.7) * (1.0 + overshoot)
    else:
        return (1.0 + overshoot) - overshoot * ease_in_out((t - 0.7) / 0.3)


def anticipation_ease(t, antic=0.08):
    """Pull back slightly before moving forward."""
    t = max(0.0, min(1.0, t))
    if t < 0.15:
        return -antic * ease_in_out(t / 0.15)
    else:
        p = (t - 0.15) / 0.85
        return -antic * (1 - ease_in_out(min(p * 2, 1.0))) + overshoot_ease(p) * (1 + antic)


def staggered_t(t, joint):
    """Apply joint-specific time delay."""
    return max(0.0, t - JOINT_DELAY[joint])


def fidget(t, seed=0):
    """Occasional small unexpected movements — not constant."""
    # Irregular pulses using product of sines (creates gaps)
    gate = max(0, math.sin(0.7 * t + seed) * math.sin(0.3 * t + seed * 2))
    return gate * noise(t * 3, seed) * 2.0


def smooth_frames(frames, passes=2, max_delta=2.0):
    """Post-process smoothing: Gaussian-like moving average + delta capping.

    1. Multi-pass moving average (window=5) smooths high-freq jitter
    2. Delta cap ensures no frame-to-frame jump exceeds max_delta degrees
    3. Preserves first and last frame exactly (for clean blend with idle)
    """
    if len(frames) < 3:
        return frames

    smoothed = frames

    # Pass 1+2: Weighted moving average (1-2-3-2-1 kernel, normalized)
    kernel = [1, 2, 3, 2, 1]
    k_sum = sum(kernel)
    k_half = len(kernel) // 2

    for _ in range(passes):
        new_frames = []
        for i in range(len(smoothed)):
            row = {"timestamp": smoothed[i]["timestamp"]}
            for j in JOINTS:
                if i < k_half or i >= len(smoothed) - k_half:
                    # Keep edges unchanged
                    row[j] = smoothed[i][j]
                else:
                    total = 0.0
                    for ki, kw in enumerate(kernel):
                        total += smoothed[i - k_half + ki][j] * kw
                    row[j] = total / k_sum
            new_frames.append(row)
        smoothed = new_frames

    # Pass 3: Delta capping — limit max change per frame
    for i in range(1, len(smoothed)):
        for j in JOINTS:
            prev = smoothed[i - 1][j]
            curr = smoothed[i][j]
            delta = curr - prev
            if abs(delta) > max_delta:
                smoothed[i][j] = prev + max_delta * (1 if delta > 0 else -1)

    return smoothed


def write_csv(filename, frames, smooth=True, max_delta=2.0):
    """Write frames to CSV with optional smoothing.

    Args:
        smooth: Apply smoothing filter (default True)
        max_delta: Max degrees change per frame (default 2.0°/frame = 60°/s at 30fps)
    """
    if smooth:
        frames = smooth_frames(frames, passes=2, max_delta=max_delta)

    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp"] + JOINTS)
        writer.writeheader()
        for row in frames:
            out = {"timestamp": round(row["timestamp"], 4)}
            for j in JOINTS:
                out[j] = round(clamp(j, row[j]), 1)
            writer.writerow(out)
    print(f"  {filename}: {len(frames)} frames ({len(frames)/FPS:.1f}s)")


# ===========================================================================
# IDLE — the most important animation. Must feel truly alive.
# ===========================================================================
def gen_idle():
    """60s: layered organic motion — breathing, weight shifts, glances, fidgets.

    Not a simple sine loop. Has distinct "phrases" of movement:
    - Breathing base rhythm (always)
    - Slow weight shifts (body leans one way then other)
    - Periodic glances (head turns to look at something)
    - Random-ish fidgets (small twitches)
    """
    duration = 60.0
    n = int(duration * FPS)
    frames = []

    for i in range(n):
        t = i / FPS
        row = {"timestamp": t}

        # Fade at loop boundaries
        fade = 1.0
        if t < 2.0:
            fade = ease_in_out(t / 2.0)
        elif t > duration - 2.0:
            fade = ease_in_out((duration - t) / 2.0)

        # Layer 1: Breathing — asymmetric (slow inhale, faster exhale)
        breath_phase = (t % 4.0) / 4.0  # 4s breath cycle
        if breath_phase < 0.6:
            # Slow inhale
            breath = ease_in_out(breath_phase / 0.6)
        else:
            # Faster exhale
            breath = 1.0 - ease_out((breath_phase - 0.6) / 0.4)

        # Layer 2: Weight shifts — body slowly leans, period ~12-15s
        weight_yaw = 10.0 * math.sin(2 * math.pi * t / 13.0)
        weight_pitch = 4.0 * math.sin(2 * math.pi * t / 11.0 + 0.7)

        # Layer 3: Glances — head turns to "look at something"
        # Two different glance rhythms layered
        glance_yaw = (
            8.0 * math.sin(2 * math.pi * t / 8.5) *
            max(0, math.sin(2 * math.pi * t / 17.0))  # gated — only happens sometimes
        )
        glance_pitch = (
            5.0 * math.sin(2 * math.pi * t / 7.0 + 1.5) *
            max(0, math.sin(2 * math.pi * t / 14.0 + 0.5))
        )

        # Layer 4: Fidgets
        fidget_scale = max(0, math.sin(2 * math.pi * t / 23.0))  # comes and goes

        for j in JOINTS:
            val = REST[j]

            # Breathing — pitch and elbow
            if j == "base_pitch.pos":
                val += 3.5 * breath * fade
            elif j == "elbow_pitch.pos":
                val += -4.0 * breath * fade
            elif j == "wrist_pitch.pos":
                val += 3.0 * breath * fade

            # Weight shifts
            if j == "base_yaw.pos":
                val += weight_yaw * fade
            elif j == "base_pitch.pos":
                val += weight_pitch * fade
            elif j == "elbow_pitch.pos":
                val += weight_pitch * 0.6 * fade
            elif j == "wrist_roll.pos":
                val += -weight_yaw * 0.3 * fade  # counter-roll

            # Glances
            if j == "base_yaw.pos":
                val += glance_yaw * fade
            elif j == "wrist_pitch.pos":
                val += glance_pitch * fade
            elif j == "wrist_roll.pos":
                val += glance_yaw * 0.25 * fade  # head tilts with glance

            # Fidgets
            val += fidget(t, seed=hash(j) % 17) * fidget_scale * fade

            row[j] = val
        frames.append(row)

    write_csv("idle.csv", frames)


# ===========================================================================
# Pose-based animations with anticipation + overshoot
# ===========================================================================
def gen_pose_animation(filename, duration, target_offset,
                       approach_time=1.5, return_time=None,
                       use_anticipation=True, overshoot_amount=0.12,
                       hold_behavior=None, max_delta=2.0):
    """Generic pose animation with lifelike motion principles.

    Args:
        hold_behavior: fn(joint, hold_t, hold_duration) -> float
    """
    if return_time is None:
        return_time = approach_time * 1.3

    hold_start = approach_time
    hold_end = duration - return_time
    hold_dur = hold_end - hold_start

    n = int(duration * FPS)
    frames = []

    for i in range(n + 1):
        t = i / FPS
        row = {"timestamp": t}

        for j in JOINTS:
            st = staggered_t(t, j)
            offset = target_offset.get(j, 0.0)

            if st <= hold_start:
                raw_p = st / hold_start
                if use_anticipation and abs(offset) > 3:
                    p = anticipation_ease(raw_p, antic=0.08)
                else:
                    p = overshoot_ease(raw_p, overshoot_amount)
            elif st <= hold_end:
                p = 1.0
            else:
                raw_p = (st - hold_end) / return_time
                p = 1.0 - ease_in_out(raw_p)

            val = REST[j] + offset * p

            # Hold behavior — fidgets, sway, etc
            if hold_start < st <= hold_end and hold_behavior:
                ht = st - hold_start
                val += hold_behavior(j, ht, hold_dur)

            # Subtle life during transitions
            if st <= hold_start or st > hold_end:
                val += noise(t, seed=hash(j) % 11) * 0.4

            row[j] = val
        frames.append(row)

    write_csv(filename, frames, max_delta=max_delta)


def gen_curious():
    """6s: gentle lean-in with slight head turn. Reduced amplitude to avoid mechanical strain."""
    offset = {
        "base_yaw.pos": 10.0,
        "base_pitch.pos": 2.0,
        "elbow_pitch.pos": -3.0,
        "wrist_roll.pos": 5.0,
        "wrist_pitch.pos": -5.0,
    }

    def hold(j, ht, dur):
        # Gentle scanning
        scan = 2.5 * math.sin(2 * math.pi * ht / 2.5)
        if j == "base_yaw.pos":
            return scan
        if j == "wrist_pitch.pos":
            return noise(ht, 3) * 1.0
        return noise(ht, hash(j) % 9) * 0.5

    gen_pose_animation("curious.csv", 6.0, offset, approach_time=2.0,
                       use_anticipation=False, overshoot_amount=0.05,
                       hold_behavior=hold)


def gen_nod():
    """5s: two distinct nods with anticipation (slight head-up before dipping).

    Natural nod: lift slightly → dip down → return. Two nods, second smaller.
    """
    duration = 5.0
    n = int(duration * FPS)
    frames = []

    # Nod keyframes: (center_time, amplitude, width)
    # Slight lift before each nod (anticipation built into the curve)
    nods = [(1.2, 1.0, 0.45), (2.5, 0.7, 0.40)]

    for i in range(n + 1):
        t = i / FPS
        row = {"timestamp": t}

        # Fade
        fade = 1.0
        if t < 0.4:
            fade = ease_in_out(t / 0.4)
        elif t > duration - 0.8:
            fade = ease_in_out((duration - t) / 0.8)

        # Sum nod impulses with anticipation
        nod_down = 0.0
        nod_up = 0.0  # anticipation lift
        for tc, amp, w in nods:
            # Anticipation: slight lift before the nod
            antic_t = tc - w * 0.8
            antic_d = (t - antic_t) / (w * 0.5)
            nod_up += amp * 0.3 * math.exp(-antic_d * antic_d * 3) if antic_d > -1 else 0

            # Main nod down
            d = (t - tc) / w
            nod_down += amp * math.exp(-d * d * 2.5)

        for j in JOINTS:
            st = staggered_t(t, j)
            val = REST[j]

            if j == "wrist_pitch.pos":
                val += (-nod_up * 6.0 + nod_down * 22.0) * fade
            elif j == "elbow_pitch.pos":
                val += (-nod_up * 3.0 + nod_down * 10.0) * fade
            elif j == "base_pitch.pos":
                val += nod_down * 3.0 * fade
            elif j == "base_yaw.pos":
                # Slight yaw drift during nod — not perfectly straight
                val += noise(t, 5) * 2.0 * fade
            else:
                val += noise(t, hash(j) % 13) * 1.0 * fade

            row[j] = val
        frames.append(row)

    write_csv("nod.csv", frames)


def gen_headshake():
    """5s: "no no no" with damping. First shake biggest, progressively smaller.

    Natural headshake has slight pitch lean and wrist counter-roll.
    """
    duration = 5.0
    n = int(duration * FPS)
    frames = []

    for i in range(n + 1):
        t = i / FPS
        row = {"timestamp": t}

        fade = 1.0
        if t < 0.5:
            fade = ease_in_out(t / 0.5)
        elif t > duration - 0.8:
            fade = ease_in_out((duration - t) / 0.8)

        # Damped oscillation — not perfectly regular period
        # Period slightly increases (slowing down) as amplitude decreases
        period = 0.8 + 0.1 * t  # starts fast, slows
        decay = math.exp(-0.7 * t)
        phase = 0
        # Accumulate phase with variable period
        # Use integral approximation
        freq = 1.0 / period
        shake = math.sin(2 * math.pi * freq * t + 0.3 * math.sin(t)) * decay

        for j in JOINTS:
            val = REST[j]
            if j == "base_yaw.pos":
                val += 25.0 * shake * fade
            elif j == "wrist_roll.pos":
                # Counter-roll — wrist opposes head direction
                val += -7.0 * shake * fade
            elif j == "base_pitch.pos":
                # Lean forward slightly during shake (emphasis)
                val += 2.5 * abs(shake) * fade
            elif j == "wrist_pitch.pos":
                # Head bobs slightly with each shake
                val += 3.0 * abs(shake) * math.sin(2 * math.pi * t / 0.4) * fade * decay
            else:
                val += noise(t, hash(j) % 7) * 0.6 * fade
            row[j] = val
        frames.append(row)

    write_csv("headshake.csv", frames)


def gen_happy_wiggle():
    """5s: joyful bouncy wiggle — like a dog seeing its owner.

    NOT a simple sine. Irregular bouncy rhythm with weight shifts
    and occasional bigger movements.
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
        elif t > duration - 0.6:
            fade = ease_in_out((duration - t) / 0.6)

        # Bouncy rhythm — alternating big and small bounces
        bounce_period = 0.35  # ~170 BPM, energetic
        bounce_phase = (t % bounce_period) / bounce_period
        # Asymmetric bounce: quick up, slower down
        if bounce_phase < 0.3:
            bounce = ease_out(bounce_phase / 0.3)
        else:
            bounce = 1.0 - ease_in_out((bounce_phase - 0.3) / 0.7)

        # Alternating bigger/smaller — every other bounce is bigger
        cycle = int(t / bounce_period)
        bounce_scale = 1.0 if cycle % 2 == 0 else 0.6

        # Body sway — slower than bounce
        sway = math.sin(2 * math.pi * t / 0.7)
        sway2 = math.sin(2 * math.pi * t / 1.4 + 0.8) * 0.5

        # Excitement decay — starts energetic, calms slightly
        energy = 1.0 - 0.2 * (t / duration)

        for j in JOINTS:
            val = REST[j]
            if j == "base_yaw.pos":
                val += (sway * 14.0 + sway2 * 6.0) * fade * energy
            elif j == "base_pitch.pos":
                val += bounce * bounce_scale * 5.0 * fade * energy
            elif j == "elbow_pitch.pos":
                val += bounce * bounce_scale * 8.0 * fade * energy
                val += sway * 3.0 * fade  # arm follows sway
            elif j == "wrist_roll.pos":
                val += -sway * 10.0 * fade * energy  # counter sway
                val += bounce * bounce_scale * 3.0 * fade
            elif j == "wrist_pitch.pos":
                val += bounce * bounce_scale * 7.0 * fade * energy
                val += sway2 * 4.0 * fade

            val += noise(t * 2, hash(j) % 11) * 0.5 * fade
            row[j] = val
        frames.append(row)

    write_csv("happy_wiggle.csv", frames)


def gen_sad():
    """7s: slow dejected droop. Everything sags with weight.

    Anticipation: slight lift (hopeful?) before drooping.
    Hold: slow heavy breathing, occasional small sigh (elbow drop).
    Return: reluctant, slow.
    """
    offset = {
        "base_yaw.pos": -10.0,
        "base_pitch.pos": -15.0,
        "elbow_pitch.pos": -12.0,
        "wrist_roll.pos": -8.0,
        "wrist_pitch.pos": -12.0,
    }

    def hold(j, ht, dur):
        # Heavy slow breathing
        breath_phase = (ht % 3.5) / 3.5
        if breath_phase < 0.65:
            breath = ease_in_out(breath_phase / 0.65)
        else:
            breath = 1.0 - ease_out((breath_phase - 0.65) / 0.35)

        # Occasional sigh — small extra droop
        sigh = 3.0 * math.exp(-((ht - 1.8) / 0.5) ** 2)

        if j == "base_pitch.pos":
            return breath * 2.0 - sigh
        if j == "elbow_pitch.pos":
            return -breath * 1.5 - sigh * 0.8
        if j == "wrist_pitch.pos":
            return breath * 1.0 - sigh * 0.5
        return noise(ht, hash(j) % 7) * 0.5

    gen_pose_animation("sad.csv", 7.0, offset, approach_time=2.5,
                       return_time=2.5, overshoot_amount=0.05,
                       hold_behavior=hold)


def gen_excited():
    """4s: quick alert rise with bouncing energy.

    Fast approach with overshoot. Hold has visible vibrating excitement.
    """
    offset = {
        "base_yaw.pos": 5.0,
        "base_pitch.pos": 14.0,
        "elbow_pitch.pos": 20.0,
        "wrist_roll.pos": 5.0,
        "wrist_pitch.pos": 28.0,
    }

    def hold(j, ht, dur):
        # Excited trembling — high freq, moderate amp, slowly decaying
        tremble = math.sin(2 * math.pi * ht * 5.0) * 2.5 * math.exp(-0.8 * ht)
        # Plus bouncing
        bounce = abs(math.sin(2 * math.pi * ht * 3.0)) * 2.0 * math.exp(-0.5 * ht)

        if j == "elbow_pitch.pos":
            return tremble + bounce * 1.5
        if j == "wrist_pitch.pos":
            return tremble * 0.8 + bounce
        if j == "base_yaw.pos":
            return tremble * 0.5
        if j == "base_pitch.pos":
            return bounce
        return tremble * 0.3

    gen_pose_animation("excited.csv", 4.0, offset, approach_time=0.6,
                       return_time=1.2, overshoot_amount=0.18,
                       hold_behavior=hold)


def gen_shock():
    """4s: fast recoil with freeze + tremor.

    Very fast approach (startle reflex). Tremor during freeze.
    Slow cautious return (checking if it's safe).
    """
    offset = {
        "base_yaw.pos": -5.0,
        "base_pitch.pos": 10.0,
        "elbow_pitch.pos": 15.0,
        "wrist_roll.pos": -10.0,
        "wrist_pitch.pos": 18.0,
    }

    def hold(j, ht, dur):
        # Tremor — high frequency, decaying
        tremor = math.sin(2 * math.pi * ht * 10) * 1.0 * math.exp(-2.0 * ht)
        # Occasional startle aftershock
        aftershock = 2.0 * math.exp(-((ht - 0.8) / 0.15) ** 2)
        return tremor + aftershock * (0.5 if j.startswith("wrist") else 0.2)

    gen_pose_animation("shock.csv", 4.0, offset, approach_time=0.3,
                       return_time=2.0, use_anticipation=False,
                       overshoot_amount=0.20, hold_behavior=hold,
                       max_delta=3.0)  # startle needs faster motion


def gen_shy():
    """7s: turn away and hide, with a peek, then slowly come back.

    Like a child hiding behind hands — turn away, duck, peek once, hide again, slowly return.
    """
    offset = {
        "base_yaw.pos": -28.0,
        "base_pitch.pos": -10.0,
        "elbow_pitch.pos": -10.0,
        "wrist_roll.pos": -15.0,
        "wrist_pitch.pos": -8.0,
    }

    def hold(j, ht, dur):
        # Peek! At ht ~1.5s — turn back slightly, look up
        peek_center = 1.5
        peek = math.exp(-((ht - peek_center) / 0.35) ** 2)

        # Fidgeting — nervous energy
        fidget_val = noise(ht * 2, hash(j) % 13) * 1.2

        if j == "base_yaw.pos":
            return 12.0 * peek + fidget_val  # peek back toward center
        if j == "wrist_pitch.pos":
            return 5.0 * peek + fidget_val   # lift head to peek
        if j == "wrist_roll.pos":
            return 4.0 * peek + fidget_val
        return fidget_val * 0.5

    gen_pose_animation("shy.csv", 7.0, offset, approach_time=1.2,
                       return_time=2.5, overshoot_amount=0.08,
                       hold_behavior=hold)


def gen_scanning():
    """7s: look left, pause, look right, pause, return. Like surveying a room.

    Each pause has micro-adjustments (focusing on what it sees).
    Transitions have momentum (slight overshoot at each stop).
    """
    duration = 7.0
    n = int(duration * FPS)
    frames = []

    # Keyframes: (time, yaw_target)
    keys = [
        (0.0, 0.0),       # start center
        (1.3, -30.0),     # look left
        (2.2, -28.0),     # settle (overshoot recovery)
        (2.5, -30.0),     # re-center on left target
        (4.3, 32.0),      # look right (overshoot)
        (4.8, 28.0),      # settle right
        (5.1, 30.0),      # re-center right
        (7.0, 0.0),       # return center
    ]

    def interp_keys(t):
        for k in range(len(keys) - 1):
            t0, v0 = keys[k]
            t1, v1 = keys[k + 1]
            if t0 <= t <= t1:
                p = ease_in_out((t - t0) / (t1 - t0))
                return v0 + (v1 - v0) * p
        return keys[-1][1]

    for i in range(n + 1):
        t = i / FPS
        row = {"timestamp": t}

        fade = 1.0
        if t < 0.3:
            fade = ease_in_out(t / 0.3)
        elif t > duration - 0.3:
            fade = ease_in_out((duration - t) / 0.3)

        yaw_offset = interp_keys(t)

        # Detect "pause" phases for micro-adjustments
        is_paused = any(
            abs(t - pk_t) < 0.6 and abs(interp_keys(t) - interp_keys(t - DT)) < 0.5
            for pk_t in [1.8, 4.5]
        ) if t > 0.5 else False

        for j in JOINTS:
            st = staggered_t(t, j)
            val = REST[j]

            if j == "base_yaw.pos":
                val += yaw_offset * fade
            elif j == "base_pitch.pos":
                # Alert posture when scanning
                val += 4.0 * fade
                # Slight pitch adjustment with yaw (looking up/down at what it sees)
                val += noise(t, 3) * 2.0 * fade
            elif j == "elbow_pitch.pos":
                # Arm follows scanning direction slightly
                val += yaw_offset * 0.12 * fade
            elif j == "wrist_pitch.pos":
                # Head tracks with focus
                val += yaw_offset * 0.2 * fade
                if is_paused:
                    val += noise(t * 2, 5) * 2.0  # micro focus adjustments
            elif j == "wrist_roll.pos":
                # Counter tilt
                val += -yaw_offset * 0.15 * fade

            val += noise(t, hash(j) % 17) * 0.3 * fade
            row[j] = val
        frames.append(row)

    write_csv("scanning.csv", frames)


def gen_wake_up():
    """9s: sleep → stir → rise → stretch → settle to rest.

    Starts with tiny sleep movements. Stirs (small movements getting bigger).
    Rises with a stretch at the peak. Settles with a satisfied sigh.
    """
    duration = 9.0
    n = int(duration * FPS)
    frames = []

    sleep_offset = {
        "base_yaw.pos": -5.0,
        "base_pitch.pos": -18.0,
        "elbow_pitch.pos": -18.0,
        "wrist_roll.pos": -5.0,
        "wrist_pitch.pos": -14.0,
    }
    stretch_offset = {
        "base_yaw.pos": 3.0,
        "base_pitch.pos": 18.0,
        "elbow_pitch.pos": 28.0,
        "wrist_roll.pos": 8.0,
        "wrist_pitch.pos": 35.0,
    }

    for i in range(n + 1):
        t = i / FPS
        row = {"timestamp": t}

        for j in JOINTS:
            if t <= 1.5:
                # Sleeping — tiny breathing
                val = REST[j] + sleep_offset[j]
                val += math.sin(2 * math.pi * t / 3.0) * 0.5
            elif t <= 2.5:
                # Stirring — starting to move, growing amplitude
                p = (t - 1.5) / 1.0
                stir_amp = p * 3.0
                val = REST[j] + sleep_offset[j] * (1 - p * 0.3)
                val += noise(t * 2, hash(j) % 9) * stir_amp
            elif t <= 4.5:
                # Rising from sleep to rest
                p = ease_in_out((t - 2.5) / 2.0)
                val = REST[j] + sleep_offset[j] * (1 - p)
                val += noise(t, hash(j) % 7) * 1.0 * p
            elif t <= 6.0:
                # Stretch! Rise above rest with overshoot
                p = overshoot_ease((t - 4.5) / 1.5, overshoot=0.15)
                val = REST[j] + stretch_offset[j] * p
                # Trembling from effort
                val += math.sin(2 * math.pi * t * 4) * 0.8 * p
            else:
                # Settle from stretch to rest with a sigh
                p = 1.0 - ease_in_out((t - 6.0) / 3.0)
                val = REST[j] + stretch_offset[j] * p
                # Satisfied sigh — small extra drop around t=6.5
                sigh = 2.0 * math.exp(-((t - 6.8) / 0.4) ** 2)
                if j in ("base_pitch.pos", "elbow_pitch.pos"):
                    val -= sigh
                val += noise(t, hash(j) % 11) * 0.5 * (1 - p * 0.5)

            row[j] = val
        frames.append(row)

    write_csv("wake_up.csv", frames)


def gen_music_groove():
    """10s: rhythmic grooving to music — head bobs, body sways, arm flair.

    Based on ~120 BPM. Has downbeat emphasis, syncopation, and body weight shifts.
    Not a simple sine — mimics how a person bobs their head to music.
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
            # Quick down
            bob = ease_out(beat_phase / 0.25)
        else:
            # Slow rise
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
    "idle": gen_idle,
    "curious": gen_curious,
    "nod": gen_nod,
    "headshake": gen_headshake,
    "happy_wiggle": gen_happy_wiggle,
    "sad": gen_sad,
    "excited": gen_excited,
    "shock": gen_shock,
    "shy": gen_shy,
    "scanning": gen_scanning,
    "wake_up": gen_wake_up,
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
