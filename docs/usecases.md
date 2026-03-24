# AI Lamp OpenClaw — Use Cases

## 1. Market Context

### What makes an AI Lamp different from a Smart Lamp?

| | Smart Lamp | AI Lamp |
|---|---|---|
| Control | Responds to explicit commands ("turn on", "set 50%") | Understands intent and context ("I'm going to read") |
| Learning | Manual schedules, fixed routines | Learns user habits, adapts over time |
| Interaction | App buttons, simple voice keywords | Natural conversation, proactive suggestions |
| Intelligence | Reactive only | Proactive + reactive |
| Role | A light you control remotely | An ambient AI companion that also controls light |

### Competitive Landscape

| Product | Type | Key Differentiator |
|---|---|---|
| Philips Hue | Smart lighting ecosystem | Largest ecosystem, Zigbee, rich app |
| LIFX | Wi-Fi smart bulb | No hub, vivid colors |
| Nanoleaf | Decorative panels | Sense+ adaptive, music sync |
| Govee | Budget smart LED | AI text-to-scene generation |
| Dyson Lightcycle | Premium desk lamp | Circadian tracking, age-adaptive |
| Xiaomi Mi Lamp | Smart desk lamp | Pomodoro mode, affordable |
| **AI Lamp (this project)** | **AI-native lamp** | **LLM-powered, conversational, on-device AI via OpenClaw** |

### Our Differentiator

- **On-device LLM** via OpenClaw on Raspberry Pi 4 — privacy-first, low latency
- **Conversational control** — not just keywords, full natural language
- **Open source** — customizable, extensible, community-driven
- **AI companion** — the lamp is the physical embodiment of an AI assistant
- **Motorized direction** — servo motor enables physical light aiming, auto-tracking
- **Computer vision** — camera enables gesture control, presence detection, face tracking

---

## 2. Hardware Specification

| Component | Role | Capabilities |
|---|---|---|
| **Raspberry Pi 4** | Main compute board | Runs OpenClaw, lamp server, AI processing |
| **Microphone** | Voice input | Wake word detection, voice commands, conversation |
| **Speaker** | Audio output | AI voice responses, notifications, alerts |
| **Camera** | Vision input | Gesture recognition, presence detection, face tracking, video call |
| **Servo Motor** | Mechanical movement | Pan/tilt lamp head, aim light direction, follow user |
| **LED (TBD)** | Light output | Brightness, color, color temperature control |

---

## 3. Target Users

