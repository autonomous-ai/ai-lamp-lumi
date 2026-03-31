# Lumi Server API — Documentation

> Lumi Server (Go, Gin framework) runs on port 5000.

## Lumi Server Endpoints (Go, :5000)

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health/live` | Liveness probe |
| GET | `/api/health/readiness` | Readiness probe (OpenClaw connected?) |

### System

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/system/info` | CPU, RAM, temp, uptime, version |
| GET | `/api/system/network` | WiFi SSID, IP, signal, internet status |
| GET | `/api/system/dashboard` | Aggregated snapshot (OpenClaw + config + HW) |

### Device Setup

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/device/setup` | Configure WiFi + LLM + channel + MQTT (async, returns immediately) |
| POST | `/api/device/channel` | Change messaging channel |

### Network

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/network` | Scan WiFi networks |
| GET | `/api/network/current` | Current SSID + IP |
| GET | `/api/network/check-internet` | Check internet connectivity |

### Sensing

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/sensing/event` | Receive sensing event from LeLamp |

**Request body:**
```json
{
  "type": "voice_command|voice|motion|sound|presence.enter|presence.leave|light.level",
  "message": "...",
  "image": "<base64 JPEG, optional>"
}
```

**Event types:**

| Type | Source | Has image? | Description |
|------|--------|-----------|-------------|
| `voice_command` / `voice` | Mic (Deepgram STT) | No | Voice command |
| `motion` | Camera (frame diff) | Yes (large motion) | Motion detected |
| `presence.enter` | Camera (Haar cascade face detection) | Yes | New face detected |
| `presence.leave` | Camera (3 consecutive ticks without face) | No | Person left |
| `light.level` | Camera (mean brightness) | No | Significant ambient light change (>30/255) |
| `sound` | Mic (RMS energy) | No | Loud noise |

**Processing flow:**
1. `voice_command` or `voice` + local intent enabled → match intent → execute directly (~50ms)
2. No match → forward to OpenClaw via WebSocket `chat.send`
3. If event has `image` → call `SendChatMessageWithImage` → send image with text for AI vision analysis

### OpenClaw

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/openclaw/status` | WS connection status |
| GET | `/api/openclaw/events` | SSE stream real-time events |
| GET | `/api/openclaw/recent` | 100 most recent events (ring buffer) |

---

## LeLamp Endpoints (Python FastAPI, :5001)

Accessed via nginx proxy: `/hw/*` → `127.0.0.1:5001`

### Servo (5-axis Feetech)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/servo` | Recordings + animation state |
| POST | `/servo/play` | Play animation (idle, curious, nod, headshake, happy_wiggle, sad, excited, shock, shy, scanning, wake_up, music_groove). Idle auto-plays on boot. |
| POST | `/servo/move` | Send joint positions with smooth interpolation |
| POST | `/servo/release` | Disable torque on all servos |
| GET | `/servo/position` | Current servo positions |
| GET | `/servo/aim` | List aim directions |
| POST | `/servo/aim` | Aim lamp head (center, desk, wall, left, right, up, down, user) |

### LED (64 WS2812, 8x5 grid)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/led` | LED strip info |
| GET | `/led/color` | Current LED color |
| POST | `/led/solid` | Fill entire strip with one color |
| POST | `/led/paint` | Set individual pixels (array up to 64) |
| POST | `/led/off` | Turn off all LEDs |
| POST | `/led/effect` | Start effect (breathing, candle, rainbow, notification_flash, pulse) |
| POST | `/led/effect/stop` | Stop running effect |

### Camera

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/camera` | Availability + resolution |
| GET | `/camera/snapshot` | Capture 1 JPEG frame |
| GET | `/camera/stream` | MJPEG live stream |

### Audio

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/audio` | Audio device availability |
| POST | `/audio/volume` | Set volume (0-100%) |
| GET | `/audio/volume` | Get volume |
| POST | `/audio/play-tone` | Play test tone |
| POST | `/audio/record` | Record WAV |

### Emotion

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/emotion` | Combined expression: servo + LED + display eyes |

8 emotions: curious, happy, sad, thinking, idle, excited, shy, shock

### Scene

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/scene` | List scene presets |
| POST | `/scene` | Activate scene (reading, focus, relax, movie, night, energize) |

### Presence

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/presence` | Current state (present/idle/away) |
| POST | `/presence/enable` | Enable auto presence control |
| POST | `/presence/disable` | Disable auto presence (manual mode) |

### Display (GC9A01 1.28" round LCD)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/display` | Current state (mode, expression) |
| POST | `/display/eyes` | Set eye expression + pupil position |
| POST | `/display/info` | Switch to info mode (text/subtitle) |
| POST | `/display/eyes-mode` | Switch back to eyes mode (default) |
| GET | `/display/snapshot` | Current frame as JPEG |

11 expressions: neutral, happy, sad, curious, thinking, excited, shy, shock, sleepy, angry, love

### Voice

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/voice/start` | Start voice pipeline (Deepgram STT + TTS) |
| POST | `/voice/stop` | Stop voice pipeline |
| POST | `/voice/speak` | TTS — convert text to speech |
| GET | `/voice/status` | voice_available, voice_listening, tts_available, tts_speaking |

### System

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Hardware driver availability |

---

## Response Format

Lumi Server (Go):
```json
{"status": 1, "data": {...}, "message": null}   // success
{"status": 0, "data": null, "message": "error"}  // failure
```

LeLamp (Python): FastAPI standard JSON responses.

## Startup

1. Lumi Server starts Gin on :5000
2. Reads `config/config.json`
3. If `SetUpCompleted`:
   - Connect OpenClaw WebSocket
   - Connect MQTT
   - Start ambient behaviors
4. If not yet set up: wait for `POST /api/device/setup`

## Local Intent Matching

When receiving a `voice_command` or `voice` event, Lumi checks local intent first (~50ms):

| Command | Action |
|---------|--------|
| "turn on light" | `/led/solid` warm + happy emotion |
| "turn off light" | `/led/off` + idle emotion |
| "reading mode" | scene:reading |
| "focus mode" | scene:focus |
| "relax" | scene:relax |
| "movie mode" | scene:movie |
| "goodnight" | scene:night + sleepy emotion |
| "brighter" | scene:energize |
| "happy" | emotion:happy |
| "sad" | emotion:sad |
| "volume up" | volume 80 |
| "volume down" | volume 30 |
| "mute" | volume 0 |

No match → forward to OpenClaw.
