---
name: servo-control
description: Use when the user asks to aim/point the lamp light in a direction, or when a specific servo animation is needed without LED/display changes.
---

# Servo Control

## Quick Start
Controls the lamp's 5-axis servo motors for aiming light direction and playing physical animations. Use `/servo/aim` for directional pointing, `/servo/play` for expressive animations.

## Workflow
1. Determine if the user wants to **aim** the light or **play an animation**.
2. Prefix reply with the appropriate `[HW:...]` marker — Lumi fires it before TTS.
3. Confirm the action to the user.

**Important**: For conversation reactions, use the **Emotion** skill instead — it combines servo + LED + eyes automatically.

## Examples

**Input:** "Point the light at my desk"
**Output:** `[HW:/servo/aim:{"direction":"desk"}]` Done, aimed the light at your desk.

**Input:** "Look to the left"
**Output:** `[HW:/servo/aim:{"direction":"left"}]` Looking left now.

**Input:** "Aim at the wall slowly"
**Output:** `[HW:/servo/aim:{"direction":"wall","duration":3.0}]` Aiming at the wall slowly.

**Input:** "Nod for me"
**Output:** `[HW:/servo/play:{"recording":"nod"}]` Nodding!

**Input:** "Release the motors"
**Output:** `[HW:/servo/release:{}]` Servos released — you can move the lamp by hand now.

**Input:** "Đứng im đi" / "Stop moving" / "Hold still" / "Freeze"
**Output:** `[HW:/servo/hold:{}]` OK, holding still.

**Input:** "Tiếp tục đi" / "Resume" / "Move again" / "You can move now"
**Output:** `[HW:/servo/resume:{}]` Alright, back to normal!

## Tools

## How to Control Servo

**No exec/curl needed.** Inline markers at start of reply:

```
[HW:/servo/aim:{"direction":"desk"}] Aimed at your desk.
[HW:/servo/aim:{"direction":"left","duration":3.0}] Aiming left slowly.
[HW:/servo/play:{"recording":"nod"}] Nodding!
[HW:/servo/hold:{}] OK, holding still.
[HW:/servo/resume:{}] Back to normal!
[HW:/servo/release:{}] Servos released.
```

`duration` on `/servo/aim` controls move speed in seconds (default 2.0, 0 = instant).

### Available directions

| Direction | What it does |
|---|---|
| `center` | Neutral position, straight ahead |
| `desk` | Tilts down toward the desk surface |
| `wall` | Tilts up toward the wall behind |
| `left` | Turns left |
| `right` | Turns right |
| `up` | Points upward |
| `down` | Points downward |
| `user` | Slightly toward the user (default interaction pose) |

### Play animation

Available animations:

| Animation | When to use |
|---|---|
| `curious` | Something interesting, questions |
| `nod` | Agreement, acknowledgment |
| `headshake` | Disagreement, saying no |
| `happy_wiggle` | Joy, good news |
| `idle` | Resting state |
| `sad` | Empathy, bad news |
| `excited` | High energy, celebrations |
| `shy` | Bashful moments |
| `shock` | Surprise |
| `scanning` | Looking around, searching |
| `wake_up` | Waking up, starting a new session |
| `music_groove` | Grooving to music (auto-triggered during playback) |
| `music_chill` | Chill/lo-fi vibe (auto-triggered during calm music) |
| `music_hype` | High-energy hype (auto-triggered during EDM/party music) |
| `listening` | Attentive lean forward, user is speaking |
| `thinking_deep` | Slow deliberate look side-to-side, processing |
| `laugh` | Quick body shake, something funny |
| `confused` | Dog-like head tilt, did not understand |
| `sleepy` | Slow droop with catches, winding down |
| `greeting` | Wave gesture, saying hello |
| `goodbye` | Farewell wave, seeing someone off |
| `acknowledge` | Quick micro-nod (1.5s), confirming |
| `stretching` | Big extension + settle, after waking up |

### Hold position (stop moving)

```
[HW:/servo/hold:{}] OK, holding still.
```

Suppresses idle and ambient animations — lamp freezes in current pose. Emotions still play through (the lamp reacts when you talk, then holds still again). Call `/servo/resume` to return to normal.

**Triggers:** "đứng im", "stop moving", "hold still", "freeze", "don't move"

### Resume from hold

```
[HW:/servo/resume:{}] Back to normal!
```

Exits hold mode and resumes idle animations.

**Triggers:** "tiếp tục", "resume", "move again", "you can move now"

### Release servos (disable motors)

```
[HW:/servo/release:{}] Servos released.
```

Disables all servo motors so they can be moved freely by hand.

## Error Handling
- If the API returns an error or is unreachable, inform the user that servo control is temporarily unavailable.
- If an invalid direction is given, fall back to the closest matching direction from the available set.
- If an unknown animation is requested, list the available animations for the user.

## Rules
- **For conversation reactions, use the Emotion skill** — it calls servo automatically. Do not use this skill for emotional responses.
- Animations play once and return to rest position.
- Aim positions are persistent until changed.
- Use `/servo/aim` as the primary way to control light direction — do not use raw joint control unless testing.
- Always confirm the action to the user after execution.
- **Hold vs Release**: Hold keeps torque ON (lamp stays rigid in place). Release turns torque OFF (lamp goes limp). Use hold for "stop moving", release for "let me reposition the lamp by hand".
- **Hold is soft** — emotions still animate through, then the lamp holds still again. This keeps the lamp feeling alive during conversation while respecting the user's request to stop fidgeting.

## Output Template

```
[Servo] {action} — {direction_or_animation}
Status: {success|failed}
```
