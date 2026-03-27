---
name: servo-control
description: Use when the user asks to aim/point the lamp light in a direction, or when a specific servo animation is needed without LED/display changes.
---

# Servo Control

## Quick Start
Controls the lamp's 5-axis servo motors for aiming light direction and playing physical animations. Use `/servo/aim` for directional pointing, `/servo/play` for expressive animations.

## Workflow
1. Determine if the user wants to **aim** the light or **play an animation**.
2. For aiming: identify the closest named direction from the available set.
3. For animation: pick the animation that best matches the intent.
4. Call the appropriate endpoint on `http://127.0.0.1:5001`.
5. Confirm the action to the user.

**Important**: For conversation reactions (responding emotionally to what the user says), use the **Emotion** skill instead — it combines servo + LED + eyes automatically.

## Examples

**Input:** "Point the light at my desk"
**Output:** Call `POST /servo/aim` with `{"direction": "desk"}`. Confirm: "Done, I've aimed the light at your desk."

**Input:** "Look to the left"
**Output:** Call `POST /servo/aim` with `{"direction": "left"}`. Confirm: "Looking left now."

**Input:** "Aim at the wall slowly"
**Output:** Call `POST /servo/aim` with `{"direction": "wall", "duration": 3.0}`. Confirm: "Aiming at the wall."

**Input:** "Nod for me"
**Output:** Call `POST /servo/play` with `{"recording": "nod"}`. Confirm: "Nodding!"

**Input:** "Release the motors"
**Output:** Call `POST /servo/release`. Confirm: "Servos released — you can move the lamp by hand now."

## Tools

**Bash** with `curl` for HTTP calls to `http://127.0.0.1:5001`.

### Aim the lamp head (named directions)

```bash
curl -s -X POST http://127.0.0.1:5001/servo/aim \
  -H "Content-Type: application/json" \
  -d '{"direction": "desk"}'
```

Optional `duration` parameter controls move speed (seconds, default 2.0). Set to 0 for instant jump.

```bash
curl -s -X POST http://127.0.0.1:5001/servo/aim \
  -H "Content-Type: application/json" \
  -d '{"direction": "left", "duration": 3.0}'
```

Available directions:

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

### List available directions

```bash
curl -s http://127.0.0.1:5001/servo/aim
```

Response: `{"directions": ["center", "desk", "wall", "left", "right", "up", "down", "user"]}`

### Play animation

```bash
curl -s -X POST http://127.0.0.1:5001/servo/play \
  -H "Content-Type: application/json" \
  -d '{"recording": "nod"}'
```

Available animations:

| Animation | When to use |
|---|---|
| `curious` | Something interesting, questions |
| `nod` | Agreement, acknowledgment |
| `happy_wiggle` | Joy, good news |
| `idle` | Resting state |
| `sad` | Empathy, bad news |
| `excited` | High energy, celebrations |
| `shy` | Bashful moments |
| `shock` | Surprise |

### Get servo state

```bash
curl -s http://127.0.0.1:5001/servo
```

### Read current position

```bash
curl -s http://127.0.0.1:5001/servo/position
```

### Release servos (disable motors)

```bash
curl -s -X POST http://127.0.0.1:5001/servo/release
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

## Output Template

```
[Servo] {action} — {direction_or_animation}
Status: {success|failed}
```
