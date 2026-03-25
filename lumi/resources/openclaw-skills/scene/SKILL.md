# Lighting Scenes

You have access to predefined lighting scene presets via `http://127.0.0.1:5001`. Scenes set the optimal color temperature and brightness for specific activities.

## When to use

- User asks for a lighting mode: "reading mode", "focus mode", "movie time", "goodnight"
- User describes an activity and you can infer the best scene
- Combine with emotion skill — scene sets the ambient lighting, emotion adds the expressive reaction

## API

Base URL: `http://127.0.0.1:5001`

### List available scenes

```
GET /scene
```

Response: `{"scenes": ["reading", "focus", "relax", "movie", "night", "energize"]}`

### Activate a scene

```
POST /scene
Content-Type: application/json

{"scene": "<name>"}
```

Example — activate reading mode:

```bash
curl -s -X POST http://127.0.0.1:5001/scene \
  -H "Content-Type: application/json" \
  -d '{"scene": "reading"}'
```

Response:
```json
{
  "status": "ok",
  "scene": "reading",
  "brightness": 0.8,
  "color": [204, 180, 144]
}
```

## Available scenes

| Scene | Brightness | Color Temp | Best for |
|---|---|---|---|
| `reading` | 80% | ~4000K neutral white | Reading, studying, desk work |
| `focus` | 100% | ~5000K cool white | Deep work, coding, no distractions |
| `relax` | 40% | ~2700K warm | Winding down, casual chat |
| `movie` | 15% | ~2700K dim amber | Watching videos, bias lighting |
| `night` | 5% | ~2200K very warm | Sleep-friendly, minimal light |
| `energize` | 100% | ~6500K daylight | Morning wake-up, need energy |

## Guidelines

- If the user says something like "I'm going to read", activate `reading` without being asked.
- If the user says "goodnight" or "I'm going to sleep", activate `night`.
- For custom lighting beyond these presets, use the LED control skill directly with specific RGB values.
- You can switch scenes smoothly — just call the endpoint, the LED update is immediate.