| Segment | Primary Need | Priority |
|---|---|---|
| Tech enthusiasts / makers | Customization, open-source, tinkering | High |
| Remote workers / home office | Eye comfort, focus, productivity | High |
| Students | Desk lighting, focus tools, affordable | Medium |
| Wellness-conscious users | Circadian health, sleep quality | Medium |
| Parents (children's room) | Sleep routines, bedtime stories | Low (future) |
| Elderly / accessibility | Simplicity, safety, visual alerts | Low (future) |

---

## 3. Use Cases

### UC-01: Voice-Controlled Lighting (Core)

**Actor**: User
**Description**: Control lamp using natural language via OpenClaw
**Examples**:
- "Turn on the light"
- "Dim to 30%"
- "Make it brighter"
- "Turn off"

**Acceptance Criteria**:
- Respond to on/off, brightness (0-100%) commands
- Response time < 1 second from voice input to light change
- Support both English and Vietnamese commands

---

### UC-02: Color & Color Temperature Control

**Actor**: User
**Description**: Change light color (RGB) or color temperature (warm/cool white)
**Examples**:
- "Warm white please"
- "Change to blue"
- "Set color temperature to 4000K"
- "Sunset orange"

**Acceptance Criteria**:
- Support RGB color spectrum (if hardware supports)
- Support color temperature range (2700K - 6500K)
- Accept color names, hex codes, and descriptive terms

---

### UC-03: Scene / Mood Presets

**Actor**: User
**Description**: Activate predefined or AI-generated lighting scenes
**Examples**:
- "Reading mode"
- "Movie mode"
- "Focus mode"
- "Relax mode"
- "Make it feel like a rainy afternoon" (AI-generated)

**Predefined Scenes**:

| Scene | Brightness | Color Temp | Color |
|---|---|---|---|
| Reading | 80% | 4000K (neutral) | White |
| Focus | 100% | 5000K (cool) | White |
| Relax | 40% | 2700K (warm) | Warm white |
| Movie | 15% | 2700K (warm) | Amber |
| Night | 5% | 2200K (very warm) | Dim warm |
| Energize | 100% | 6500K (daylight) | White |

**Acceptance Criteria**:
- At least 6 predefined scenes
- AI can generate custom scenes from natural language descriptions
- Smooth transition between scenes (fade, not instant switch)

---

### UC-04: Timer & Schedule

**Actor**: User
**Description**: Set timers or schedules for lighting changes
**Examples**:
- "Turn off in 30 minutes"
- "Wake me up at 6:30 AM with sunrise light"
- "Dim gradually over 20 minutes"
- "Turn on every day at 7 PM"

**Acceptance Criteria**:
- One-time timers (turn off after X minutes)
- Recurring schedules (daily, weekdays, weekends)
- Sunrise simulation (gradual warm brightening over 15-30 min)
- Sunset simulation (gradual dimming for sleep)

---

### UC-05: Adaptive / Circadian Lighting

**Actor**: System (automatic)
**Description**: Automatically adjust color temperature based on time of day to support natural circadian rhythm
**Behavior**:
- Morning (6-9 AM): Gradually increase to cool white (5000-6500K) — energize
- Daytime (9 AM-5 PM): Neutral to cool white (4000-5000K) — focus
- Evening (5-9 PM): Transition to warm white (3000-3500K) — wind down
- Night (9 PM+): Dim warm (2200-2700K) — prepare for sleep

**Acceptance Criteria**:
- Configurable schedule based on user's timezone
- Can be overridden manually (manual override lasts until next period)
- User can enable/disable this feature

---

### UC-06: AI Conversational Companion

**Actor**: User
**Description**: Beyond lamp control, OpenClaw serves as a conversational AI assistant
**Examples**:
- "What's the weather today?" (and adjust light accordingly)
- "Tell me a joke"
- "What time is it?"
- "Remind me to take a break in 25 minutes" (Pomodoro + light effect)

**Acceptance Criteria**:
- General Q&A via OpenClaw's LLM capabilities
- Context-aware responses that may trigger light changes
- Conversation memory within a session

---

### UC-07: Light Effects & Animations

**Actor**: User
**Description**: Trigger dynamic lighting effects
**Examples**:
- "Breathing effect" (slow pulse)
- "Candle flicker"
- "Rainbow cycle"
- "Notification flash" (quick blink for alerts)
- "Pomodoro timer" (25 min focus light, 5 min break color change)

**Acceptance Criteria**:
- At least 5 built-in effects
- Configurable speed and intensity
- Can be triggered by voice or system events

---

### UC-08: Servo — Light Direction Control

**Actor**: User
**Description**: Control the physical direction of the lamp using servo motor (pan/tilt)
**Examples**:
- "Point the light to the left"
- "Aim down at my desk"
- "Center the light"
- "Tilt up 30 degrees"

**Behavior**:
- Pan (horizontal): 0° - 180° range
- Tilt (vertical): 0° - 90° range
- Smooth movement with configurable speed
- Return to home position on command

**Acceptance Criteria**:
- Voice commands to control direction
- Smooth, quiet servo movement (no jerky motion)
- Preset positions (desk, wall, ceiling, center)
- Response time < 500ms from command to movement start

---

### UC-09: Servo — Auto-Tracking (Follow User)

**Actor**: System (automatic, using Camera)
**Description**: Camera detects user's face/body position, servo motor automatically aims the lamp to follow the user
**Modes**:
- **Follow mode**: Light follows user as they move within camera view
- **Away mode**: Light dims or turns off when no one is detected
- **Spotlight mode**: Keep light focused on the user's workspace

**Acceptance Criteria**:
- Face/body detection via camera with reasonable accuracy
- Smooth tracking (no jittery movement)
- Configurable tracking speed and sensitivity
- User can enable/disable tracking
- Must work in various lighting conditions

---

### UC-10: Camera — Gesture Control

**Actor**: User
**Description**: Control lamp functions using hand gestures detected by the camera
**Gestures**:
- Wave hand: Toggle on/off
- Palm up/down: Increase/decrease brightness
- Thumbs up: Activate favorite scene
- Circle motion: Cycle through scenes
- Two fingers swipe: Change color temperature

**Acceptance Criteria**:
- At least 5 recognized gestures
- Recognition accuracy > 85%
- Response time < 500ms from gesture to action
- Works within 0.5m - 2m range from camera
- User can customize gesture-to-action mapping

---

### UC-11: Camera — Presence Detection & Smart Automation

**Actor**: System (automatic)
**Description**: Camera detects whether someone is in the room and adjusts lamp behavior accordingly
**Behavior**:
- Person enters room → auto turn on (with last used settings)
- Person leaves room → dim after 5 min, turn off after 15 min (configurable)
- Person falls asleep (no movement for extended time) → gradually dim to night mode
- Multiple people detected → adjust brightness for group setting

**Acceptance Criteria**:
- Detect presence/absence reliably
- Configurable delay timers for on/off
- Privacy mode: user can disable camera detection
- Low CPU usage (not continuous high-res processing)

---

### UC-12: Camera — Video Call Light

**Actor**: User
**Description**: Optimize lighting for video calls using camera feedback
**Examples**:
- "Video call mode"
- "Optimize my lighting for camera"

**Behavior**:
- Analyze user's face lighting via camera
- Auto-adjust brightness and color temperature for flattering, even illumination
- Servo aims light to reduce shadows on face
- Maintain consistent lighting throughout the call

**Acceptance Criteria**:
- Detect face and analyze lighting quality
- Auto-adjust within 3 seconds
- Servo positions light for optimal face illumination
- Can be activated by voice or manually

---

### UC-13: Status Indication

**Actor**: System
**Description**: Use the lamp light itself to communicate system status
**Indicators**:
- Booting: Slow blue pulse
- Ready / Listening: Brief white flash
- Processing AI request: Gentle breathing effect
- Error / Offline: Red blink
- Low connectivity: Yellow pulse
- Timer active: Subtle periodic dim

**Acceptance Criteria**:
- Status indications should be subtle, not disruptive
- User can disable status indicators
- Must not interfere with normal lighting

---

### UC-14: Speaker — Audio Feedback & Notifications

**Actor**: System / User
**Description**: Speaker provides voice responses, sound effects, and audio notifications
**Capabilities**:

**Voice Responses (via OpenClaw TTS)**:
- AI voice replies to user questions and commands
- Confirmation audio: "Light set to 50%", "Reading mode activated"
- Proactive suggestions: "It's getting late, want me to switch to night mode?"

**Sound Notifications**:
- Wake word acknowledged: short chime
- Timer completed: gentle alarm sound
- System error: warning tone
- Schedule triggered: notification sound

**Ambient Audio (Future)**:
- White noise / nature sounds for focus or sleep
- Background music playback
- Sound-reactive lighting (music sync with LED effects)

**Examples**:
- "Play rain sounds"
- "Set a 25-minute focus timer with bell"
- "Read me the news" (AI reads aloud + adjusts light for listening)

**Acceptance Criteria**:
- Clear, audible voice output at configurable volume
- Volume control via voice: "Louder", "Quieter", "Mute"
- Low-latency TTS response (< 500ms after AI processing)
- Distinct notification sounds (not annoying)
- User can disable audio notifications while keeping voice responses

---

### UC-15: Network / Remote Control (Future)

**Actor**: User (remote)
**Description**: Control the lamp over local network or internet
**Capabilities**:
- REST API for local network control
- Web dashboard on the Pi
- Mobile app (future consideration)
- MQTT integration for smart home systems

**Acceptance Criteria**:
- Local API works without internet
- Secure authentication for remote access
- API documentation for third-party integration

---

## 4. Use Case Priority Matrix

| Use Case | Priority | MVP? | Hardware Dependency |
|---|---|---|---|
| UC-01: Voice Control | P0 - Critical | Yes | Microphone, Speaker, LED |
| UC-02: Color Control | P0 - Critical | Yes | RGB LED / LED strip |
| UC-03: Scene Presets | P1 - High | Yes | LED |
| UC-04: Timer & Schedule | P1 - High | Yes | None (software) |
| UC-05: Circadian Lighting | P2 - Medium | No | LED with color temp |
| UC-06: AI Companion | P1 - High | Partial | Microphone, Speaker |
| UC-07: Light Effects | P2 - Medium | No | RGB LED |
| UC-08: Servo Direction | P1 - High | Yes | Servo Motor |
| UC-09: Auto-Tracking | P2 - Medium | No | Servo Motor, Camera |
| UC-10: Gesture Control | P2 - Medium | No | Camera |
| UC-11: Presence Detection | P1 - High | Yes | Camera |
| UC-12: Video Call Light | P2 - Medium | No | Camera, Servo Motor |
| UC-13: Status Indication | P1 - High | Yes | LED |
| UC-14: Remote Control | P2 - Medium | No | Wi-Fi/Network |

---

## 5. System Architecture (High-Level)

```
                    ┌──────────────────────────────────────────┐
                    │           INPUT DEVICES                   │
                    │  ┌─────────┐  ┌────────┐  ┌───────────┐ │
                    │  │   Mic   │  │ Camera │  │  Network  │ │
                    │  └────┬────┘  └───┬────┘  └─────┬─────┘ │
                    └───────┼──────────┼────────────┼─────────┘
                            │          │            │
                            ▼          ▼            ▼
                    ┌──────────────────────────────────────────┐
                    │              OpenClaw (AI/LLM)            │
                    │  ┌────────────┐  ┌─────────────────────┐ │
                    │  │ Voice/NLU  │  │  Vision Processing  │ │
                    │  └────────────┘  └─────────────────────┘ │
                    └──────────────────┬───────────────────────┘
                                       │ WebSocket
                                       ▼
                    ┌──────────────────────────────────────────┐
                    │           Lamp Server (Go)                │
                    │                                          │
                    │  ┌───────────┐ ┌──────────┐ ┌─────────┐ │
                    │  │ LED Ctrl  │ │  Servo   │ │Scheduler│ │
                    │  │(GPIO/PWM) │ │  Ctrl    │ │  /Timer │ │
                    │  └─────┬─────┘ └────┬─────┘ └─────────┘ │
                    │  ┌─────┴─────┐ ┌────┴─────┐ ┌─────────┐ │
                    │  │  Effects  │ │ Tracking │ │ Presence│ │
                    │  │  Engine   │ │  Engine  │ │ Detect  │ │
                    │  └───────────┘ └──────────┘ └─────────┘ │
                    └──────┬──────────────┬───────────────────┘
                           │              │
                    ┌──────▼──────┐ ┌─────▼──────┐
                    │  LED / Light │ │Servo Motor │
                    │  (Hardware)  │ │ (Pan/Tilt) │
                    └─────────────┘ └────────────┘
```

**Output Devices**: Speaker (voice feedback), LED (light), Servo Motor (movement)

**Communication Flow**:
1. User speaks, gestures, or sends network command
2. OpenClaw processes input (voice NLU, vision, or API)
3. OpenClaw sends structured command via WebSocket to Lamp Server
4. Lamp Server executes command (LED, servo, schedule, effect)
5. Lamp Server responds with status back to OpenClaw
6. OpenClaw provides voice feedback via Speaker

---

## 6. Non-Functional Requirements

| Requirement | Target |
|---|---|
| Response latency (voice to light) | < 1 second |
| Boot time | < 30 seconds |
| Power consumption (idle) | < 5W (Pi 5 + LED idle) |
| Offline capability | Basic controls work without internet |
| Language support | English, Vietnamese |
| Operating temperature | 0-45°C |
| Uptime | 24/7 capable |
