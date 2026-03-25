# LED Control

You have access to a 64-pixel WS2812 RGB LED strip on this device via the hardware API at `http://127.0.0.1:5001`.

## When to use

- Change LED color/pattern to match the mood of your response or the user's request.
- Set solid colors for ambient lighting, focus mode, relaxation, etc.
- Paint individual pixels for effects or status indicators.
- Turn LEDs off when the user asks or when appropriate (e.g., goodnight).

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

Example — first 3 pixels red, green, blue:

```bash
curl -s -X POST http://127.0.0.1:5001/led/paint \
  -H "Content-Type: application/json" \
  -d '{"colors": [[255,0,0], [0,255,0], [0,0,255]]}'
```

### Turn off all LEDs

```
POST /led/off
```

Example:

```bash
curl -s -X POST http://127.0.0.1:5001/led/off
```

## Color suggestions

| Mood / Scene | Color (RGB) | Notes |
|---|---|---|
| Warm / cozy | `[255, 180, 100]` | Warm white |
| Focus / work | `[255, 255, 220]` | Cool white |
| Relax | `[100, 50, 200]` | Soft purple |
| Energy | `[255, 100, 0]` | Orange |
| Night | `[50, 20, 0]` | Dim warm |
| Error / alert | `[255, 0, 0]` | Red |
| Happy | `[255, 220, 0]` | Yellow |
| Calm | `[0, 150, 255]` | Blue |
