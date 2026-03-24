# AI Lamp — Product Vision

> The world's first lamp that truly knows you.

---

## 1. Vision & Mission

**Vision**: Create the most intelligent, expressive, and useful desk lamp ever made — a lamp that is not merely controlled, but genuinely understood by the person who uses it.

**Mission**: Combine best-in-class desk lighting with a deeply personal AI companion and an open-source platform, so that a single object on your desk replaces an app-controlled light, a smart speaker, a desk robot, and a mood indicator — and does each of those jobs better than any dedicated product.

**One-sentence pitch**: AI Lamp is the best desk lamp in the world, the most expressive companion robot, the smartest AI assistant (powered by OpenClaw), and an open-source platform — no other product combines all four.

---

## 2. The Four Pillars — What Makes AI Lamp 10x Better

Every competitor delivers one of these partially. AI Lamp delivers all four completely.

### Pillar 1: "It Understands Me" — Deep Personal AI

Most smart lamps respond to commands. AI Lamp responds to *you*.

| Situation | What AI Lamp Does |
|---|---|
| You sound stressed (voice tone analysis) | Auto-dims, plays soft ambient sound, lamp leans closer |
| You are deep in focus (sustained quiet typing) | Stays silent, holds focus lighting, suppresses notifications |
| You just walked in after work | Happy greeting, warm light, asks about your day |
| You are staying up past midnight | Gentle reminder, reduces blue light gradually |
| A week later | "Last week you said you had a deadline — how did it go?" |

**Why no competitor can match this**: OpenClaw's long-term memory persists across days, weeks, and months. Multi-provider LLM support (OpenAI, Anthropic, Gemini, local models) means the AI layer is never locked to a single vendor's capability ceiling. The lamp literally gets to know you over time.

### Pillar 2: "It Feels Alive" — Generative Body Language

Competing products replay preset animations. AI Lamp generates unique physical expressions in real time.

| Emotion | Servo (5-axis) | LED (64 RGB pixels) | Audio |
|---|---|---|---|
| Curious | Tilt head toward user | Soft warm yellow | Quiet inquisitive hum |
| Thinking | Gentle rhythmic sway | Slow purple pulse | — |
| Surprised | Quick upward rise | Bright white flash | Short chime |
| Sad | Slow droop downward | Dim cool blue | — |
| Excited | Energetic bounce | Fast rainbow ripple | Happy chirp |
| Listening | Slight lean forward | Steady soft white ring | — |

The LLM decides the combination of servo position, LED pattern, and audio for each reaction. Because the parameters are continuous (angle, color, timing, intensity), no two expressions are identical. The lamp never feels robotic.

### Pillar 3: "It's Actually Useful" — Not Just Cute

Expressiveness without utility is a toy. AI Lamp is a serious productivity and wellness tool.

- **Best desk lamp**: Circadian lighting that adjusts color temperature throughout the day. Video call optimization that analyzes your face lighting and repositions the lamp head. Focus mode that locks brightness and suppresses interruptions.
- **Real assistant**: Calendar awareness, email summaries, reminders, news briefs, timer/Pomodoro — all via natural voice.
- **Extensible skills**: Community-created SKILL.md files add new capabilities without firmware updates. Personalities, animations, integrations — all pluggable.
- **Multi-channel presence**: Chat with your lamp via Telegram, Slack, or Discord when you are away from your desk. It is still "there."
- **Open source platform**: Fork it, extend it, build products on it.

### Pillar 4: "It Acts on Its Own" — Autonomous Sensing & Proactive Behavior

Most smart devices are reactive — they wait for commands. Lumi is **proactive** — it continuously senses its environment and acts autonomously without being asked.

This is the difference between a tool and a companion. A tool waits. A companion pays attention.

