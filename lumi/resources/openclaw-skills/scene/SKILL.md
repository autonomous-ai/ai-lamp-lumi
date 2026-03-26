# Lighting Scenes

You have access to predefined lighting scene presets via `http://127.0.0.1:5001`. Scenes set the optimal color temperature AND brightness for specific activities.

## Priority

**Use this for ALL activity/environment lighting requests.** Scenes control both color AND brightness — direct LED control only sets color at full brightness, which is often too harsh.

## When to use

- User asks for a lighting mode: "reading mode", "focus mode", "movie time"
- User describes going to sleep, winding down, relaxing → `night`, `relax`, or `movie`
- User describes an activity and you can infer the best scene
- **"buồn ngủ", "sleepy", "goodnight", "ngủ thôi", "đi ngủ"** → ALWAYS use `night` (5% brightness, ultra-dim)
- **"thư giãn", "relax", "chill"** → use `relax` (40%)
- **"xem phim", "movie"** → use `movie` (15%)

## When NOT to use

- User asks for a specific color ("make it purple") → use **LED Control**
- You want to express YOUR emotion → use **Emotion** skill

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

Example — activate night mode:

```bash
curl -s -X POST http://127.0.0.1:5001/scene \
  -H "Content-Type: application/json" \
  -d '{"scene": "night"}'
```

Response:
```json
{
  "status": "ok",
  "scene": "night",
  "brightness": 0.05,
  "color": [12, 7, 2]
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

- **Scene = brightness + color.** This is why you must use Scene instead of direct LED for ambiance. LED `/led/solid` is always 100% brightness — useless for sleep/relax.
- After activating a scene, you can ALSO call Emotion to show your personality — emotion is a brief reaction, scene is the persistent ambient light.
- You can switch scenes smoothly — just call the endpoint, the LED update is immediate.
- For custom lighting beyond these presets, use the LED control skill directly with specific RGB values.
