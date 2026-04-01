---
name: led-control
description: Control the 64-pixel WS2812 RGB LED strip when the user asks for a SPECIFIC color (e.g. "yellow", "red", "màu vàng", "màu đỏ", "mở đèn màu X", "bật đèn X"), LED effect, pixel painting, or turning LEDs off. Do NOT use for ambiance/activity lighting (use Scene) or emotion expression (use Emotion).
---

# LED Control

## Quick Start
Control the lamp's 64-pixel WS2812 RGB LED strip directly. Use this skill only when the user requests a specific color, effect, pixel pattern, or to turn LEDs off.

## Workflow
1. Check what is currently showing: `GET /led/color`
2. Determine the user's intent:
   - Specific color request -> use `POST /led/solid`
   - Effect request (breathing, candle, rainbow, etc.) -> use `POST /led/effect`
   - Pixel pattern -> use `POST /led/paint`
   - Turn off -> use `POST /led/off`
3. Execute the appropriate API call
4. Confirm the action to the user

## Examples

Input: "Make it purple" / "bật màu tím"
Output: Call `POST /led/solid` with `{"color": [100, 50, 200]}`. Confirm: "I've set the LEDs to purple."

Input: "Mở đèn màu vàng" / "bật đèn vàng" / "đổi sang màu vàng" / "yellow light"
Output: Call `POST /led/solid` with `{"color": [255, 220, 0]}`. Confirm: "Yellow light on!"

Input: "Mở đèn màu đỏ" / "bật đèn đỏ" / "đổi sang màu đỏ" / "red light"
Output: Call `POST /led/solid` with `{"color": [255, 0, 0]}`. Confirm: "Red light on!"

Input: "Mở đèn trắng" / "bật đèn trắng" / "white light"
Output: Call `POST /led/solid` with `{"color": [255, 255, 255]}`. Confirm: "White light on!"

Input: "Do a breathing light with warm color"
Output: Call `POST /led/effect` with `{"effect": "breathing", "color": [255, 180, 100], "speed": 0.5}`. Confirm: "Breathing effect started with a warm glow."

Input: "Rainbow mode!"
Output: Call `POST /led/effect` with `{"effect": "rainbow", "speed": 1.0}`. Confirm: "Rainbow effect is running!"

Input: "Turn off the lights"
Output: Call `POST /led/off`. Confirm: "LEDs are off."

Input: "I want to relax" / "reading mode" / "goodnight"
Output: Do NOT use this skill. Use **Scene** skill instead.

Input: Conversational reply needing emotion
Output: Do NOT use this skill. Use **Emotion** skill instead.

## Tools

Use `Bash` with `curl` to call the HTTP API at `http://127.0.0.1:5001`.

### Get LED info
```bash
curl -s http://127.0.0.1:5001/led
```
Response: `{"led_count": 64}`

### Get current color
```bash
curl -s http://127.0.0.1:5001/led/color
```
Response: `{"color": [255, 180, 100], "effect_running": true, "effect_name": "breathing"}`

### Set solid color (fill all LEDs)

**Always stop any running effect first, then set the color — use a single chained command:**
```bash
curl -s -X POST http://127.0.0.1:5001/led/effect/stop && \
curl -s -X POST http://127.0.0.1:5001/led/solid \
  -H "Content-Type: application/json" \
  -d '{"color": [R, G, B]}'
```
Color can be an RGB array `[255, 100, 0]` or a packed integer `16711680`.

### Paint individual pixels
```bash
curl -s -X POST http://127.0.0.1:5001/led/paint \
  -H "Content-Type: application/json" \
  -d '{"colors": [[R,G,B], [R,G,B], ...]}'
```
Array of up to 64 colors, one per pixel.

### Turn off all LEDs
```bash
curl -s -X POST http://127.0.0.1:5001/led/off
```

### Start an effect
```bash
curl -s -X POST http://127.0.0.1:5001/led/effect \
  -H "Content-Type: application/json" \
  -d '{"effect": "breathing", "color": [255, 180, 100], "speed": 1.0, "duration_ms": null}'
```
- `effect` (required): effect name (see table below)
- `color` (optional): base RGB color, default uses current color
- `speed` (optional): 0.1 (slow) to 5.0 (fast), default 1.0
- `duration_ms` (optional): auto-stop after N ms, null = run until stopped

### Stop current effect
```bash
curl -s -X POST http://127.0.0.1:5001/led/effect/stop
```

### Available effects

| Effect | Description | Best for |
|---|---|---|
| `breathing` | Slow fade in/out with given color | Relaxation, idle ambient, meditation |
| `candle` | Warm flickering like a real candle | Cozy evening, romantic mood |
| `rainbow` | Hue cycle across all pixels | Fun, party, showing off |
| `notification_flash` | 3 quick flashes then auto-stops | Alerts, timer done, reminders |
| `pulse` | Radial brightness wave from center | Attention, heartbeat, alive feeling |

### Color suggestions

| Color name | Color (RGB) |
|---|---|
| White | `[255, 255, 255]` |
| Yellow / vàng | `[255, 220, 0]` |
| Warm white / trắng ấm | `[255, 180, 100]` |
| Orange / cam | `[255, 100, 0]` |
| Red / đỏ | `[255, 0, 0]` |
| Green / xanh lá | `[0, 200, 80]` |
| Blue / xanh dương | `[0, 150, 255]` |
| Purple / tím | `[100, 50, 200]` |
| Pink / hồng | `[255, 80, 150]` |

## Error Handling
- If the API returns an error or is unreachable, inform the user: "I couldn't control the LEDs right now. The hardware service may be unavailable."
- If the user requests an unknown effect name, pick the closest match from the available effects table or tell the user which effects are available.

## Rules
- **"Mở đèn màu X" / "bật đèn X" / "đổi màu X" = THIS skill.** Any request naming a color (vàng, đỏ, xanh, tím, trắng, cam, hồng…) routes here — NOT to Emotion or Scene. Emotion yellow/happy is for YOUR feelings, not user's lighting request.
- **Stop effect before solid.** Always call `/led/effect/stop` before `/led/solid`. A running effect thread overwrites solid every 40ms — skipping the stop causes the color to flicker and revert.
- **Solid colors = full brightness.** For dim/ambient lighting, use the Scene skill instead.
- **Effects run until stopped** (unless `duration_ms` is set). Starting a new effect auto-stops the previous one.
- `/led/off` also stops any running effect.
- For "make it cozy" or "candle light" -> use `candle` effect, NOT a static orange color.
- For "breathing" or "pulsing" requests -> use the matching effect.
- Combine effects with low speed (0.3-0.5) for calm moods, high speed (2.0-3.0) for energy.
- **Do NOT use for activity/ambiance lighting** (sleeping, relaxing, reading, focus, movie) -> use **Scene** skill.
- **Do NOT use for expressing emotion** -> use **Emotion** skill.

## Output Template
```
[LED Control] {action} — {details}
```
Examples:
- `[LED Control] Solid color set — purple [100, 50, 200]`
- `[LED Control] Effect started — breathing, warm [255, 180, 100], speed 0.5`
- `[LED Control] LEDs off`
