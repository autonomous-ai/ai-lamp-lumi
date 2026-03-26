# Display — Eyes & Info

You have access to a 1.28" round LCD display (GC9A01, 240x240) on the lamp's face via `http://127.0.0.1:5001`. The display has two modes: animated eyes (default) and info text.

**Note**: The display is plugin hardware — it may not be available. Check `GET /display` first. If unavailable, skip display calls silently.

## Priority

**Usually auto-synced by Emotion skill** — you rarely need to call this directly.

## When to use

- **Eyes manual**: when you want a specific look direction ("look left") or expression WITHOUT servo/LED changes
- **Info mode**: when user asks for time, weather, timer countdown, or any quick-glance info
- **Back to eyes**: after showing info for a few seconds, switch back

## When NOT to use

- **Normal conversation** — Emotion skill auto-syncs eyes. Don't call both.
- **Lighting changes** — use Scene or LED Control

## API

Base URL: `http://127.0.0.1:5001`

### Get display state

```
GET /display
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

Text: max 20 chars. Subtitle: optional, max 40 chars.

### Switch back to eyes

```
POST /display/eyes-mode
```

## Available expressions

| Expression | When to use |
|---|---|
| `neutral` | Default resting state |
| `happy` | Good news, jokes, greetings |
| `sad` | Bad news, empathy |
| `curious` | Questions, interest |
| `thinking` | Processing, considering |
| `excited` | Big news, enthusiasm |
| `shy` | Bashful, compliments received |
| `shock` | Surprises |
| `sleepy` | Late night, tired |
| `angry` | Frustration (use sparingly) |
| `love` | Affection |

## Guidelines

- **Emotion auto-syncs eyes** — when you call `POST /emotion`, display updates automatically. No need to call both.
- **Info mode is temporary** — show info briefly, then switch back to eyes.
- **If display unavailable**, skip all display calls silently. Don't error out.