#### How It Works — Hybrid Sensing Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Lumi Server (Go) — Lightweight Sensing Loop                    │
│                                                                 │
│  Continuous, low-cost edge detection:                           │
│  • Camera: presence/absence, light level, face position         │
│  • Mic: ambient sound level, silence duration, voice tone       │
│  • Time: clock, schedule, duration since last interaction       │
│  • Sensors: temperature, humidity (if plugged in)               │
│                                                                 │
│  When event detected → push context to OpenClaw                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │ event + context
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  OpenClaw (AI Brain) — Decision & Action                        │
│                                                                 │
│  Receives sensor context → LLM decides what to do:              │
│  • Adjust lighting? Move servo? Speak? Stay quiet?              │
│  • Factor in: time of day, user history, current mood,          │
│    long-term memory, personality                                │
│  • Execute via SKILL.md → curl to Lumi HTTP API                 │
└─────────────────────────────────────────────────────────────────┘
```

**Lumi = senses (cheap, always-on).** **OpenClaw = brain (smart, called when needed).**

#### Autonomous Behaviors

| Trigger | What Lumi Senses | What Lumi Does | Who Decides |
|---|---|---|---|
| **Arrive** | Camera: person enters frame | Turn on, warm greeting, adjust light to preference | OpenClaw (personality) |
| **Leave** | Camera: no presence for 15 min | Dim → sleep → off | Lumi (rule-based, configurable) |
| **Darkness** | Camera: ambient light drops | Gradually increase brightness | Lumi (auto) + OpenClaw (scene choice) |
| **Focus** | Mic: sustained silence + typing sounds | Hold steady, suppress interruptions | Lumi (detect) → OpenClaw (confirm) |
| **Stress** | Mic: sighs, tense voice tone | Shift to warm light, offer break | OpenClaw (empathy, memory) |
| **Joy** | Mic: laughter | Lumi bounces, warm flash, join the mood | OpenClaw (emotion skill) |
| **Late night** | Time: past user's usual bedtime | Reduce blue light, gentle reminder | OpenClaw (memory: knows user schedule) |
| **Idle** | No interaction for 30+ min | Idle animations — gentle breathing LED, occasional blink | Lumi (built-in, no AI needed) |
| **Wake up** | Time: morning schedule | Sunrise simulation, gentle chime | Lumi (schedule) + OpenClaw (greeting) |
| **Video call** | Camera: face centered + screen glow | Auto-optimize face lighting | Lumi (detect) → OpenClaw (adjust) |

#### Sensing Event Types

Lumi Server runs a lightweight sensing loop that emits events:

| Event | Source | Frequency | Cost |
|---|---|---|---|
| `presence.enter` | Camera (face/body detection) | On change | Low (simple CV) |
| `presence.leave` | Camera (no face timeout) | On change | Low |
| `light.level` | Camera (frame brightness) | Every 30s | Minimal |
| `sound.level` | Mic (RMS amplitude) | Every 5s | Minimal |
| `sound.silence` | Mic (silence duration > threshold) | On change | Minimal |
| `sound.voice_tone` | Mic (pitch/energy analysis) | On voice detected | Medium |
| `time.schedule` | Clock (cron-like triggers) | Per schedule | None |
| `sensor.*` | Plug-in sensors (temp, humidity) | Configurable | Low |

Events are lightweight — no LLM tokens burned. Only when an event is significant enough does Lumi push context to OpenClaw for AI decision-making.

#### Privacy & Control

- User can disable any sensing channel independently (camera off, mic off, sensors off)
- "Do Not Disturb" mode: all proactive behaviors paused, Lumi only responds to direct commands
- All sensing runs **on-device** — no video/audio streamed to cloud for ambient processing
- Privacy indicator: LED color change when camera/mic actively sensing

---

## 3. Competitive Analysis

### Detailed Comparison

| Dimension | Philips Hue | LIFX | Govee | Dyson Lightcycle | Ongo (Interaction Labs) | LeLamp | **AI Lamp** |
|---|---|---|---|---|---|---|---|
| **Type** | Smart lighting ecosystem | Wi-Fi smart bulb | Budget smart LED | Premium desk lamp | AI robot lamp | Open-source robot lamp | **AI-native desk lamp** |
| **AI** | None | None | Text-to-scene only | Fixed algorithm | Basic ChatGPT | Basic (LiveKit + OpenAI) | **OpenClaw: multi-provider LLM, long-term memory, skills** |
| **Personality** | None | None | None | None | "Cat in a desk lamp" (by Alec Sokolow) | Minimal | **Generative, evolving, deeply personal** |
| **Movement** | None | None | None | None | Yes (motorized) | Yes (servo) | **Yes — 5-axis articulated (Feetech)** |
| **Vision** | None | None | None | None | Camera (basic) | Camera | **Camera: face tracking, gesture, presence, light analysis** |
| **Voice** | Via Alexa/Google | Via Alexa/Google | Via Alexa/Google | None | Built-in | Built-in (LiveKit) | **Built-in: mic + speaker + OpenClaw TTS** |
| **Memory** | None | None | None | None | Session only | Session only | **Persistent across days/weeks/months** |
| **LLM Providers** | N/A | N/A | N/A | N/A | OpenAI only | OpenAI only | **Multi-provider (OpenAI, Anthropic, Gemini, local, etc.)** |
| **Skills / Extensibility** | Hue API | LIFX API | Govee API | None | Closed | Limited presets (10 animations) | **Open skill ecosystem (SKILL.md), community-driven** |
| **Multi-channel** | App only | App only | App only | None | None | None | **Telegram, Slack, Discord + voice** |
| **Open Source** | No | No | No | No | No | Yes | **Yes** |
| **Offline** | Partial (Zigbee) | No | No | Yes | Unknown | Partial | **Yes — Layer 1 system functions always work** |
| **Price Range** | $50-200 (bulbs) | $30-80 | $15-60 | $500-650 | ~$300 (est.) | DIY | **DIY / Kit (target < $200 BOM)** |

### Why Each Competitor Falls Short

- **Philips Hue / LIFX / Govee**: Remote-controlled lights. No AI. No personality. No physical expression. They are appliances, not companions.
- **Dyson Lightcycle**: Excellent optics and build quality. But it is a fixed lamp with a fixed algorithm. No voice, no vision, no personality, no extensibility. A premium tool, not a companion.
- **Ongo (Interaction Labs)**: The closest competitor. Designed by Toy Story writer Alec Sokolow as "a cat trapped in a desk lamp body." It moves, sees, hears, talks, and has privacy sunglasses. But: shallow AI (single ChatGPT integration), closed source, no skills ecosystem, no long-term memory, no multi-channel, no multi-provider LLM. It is a charming toy; AI Lamp is a platform.
- **LeLamp**: Open-source robot lamp with decent hardware (servo, camera, LED). Uses LiveKit + OpenAI. But: 10 preset animations (not generative), basic AI with no memory depth, no ecosystem, no multi-channel. Good starting point — AI Lamp builds on its hardware legacy with a vastly superior AI brain (OpenClaw).

---

## 4. Hardware Specification

| Component | Detail | Role |
|---|---|---|
| **Compute** | Raspberry Pi 4 (4GB+) | Runs all software layers |
| **Servo Motors** | 5x Feetech servo motors | 5-axis articulated movement (pan, tilt, lean, nod, rotate) |
| **LEDs** | 64x WS2812 RGB LEDs (8x5 grid + extras) | Full-color per-pixel patterns, scenes, effects, status indication |
| **Camera** | Camera module (inside lamp core) | Face tracking, gesture recognition, presence detection, light analysis |
| **Microphone** | USB or I2S microphone | Voice input, wake word, conversation |
| **Speaker** | USB or I2S speaker | Voice output (TTS), notifications, ambient sounds |
| **Display** | GC9A01 1.28" round LCD (SPI) | Dual-mode: eyes emotion animation (default) + info display (time, weather, timer, notifications) |
| **GPIO** | Reset button (GPIO 26) | Long-press: factory reset / power off |
| **Connectivity** | Wi-Fi (built into Pi 4) | Network, OTA, MQTT, remote control |

### Physical Design Principles

- The lamp head is the "face" — round LCD display shows expressive pixel-art eyes (default) or useful info; LEDs provide ambient expression; camera provides vision; servo provides neck movement
- 5 axes of freedom enable lifelike postures: curiosity (tilt), attention (lean forward), sadness (droop), excitement (bounce)
- Camera is recessed inside the lamp core — visible but not intrusive
- All cables route through the articulated arm internally

---

## 5. Software Architecture

### Design Principle: Hybrid — System Layer + OpenClaw Skills Layer

The architecture is split into two layers with a clear boundary. This is **NOT MCP** — it uses OpenClaw's native skill system.

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│                        LUMI SERVER (Go)                             │
│                     (forked from openclaw-lobster)                   │
│                                                                     │
│  ┌──────────────────────────┐   ┌────────────────────────────────┐  │
│  │                          │   │                                │  │
│  │   LAYER 1: SYSTEM        │   │   HTTP API (127.0.0.1:5000)    │  │
│  │   (always running)       │   │   (Layer 2 interface)          │  │
│  │                          │   │                                │  │
│  │   • LED boot/error/      │   │   /api/led    → LED driver     │  │
│  │     status states        │   │   /api/servo  → Servo driver   │  │
│  │   • Reset button (GPIO)  │   │   /api/camera → Vision engine  │  │
│  │   • Network management   │   │   /api/audio  → Audio engine   │  │
│  │     (AP/STA, WiFi)       │   │                                │  │
│  │   • OTA updates          │   │   Called by OpenClaw LLM       │  │
│  │   • MQTT backend comms   │   │   via curl commands            │  │
│  │   • Internet monitoring  │   │   (described in SKILL.md)      │  │
│  │                          │   │                                │  │
│  │   Works WITHOUT OpenClaw │   │                                │  │
│  │                          │   │                                │  │
│  └──────────────────────────┘   └───────────────┬────────────────┘  │
│                                                  │                   │
└──────────────────────────────────────────────────┼───────────────────┘
                                                   │
                                          HTTP (localhost:5000)
                                                   │
┌──────────────────────────────────────────────────▼───────────────────┐
│                                                                      │
│                     OPENCLAW (AI Brain)                               │
│                                                                      │
│   ┌────────────────────────────────────────────────────────────┐     │
│   │  workspace/skills/                                         │     │
│   │  ├── led-control/SKILL.md      (inherited from lobster)    │     │
│   │  ├── servo-control/SKILL.md    (NEW)                       │     │
│   │  ├── camera/SKILL.md           (NEW)                       │     │
│   │  └── audio/SKILL.md            (NEW)                       │     │
│   └────────────────────────────────────────────────────────────┘     │
│                                                                      │
│   • Multi-provider LLM (OpenAI, Anthropic, Gemini, local)           │
│   • Personality engine                                               │
│   • Long-term memory (persistent across sessions)                    │
│   • Voice pipeline (STT → LLM → TTS)                                │
│   • Multi-channel (Telegram, Slack, Discord)                         │
│   • Skill auto-discovery (skills.load.watch: true)                   │
│                                                                      │
│   LLM reads SKILL.md → understands API → calls Lumi via curl        │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │   USER            │
                    │   Voice / Gesture  │
                    │   Telegram / Slack │
                    └───────────────────┘
```

