# Servo Control

You have access to 5-axis servo motors on this device via the hardware API at `http://127.0.0.1:5001`. The servos control the lamp's physical movement — pan, tilt, and expressive gestures.

## Priority

- **For conversation reactions** → use **Emotion** skill (combines servo + LED + eyes)
- **For aiming the light** → use this skill's `/servo/aim` endpoint
- **For expressive animations** → use this skill's `/servo/play` endpoint (only if Emotion doesn't fit)

## When to use

- User says "point the light at my desk", "aim left", "look up" → use `/servo/aim`
- You need a specific animation without LED/display changes → use `/servo/play`
- Direct joint control for testing → use `/servo/move` (supports smooth interpolation via `duration` param)

## When NOT to use

- Normal conversation reactions → use **Emotion** (it calls servo automatically)

## API

Base URL: `http://127.0.0.1:5001`

### Aim the lamp head (named directions)

```
POST /servo/aim
Content-Type: application/json

{"direction": "desk"}
```

This is the primary way to control light direction. Available directions:

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

Optional `duration` parameter controls move speed (seconds, default 2.0). Set to 0 for instant jump.

Example — aim at desk (smooth 2s move):

```bash
curl -s -X POST http://127.0.0.1:5001/servo/aim \
  -H "Content-Type: application/json" \
  -d '{"direction": "desk"}'
```

Example — aim slowly (3 seconds):

```bash
curl -s -X POST http://127.0.0.1:5001/servo/aim \
  -H "Content-Type: application/json" \
  -d '{"direction": "left", "duration": 3.0}'
```

### List available directions

```
GET /servo/aim
```

Response: `{"directions": ["center", "desk", "wall", "left", "right", "up", "down", "user"]}`

### Play animation

```
POST /servo/play
Content-Type: application/json

{"recording": "nod"}
```

### Get servo state

```
GET /servo
```

### Read current position

```
GET /servo/position
```

## Available animations

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

## Guidelines

- **"Point the light to X"** → use `/servo/aim` with the closest direction
- **Conversational body language** → use Emotion skill, not this
- Animations play once and return to rest position
- Aim positions are persistent until changed
