# Architecture Decision: Hybrid Hardware Control

## Date: 2026-03-24

## Context

This project (AI Lamp) shares ~70-80% of its software architecture with [openclaw-lobster](../../../openclaw-lobster) (codename "Intern"). The key difference is that AI Lamp has more peripherals: Servo Motor, Camera, Microphone, Speaker — in addition to LED.

The question arose: **How should hardware control be architected?**

## Decision: Fork Lobster + Hybrid Architecture

### 1. Separate Repos Per Device (Fork Strategy)

Each hardware product has its own codebase. AI Lamp forks from openclaw-lobster and adapts for its specific hardware.

**Rationale**: Simple, clear ownership, no over-engineering. Each device evolves independently.

### 2. Hybrid Hardware Control (System Layer + MCP Layer)

Instead of embedding all hardware control inside the intern server (like lobster does with LED), we split into two layers:

#### Layer 1 — System (Intern Server, always running)

Handles **system-critical** functions that must work **before and without OpenClaw**:

- LED system states (boot, error, no internet, factory reset)
- Reset button (GPIO)
- Network management (AP/STA, WiFi provisioning)
- OTA updates
- MQTT backend communication
- Internet monitoring

These are inherited directly from lobster's existing architecture:
- `internal/led/` — LED state machine with auto-rollback
- `internal/resetbutton/` — GPIO long-press detection
- `internal/network/` — WiFi management
- `internal/openclaw/` — OpenClaw config & WebSocket
- `lib/mqtt/` — MQTT client

**Key principle**: If OpenClaw is down, the device still boots, shows status via LED, and can be re-provisioned.

#### Layer 2 — MCP Server (runs alongside Intern, exposed to OpenClaw)

All **user-facing hardware control** is packaged as an MCP (Model Context Protocol) server. OpenClaw sees hardware as tools/skills it can call directly.

**MCP Tools exposed**:

| Tool | Description | Hardware |
|---|---|---|
| `led.set_brightness` | Set LED brightness (0-100%) | LED |
| `led.set_color` | Set RGB color or color temperature | LED |
| `led.set_scene` | Activate predefined scene (reading, focus, relax, movie, night, energize) | LED |
| `led.set_effect` | Trigger effect (breathing, candle, rainbow, notification) | LED |
| `servo.pan` | Rotate lamp horizontally (0-180°) | Servo Motor |
| `servo.tilt` | Tilt lamp vertically (0-90°) | Servo Motor |
| `servo.set_position` | Move to preset position (desk, wall, center) | Servo Motor |
| `servo.home` | Return to home/default position | Servo Motor |
| `camera.get_presence` | Check if someone is in the room | Camera |
| `camera.get_face_position` | Get face coordinates for tracking | Camera |
| `camera.get_gesture` | Detect hand gesture | Camera |
| `camera.get_light_analysis` | Analyze face lighting quality (for video call) | Camera |
| `audio.speak` | Text-to-speech output | Speaker |
| `audio.play_sound` | Play notification/effect sound | Speaker |
| `audio.set_volume` | Set speaker volume (0-100%) | Speaker |
| `audio.play_ambient` | Play ambient sounds (rain, nature) | Speaker |

**How it works with OpenClaw**:

The LLM (via OpenClaw) receives user input and autonomously decides which tools to call. No command parsing needed in the intern server.

Example — User says: *"Point the light at my desk, focus mode"*

OpenClaw LLM calls:
```json
[
  {"tool": "servo.set_position", "params": {"preset": "desk"}},
  {"tool": "led.set_scene", "params": {"scene": "focus"}}
]
```

Example — User says: *"Is anyone in the room?"*