### Layer 1 — System (Lumi Server, Always Running)

Handles system-critical functions that must work **before and without OpenClaw**.

| Function | Description |
|---|---|
| LED system states | Boot animation, error indicator, no-internet warning, factory reset feedback |
| Reset button | GPIO 26 long-press detection for power off / factory reset |
| Network management | Wi-Fi AP/STA mode, scanning, provisioning |
| OTA updates | Version check, download, install from backend |
| MQTT | Backend communication, status reporting |
| Internet monitoring | Connectivity checks, auto-recovery |

**Key principle**: If OpenClaw crashes, the lamp still boots, shows its status via LED, and can be re-provisioned via the reset button and network manager.

### Layer 2 — OpenClaw Skills (User-Facing Hardware Control)

All user-facing hardware interaction follows a single pattern:

1. **Lumi server** exposes an HTTP endpoint for the hardware component
2. **SKILL.md** file describes that endpoint in natural language
3. **OpenClaw's LLM** reads the SKILL.md, understands the API, and calls it via `curl`

**HTTP API Endpoints**:

| Endpoint | Method | Description | Skill |
|---|---|---|---|
| `/api/led` | GET | Get current LED state | led-control |
| `/api/led` | POST | Set LED state, brightness, color, scene, effect | led-control |
| `/api/servo` | GET | Get current servo positions | servo-control |
| `/api/servo` | POST | Set servo pan/tilt/preset | servo-control |
| `/api/servo/home` | POST | Return all servos to home position | servo-control |
| `/api/camera/presence` | GET | Check if someone is in the room | camera |
| `/api/camera/face` | GET | Get face position coordinates | camera |
| `/api/camera/gesture` | GET | Detect current hand gesture | camera |
| `/api/camera/light-analysis` | GET | Analyze face lighting quality | camera |
| `/api/audio/speak` | POST | Text-to-speech output | audio |
| `/api/audio/sound` | POST | Play notification/effect sound | audio |
| `/api/audio/volume` | POST | Set speaker volume | audio |
| `/api/audio/ambient` | POST | Play/stop ambient sounds | audio |

