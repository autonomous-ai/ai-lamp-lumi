# Architecture Decision: AI Lamp — Hybrid Hardware Control

## Date: 2026-03-24

## 1. Context & Decision Journey

This project controls an AI-powered desk lamp built on a Raspberry Pi 4 with articulated servos, RGB LEDs, camera, microphone, and speaker.

The architecture went through several pivots before reaching the final design:

1. **Standalone Go + MCP** — Initially planned as a new Go project using MCP protocol for hardware control. Abandoned when we discovered OpenClaw uses its own native skill system (SKILL.md), not MCP.
2. **Fork lobster** — Discovered that openclaw-lobster (the Go server for OpenClaw hardware products, now renamed to Lumi) shares ~70-80% of the architecture we need. Decision: fork lobster, one repo per hardware product.
3. **LeLamp runtime already exists** — Discovered a Python runtime is ALREADY running on the Pi4 with working hardware drivers for servos (MotorsService), LEDs (RGBService), and audio (amixer). It was previously controlled via LiveKit @function_tool decorators.
4. **Final decision** — Hybrid architecture. OpenClaw replaces LiveKit + OpenAI entirely. OpenClaw skills call the Lumi HTTP API, which bridges to the existing LeLamp Python services for hardware access.

## 2. Final Architecture Decision

**Fork lobster + Hybrid two-layer architecture + LeLamp Python bridge + Hardware Plugin system.**

- **Layer 1 (System)**: Lumi Server handles system-critical functions that work without OpenClaw.
- **Layer 2 (Skills)**: OpenClaw's LLM reads SKILL.md files and calls Lumi HTTP endpoints, which bridge to LeLamp's Python hardware drivers.

The LeLamp Python runtime is kept as the hardware driver layer. We do NOT rewrite drivers in Go — we bridge to them.

### Hardware as Plugins (Plug & Play)

Every hardware component is a **plugin** — if it's plugged in, its driver loads and its skill becomes available. If not, the system works fine without it.

On startup, the Lumi server auto-detects connected hardware and:
1. Loads only the drivers for detected hardware
2. Enables only the corresponding HTTP API endpoints
3. Deploys only the relevant SKILL.md files to OpenClaw

| Plugin | Detection Method | If Missing |
|---|---|---|
| Servo Motors | USB serial port scan (Feetech) | No body language, lamp is static — still works as smart light |
| LED (WS2812) | SPI device check (`/dev/spidev0.0`) | No light control — system LED only |
| Camera | V4L2 device check (`/dev/video0`) | No gesture, presence, tracking — voice-only control |
| Microphone | ALSA device enumeration | No voice input — app/text control only |
| Speaker | ALSA device enumeration | No voice output — silent mode, LED-only feedback |
| Display (Eyes) | I2C/SPI device scan (GC9A01/SSD1306) | No eyes — LED-only emotion feedback |

This means the same codebase supports different product configurations:
- **Full lamp**: All plugins → complete AI companion
- **Simple lamp**: LED + Mic + Speaker only → smart light with voice
- **Dev/test**: No hardware → stub drivers, API still works

## 3. Software Stack

### OpenClaw — AI Brain

Replaces LeLamp's previous LiveKit + OpenAI stack completely. Provides:

- Personality and conversation management
- LLM inference (multi-provider: Anthropic, OpenAI, local)
- Native skill system (SKILL.md auto-discovery)
- Channels (voice, text, app)
- Memory and context

### LeLamp Runtime — Hardware Drivers (Python)

Already running on the Pi4. Provides event-driven services with priority dispatch via ServiceBase:

