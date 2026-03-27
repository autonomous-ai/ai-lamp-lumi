# Web UI — Lumi Monitor Dashboard

## Last updated: 2026-03-27

---

## 1. Overview

Lumi's Web UI is a React SPA (Single Page Application) built with **React 19 + TypeScript + Vite + Tailwind CSS 4**, serving two purposes:

1. **Setup flow** — WiFi, LLM provider, messaging channel onboarding (`/setup/*` pages)
2. **Monitor Dashboard** — Real-time device status monitoring (`/monitor`)

Build output (`dist/`) is served by nginx at root `/` on the device.

---

## 2. Directory Structure

```
lumi/web/
├── src/
│   ├── pages/
│   │   ├── Monitor.tsx        # Dashboard monitor (main file)
│   │   └── ...                # Setup pages
│   ├── components/
│   │   └── ui/                # shadcn/ui components
│   ├── index.css              # Global styles + theme variables
│   └── main.tsx
├── vite.config.ts
└── package.json
```

---

## 3. Monitor Dashboard (`/monitor`)

### 3.1 Overall Design

Monitor uses a dedicated dark theme with class `.lm-root` (defined in `index.css`), **not using Tailwind** — all styling uses inline styles with CSS variables `--lm-*`.

Layout: **Fixed 192px sidebar + flexible main area**, 100vh height.

### 3.2 Sidebar Navigation

4 sections toggled via local state (`section: Section`):

| Icon | Section | Content |
|------|---------|---------|
| ◈ | Overview | Full system overview |
| ⬡ | System | CPU/RAM/Temp details + history |
| ◎ | Workflow | OpenClaw event feed real-time |
| ⬟ | Camera | MJPEG stream + Display LCD |

Bottom of sidebar shows OpenClaw status (online/offline) and last update time.

### 3.3 Dark Theme Variables

Defined at `.lm-root` in `index.css`:

```css
--lm-bg:          #0C0B09   /* Main background */
--lm-sidebar:     #111009   /* Sidebar */
--lm-card:        #17160F   /* Card background */
--lm-surface:     #1E1D14   /* Surface inside card */
--lm-border:      #2A2820   /* Border */
--lm-border-hi:   #3A3828   /* Border highlight */
--lm-amber:       #F59E0B   /* Primary color (warm lamp) */
--lm-amber-dim:   rgba(245,158,11,0.12)
--lm-amber-glow:  rgba(245,158,11,0.35)
--lm-teal:        #2DD4BF
--lm-green:       #34D399
--lm-red:         #F87171
--lm-blue:        #60A5FA
--lm-purple:      #A78BFA
--lm-text:        #F0EEE8
--lm-text-dim:    #9A9080
--lm-text-muted:  #504A3C
```

---

## 4. Polling & Data Sources

Monitor polls system/HW APIs every **3 seconds**. Flow uses file-backed hybrid mode: REST seed + live stream.

### 4.1 Lumi Server (Go, port 5000, prefix `/api`)

| Endpoint | Data |
|----------|------|
| `GET /api/system/info` | CPU load, RAM (KB), temperature, uptime, goroutines, version, deviceId |
| `GET /api/system/network` | SSID, IP, signal (dBm), internet (bool) |
| `GET /api/openclaw/status` | name, connected (bool), sessionKey (bool) |
| `GET /api/openclaw/recent` | Latest flow events from today's JSONL file (`local/flow_events_<date>.jsonl`) |
| `GET /api/openclaw/flow-events?date=YYYY-MM-DD&last=500` | File-backed flow events API used for Flow seed/history |
| `GET /api/openclaw/flow-stream` | File-backed live stream (SSE) for Flow updates when JSONL changes |
| `GET /api/openclaw/debug-lines?last=300` | Parsed tail rows from `openclaw_debug_payloads.jsonl` for Logs tab |
| `GET /api/openclaw/events` | Monitor bus SSE endpoint (kept for compatibility) |

