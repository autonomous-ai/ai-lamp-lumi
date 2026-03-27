# LED Control — Documentation

## Hardware

- **64 WS2812 RGB LEDs** — grid 8x5
- Driver: `rpi_ws281x` (Python, LeLamp owns)
- FastAPI endpoints on `:5001`

## Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/led` | LED strip info (count, available) |
| GET | `/led/color` | Current color `{"r", "g", "b"}` |
| POST | `/led/solid` | Fill entire strip with one color |
| POST | `/led/paint` | Set per-pixel colors (array up to 64 items) |
| POST | `/led/off` | Turn off all LEDs |
| POST | `/led/effect` | Start an effect |
| POST | `/led/effect/stop` | Stop running effect |

## Solid Color

```json
POST /led/solid
{"r": 255, "g": 180, "b": 100}
```

RGB values 0-255.

## Paint (Per-Pixel)

```json
POST /led/paint
{"pixels": [{"i": 0, "r": 255, "g": 0, "b": 0}, {"i": 1, "r": 0, "g": 255, "b": 0}]}
```

`i` = pixel index (0-63).

## Effects

```json
POST /led/effect
{"effect": "breathing", "color": [255, 100, 50], "speed": 1.0}
```

| Effect | Description | Params |
|--------|-------------|--------|
| `breathing` | Sine-wave brightness fade | color, speed |
| `candle` | Warm random flicker | color |
| `rainbow` | Hue rotation across strip | speed |
| `notification_flash` | 3 quick flashes then stop | color |
| `pulse` | Wavefront expanding from center | color, speed |

## Lighting Scenes

```json
POST /scene
{"scene": "reading"}
```

| Scene | Brightness | Color | Description |
|-------|-----------|-------|-------------|
| `reading` | 80% | Warm white | Reading |
| `focus` | 100% | Cool white | Focus work |
| `relax` | 40% | Warm amber | Relaxation |
| `movie` | 15% | Dim warm | Movie watching |
| `night` | 5% | Soft orange | Night light |
| `energize` | 100% | Bright daylight | Wake up |

## Status LED

See details: [status-led.md](status-led.md)

LED feedback for system states:

| State | Color | Effect |
|-------|-------|--------|
| Processing | Blue `(80, 140, 255)` | `pulse` |
| OTA | Orange `(255, 140, 0)` | `breathing` |
| Error | Red `(255, 30, 30)` | `pulse` |

Managed by `internal/statusled/Service` (lumi) and `lib/lelamp` (bootstrap).

## Ambient Idle Behaviors

When Lumi is idle (no interaction):
- **Breathing LED** — sine-wave brightness, warm palette

Auto-pauses on interaction, resumes after 60s of silence.

## LED in Emotion

Each emotion preset has its own LED color:

| Emotion | LED Color |
|---------|-----------|
| curious | Warm yellow |
| happy | Bright yellow |
| sad | Light blue |
| thinking | Soft purple |
| idle | Dim warm white |
| excited | Bright orange |
| shy | Soft pink |
| shock | White flash |
