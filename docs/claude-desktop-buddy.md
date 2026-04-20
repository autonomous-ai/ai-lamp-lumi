# Claude Desktop Buddy — Integration Spec

> Turn Lumi into a Hardware Buddy for Claude Desktop, running as a standalone plugin that integrates with the existing LED/voice/sensing coordination system.

**Source**: [anthropics/claude-desktop-buddy](https://github.com/anthropics/claude-desktop-buddy)
**Status**: Spec draft
**Date**: 2026-04-20

---

## 1. What & Why

Claude Desktop (Cowork) exposes a BLE API that lets hardware devices connect as a "buddy". The reference implementation is an ESP32 desk pet — small LCD, one button, no brain.

Lumi implements the same protocol but as a **smart buddy** — with camera, mic, speaker, LED ring, servo, display, and its own OpenClaw brain. Lumi doesn't just display prompts and approve; it can reason about what to do, speak naturally, and feed presence context back.

### Use cases

| # | Use case | Description |
|---|----------|-------------|
| UC-1 | **Ambient state** | LED ring reflects Claude Desktop state: idle (breathing), busy (pulse), waiting (blink) |
| UC-2 | **Voice approval** | Claude Desktop needs tool call approval → Lumi speaks the prompt → user says "approve" / "deny" hands-free |
| UC-3 | **Token dashboard** | Lumi display shows token count, session count via `/display/info` |
| UC-4 | **Presence feedback** | Lumi detects user present/away (camera/motion) → sends info back to Desktop (protocol extension) |
| UC-5 | **Transcript relay** | Lumi receives Desktop transcript → when user asks via voice, OpenClaw has extra context |

**MVP scope: UC-1 + UC-2 + UC-3 only.** UC-4 and UC-5 are future extensions.

---

## 2. Architecture

```
┌──────────────────┐        BLE (Nordic UART)        ┌──────────────────────────────┐
│  Claude Desktop  │ ◄──────────────────────────────► │          Lumi (Pi4)          │
│  (Mac)           │                                  │                              │
│                  │  heartbeat: state, prompts,      │  ┌────────────────────────┐  │
│                  │  transcript, tokens              │  │    buddy-plugin        │  │
│                  │                                  │  │    (Go, port 5002)     │  │
│                  │  permission decisions,            │  │    BLE + HTTP server   │  │
│                  │  status acks                      │  └──────┬───────┬────────┘  │
│                  │                                  │         │       │            │
│                  │                                  │    HTTP │       │ HTTP       │
│                  │                                  │         ▼       ▼            │
│                  │                                  │  ┌──────────┐ ┌──────────┐  │
│                  │                                  │  │  Lumi    │ │ LeLamp   │  │
│                  │                                  │  │  :5000   │ │ :5001    │  │
│                  │                                  │  │ sensing  │ │ LED/TTS/ │  │
│                  │                                  │  │ event API│ │ display  │  │
│                  │                                  │  └──────────┘ └──────────┘  │
└──────────────────┘                                  └──────────────────────────────┘
```

### Plugin design

`buddy-plugin` runs as a **standalone process** on Pi4 (port 5002):
- Separate binary, separate lifecycle — not linked into Lumi server
- **BLE server**: advertises as `Claude-Lumi`, handles Nordic UART protocol
- **HTTP server**: exposes `/status` endpoint so OpenClaw skill and Lumi can query buddy state
- **Calls LeLamp** (localhost:5001) for LED/TTS/display — same as every other service
- **Calls Lumi** (localhost:5000) to post sensing events for voice approval flow
- No Wire DI, no Gin — lightweight standalone binary

```
ai-lamp-openclaw/
├── lumi/               # Lumi server (existing, Go, port 5000)
├── lelamp/             # LeLamp runtime (existing, Python, port 5001)
├── claude-desktop-buddy/  # ← NEW: Claude Desktop Buddy plugin (Go, port 5002)
│   ├── main.go         # Entry point
│   ├── ble.go          # BLE GATT server (Nordic UART)
│   ├── protocol.go     # Wire protocol parse/serialize
│   ├── state.go        # State machine (sleep/idle/busy/attention/celebrate)
│   ├── bridge.go       # Map state → LeLamp + Lumi HTTP calls
│   ├── approval.go     # Voice approval flow
│   ├── httpserver.go   # GET /status, POST /approve, /deny
│   ├── go.mod          # Separate Go module
│   └── config/
│       └── buddy.json  # Plugin config
```

### NEW: OpenClaw Skill

A `SKILL.md` file so the OpenClaw agent knows about buddy and coordinates:

```
lumi/resources/openclaw-skills/claude-desktop-buddy/SKILL.md   # skill lives in lumi (deployed via OTA)
```

---

## 3. Pairing Flow

```
┌─────────────┐                              ┌──────────────┐
│ Lumi (Pi4)  │                              │ Claude Desktop│
│             │   1. BLE advertise           │ (Mac)        │
│ buddy-plugin├─────────────────────────────►│              │
│ name:       │   "Claude-Lumi" +            │              │
│ Claude-Lumi │    Nordic UART UUID          │              │
│             │                              │              │
│             │   2. User clicks Connect     │  Developer → │
│             │◄─────────────────────────────┤  Hardware    │
│             │   BLE connection request     │  Buddy...    │
│             │                              │              │
│             │   3. OS bonding              │              │
│             │◄────────────────────────────►│  macOS BT    │
│             │   LE Secure Connections      │  permission  │
│             │   AES-CCM encryption         │  popup       │
│             │                              │              │
│             │   4. Init messages           │              │
│             │◄─────────────────────────────┤              │
│             │   time sync + owner name     │              │
│             │                              │              │
│             │   5. Heartbeats begin        │              │
│             │◄─────────────────────────────┤              │
│             │   every 10s or on state change              │
└─────────────┘                              └──────────────┘
```

### Prerequisites (one-time)

1. Pi4 Bluetooth enabled (`bluetoothctl power on`)
2. Claude Desktop: **Help → Troubleshooting → Enable Developer Mode**
3. New menu appears: **Developer → Open Hardware Buddy...**

### Pairing steps

1. Lumi runs buddy-plugin → advertises BLE with name `Claude-Lumi`
2. Claude Desktop → Developer → Open Hardware Buddy → **Connect**
3. Scan list shows "Claude-Lumi" → select it
4. macOS shows Bluetooth permission popup → Allow
5. OS-level bonding (LE Secure Connections) → link encrypted with AES-CCM
6. Claude Desktop sends init: time sync + owner name
7. Heartbeats begin flowing → Lumi receives state

### Auto-reconnect

After initial pairing, both sides store the bond key (LTK). When Lumi reboots or Mac wakes up → auto-reconnects without re-pairing.

### Unpair

Claude Desktop sends `{"cmd":"unpair"}` → Lumi erases stored bond → returns to advertising for new pairing.

---

## 4. BLE Protocol (from REFERENCE.md)

### Transport

| Property | Value |
|----------|-------|
| Service UUID | `6e400001-b5a3-f393-e0a9-e50e24dcca9e` |
| RX (Desktop → Device) | `6e400002-b5a3-f393-e0a9-e50e24dcca9e` |
| TX (Device → Desktop) | `6e400003-b5a3-f393-e0a9-e50e24dcca9e` |
| Wire format | UTF-8 JSON, one object per line, `\n` terminated |
| Device name | Must start with `Claude` (e.g. `Claude-Lumi`) |

### Messages: Desktop → Device

**Heartbeat snapshot** (every 10s or on state change):
```json
{
  "total": 3,
  "running": 1,
  "waiting": 1,
  "msg": "Editing main.go",
  "entries": ["Latest message", "Previous message"],
  "tokens": 52340,
  "tokens_today": 8200,
  "prompt": {
    "id": "req_abc123",
    "tool": "Edit",
    "hint": "server/server.go lines 10-20"
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `total` | number | All session count |
| `running` | number | Actively generating sessions |
| `waiting` | number | Sessions awaiting permission |
| `msg` | string | Display summary for small screens |
| `entries` | string[] | Recent transcript, newest first |
| `tokens` | number | Cumulative output tokens since app start |
| `tokens_today` | number | Output tokens since local midnight |
| `prompt` | object or null | Present only when permission required |
| `prompt.id` | string | Must echo in response |
| `prompt.tool` | string | Tool name (e.g. "Edit", "Bash") |
| `prompt.hint` | string | Short context about the tool call |

**Init messages** (on connect):
```json
{ "time": [1713600000, 25200] }
```
```json
{ "cmd": "owner", "name": "Leo" }
```

**Commands**:
```json
{"cmd": "status"}
```
```json
{"cmd": "name", "name": "Lumi"}
```
```json
{"cmd": "unpair"}
```

### Messages: Device → Desktop

**Permission decision**:
```json
{"cmd": "permission", "id": "req_abc123", "decision": "once"}
```
```json
{"cmd": "permission", "id": "req_abc123", "decision": "deny"}
```

| Decision | Effect |
|----------|--------|
| `"once"` | Approves the tool call |
| `"deny"` | Rejects the tool call |

**Ack** (required for any received `cmd`):
```json
{"ack": "owner", "ok": true, "n": 0}
```
```json
{"ack": "status", "ok": true, "data": {...}}
```

**Status response**:
```json
{
  "ack": "status",
  "ok": true,
  "data": {
    "name": "Lumi",
    "sec": true,
    "bat": { "pct": 100, "mV": 5000, "mA": 0, "usb": true },
    "sys": { "up": 86400, "heap": 1048576 },
    "stats": { "appr": 42, "deny": 3, "vel": 2.5, "nap": 0, "lvl": 5 }
  }
}
```

**Turn event** (device → desktop, after completed turn, dropped if >4KB):
```json
{
  "evt": "turn",
  "role": "assistant",
  "content": [{ "type": "text", "text": "..." }]
}
```

### Timeouts

- Heartbeat keepalive: 10s
- Connection dead: 30s without heartbeat
- Desktop polls status: ~2s

---

## 5. State Machine

```
                    ┌─────────────┐
         BLE off    │    sleep    │   BLE disconnected
         ──────────►│  LED: off   │◄──────────────
                    └──────┬──────┘
                           │ BLE connected
                           ▼
                    ┌─────────────┐
      running == 0  │    idle     │   no sessions
      ─────────────►│  LED: soft  │◄──────────────
                    │  breathing  │
                    └──────┬──────┘
                           │ running > 0
                           ▼
                    ┌─────────────┐
      waiting == 0  │    busy     │   sessions active
      ─────────────►│  LED: pulse │
                    └──────┬──────┘
                           │ prompt != null (waiting > 0)
                           ▼
                    ┌─────────────┐
                    │  attention  │   approval needed
                    │  LED: blink │
                    │  + voice    │
                    └──────┬──────┘
                           │ user approves/denies
                           ▼
                    ┌─────────────┐
                    │   heart     │   approved quickly (<5s)
                    │  LED: warm  │   (3s then → busy/idle)
                    └─────────────┘

        Token milestone (every 50K):
                    ┌─────────────┐
                    │  celebrate  │   rainbow burst
                    │  LED: party │   (3s then → prev state)
                    └─────────────┘
```

### State derivation from heartbeat

```
if BLE disconnected           → sleep
if prompt != null             → attention
if running > 0                → busy
else                          → idle

// Transient states (overlay, auto-expire):
if approved in <5s            → heart (3s, then re-derive)
if tokens crossed 50K boundary → celebrate (3s, then re-derive)
```

---

## 6. LED Priority Integration

The existing system has a 4-level LED hierarchy:

```
Level 0: Status LED     (error, OTA, booting, connectivity, processing, listening)
Level 1: Agent LED      (emotion via [HW:/emotion:...])
Level 2: Local Intent   (voice commands: "turn on blue light")
Level 3: Ambient        (idle breathing, lowest priority)
```

**Buddy fits at Level 1.5** — below Agent emotion, above Local Intent idle:

```
Level 0: Status LED        ← unchanged (highest priority)
Level 1: Agent emotion     ← unchanged (OpenClaw responses)
Level 1.5: Buddy state     ← NEW (Desktop state reflection)
Level 2: Local Intent      ← unchanged (voice LED commands)
Level 3: Ambient           ← unchanged (idle breathing)
```

### Coordination rules

| Scenario | Winner | Behavior |
|----------|--------|----------|
| Agent expressing emotion + buddy active | Agent | Buddy pauses LED for emotion duration, resumes after |
| Buddy attention (approval) + ambient breathing | Buddy | Ambient sees `led_set` from buddy → stops breathing |
| User says "turn on blue light" + buddy active | User | Local intent overrides, buddy pauses LED |
| Buddy idle/sleep + nothing else | Ambient | Buddy does not set LED in idle/sleep → ambient resumes |
| Status LED error + buddy active | Status LED | Status always wins (level 0) |

### Implementation: monitor bus integration

Buddy-plugin posts events to Lumi monitor bus via `POST /api/monitor/event`:

```json
{
  "type": "buddy_state",
  "summary": "buddy: attention (approval pending)",
  "detail": { "state": "attention", "tool": "Edit", "hint": "server.go" }
}
```

Ambient service listens for `buddy_state` events:
- `attention`, `busy` → treat as `led_set` (lock ambient breathing)
- `idle`, `sleep` → treat as `led_off` (unlock ambient breathing)
- `heart`, `celebrate` → transient, auto-unlock after 3s

---

## 7. State → LeLamp Mapping (MVP)

Buddy-plugin calls LeLamp HTTP API directly for LED/display. Uses existing endpoints:

| Buddy state | LeLamp endpoint | Parameters | Display |
|-------------|----------------|------------|---------|
| `sleep` | `/led/off` | — | eyes: `sleepy` |
| `idle` | (no LED call — let ambient handle) | — | eyes: `neutral` |
| `busy` | `/led/effect` | `{"effect":"pulse","color":[0,100,255],"speed":0.8}` | info: "{running} sessions, {tokens_today} tokens" |
| `attention` | `/led/effect` | `{"effect":"blink","color":[255,80,0],"speed":1.5}` | info: "Approve {tool}?" |
| `heart` | `/led/solid` | `{"color":[255,200,100]}` (3s, then resume) | eyes: `happy` |
| `celebrate` | `/led/effect` | `{"effect":"rainbow","speed":2.0,"duration_ms":3000}` | eyes: `excited` |

### Display integration

Token dashboard uses LeLamp `/display/info`:

```
POST http://127.0.0.1:5001/display/info
{
  "text": "8.2K tokens",
  "subtitle": "2 sessions running"
}
```

When buddy is in `idle` or `sleep`, release display back to eyes mode:

```
POST http://127.0.0.1:5001/display/eyes-mode
```

---

## 8. Voice Approval Flow (UC-2)

Approval uses the **existing sensing event pipeline** — buddy-plugin posts a sensing event to Lumi, which routes to OpenClaw. OpenClaw reads the buddy SKILL.md and knows how to handle it.

```
1. Heartbeat arrives with prompt != null
2. buddy-plugin state → attention
3. buddy-plugin calls:
   - LeLamp /led/effect (blink orange)
   - LeLamp /display/info ("Approve Edit?", "server.go lines 10-20")
   - Lumi POST /api/sensing/event:
     {
       "type": "buddy_approval",
       "message": "Claude Desktop needs approval: Edit on server.go lines 10-20"
     }

4. OpenClaw receives sensing event → reads buddy SKILL.md
5. OpenClaw responds via TTS: "Hey, Claude Desktop wants to edit server.go. Approve?"
6. User speaks: "yes" / "approve" / "no" / "deny"

7. OpenClaw matches response → calls buddy-plugin HTTP API:
   POST http://127.0.0.1:5002/approve  {"id": "req_abc123"}
   POST http://127.0.0.1:5002/deny     {"id": "req_abc123"}

8. buddy-plugin receives → sends BLE permission decision to Desktop
9. State → heart (if approved <5s) or → busy/idle
```

### Why route through OpenClaw?

- OpenClaw handles TTS naturally (strip markdown, speak in character)
- OpenClaw coordinates with existing voice pipeline (busy state, queue)
- OpenClaw can decide: if user is away, don't TTS — just blink LED silently
- OpenClaw logs the event in flow events for monitoring
- No duplicate voice/intent system needed in buddy-plugin

---

## 9. OpenClaw SKILL.md

```markdown
---
name: claude-desktop-buddy
description: Coordinate with Claude Desktop Buddy plugin for approval prompts and state awareness
---

# Claude Desktop Buddy

Lumi is connected to Claude Desktop on the user's Mac via Bluetooth.
A buddy-plugin runs on this device and syncs Desktop state to Lumi's LED/display.

## When you receive a `[sensing:buddy_approval]` event

Claude Desktop is waiting for the user to approve or deny a tool call.

**Workflow:**
1. Express emotion: curious (intensity 0.8)
2. Read the approval details from the event message
3. Ask the user naturally: mention the tool name and what it affects
4. Wait for the user's verbal response

**If user says approve/yes/ok/go ahead:**
```bash
curl -s -X POST http://127.0.0.1:5002/approve \
  -H "Content-Type: application/json" \
  -d '{"id": "<prompt_id from event>"}'
```

**If user says deny/no/skip/cancel:**
```bash
curl -s -X POST http://127.0.0.1:5002/deny \
  -H "Content-Type: application/json" \
  -d '{"id": "<prompt_id from event>"}'
```

## Buddy state awareness

You can check what Claude Desktop is doing:
```bash
curl -s http://127.0.0.1:5002/status
```

Response:
```json
{
  "state": "busy",
  "connected": true,
  "sessions_running": 2,
  "tokens_today": 8200,
  "pending_prompt": null
}
```

## Rules

- When buddy state is `attention`: do NOT start ambient behaviors or proactive conversations — the user is being prompted for approval
- When buddy state is `busy`: the user is actively using Claude Desktop — reduce proactive interruptions (no wellbeing reminders, no music suggestions)
- When buddy state is `idle` or `sleep`: operate normally
- NEVER mention "buddy-plugin", "BLE", "Bluetooth", or technical internals to the user — just say "Claude Desktop" naturally
```

---

## 10. buddy-plugin HTTP API (port 5002)

Lightweight HTTP server for OpenClaw and Lumi to query/control buddy state:

| Method | Path | Description | Request | Response |
|--------|------|-------------|---------|----------|
| GET | `/status` | Current buddy state | — | `{"state":"busy","connected":true,"sessions_running":2,"tokens_today":8200,"pending_prompt":null}` |
| POST | `/approve` | Approve pending prompt | `{"id":"req_abc123"}` | `{"ok":true}` |
| POST | `/deny` | Deny pending prompt | `{"id":"req_abc123"}` | `{"ok":true}` |
| GET | `/health` | Plugin health check | — | `{"status":"ok","ble_advertising":true}` |

### Pending prompt detail in `/status`

When there is a pending approval:
```json
{
  "state": "attention",
  "connected": true,
  "sessions_running": 1,
  "tokens_today": 8200,
  "pending_prompt": {
    "id": "req_abc123",
    "tool": "Edit",
    "hint": "server/server.go lines 10-20",
    "received_at": "2026-04-20T10:30:00Z"
  }
}
```

---

## 11. Implementation Plan

### Phase 1: BLE + state sync + LED (UC-1)

- [ ] Go BLE GATT server (Nordic UART Service)
- [ ] Advertise as `Claude-Lumi`
- [ ] Parse heartbeat JSON → derive state
- [ ] State machine: sleep/idle/busy/attention/heart/celebrate
- [ ] Map state → LeLamp LED calls (`/led/effect`, `/led/solid`, `/led/off`)
- [ ] Map state → LeLamp display (`/display/info`, `/display/eyes`, `/display/eyes-mode`)
- [ ] Post `buddy_state` events to Lumi monitor bus
- [ ] HTTP server on port 5002 with `/status` and `/health`

### Phase 2: Voice approval (UC-2)

- [ ] On attention state, post sensing event to Lumi `/api/sensing/event`
- [ ] Add SKILL.md to `resources/openclaw-skills/claude-desktop-buddy/`
- [ ] HTTP endpoints `/approve` and `/deny` on port 5002
- [ ] Send BLE permission decision when called
- [ ] Track approval stats (count, persist to file)

### Phase 3: Token dashboard (UC-3)

- [ ] Update `/display/info` with token count on each heartbeat
- [ ] Show: sessions running, tokens today, current state
- [ ] Release display to eyes-mode when idle/sleep

### Phase 4: Extended features (UC-4, UC-5) — Future

- [ ] Presence signal from Lumi → Desktop (requires protocol extension)
- [ ] Transcript context injection into OpenClaw

---

## 12. BLE Library Choice

| Library | Pros | Cons |
|---------|------|------|
| `tinygo.org/x/bluetooth` | Pure Go, cross-platform, GATT server support | Pi4 BlueZ support needs testing |
| `github.com/muka/go-bluetooth` | Mature, DBus/BlueZ native | Heavier dependency |
| Python `bleak` + subprocess | Battle-tested BLE on Pi | Not Go, extra process |

Recommendation: start with `tinygo.org/x/bluetooth`. If Pi4 has issues, fall back to `go-bluetooth`.

---

## 13. Config

Plugin reads its own config file: `config/buddy.json`

```json
{
  "enabled": true,
  "device_name": "Claude-Lumi",
  "http_port": 5002,
  "lelamp_url": "http://127.0.0.1:5001",
  "lumi_url": "http://127.0.0.1:5000",
  "approval_timeout_sec": 30,
  "led_mapping": {
    "sleep": { "action": "off" },
    "idle": { "action": "none" },
    "busy": { "effect": "pulse", "color": [0, 100, 255], "speed": 0.8 },
    "attention": { "effect": "blink", "color": [255, 80, 0], "speed": 1.5 },
    "heart": { "action": "solid", "color": [255, 200, 100], "duration_ms": 3000 },
    "celebrate": { "effect": "rainbow", "speed": 2.0, "duration_ms": 3000 }
  }
}
```

Note: `idle` has `action: "none"` — buddy does not set LED in idle state, lets ambient service handle it.

---

## 14. Deployment

```bash
# Build (from repo root)
cd claude-desktop-buddy && GOOS=linux GOARCH=arm64 go build -o buddy-plugin .

# Run as systemd service
# File: /etc/systemd/system/lumi-buddy.service
[Unit]
Description=Lumi Claude Desktop Buddy
After=bluetooth.target lumi.service
Wants=bluetooth.target

[Service]
ExecStart=/opt/lumi/buddy-plugin
WorkingDirectory=/opt/lumi
Restart=always
RestartSec=5
Environment=BUDDY_CONFIG=/opt/lumi/config/buddy.json

[Install]
WantedBy=multi-user.target
```

---

## 15. Risks & Constraints

| Risk | Impact | Mitigation |
|------|--------|------------|
| Pi4 BLE range ~10m | Mac must be in same room as lamp | OK for desk setup |
| Low BLE bandwidth | Long transcripts truncated (>4KB dropped) | Only receive summary, not full transcript |
| Claude Desktop BLE API not yet stable | Protocol may change | Follow REFERENCE.md, version pin |
| LED conflict with agent emotion | Buddy LED overwritten during emotion | Buddy pauses LED during emotion, resumes after (via monitor bus) |
| Voice conflict with active conversation | Approval TTS interrupts ongoing TTS | Route through OpenClaw sensing → respects busy/queue logic |
| Ambient breathing vs buddy LED | Both try to control LED | Buddy posts `led_set`/`led_off` events; idle state = no LED call |

---

## 16. Success Criteria

- [ ] Claude Desktop sees "Claude-Lumi" in Hardware Buddy scan
- [ ] Pairing succeeds, auto-reconnects after reboot
- [ ] LED changes reflect Desktop state without conflicting with agent emotion or ambient
- [ ] Voice approve/deny routes through OpenClaw and completes end-to-end
- [ ] Token count displays on Lumi round LCD via `/display/info`
- [ ] Plugin crash does not affect main Lumi server
- [ ] OpenClaw reduces proactive behavior when Desktop is busy