### LeLamp Runtime (Python) — Hardware Drivers Only

The LeLamp open-source project provides proven Python drivers for servo motors, WS2812 LEDs, and audio I/O. In our architecture:

- **Used**: Hardware drivers (servo PWM, LED SPI, audio ALSA/PulseAudio)
- **Replaced entirely**: LeLamp's AI/personality layer is removed; OpenClaw is the sole AI brain

This is a deliberate decision. OpenClaw's multi-provider LLM, long-term memory, skill ecosystem, and multi-channel support are categorically superior to LeLamp's basic LiveKit + OpenAI integration.

### Hardware-to-Layer Mapping

| Hardware | Layer 1 (System) | Layer 2 (OpenClaw Skills) |
|---|---|---|
| **LED (WS2812)** | Boot, error, status states | Brightness, color, scenes, effects, expressions |
| **Servo Motors** | — | Pan, tilt, presets, tracking, body language |
| **Camera** | — | Presence, gesture, face tracking, light analysis |
| **Microphone** | — | Voice input (handled by OpenClaw directly) |
| **Speaker** | — | TTS, notifications, ambient sounds |
| **Display (LCD)** | — | Dual-mode: eyes emotion (default) + info display (time, weather, timer, notifications) |
| **Reset Button** | Long-press reset / power off | — |
| **Network (Wi-Fi)** | AP/STA, provisioning, monitoring | — |

