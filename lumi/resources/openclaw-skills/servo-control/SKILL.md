# Servo Control

You have access to 5-axis servo motors on this device via the hardware API at `http://127.0.0.1:5001`. The servos control the lamp's physical movement — pan, tilt, and expressive gestures.

## When to use

- Play expressive animations to make the lamp feel alive during conversation.
- React to what the user says with body language (nod for agreement, curious tilt for questions).
- Use idle animation when waiting, to keep the lamp feeling present.

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

Example — nod in agreement:

```bash
curl -s -X POST http://127.0.0.1:5001/servo/play \
  -H "Content-Type: application/json" \
  -d '{"recording": "nod"}'
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

- Always play an animation that matches the emotional tone of your response.
- Use `idle` as the default when no specific emotion is needed.
- You can combine servo animations with LED color changes for richer expression.
- Animations play once and return to rest position.
