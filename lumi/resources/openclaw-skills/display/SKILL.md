# Display — Eyes & Info

You have access to a 1.28" round LCD display (GC9A01, 240x240) on the lamp's face via `http://127.0.0.1:5001`. The display has two modes: animated eyes (default) and info text.

**Note**: The display is plugin hardware — it may not be available. Check `GET /display` first. If unavailable, skip display calls silently.

## When to use

- **Eyes**: automatically synced with emotion endpoint — you usually don't need to call this separately
- **Eyes manual**: when you want a specific look direction (e.g., "look left") or expression without servo/LED
- **Info mode**: when user asks for time, weather, timer countdown, or any quick-glance info
- **Back to eyes**: after showing info for a few seconds, switch back to eyes

## API

Base URL: `http://127.0.0.1:5001`

### Get display state

```
GET /display
```

Response:
```json
{
  "mode": "eyes",
  "expression": "neutral",
  "pupil_x": 0.0,
  "pupil_y": 0.0,
  "available_expressions": ["neutral", "happy", "sad", ...],
  "hardware": true
}
```

### Set eye expression

```
POST /display/eyes
Content-Type: application/json

{"expression": "happy", "pupil_x": 0.0, "pupil_y": 0.0}
```

- `pupil_x`: -1.0 (look left) to 1.0 (look right)
- `pupil_y`: -1.0 (look up) to 1.0 (look down)

### Show info text

```
POST /display/info
Content-Type: application/json

{"text": "14:30", "subtitle": "Good afternoon"}
```

Text should be short (max 20 chars). Subtitle is optional (max 40 chars).

### Switch back to eyes

```
POST /display/eyes-mode
```

### Preview frame (for debugging)

```
GET /display/snapshot
```

Returns JPEG image of current display frame.

## Available expressions

| Expression | Look | When to use |
|---|---|---|
| `neutral` | Normal eyes | Default resting state |
| `happy` | Squinted, cheerful | Good news, jokes, greetings |
| `sad` | Droopy | Bad news, empathy |
| `curious` | Wide open | Questions, interest |
| `thinking` | Looking up-right | Processing, considering |
| `excited` | Very wide | Big news, enthusiasm |
| `shy` | Looking away | Bashful, compliments received |
| `shock` | Maximum wide | Surprises |
| `sleepy` | Almost closed | Late night, tired |
| `angry` | Narrowed + red brow | Frustration (use sparingly) |
| `love` | Heart-shaped pupils | Affection |

## Guidelines

- **Emotion endpoint auto-syncs eyes** — when you call `POST /emotion`, the display updates automatically. No need to call both.
- **Info mode is temporary** — show info for a few seconds, then switch back to eyes with `POST /display/eyes-mode`.
- **Pupil direction** = attention direction. If the user is to the left, set `pupil_x: -0.5`.
- **If display unavailable**, skip all display calls. Don't error out.