> **Note on format**: Lumi API returns `{ status: 1, data: <payload>, message: null }` on success.

### 4.2 LeLamp (Python/FastAPI, port 5001, prefix `/hw`)

| Endpoint | Data |
|----------|------|
| `GET /hw/health` | Status of 8 hardware: servo, led, camera, audio, sensing, voice, tts, display |
| `GET /hw/presence` | state, enabled, seconds_since_motion |
| `GET /hw/voice/status` | voice_available, voice_listening, tts_available, tts_speaking |
| `GET /hw/servo` | available_recordings, current |
| `GET /hw/display` | mode, hardware, available_expressions |
| `GET /hw/audio/volume` | control, volume (0-100) |
| `GET /hw/led/color` | led_count, color [R,G,B], hex (#rrggbb) |

---

## 5. Section Details

### 5.1 Overview Section

Cards included:

**OpenClaw AI**
- Connected/disconnected status
- Agent name
- Session key: Acquired / Pending

**Network**
- SSID + Signal bars (4 levels based on dBm)
- IP address
- Internet status

**Presence**
- State (active/idle)
- Sensing enabled/disabled
- Time since last motion detection

**Voice & TTS**
- Mic available + listening (LIVE badge)
- TTS available + speaking (SPEAKING badge)
- Current volume

**Hardware** (horizontal card)
- 8 badges: Servo / LED / Camera / Audio / Sensing / Voice / TTS / Display
- **LED color swatch**: rounded square showing current LED strip color with hex code. Fetched from `GET /hw/led/color`.

**Servo Pose**
- Currently running pose (current)
- List of available poses (up to 8)

**Display Eyes**
- Currently displayed expression (mode)
- List of available expressions

**System quick stats**
- CPU, RAM, Temp, Uptime as pills

### 5.2 System Section

**Performance** — 3 GaugeRing SVGs:
- CPU: amber color, shows `%`
- Memory: blue color, detail `used/total MB` (converted from KB: `value / 1024`)
- Temp: teal (< 70C) or red (>= 70C), scale 0-85C

**CPU History / RAM History** — Sparkline chart (area + line):
- Stores 60 history points (`HISTORY_LEN = 60`)
- Updates every 3 seconds

**Process**: goroutines, uptime, version, deviceId
**Network Detail**: SSID, IP, signal, internet

### 5.3 Workflow Section

File-backed hybrid feed:

| Type | Color | Meaning |
|------|-------|---------|
| `lifecycle` | amber | Agent starts / ends run |
| `tool_call` | teal | AI calls a tool |
| `thinking` | purple | AI is thinking (streaming) |
| `assistant_delta` | blue | AI is responding (streaming delta) |
| `chat_response` | green | Final chat response |

Each event displays: type badge, phase (if any), runId (first 8 chars), timestamp, summary text, error (if any).

- Initial/history load via `GET /api/openclaw/flow-events`.
- Live updates via `GET /api/openclaw/flow-stream` (SSE emitted on file change).
- Fallback polling (2s) is used only if live stream disconnects.
- Displayed turns/events are fully derived from JSONL flow logs.

Turn Pipeline grouping behavior:
- Turns are still started by input/trigger events (`sensing_input`, `chat_input`, `schedule_trigger`, etc.).
- The UI now anchors each turn to the first detected `run_id` (from event root or detail payload).
- If a later event has a different `run_id`, Monitor splits it into a new inferred agent turn.
- `OUT` text is only taken from `tts_send`/`intent_match` events matching the turn `run_id` (or events without run_id), preventing cross-turn input/output mismatch.
- For Telegram input, placeholder summaries like `[telegram]` no longer lock the `IN` field; when a later event with the same `run_id` contains real message text, the UI replaces the placeholder with that text.
- Temporary fallback: when Telegram text is unavailable, UI displays `Message content from telegram`.
- Turn badges always render the `IN` row; if input is missing, UI shows `Input not captured`.
- Flow Panel header actions now include `↓ Logs`, `↓ Debug`, `✕ Clear`, and `🗑 Log`.
- `↓ Debug` downloads raw OpenClaw debug payloads from `GET /api/openclaw/debug-logs` (file: `local/openclaw_debug_payloads.jsonl` on the server).
- `✕ Clear` asks for confirmation, then clears all currently displayed Flow events/turns in the UI (client-side only).
- `🗑 Log` asks for confirmation and calls `DELETE /api/openclaw/flow-logs` to truncate today's server flow log file, then clears current Flow UI events.
- Turn history list shows the latest 100 turns (newest first).
- Flow event memory is capped at 500 events.
- Telegram stitching heuristic: if a Telegram fallback input turn (without real input text) is immediately followed by an agent-output turn within 30s, Monitor stitches them into one turn so the reply stays with the original Telegram input.

### 5.4 Camera Section

- **Camera Stream**: MJPEG live stream from `GET /hw/camera/stream`
- **Display Eyes (GC9A01)**: Round 1.28" screen snapshot from `GET /hw/display/snapshot`, displayed as circle with amber glow. Has Refresh button.
- **Camera Snapshot**: Static image from `GET /hw/camera/snapshot`, with Capture button to take new shot.

### 5.5 Logs Section

- Dedicated runtime log panel for debugging Telegram/OpenClaw inputs.
- Polls `GET /api/openclaw/debug-lines` every 2 seconds and renders newest rows first.
- Shows `source`, `role`, `run_id`, `at`, and parsed `message` if available.
- Includes direct file download via `GET /api/openclaw/debug-logs`.

> **Note**: Camera serves a dual role — (1) live stream display for user viewing, (2) automatic sensing data source. Sensing service reads a frame from camera every 2s to detect motion, faces (Haar cascade), and light level. When significant events are detected (person appears, large motion), a 320px JPEG auto-snapshot is sent with the event to OpenClaw AI for vision analysis.

---

## 6. LED Color API

### Problem
Original `GET /hw/led` only returned `{ led_count: 64 }` — no current color info.

### Solution
Added `GET /hw/led/color` to `lelamp/server.py`:

```python
@app.get("/led/color", response_model=LEDColorResponse, tags=["LED"])
def get_led_color():
    """Get the current LED color (last color set on the strip)."""
```

**Color priority:**
1. `sensing_service.presence._last_color` — base color tracked when AI sets it
2. Fallback: `rgb_service.strip.getPixelColor(0)` — read directly from hardware

**Tracking added for:**
- `POST /led/solid` (existing)
- `POST /scene` (existing)
- `POST /emotion` (added — this is the path AI uses most)

> **Note**: `GET /hw/led/color` is **read-only**, monitor only reads, does not set color.

---

## 7. Reusable Components (internal to Monitor.tsx)

| Component | Description |
|-----------|-------------|
| `GaugeRing` | SVG ring chart with drop-shadow glow, 0.7s transition |
| `Sparkline` | SVG area + line chart, accepts number array |
| `HWBadge` | Green/red badge for hardware status |
| `StatusDot` | Green/red dot with glow |
| `SignalBars` | 4-bar WiFi signal (thresholds: -50/-65/-75/-85 dBm) |
| `StatPill` | Row label + value in card |

---

## 8. Build & Deploy

```bash
# Build production
make web-build        # tsc + vite build → lumi/web/dist/

# Deploy to Pi
make web-deploy       # web-build + rsync dist/ → /usr/share/nginx/html/setup/

# Deploy LeLamp (when server.py changes)
make lelamp-deploy    # rsync + pip install + systemctl restart lumi-lelamp.service
```

> Deploy uses `PI_HOST=lumi.local` (mDNS). If it doesn't resolve, use IP directly:
> `PI_USER=root PI_HOST=172.168.20.230 make web-deploy`
