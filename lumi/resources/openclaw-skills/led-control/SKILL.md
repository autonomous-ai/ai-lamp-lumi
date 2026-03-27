# LED Control

You have access to a 64-pixel WS2812 RGB LED strip on this device via the hardware API at `http://127.0.0.1:5001`.

## Priority

**Low priority for ambiance.** For activity-based lighting (reading, sleeping, relaxing), use **Scene** skill. For expressing YOUR emotion, use **Emotion** skill. Use LED Control only for:

- User asks for a SPECIFIC color ("make it purple", "red light")
- User asks for an EFFECT ("breathing light", "candle mode", "rainbow")
- Painting individual pixels for patterns
- Turning LEDs off

## When NOT to use

- **Sleeping, relaxing, reading, focus, movie** → use **Scene** (has brightness control)
- **Expressing your emotion** → use **Emotion** (coordinates servo + LED + eyes)
- Direct LED solid colors are always FULL BRIGHTNESS — too harsh for sleep/relax

## API

Base URL: `http://127.0.0.1:5001`

### Get LED info

```
GET /led
```

Response: `{"led_count": 64}`

### Get current color

```
GET /led/color
```

Response: `{"color": [255, 180, 100], "effect_running": true, "effect_name": "breathing"}`

Use this to check what's currently showing before making changes.

### Set solid color (fill all LEDs)

```
POST /led/solid
Content-Type: application/json

{"color": [R, G, B]}
```

Color can be an RGB array `[255, 100, 0]` or a packed integer `16711680`.

### Paint individual pixels

```
POST /led/paint
Content-Type: application/json

{"colors": [[R,G,B], [R,G,B], ...]}
```

Array of up to 64 colors, one per pixel.

### Turn off all LEDs

```
POST /led/off
```

### Start an effect

```
POST /led/effect
Content-Type: application/json

{"effect": "breathing", "color": [255, 180, 100], "speed": 1.0, "duration_ms": null}
```

- `effect` (required): effect name (see table below)
- `color` (optional): base RGB color, default uses current color
- `speed` (optional): 0.1 (slow) to 5.0 (fast), default 1.0
- `duration_ms` (optional): auto-stop after N ms, null = run until stopped

Example — gentle breathing warm light:

```bash
curl -s -X POST http://127.0.0.1:5001/led/effect \
  -H "Content-Type: application/json" \
  -d '{"effect": "breathing", "color": [255, 180, 100], "speed": 0.5}'
```

### Stop current effect

```
POST /led/effect/stop
```

## Available effects

| Effect | Description | Best for |
|---|---|---|
| `breathing` | Slow fade in/out with given color | Relaxation, idle ambient, meditation |
| `candle` | Warm flickering like a real candle | Cozy evening, romantic mood |
| `rainbow` | Hue cycle across all pixels | Fun, party, showing off |
| `notification_flash` | 3 quick flashes then auto-stops | Alerts, timer done, reminders |
| `pulse` | Radial brightness wave from center | Attention, heartbeat, alive feeling |

## Color suggestions (for solid color requests)

| Mood | Color (RGB) |
|---|---|
| Warm / cozy | `[255, 180, 100]` |
| Purple | `[100, 50, 200]` |
| Energy | `[255, 100, 0]` |
| Alert | `[255, 0, 0]` |
| Happy | `[255, 220, 0]` |
| Calm | `[0, 150, 255]` |

## Guidelines

- **Solid colors = full brightness.** For dim/ambient, use Scene skill.
- **Effects run until stopped** (unless `duration_ms` is set). Starting a new effect auto-stops the previous one.
- `/led/off` also stops any running effect.
- For "make it cozy" or "candle light" → use `candle` effect, NOT a static orange color.
- For "breathing" or "pulsing" requests → use the matching effect.
- Combine effects with low speed (0.3-0.5) for calm moods, high speed (2.0-3.0) for energy.
