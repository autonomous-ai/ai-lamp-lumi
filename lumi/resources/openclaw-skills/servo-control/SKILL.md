# Servo Control

You have access to 5-axis servo motors on this device via the hardware API at `http://127.0.0.1:5001`. The servos control the lamp's physical movement — pan, tilt, and expressive gestures.

## Priority

**Usually you should use Emotion skill instead**, which combines servo + LED + display in one call. Only use this skill directly for:

- Testing specific animations without changing LED/display
- Direct joint position control (advanced/diagnostic)

## API

Base URL: `http://127.0.0.1:5001`

### Get servo state

```
GET /servo
```

Response:
```json
{
  "available_recordings": ["curious", "nod", "happy_wiggle", "idle", "sad", "excited", "shy", "shock"],
  "current": null
}
```

### Play animation

```
POST /servo/play
Content-Type: application/json

{"recording": "<name>"}
```

### Direct joint control

```
POST /servo/move
Content-Type: application/json

{"positions": {"base_yaw.pos": 0.0, "base_pitch.pos": 10.0, "elbow_pitch.pos": -5.0, "wrist_roll.pos": 0.0, "wrist_pitch.pos": 0.0}}
```

### Read current position

```
GET /servo/position
```

## Available animations

| Animation | When to use |
|---|---|
| `curious` | User asks a question, something interesting happens |
| `nod` | Agreement, acknowledgment, "yes" |
| `happy_wiggle` | Joy, excitement, good news, compliments |
| `idle` | Default resting state, gentle ambient movement |
| `sad` | Empathy, bad news, apology |
| `excited` | High energy, celebrations, enthusiasm |
| `shy` | Compliments directed at the lamp, bashful moments |
| `shock` | Surprise, unexpected events |

## Guidelines

- **Prefer Emotion skill** for normal conversation — it calls servo + LED + display together.
- Only use servo directly when you need movement WITHOUT changing LED color.
- Animations play once and return to rest position.