- **MotorsService** — 5x Feetech servo control (pan, tilt, 5-axis articulation)
- **RGBService** — 64x WS2812 LED control (8x5 grid, per-pixel color via rpi_ws281x)
- **Audio** — amixer volume, playback, TTS
- **DisplayService** — small round display (GC9A01 1.28" or similar), dual-mode: eyes emotion (default) + info display (time, weather, timer, notifications)

Previously controlled via LiveKit `@function_tool`. Will be controlled via Lumi HTTP API instead.

### Lumi Server — System Layer + HTTP API Bridge (Go)

Forked from openclaw-lobster. Provides:

- All system-critical services (boot, network, OTA, reset, MQTT)
- HTTP API on port 5000 that bridges requests to LeLamp Python services
- LED system states via direct SPI driver (independent of Python runtime)

## 4. Layer 1: System (Lumi Server, Always Running)

Works **without OpenClaw**. If the AI is down, the device still boots, shows status via LED, and can be re-provisioned.

| Function | Description |
|---|---|
| LED system states | Boot animation, error indication, no-internet pulse, factory reset — via direct WS2812 SPI driver |
| Reset button | GPIO 26 long-press detection for power off / factory reset |
| Network management | AP mode for provisioning, STA mode for operation, WiFi scanning |
| OTA updates | Version check, download, install via bootstrap |
| MQTT communication | Auto-reconnect, message dispatch to backend |
| Internet monitoring | Connectivity check, triggers LED error state on failure |
| **Autonomous sensing** | Lightweight sensing loop: camera (presence, light level), mic (sound level, silence, voice tone), time (schedules), plug-in sensors. Emits events to OpenClaw when significant changes detected. |

### Autonomous Sensing Loop (Layer 1.5)

Lumi runs a continuous, low-cost sensing loop that does **edge detection** on-device. When a significant event is detected, Lumi pushes context to OpenClaw for AI decision-making. This enables proactive behavior without burning LLM tokens continuously.

```
Sensing Loop (Lumi Server, always running):
  Camera → presence.enter / presence.leave / light.level
  Mic    → sound.level / sound.silence / sound.voice_tone
  Time   → time.schedule (cron-like)
  Sensor → sensor.* (plug-in: temp, humidity, etc.)
       │
       │ event + context (only on significant change)
       ▼
  OpenClaw (AI Brain) → decides action → calls Lumi HTTP API → hardware
```

**Rule-based actions** (no AI needed): auto-dim on leave, brightness adjust on darkness, idle animations.
**AI-driven actions** (OpenClaw decides): greetings, mood response, empathetic reactions, schedule-aware suggestions.

Inherited from lobster (now in `lumi/` subdirectory):

- `server/server.go` — Gin HTTP server on port 5000
- `server/config/` — JSON config with reload
- `internal/led/` — WS2812 SPI driver (pure Go) and state machine with auto-rollback
- `internal/resetbutton/` — GPIO long-press detection
- `internal/network/` — WiFi AP/STA management
- `internal/openclaw/` — OpenClaw config generation and WebSocket
- `internal/beclient/` — Backend status reporter
- `internal/device/` — Setup, MQTT command handling, status reporting
- `lib/mqtt/` — MQTT client with auto-reconnect
- `bootstrap/` — OTA version check and install
- `domain/` — Shared structs (device, LED, network, OTA, OpenClaw)

**MQTT commands** (received via fa_channel): `info`, `add_channel`, `ota`

**Removed from lobster**: GWS (Google Workspace) handlers, internal/llm/ service (LLM model listing inlined into openclaw/service.go), onboarding flow, sendip scripts, release scripts.

## 5. Layer 2: OpenClaw Skills (SKILL.md + HTTP API)

All user-facing hardware control uses OpenClaw's native skill system. This is **NOT MCP**.

How it works:

1. SKILL.md files are placed in `workspace/skills/`
2. OpenClaw auto-discovers them (`skills.load.watch: true`)
3. The LLM reads the SKILL.md description and understands available APIs
4. The LLM calls the Lumi HTTP API via `curl` at `127.0.0.1:5000`
5. The Lumi server bridges the request to the appropriate LeLamp Python service
6. The Python service drives the hardware

### Skills

| Skill | SKILL.md Location | Description |
|---|---|---|
| `led-control` | `workspace/skills/led-control/SKILL.md` | Color, brightness, scenes, effects, patterns for 64-LED grid |
| `servo-control` | `workspace/skills/servo-control/SKILL.md` | Pan, tilt, preset positions, expressions for 5 servo axes |
| `camera` | `workspace/skills/camera/SKILL.md` | Presence detection, face tracking, gesture recognition, light analysis |
| `audio` | `workspace/skills/audio/SKILL.md` | TTS output, sound effects, volume control, ambient sounds |
| `display` | `workspace/skills/display/SKILL.md` | Dual-mode: eyes emotion animation (default) + info display (time, weather, timer, notifications, system status) |
| `emotion` | `workspace/skills/emotion/SKILL.md` | Combined emotional expression (servo + LED + audio + display) |

### HTTP API Endpoints

| Endpoint | Method | Description | Bridges To |
|---|---|---|---|
| `/api/led` | GET | Get current LED state | RGBService |
| `/api/led` | POST | Set color, brightness, scene, effect, pattern | RGBService |
| `/api/servo` | GET | Get current servo positions | MotorsService |
| `/api/servo` | POST | Set pan, tilt, preset, expression | MotorsService |
| `/api/servo/home` | POST | Return all servos to home position | MotorsService |
| `/api/camera/presence` | GET | Check if someone is in the room | Camera module |
| `/api/camera/face` | GET | Get face position coordinates | Camera module |
| `/api/camera/gesture` | GET | Detect current hand gesture | Camera module |
| `/api/camera/light-analysis` | GET | Analyze face lighting quality | Camera module |
| `/api/audio/speak` | POST | Text-to-speech output | Audio / amixer |
| `/api/audio/sound` | POST | Play notification or effect sound | Audio / amixer |
| `/api/audio/volume` | POST | Set speaker volume | Audio / amixer |
| `/api/audio/ambient` | POST | Play or stop ambient sounds | Audio / amixer |
| `/api/display` | GET | Get current display state | DisplayService |
| `/api/display` | POST | Dual-mode: eyes emotion (default) or info display (time, weather, timer, notifications, system status) | DisplayService |
| `/api/emotion` | POST | Combined emotional expression | MotorsService + RGBService + Audio + Display |

### Example

User says: *"Point the light at my desk, focus mode"*

OpenClaw LLM reads `servo-control/SKILL.md` and `led-control/SKILL.md`, then executes:

```bash
curl -s -X POST http://127.0.0.1:5000/api/servo \
  -H "Content-Type: application/json" \
  -d '{"preset": "desk"}'

curl -s -X POST http://127.0.0.1:5000/api/led \
  -H "Content-Type: application/json" \
  -d '{"scene": "focus"}'
```

No command parsing logic needed — the LLM figures it out from the SKILL.md description.

## 6. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         User (Voice / Gesture / App)                │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        OpenClaw (AI / LLM)                          │
│                                                                     │
│  • Personality, conversation, memory                                │
│  • Multi-provider LLM (Anthropic, OpenAI, local)                    │
│  • Channels (voice, text, app)                                      │
│                                                                     │
│  workspace/skills/                                                  │
│  ├── led-control/SKILL.md                                           │
│  ├── servo-control/SKILL.md                                         │
│  ├── camera/SKILL.md                                                │
│  ├── audio/SKILL.md                                                 │
│  └── emotion/SKILL.md       ← key: combined emotional expression   │
│                                                                     │
│  LLM reads SKILL.md → calls curl → Lumi HTTP API                  │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ HTTP (127.0.0.1:5000)
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Lumi Server (Go, forked from lobster)          │
│                                                                     │
│  ┌───────────────────────────┐  ┌─────────────────────────────────┐ │
│  │  Layer 1: System          │  │  Layer 2: HTTP API Bridge       │ │
│  │  (always running)         │  │  (port 5000)                    │ │
│  │                           │  │                                 │ │
│  │  • LED boot/error (SPI)   │  │  /api/led     → LeLamp RGB     │ │
│  │  • Reset button (GPIO 26) │  │  /api/servo   → LeLamp Motors  │ │
│  │  • Network mgmt (AP/STA)  │  │  /api/camera  → Camera module  │ │
│  │  • OTA updates            │  │  /api/audio   → Audio / amixer │ │
│  │  • MQTT backend           │  │  /api/emotion → Motors+RGB+Audio│ │
│  │  • Internet monitor       │  │                                 │ │
│  │                           │  │  Bridges HTTP requests to       │ │
│  │  Works WITHOUT OpenClaw   │  │  LeLamp Python services         │ │
│  └───────────────────────────┘  └────────────────┬────────────────┘ │
│                                                   │                  │
└───────────────────────────────────────────────────┼──────────────────┘
                                                    │ Bridge (HTTP / gRPC / subprocess)
                                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   LeLamp Runtime (Python, on Pi4)                    │
│                                                                     │
│  • MotorsService  — 5x Feetech servos (5-axis articulation)        │
│  • RGBService     — 64x WS2812 LEDs (8x5 grid, rpi_ws281x)        │
│  • Audio          — amixer volume, playback, TTS                    │
│  • ServiceBase    — event-driven with priority dispatch             │
│                                                                     │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Hardware (Raspberry Pi 4)                    │
│                                                                     │
│  • 5x Feetech servo motors (5-axis articulated movement)            │
│  • 64x WS2812 RGB LEDs (8x5 grid, full color, per-pixel)           │
│  • Camera (inside lamp core, vision)                                │
│  • Microphone (voice input)                                         │
│  • Speaker (voice output)                                           │
│  • Reset button (GPIO 26)                                           │
└─────────────────────────────────────────────────────────────────────┘
```

## 7. Emotion Skill — Key Differentiator

The emotion skill is the most important new skill. It combines all hardware subsystems to create generative body language — making the lamp feel alive.

Instead of calling servo, LED, and audio separately, the LLM calls a single endpoint:

```
POST /api/emotion
{"emotion": "curious", "intensity": 0.8}
```

The Lumi server translates this into coordinated hardware actions:

- **Servo**: Tilt head forward and slightly to the side (curious posture)
- **LED**: Shift to warm yellow-white, gentle pulse
- **Audio**: Optional soft chime or intake sound

Each call produces a unique expression — predefined emotion presets with randomized parameters (slight variations in tilt angle, LED hue, timing) so the lamp never repeats the exact same gesture.

The LLM calls this whenever it wants to express emotion during conversation, making interactions feel natural and embodied rather than purely verbal.

## 8. Communication Flow

```
User speaks
  → Microphone captures audio
    → OpenClaw processes voice input
      → LLM generates response + decides on actions
        → LLM reads relevant SKILL.md files
          → LLM calls curl to Lumi HTTP API (127.0.0.1:5000)
            → Lumi Server receives HTTP request
              → Lumi bridges to LeLamp Python service
                → Python service drives hardware
                  → Servos move / LEDs change / Speaker outputs audio
```

## 9. Inherited from Lobster

| Component | Path | Notes |
|---|---|---|
| HTTP server | `server/server.go` | Gin framework, port 5000 |
| Config management | `server/config/` | JSON config with reload |
| LED SPI driver | `internal/led/` | WS2812 SPI driver (pure Go) |
| LED state machine | `internal/led/engine.go` | States, effects, auto-rollback |
| LED skill | `resources/openclaw-skills/led-control/SKILL.md` | Adapted for 64-LED grid |
| Reset button | `internal/resetbutton/` | GPIO 26 long-press |
| Network service | `internal/network/` | WiFi AP/STA, scanning |
| OpenClaw service | `internal/openclaw/` | Config generation, WebSocket |
| Backend client | `internal/beclient/` | Status reporter |
| Device service | `internal/device/` | Setup, MQTT command handling, status reporting |
| MQTT client | `lib/mqtt/` | Auto-reconnect, dispatch |
| OTA bootstrap | `bootstrap/` | Version check, install |
| Domain models | `domain/` | Shared structs (device, LED, network, OTA, OpenClaw) |
| Build and deploy | `scripts/`, `Makefile` | Cross-compile for ARM, systemd |

## 10. New to Build

| Component | Path | Description |
|---|---|---|
| Servo HTTP handlers | `server/servo/delivery/` | Gin routes for `/api/servo`, bridges to LeLamp MotorsService |
| Camera HTTP handlers | `server/camera/delivery/` | Gin routes for `/api/camera/*`, bridges to camera module |
| Audio HTTP handlers | `server/audio/delivery/` | Gin routes for `/api/audio/*`, bridges to audio / amixer |
| Emotion HTTP handler | `server/emotion/delivery/` | Gin route for `/api/emotion`, coordinates servo + LED + audio |
| OpenClaw skills | `resources/openclaw-skills/` | SKILL.md files for servo-control, camera, audio, emotion |
| Python bridge layer | TBD | Communication layer between Go Lumi server and LeLamp Python services (HTTP, gRPC, or subprocess) |

## 11. Open Questions

- [x] **Go-to-Python bridge**: HTTP proxy. LeLamp runs FastAPI on `127.0.0.1:5001`, Lumi Server proxies requests from port 5000. Simple, debuggable, no tight coupling.
- [ ] **Camera processing**: Run vision on-device with OpenCV, or offload to OpenClaw's vision capabilities?
- [ ] **Audio input**: Does OpenClaw handle the microphone directly, or does the Lumi server capture audio and forward it?
- [ ] **LED driver**: Adapt lobster's pure Go SPI driver for the 64-LED grid, or use LeLamp's existing rpi_ws281x Python driver via the bridge?
- [ ] **Generative body language**: How does the LLM generate servo positions for emotions? Predefined emotion presets with randomized parameters, or fully generative coordinates from the LLM?