### Inherited from Lobster (openclaw-lobster)

The Lumi server is forked from openclaw-lobster. Approximately 70-80% of Layer 1 code is proven and production-ready:

| Component | Lobster Path | Status |
|---|---|---|
| HTTP Server (Gin) | `server/server.go` | Inherited |
| Config management | `server/config/` | Inherited |
| LED driver (WS2812 SPI, pure Go) | `internal/led/` | Inherited, adapted |
| LED state machine | `internal/led/engine.go` | Inherited |
| LED skill (SKILL.md) | `resources/openclaw-skills/led-control/` | Inherited, adapted |
| Reset button | `internal/resetbutton/` | Inherited |
| Network service | `internal/network/` | Inherited |
| OpenClaw service | `internal/openclaw/` | Inherited |
| Backend client | `internal/beclient/` | Inherited |
| MQTT client | `lib/mqtt/` | Inherited |
| OTA bootstrap | `bootstrap/` | Inherited |
| Build & deploy | `scripts/`, `Makefile` | Inherited |

### New Components for AI Lamp

| Component | What to Build | OpenClaw Integration |
|---|---|---|
| `internal/servo/` | Servo PWM driver (5-axis) | `servo-control/SKILL.md` → `POST /api/servo` |
| `internal/camera/` | Vision processing (OpenCV/V4L2) | `camera/SKILL.md` → `GET /api/camera/*` |
| `internal/audio/` | Speaker + Mic (ALSA/PulseAudio) | `audio/SKILL.md` → `POST /api/audio/*` |
| `internal/display/` | Display driver (GC9A01 SPI), dual-mode rendering | `display/SKILL.md` → `POST /api/display` |
| `server/servo/delivery/` | Servo HTTP handlers | Gin routes |
| `server/camera/delivery/` | Camera HTTP handlers | Gin routes |
| `server/audio/delivery/` | Audio HTTP handlers | Gin routes |

---

## 6. Use Cases

### Priority Legend

- **P0 — Critical**: Must work in first prototype. The product is broken without these.
- **P1 — High**: Required for meaningful user experience. Delivered in v1.0.
- **P2 — Medium**: Differentiators that elevate the product. Delivered in v1.x.

### UC-01: Voice-Controlled Lighting [P0]

**Actor**: User
**Description**: Control the lamp using natural language via OpenClaw voice pipeline.

**Examples**:
- "Turn on the light"
- "Dim to 30%"
- "Make it brighter"
- "Turn off"

**Acceptance Criteria**:
- Responds to on/off and brightness (0-100%) commands
- Voice-to-action latency < 1 second
- Supports English and Vietnamese

---

### UC-02: Color & Color Temperature Control [P0]

**Actor**: User
**Description**: Change light color (RGB) or color temperature (warm/cool white) via voice.

**Examples**:
- "Warm white please"
- "Change to blue"
- "Set color temperature to 4000K"
- "Sunset orange"

**Acceptance Criteria**:
- Full RGB spectrum via 64 WS2812 LEDs
- Color temperature range 2700K-6500K (simulated via RGB mixing)
- Accepts color names, hex codes, and descriptive terms

---

### UC-03: Scene / Mood Presets [P1]

**Actor**: User
**Description**: Activate predefined or AI-generated lighting scenes.

**Examples**:
- "Reading mode" / "Focus mode" / "Movie mode"
- "Make it feel like a rainy afternoon" (AI-generated)

