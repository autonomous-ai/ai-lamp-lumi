# LED Control

You have access to a 64-pixel WS2812 RGB LED strip on this device via the hardware API at `http://127.0.0.1:5001`.

## Priority

**Low priority for ambiance.** Only use this when the user wants a SPECIFIC color or pattern. For activity-based lighting (reading, sleeping, relaxing), use the **Scene** skill — it has proper brightness control.

## When to use

- User asks for a specific color: "make it purple", "red light", "turn green"
- Paint individual pixels for effects or status indicators
- Turn LEDs off when the user asks

## When NOT to use

- **Sleeping, relaxing, reading, focus, movie** → use **Scene** skill (controls brightness + color)
- **Expressing your emotion** → use **Emotion** skill (coordinates servo + LED + eyes)
- Direct LED colors are always FULL BRIGHTNESS. If you set `[255, 180, 100]` for "warm light at bedtime", it will be blinding. Use Scene `night` instead.

## API

Base URL: `http://127.0.0.1:5001`

### Get LED info

```
GET /led
```

Response: `{"led_count": 64}`

### Set solid color (fill all LEDs)

```
POST /led/solid
Content-Type: application/json

{"color": [R, G, B]}
```

Color can be an RGB array `[255, 100, 0]` or a packed integer `16711680` (= 0xFF0000 = red).

Example — warm white:

```bash
curl -s -X POST http://127.0.0.1:5001/led/solid \
  -H "Content-Type: application/json" \
  -d '{"color": [255, 180, 100]}'
```

### Paint individual pixels

```
POST /led/paint
Content-Type: application/json

{"colors": [[R,G,B], [R,G,B], ...]}
```

Array of up to 64 colors, one per pixel. Use this for gradients, patterns, or per-pixel effects.

### Turn off all LEDs

```
POST /led/off
```

## Color suggestions (for specific color requests only)

| Mood / Scene | Color (RGB) | Notes |
|---|---|---|
| Warm / cozy | `[255, 180, 100]` | Warm white (full brightness!) |
| Cool / work | `[255, 255, 220]` | Cool white |
| Purple | `[100, 50, 200]` | Soft purple |
| Energy | `[255, 100, 0]` | Orange |
| Error / alert | `[255, 0, 0]` | Red |
| Happy | `[255, 220, 0]` | Yellow |
| Calm | `[0, 150, 255]` | Blue |

## Guidelines

- All colors are at **full brightness** — there is no dimming. For dim/ambient lighting, use Scene skill.
- If the user says "dim" or "soft", do NOT use this skill — use Scene with appropriate preset.
