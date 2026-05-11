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
| POST | `/led/restore` | Repaint user's saved LED state (or clear if none) |

### Transient writes

`/led/solid`, `/led/effect`, and `/led/off` accept an optional `"transient": true` flag. When set, the call paints the strip but does **not** overwrite the saved user LED state. The saved state is restored when the caller (e.g. Claude Desktop Buddy) is done — either via the natural emotion restore timer, or by an explicit `POST /led/restore`. Pulse effects launched with `transient: true` also overlay on the user's saved color instead of black.

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
{"effect": "breathing", "r": 255, "g": 100, "b": 50, "speed": 1.0}
```

| Effect | Description | Params |
|--------|-------------|--------|
| `breathing` | Sine-wave brightness up/down | r, g, b, speed |
| `candle` | Random flickering candle | r, g, b |
| `rainbow` | Hue rotation across strip | speed |
| `notification_flash` | Quick flash 3 times | r, g, b |
| `pulse` | Single pulse from center outward | r, g, b, speed |

## Lighting Scenes

```json
POST /scene
{"scene": "reading"}
```

Each scene controls **all peripherals** — not just LED, but also camera, mic, speaker, and servo.

Deactivate: `POST /scene/off` — clears active scene, restores idle LED, re-enables camera/speaker, releases servo hold.

| Scene | Bright | Color (K) | Servo | Camera | Mic | Speaker |
|-------|--------|-----------|-------|--------|-----|---------|
| `reading` | 80% | 4000K warm white | desk + hold | off | on | off |
| `focus` | 70% | 4200K warm-neutral | desk + hold | off | on | off |
| `relax` | 40% | 2700K warm | wall | on | on | on |
| `movie` | 15% | 2400K dim amber | wall | off | on | off |
| `night` | 5% | 1800K deep amber | down | off | on | off |
| `energize` | 100% | 5000K daylight | up | on | on | on |

### Scene peripheral control

When a scene activates, `POST /scene` applies in order:

1. **LED** — solid color = `preset.color × preset.brightness`
2. **Servo aim** — moves lamp head to preset direction (desk, wall, up, down)
3. **Servo hold** — if `"servo": "hold"`, freezes servo **after** aim completes (aim → hold in one thread). Released when switching to a scene without hold.
4. **Camera** — auto on/off via `_auto_camera_on`/`_auto_camera_off`
5. **Mic** — mute stops voice pipeline (STT), unmute restarts it
6. **Speaker** — mute stops TTS + music playback, unmute re-enables output

### Emotion suppression during hold mode

When servo is in hold mode (reading/focus), **emotion animations are suppressed** to avoid distraction:

- `happy`, `thinking`, `curious`, `sad`, etc. → servo + LED skipped
- `greeting`, `sleepy`, `stretching` → **allowed** (these signal state changes: wake, sleep, scene transition)

This means during focus, sensing events (face emotion, motion) still reach OpenClaw but Lumi stays physically still and visually stable.

### Color temperature rationale

- **Focus 4200K/70%** (not 5000K/100%) — 4000-4300K optimizes alertness without visual fatigue for sustained work
- **Night 1800K deep amber** — blue-free wavelengths (>580nm) preserve melatonin production
- **Movie mic on** — allows voice control ("pause", "stop") while watching

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

See [emotion-led-mapping.md](emotion-led-mapping.md) for the full emotion → LED color + effect + servo mapping.