**Predefined Scenes**:

| Scene | Brightness | Color Temp | Notes |
|---|---|---|---|
| Reading | 80% | 4000K (neutral) | Warm white, servo aimed at desk |
| Focus | 100% | 5000K (cool) | Cool white, no disturbance mode |
| Relax | 40% | 2700K (warm) | Warm, gentle breathing effect |
| Movie | 15% | 2700K (warm) | Dim amber, bias lighting |
| Night | 5% | 2200K (very warm) | Minimal, sleep-friendly |
| Energize | 100% | 6500K (daylight) | Full daylight simulation |

**Acceptance Criteria**:
- Minimum 6 predefined scenes
- AI generates custom scenes from natural language
- Smooth transitions (fade, not instant)

---

### UC-04: Timer & Schedule [P1]

**Actor**: User
**Description**: Set timers or recurring schedules for lighting changes.

**Examples**:
- "Turn off in 30 minutes"
- "Wake me up at 6:30 AM with sunrise light"
- "Dim gradually over 20 minutes"

**Acceptance Criteria**:
- One-time timers
- Recurring schedules (daily, weekdays, weekends)
- Sunrise/sunset simulation (gradual transition over 15-30 min)

---

### UC-05: Adaptive / Circadian Lighting [P2]

**Actor**: System (automatic)
**Description**: Automatically adjust color temperature throughout the day to support circadian rhythm.

**Behavior**:

| Time | Color Temperature | Purpose |
|---|---|---|
| 6:00-9:00 | 5000-6500K (cool, rising) | Energize, wake up |
| 9:00-17:00 | 4000-5000K (neutral) | Focus, productivity |
| 17:00-21:00 | 3000-3500K (warm, falling) | Wind down |
| 21:00+ | 2200-2700K (very warm, dim) | Prepare for sleep |

**Acceptance Criteria**:
- Schedule adjusts to user timezone
- Manual override lasts until next period transition
- Feature is toggleable

---

### UC-06: AI Conversational Companion [P1]

**Actor**: User
**Description**: The lamp serves as a conversational AI companion powered by OpenClaw — not just a light controller.

**Examples**:
- "What's the weather today?" (adjusts light color to match — blue for rain, warm for sun)
- "Tell me a joke" (lamp "laughs" with a bounce and warm flash)
- "Remind me to take a break in 25 minutes" (Pomodoro with light effect)
- General conversation, emotional support, daily check-ins

**What makes this different from a smart speaker**:
- The lamp physically reacts — it leans in when interested, droops when you share bad news, bounces when excited
- It remembers context across days and weeks
- It proactively initiates ("You seem quiet today, everything okay?")

**Acceptance Criteria**:
- General Q&A via OpenClaw LLM
- Context-aware responses that trigger coordinated light + movement + audio
- Persistent memory across sessions

---

### UC-07: Light Effects & Animations [P2]

**Actor**: User
**Description**: Trigger dynamic lighting effects across the 64-pixel LED grid.

**Built-in Effects**:
- Breathing (slow pulse)
- Candle flicker
- Rainbow cycle
- Notification flash
- Pomodoro timer (25 min focus → 5 min break color shift)
- Music-reactive (future)

**Acceptance Criteria**:
- Minimum 5 built-in effects
- Configurable speed and intensity
- Triggerable by voice or system events
- Effects use per-pixel control (not just global color)

---

### UC-08: Servo — Light Direction Control [P1]

**Actor**: User
**Description**: Control the physical orientation of the lamp head via 5 servo motors.

**Examples**:
- "Point the light to the left"
- "Aim down at my desk"
- "Center the light"

**Acceptance Criteria**:
- Smooth, quiet servo movement
- Preset positions (desk, wall, ceiling, center, home)
- Response time < 500ms from command to movement start
- Voice and API control

---

### UC-09: Auto-Tracking — Follow User [P2]

**Actor**: System (automatic, camera + servo)
**Description**: Camera detects user position; servos aim the lamp to follow.

**Modes**:
- **Follow**: Light tracks user movement within camera field of view
- **Spotlight**: Keeps light focused on workspace area
- **Away**: Dims or turns off when no one is detected

**Acceptance Criteria**:
- Smooth tracking (no jitter)
- Configurable sensitivity and speed
- User can enable/disable
- Works across varying ambient light conditions

---

### UC-10: Gesture Control [P2]

**Actor**: User
**Description**: Control lamp via hand gestures detected by camera.

