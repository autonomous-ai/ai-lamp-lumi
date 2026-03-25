# Open Decisions — AI Lamp (Lumi)

> Decisions that must be made before implementation can proceed. Each blocks specific features.
> Once resolved, move to "Resolved" section with the decision and date.

## Unresolved

### 1. SKILL.md Content for New Skills

**Question**: What goes inside the 5 new SKILL.md files (servo-control, camera, audio, display, emotion)?

**Context**: OpenClaw's LLM reads SKILL.md to understand available APIs. The `led-control/SKILL.md` already exists (inherited from lobster). The 5 new skills need to describe the HTTP API endpoints defined in `architecture-decision.md` Section 5.

**Blocks**: OpenClaw cannot control any new hardware without these files.

**Suggested approach**: Draft based on API endpoints already defined. Can be iterated after testing with OpenClaw.

---

### 2. OpenClaw Event Push — How Does Lumi Notify OpenClaw?

**Question**: When Lumi's sensing loop detects an event (person arrives, light changes, stress detected), how does it push that context to OpenClaw for AI decision-making?

**Options**:
- A. WebSocket message to OpenClaw
- B. HTTP callback to an OpenClaw API endpoint
- C. Write to a shared file/pipe that OpenClaw watches
- D. OpenClaw polls Lumi's `/api/events` endpoint

**Context**: OpenClaw has a WebSocket connection with Lumi (inherited from lobster's `internal/openclaw/`). May be able to send messages through that channel.

**Blocks**: All autonomous/proactive behavior (Pillar 4). Without this, Lumi can only respond to commands, never act on its own.

---

### 3. Camera Processing — On-Device or OpenClaw?

**Question**: Does camera vision processing (face detection, presence, gesture, light analysis) run on the Pi 4 locally, or does OpenClaw handle it via its vision capabilities?

**Options**:
- A. On-device with OpenCV/GoCV — fast, no network, but Pi 4 GPU is limited
- B. OpenClaw vision — smarter, but adds latency and depends on LLM
- C. Hybrid — simple CV on-device (presence, light level), complex tasks (gesture, face emotion) via OpenClaw

**Blocks**: Camera skill, sensing loop, auto-tracking, video call optimization.

---

### 4. Audio Input Ownership

**Question**: Who owns the microphone — OpenClaw or Lumi?

**Options**:
- A. OpenClaw owns mic directly (via its own voice pipeline for STT → LLM → TTS)
- B. Lumi captures audio, forwards stream to OpenClaw
- C. Shared — OpenClaw owns voice pipeline, Lumi taps mic for ambient sensing (sound level, silence detection) independently

**Context**: OpenClaw likely has its own voice input mechanism. Lumi's sensing loop also needs mic access for ambient sound analysis.

**Blocks**: Voice pipeline architecture, sensing loop audio events.

---

### 5. LED Driver Ownership — Go or Python?

**Question**: For user-facing LED control (scenes, effects, colors), which driver is used?

**Options**:
- A. Go SPI driver (from lobster `internal/led/`) — Lumi owns LED directly, no bridge needed
- B. Python rpi_ws281x (from LeLamp) — bridge via HTTP to LeLamp
- C. Both — Go for system states (boot, error), Python for user-facing (scenes, effects, patterns)

**Context**: Lobster already has a working pure Go WS2812 SPI driver with state machine and effects. LeLamp has Python rpi_ws281x with 64-LED grid support. Using both may cause SPI bus conflicts.

**Blocks**: LED skill implementation, whether LED goes through bridge or not.

---

### 6. Emotion Presets — Specific Parameters

**Question**: What are the actual hardware parameters for each emotion?

**Example**: "curious" at intensity 0.8 =
- Servo: which axes, what angles, what speed?
- LED: which color, which pattern, what brightness?
- Audio: which sound file, what volume?
- Display: which eye animation?
- Randomization: what range of variation per parameter?

**Context**: Need LeLamp driver code first to understand actual servo ranges, LED capabilities. Can be defined iteratively.

**Blocks**: Emotion skill implementation. Can be deferred — start with 3-4 basic emotions, expand later.

---

### 7. Display Rendering — GC9A01 Driver & Eye Animation

**Question**: What Python library drives the GC9A01 display? How are pixel-art eyes rendered?

**Options for driver**: `luma.lcd`, `ST7789` compatible libs, `Pillow` direct SPI
**Options for rendering**: Pre-rendered sprite sheets, Pillow draw calls, pygame

**Context**: GC9A01 is 240x240 round LCD, SPI interface. Need smooth eye animations (blink, look direction, emotions). Display is NOT from LeLamp upstream — entirely new.

**Blocks**: Display skill, eye animations in emotion skill. Can be deferred — start without display, add later (plugin architecture supports this).

---

## Resolved (2026-03-24)

| Decision | Resolution | Docs |
|---|---|---|
| Go-to-Python bridge protocol | HTTP proxy. LeLamp FastAPI on `127.0.0.1:5001`, Lumi proxies from port 5000. | `architecture-decision.md` §11, `bootstrap-ota.md` §6 |
| LeLamp source strategy | Mono-repo. Copy drivers from `humancomputerlab/lelamp_runtime` into `lelamp/`. Track upstream via `UPSTREAM.md`. | `bootstrap-ota.md` §6 |
| Project/character name | **Lumi** (from "luminous"). Binary: `lumi-server`. Service: `lumi.service`. Wake word: "Hey Lumi". | All docs updated |
| Display concept | Dual-mode: pixel-art eyes emotion (default) + info display (time, weather, timer, notifications). | `architecture-decision.md` §3, `product-vision.md` §4 |
| Autonomous sensing architecture | Hybrid. Lumi runs lightweight edge detection (camera, mic, time, sensors). Pushes events to OpenClaw for AI decisions. Rule-based actions don't need AI. | `product-vision.md` §2 Pillar 4, `architecture-decision.md` §4 |
| OTA components | 5 components: lumi, bootstrap, web, openclaw, lelamp. LeLamp = setup stage 2b. | `bootstrap-ota.md` §1-§3 |
| Product pillars | 4 Pillars: "It understands me", "It feels alive", "It's actually useful", "It acts on its own". | `product-vision.md` §2 |

## Resolved (2026-03-25)

| Decision | Resolution | Docs |
|---|---|---|
| GWS removal | Removed all GWS (Google Workspace) handlers, scripts, and domain types. MQTT commands reduced to: `info`, `add_channel`, `ota`. | `architecture-decision.md` §4 |
| LLM service inlining | Removed `internal/llm/` service. `ListModelsFromAPI` inlined into `internal/openclaw/service.go`. | `architecture-decision.md` §4 |
| Onboarding removal | Removed `onboarding.go` from openclaw. Setup flow simplified. | `architecture-decision.md` §4 |
| Scripts cleanup | Removed `release-*.sh`, `setup-gws-cli.sh`, `upload-gws-cli.sh`, `install-sendip.sh`, `sendip.sh`. Added `upload-lelamp.sh`. | `bootstrap-ota.md` §7 |
| Code directory rename | All code moved under `lumi/` subdirectory. "intern" references replaced with "lumi". | All docs |

---

*When a decision is made, move it from Unresolved to Resolved with the date and update the relevant docs.*