OpenClaw LLM calls:
```json
[
  {"tool": "camera.get_presence", "params": {}}
]
```
Then responds verbally via `audio.speak`.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────┐
│                     Intern Server (Go)                    │
│                                                          │
│  ┌─────────────────────┐   ┌──────────────────────────┐  │
│  │   Layer 1: System    │   │   Layer 2: MCP Server    │  │
│  │   (always running)   │   │   (exposed to OpenClaw)  │  │
│  │                     │   │                          │  │
│  │  • LED boot/error   │   │  Tools:                  │  │
│  │  • Reset button     │   │  • led.set_brightness()  │  │
│  │  • Network mgmt    │   │  • led.set_color()       │  │
│  │  • OTA updates     │   │  • led.set_scene()       │  │
│  │  • MQTT dispatch   │   │  • servo.pan()           │  │
│  │  • Internet monitor │   │  • servo.tilt()          │  │
│  │                     │   │  • camera.get_presence() │  │
│  │  Works WITHOUT      │   │  • camera.get_gesture()  │  │
│  │  OpenClaw           │   │  • audio.speak()         │  │
│  │                     │   │  • audio.set_volume()    │  │
│  └─────────────────────┘   └────────────┬─────────────┘  │
│                                          │                │
└──────────────────────────────────────────┼────────────────┘
                                           │ MCP (stdio/SSE)
                                           ▼
                                   ┌──────────────┐
                                   │   OpenClaw    │
                                   │   (AI/LLM)   │
                                   │              │
                                   │  Calls tools │
                                   │  via MCP     │
                                   └──────┬───────┘
                                          │
                                          ▼
                                   ┌──────────────┐
                                   │  User (Voice/ │
                                   │  Gesture/App) │
                                   └──────────────┘
```

## Hardware ↔ Layer Mapping

| Hardware | Layer 1 (System) | Layer 2 (MCP Tools) |
|---|---|---|
| **LED** | Boot, error, status states | Brightness, color, scenes, effects |
| **Servo Motor** | — | Pan, tilt, preset positions, tracking |
| **Camera** | — | Presence detection, gesture, face tracking, light analysis |
| **Microphone** | — | Voice input (handled by OpenClaw directly) |
| **Speaker** | — | TTS output, notifications, ambient sounds |
| **Reset Button** | Long-press power off / factory reset | — |
| **Network** | AP/STA, WiFi provisioning, internet monitor | — |

## Benefits

1. **Reliability**: System-critical functions (LED status, network, OTA) work without OpenClaw
2. **AI-native**: LLM decides which hardware to control — no manual command parsing
3. **Extensibility**: Adding new hardware = adding new MCP tool definitions
4. **Clean separation**: System layer vs user-facing layer clearly defined
5. **Inherited from lobster**: 70-80% of Layer 1 code is proven, production-ready

## Inherited from Lobster (openclaw-lobster)

The following components are forked directly:

| Component | Lobster Path | Notes |
|---|---|---|
| HTTP Server | `server/server.go` | Gin framework, port 5000 |
| Config management | `server/config/` | JSON config with reload |
| LED driver | `internal/led/` | WS2812 SPI driver (pure Go) |
| LED state machine | `internal/led/engine.go` | States, effects, auto-rollback |
| Reset button | `internal/resetbutton/` | GPIO 26 long-press |
| Network service | `internal/network/` | WiFi AP/STA, scanning |
| OpenClaw service | `internal/openclaw/` | Config gen, WebSocket |
| Backend client | `internal/beclient/` | Status reporter |
| MQTT client | `lib/mqtt/` | Auto-reconnect, dispatch |
| OTA bootstrap | `bootstrap/` | Version check, install |
| Domain models | `domain/` | Shared structs |
| Build & deploy | `scripts/`, `Makefile` | Cross-compile, systemd |

## New for AI Lamp

| Component | Path (planned) | Description |
|---|---|---|
| MCP Server | `mcp/` | MCP protocol handler, tool registry |
| Servo driver | `internal/servo/` | PWM control for pan/tilt servo |
| Camera service | `internal/camera/` | OpenCV/GoCV or V4L2 for vision |
| Audio service | `internal/audio/` | ALSA/PulseAudio for mic + speaker |
| MCP tool definitions | `mcp/tools/` | LED, servo, camera, audio tool handlers |

## Open Questions

- [ ] MCP transport: stdio or SSE? (depends on how OpenClaw spawns MCP servers)
- [ ] Camera processing: on-device (GoCV) or offload to OpenClaw vision capabilities?
- [ ] Audio input: does OpenClaw handle mic directly, or does intern capture and forward?
- [ ] Servo hardware: which servo model? How many axes (1 pan or pan+tilt)?
- [ ] LED type: same WS2812 as lobster, or different LED for lamp?