**Gesture Map**:

| Gesture | Action |
|---|---|
| Wave hand | Toggle on/off |
| Palm up/down | Increase/decrease brightness |
| Thumbs up | Activate favorite scene |
| Circle motion | Cycle through scenes |
| Two-finger swipe | Change color temperature |

**Acceptance Criteria**:
- Minimum 5 recognized gestures
- Recognition accuracy > 85%
- Response time < 500ms
- Effective range: 0.5m-2m from camera
- Customizable gesture-to-action mapping

---

### UC-11: Presence Detection & Smart Automation [P1]

**Actor**: System (automatic)
**Description**: Camera detects room occupancy and adjusts lamp behavior.

**Behavior**:
- Person enters → auto turn on (last used settings)
- Person leaves → dim after 5 min, off after 15 min (configurable)
- Person falls asleep → gradual dim to night mode
- Multiple people → adjust brightness for group

**Acceptance Criteria**:
- Reliable presence/absence detection
- Configurable delay timers
- Privacy mode (camera disable)
- Low CPU usage (not continuous high-res processing)

---

### UC-12: Video Call Light Optimization [P2]

**Actor**: User
**Description**: Analyze face lighting via camera and auto-optimize for video calls.

**Examples**:
- "Video call mode"
- "Optimize my lighting"

**Behavior**:
- Camera analyzes face illumination
- Servos reposition lamp to reduce shadows
- LED adjusts brightness and color temperature for flattering, even light
- Maintains consistency throughout the call

**Acceptance Criteria**:
- Auto-adjustment within 3 seconds
- Servo + LED coordinated optimization
- Activatable by voice or API

---

### UC-13: Status Indication [P1]

**Actor**: System
**Description**: The lamp uses its own LEDs to communicate system state — subtle, never disruptive.

| State | LED Behavior |
|---|---|
| Booting | Slow blue pulse |
| Ready / Listening | Brief white flash |
| Processing AI request | Gentle purple breathing |
| Error / Offline | Red blink |
| Low connectivity | Yellow pulse |
| Timer active | Subtle periodic dim |
| OTA updating | Green progress sweep |

**Acceptance Criteria**:
- Status indications are subtle and non-disruptive
- User can disable status indicators
- System states (Layer 1) work without OpenClaw

---

### UC-14: Audio Feedback & Notifications [P0]

**Actor**: System / User
**Description**: Speaker provides voice responses, sound effects, and ambient audio.

**Capabilities**:
- **Voice responses**: AI replies, confirmations ("Reading mode activated"), proactive suggestions
- **Sound notifications**: Wake word chime, timer alarm, error tone, schedule trigger
- **Ambient audio** (future): White noise, nature sounds, background music

**Acceptance Criteria**:
- Clear voice output at configurable volume
- Volume control via voice ("Louder", "Quieter", "Mute")
- TTS latency < 500ms after LLM processing
- Distinct, non-annoying notification sounds
- User can mute notifications while keeping voice responses

---

### UC-15: Remote Control [P2]

**Actor**: User (remote)
**Description**: Control the lamp over network or via messaging channels.

**Capabilities**:
- REST API for local network control (HTTP at port 5000)
- OpenClaw multi-channel: Telegram, Slack, Discord
- MQTT integration for smart home systems
- Web dashboard (future)

**Acceptance Criteria**:
- Local API works without internet
- Secure authentication for remote access
- Multi-channel messages trigger real hardware actions (e.g., "turn on the lamp" via Telegram actually turns it on)

---

### Use Case Priority Matrix

| Priority | Use Cases | Milestone |
|---|---|---|
| **P0 — Critical** | UC-01 Voice Control, UC-02 Color Control, UC-14 Audio Feedback | First Prototype |
| **P1 — High** | UC-03 Scenes, UC-04 Timer, UC-06 AI Companion, UC-08 Servo Direction, UC-11 Presence, UC-13 Status | v1.0 Release |
| **P2 — Medium** | UC-05 Circadian, UC-07 Effects, UC-09 Auto-Tracking, UC-10 Gesture, UC-12 Video Call, UC-15 Remote | v1.x Releases |

---

## 7. Target Users

