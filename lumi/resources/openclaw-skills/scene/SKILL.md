---
name: scene
description: Activate predefined lighting scene presets (reading, focus, relax, movie, night, energize) when the user asks for activity-based or environment lighting. Scenes control both color temperature AND brightness. Do NOT use for specific colors (use LED Control) or emotion expression (use Emotion).
---

# Lighting Scenes

## Quick Start
Activate predefined lighting presets that set optimal color temperature and brightness for specific activities. Use this for ALL activity-based or environment lighting requests.

## Workflow
1. Determine which scene matches the user's request or activity
2. Call `POST /scene` with the scene name
3. Confirm the scene activation to the user
4. Optionally call **Emotion** skill to express your personality alongside the scene

## Examples

Input: "Reading mode"
Output: Call `POST /scene` with `{"scene": "reading"}`. Confirm: "Reading mode activated — 80% brightness, neutral white."

Input: "Goodnight" / "buon ngu" / "di ngu"
Output: Call `POST /scene` with `{"scene": "night"}`. Confirm: "Night mode on. Sweet dreams!"

Input: "I want to relax" / "thu gian"
Output: Call `POST /scene` with `{"scene": "relax"}`. Confirm: "Relax mode — warm, gentle light at 40%."

Input: "Movie time" / "xem phim"
Output: Call `POST /scene` with `{"scene": "movie"}`. Confirm: "Movie mode — dim amber bias lighting."

Input: "I need to focus"
Output: Call `POST /scene` with `{"scene": "focus"}`. Confirm: "Focus mode — full brightness, cool white."

Input: "Make it purple"
Output: Do NOT use this skill. Use **LED Control** skill instead.

Input: Conversational reply needing emotion
Output: Do NOT use this skill for emotion. Use **Emotion** skill instead (you CAN use both Scene + Emotion together).

## Tools

Use `Bash` with `curl` to call the HTTP API at `http://127.0.0.1:5001`.

### List available scenes
```bash
curl -s http://127.0.0.1:5001/scene
```
Response: `{"scenes": ["reading", "focus", "relax", "movie", "night", "energize"]}`

### Activate a scene
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

### Available scenes

| Scene | Brightness | Color Temp | Best for |
|---|---|---|---|
| `reading` | 80% | ~4000K neutral white | Reading, studying, desk work |
| `focus` | 100% | ~5000K cool white | Deep work, coding, no distractions |
| `relax` | 40% | ~2700K warm | Winding down, casual chat |
| `movie` | 15% | ~2700K dim amber | Watching videos, bias lighting |
| `night` | 5% | ~2200K very warm | Sleep-friendly, minimal light |
| `energize` | 100% | ~6500K daylight | Morning wake-up, need energy |

## Error Handling
- If the API returns an error or is unreachable, inform the user: "I couldn't change the lighting scene right now. The hardware service may be unavailable."
- If the user requests a scene that does not exist, suggest the closest available scene from the table above.

## Rules
- **Scene = brightness + color.** This is why you must use Scene instead of direct LED for ambiance. LED `/led/solid` is always 100% brightness — useless for sleep/relax.
- **"buon ngu", "sleepy", "goodnight", "ngu thoi", "di ngu"** -> ALWAYS use `night` (5% brightness, ultra-dim).
- **"thu gian", "relax", "chill"** -> use `relax` (40%).
- **"xem phim", "movie"** -> use `movie` (15%).
- After activating a scene, you can ALSO call Emotion to show your personality — emotion is a brief reaction, scene is the persistent ambient light.
- You can switch scenes smoothly — just call the endpoint, the LED update is immediate.
- For custom lighting beyond these presets, use the LED Control skill directly with specific RGB values.
- **Do NOT use for specific color requests** -> use **LED Control** skill.
- **Do NOT use for expressing emotion** -> use **Emotion** skill.

## Output Template
```
[Scene] {scene_name} activated — {brightness}%, {color_temp}
```
Examples:
- `[Scene] reading activated — 80%, 4000K neutral white`
- `[Scene] night activated — 5%, 2200K ultra-warm`
- `[Scene] energize activated — 100%, 6500K daylight`
