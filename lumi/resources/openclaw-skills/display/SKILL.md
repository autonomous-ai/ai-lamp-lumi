---
name: display
description: Use when the user asks to change eye expression directly, show info text on the display (time, weather, timer), or manually control the round LCD — NOT needed for normal conversation (Emotion skill auto-syncs eyes).
---

# Display — Eyes & Info

## Quick Start
Controls the lamp's 1.28" round LCD display (GC9A01, 240x240). Two modes: animated eyes (default) and info text. Usually auto-synced by the Emotion skill — only call directly for manual eye control or info display.

## Workflow
1. Check display availability with `GET /display`. If unavailable, skip silently.
2. Determine the mode needed:
   - **Eyes**: set expression and optional pupil direction via `POST /display/eyes`.
   - **Info**: show text/subtitle via `POST /display/info`.
3. Call the appropriate endpoint on `http://127.0.0.1:5001`.
4. If info mode was used, switch back to eyes after a few seconds with `POST /display/eyes-mode`.

**Important**: The Emotion skill auto-syncs eyes during conversation. Do not call both Emotion and Display for the same reaction.

## Examples

**Input:** "Look to the left"
**Output:** Call `POST /display/eyes` with `{"expression": "neutral", "pupil_x": -1.0, "pupil_y": 0.0}`. No verbal confirmation needed.

**Input:** "What time is it?"
**Output:** Call `POST /display/info` with `{"text": "14:30", "subtitle": "Good afternoon"}`. Say the time. After a few seconds, call `POST /display/eyes-mode` to switch back.

**Input:** "Show me a happy face"
**Output:** Call `POST /display/eyes` with `{"expression": "happy"}`.

## Tools

**Bash** with `curl` for HTTP calls to `http://127.0.0.1:5001`.

### Get display state

```bash
curl -s http://127.0.0.1:5001/display
```

### Set eye expression

```bash
curl -s -X POST http://127.0.0.1:5001/display/eyes \
  -H "Content-Type: application/json" \
  -d '{"expression": "happy", "pupil_x": 0.0, "pupil_y": 0.0}'
```

- `pupil_x`: -1.0 (look left) to 1.0 (look right)
- `pupil_y`: -1.0 (look up) to 1.0 (look down)

### Show info text

```bash
curl -s -X POST http://127.0.0.1:5001/display/info \
  -H "Content-Type: application/json" \
  -d '{"text": "14:30", "subtitle": "Good afternoon"}'
```

- `text`: max 20 characters
- `subtitle`: optional, max 40 characters

### Switch back to eyes

```bash
curl -s -X POST http://127.0.0.1:5001/display/eyes-mode
```

### Get display snapshot

```bash
curl -s http://127.0.0.1:5001/display/snapshot --output snapshot.png
```

Returns a PNG image of what's currently shown on the display.

### Available expressions

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

## Error Handling
- If `GET /display` returns unavailable or the API is unreachable, skip all display calls silently. Do not error out to the user.
- If an invalid expression is given, fall back to `neutral`.
- If text exceeds character limits, truncate gracefully.

## Rules
- **Emotion skill auto-syncs eyes** — when you call `POST /emotion`, the display updates automatically. Do not call both.
- **Info mode is temporary** — show info briefly, then switch back to eyes.
- The display is plugin hardware — it may not be available. Always check first, and skip silently if absent.
- Do not use this skill for normal conversation reactions — use the Emotion skill instead.

## Output Template

```
[Display] Mode: {eyes|info}
Expression: {expression} | Text: {text}
Status: {success|skipped|unavailable}
```