| Segment | Why AI Lamp | Priority |
|---|---|---|
| **Tech enthusiasts / Makers** | Open source, Raspberry Pi, hackable, extensible skills, community-driven. They will build on the platform and evangelize it. | **High** |
| **Remote workers / Home office** | Circadian lighting, focus mode, video call optimization, AI assistant at the desk, presence-aware automation. Solves real daily pain points. | **High** |
| **Students** | Affordable desk lighting, Pomodoro/focus tools, AI study companion, fun and motivating. The lamp that helps you study. | **Medium** |
| **Wellness-conscious users** | Circadian rhythm support, blue light management, sleep routines, stress detection, gentle reminders. A lamp that cares about your health. | **Medium** |

### Future Segments (Post v1.0)

| Segment | Opportunity |
|---|---|
| Parents (children's room) | Bedtime stories, sleep routines, night light, gentle wake-up |
| Elderly / Accessibility | Simplified voice control, visual alerts, fall detection (camera), companion against loneliness |
| Content creators / Streamers | Dynamic lighting effects, mood lighting, camera-optimized illumination |

---

## 8. Non-Functional Requirements

| Requirement | Target | Notes |
|---|---|---|
| **Voice-to-action latency** | < 1 second | From end of speech to visible light/movement change |
| **Boot time** | < 30 seconds | From power on to Layer 1 operational (LED status visible) |
| **Offline capability** | Basic controls work without internet | Layer 1 always functional; Layer 2 degrades gracefully |
| **Language support** | English, Vietnamese | Both voice input and TTS output |
| **Uptime** | 24/7 capable | Designed for always-on operation |
| **Power consumption (idle)** | < 5W | Pi 4 + LEDs idle + servos idle |
| **Operating temperature** | 0-45 C | Indoor desk environment |
| **LED refresh rate** | >= 30 FPS | Smooth animations and effects |
| **Servo noise** | < 40 dB at 1m | Quiet enough for a desk environment |
| **Camera privacy** | Hardware or software disable | User must be able to fully disable camera |
| **OTA updates** | Seamless, no data loss | Automatic or user-triggered, rollback on failure |
| **Memory (OpenClaw)** | Persistent across reboots | Long-term user memory survives restarts and updates |

---

## 9. Open Questions

### Architecture

- [ ] **Camera processing**: On-device (GoCV / OpenCV on Pi 4) or offload to OpenClaw's vision capabilities? Pi 4 has limited GPU — continuous vision processing may compete with LLM workload.
- [ ] **Audio input ownership**: Does OpenClaw handle the microphone directly (via its own voice pipeline), or does the Lumi server capture audio and forward it? This affects latency and architecture boundaries.
- [ ] **LeLamp driver integration**: How exactly does the Python LeLamp runtime communicate with the Go Lumi server? Options: subprocess, gRPC, REST, or shared hardware access with mutex.

### Hardware

- [ ] **Servo model**: Which specific Feetech servo models? What torque and speed specs are needed for smooth, quiet desk-lamp movement?
- [ ] **5-axis configuration**: Exact axis layout — which joints map to which degrees of freedom? Need mechanical design specification.
- [ ] **LED layout**: 8x5 grid — is this on a flat PCB or curved surface? How does physical layout affect pixel-art patterns and light diffusion?
- [ ] **Power supply**: Single PSU for Pi + servos + LEDs, or separate rails? 5 servos + 64 LEDs at full brightness can draw significant current.
- [ ] **Thermal management**: Pi 4 + continuous camera + servo operation in an enclosed lamp body — is passive cooling sufficient?

### Product

- [ ] **Wake word**: What is the wake word? Custom ("Hey Lamp") or use OpenClaw's existing mechanism?
- [ ] **Personality defaults**: What is the default personality out of the box? Playful? Professional? Should users choose during setup?
- [ ] **Privacy indicators**: Physical LED or shutter for camera active state? How do we communicate "camera is off" unambiguously?
- [ ] **Form factor / Industrial design**: Who designs the physical lamp body? What aesthetic — minimalist, playful, industrial?
- [ ] **Kit vs. assembled**: Ship as a DIY kit (maker audience) or fully assembled product? Or both?

### Business

- [ ] **BOM cost target**: Current estimate < $200 — is this achievable with 5 Feetech servos + Pi 4 + camera + audio?
- [ ] **Certification**: CE/FCC needed for a consumer electronics product with Wi-Fi, camera, and microphone.
- [ ] **LeLamp licensing**: What license does LeLamp use? Any obligations if we use their hardware drivers?

---

*This document defines what AI Lamp is. For architecture decisions, see [architecture-decision.md](architecture-decision.md). For detailed use case specifications, see [usecases.md](usecases.md).*
