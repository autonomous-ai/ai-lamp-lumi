# Claude Desktop Buddy — Integration Spec

> Turn Lumi into a Hardware Buddy for Claude Desktop, running as a standalone plugin.

**Source**: [anthropics/claude-desktop-buddy](https://github.com/anthropics/claude-desktop-buddy)
**Status**: Spec draft
**Date**: 2026-04-20

---

## 1. What & Why

Claude Desktop (Cowork) exposes a BLE API that lets hardware devices connect as a "buddy". The reference implementation is an ESP32 desk pet — small LCD, one button, no brain.

Lumi implements the same protocol but as a **smart buddy** — with camera, mic, speaker, LED ring, servo, and its own OpenClaw brain. Lumi doesn't just display prompts and approve; it can **feed context back** to Claude Desktop.

### Use cases

| # | Use case | Description |
|---|----------|-------------|
| UC-1 | **Ambient state** | LED ring reflects Claude Desktop state: idle (breathing), busy (pulse), waiting (blink attention) |
| UC-2 | **Voice approval** | Claude Desktop needs tool call approval → Lumi LED blinks + reads prompt aloud → user says "approve" / "deny" hands-free |
| UC-3 | **Token dashboard** | Lumi display shows token count, session count in real-time |
| UC-4 | **Presence feedback** | Lumi detects user present/away (camera/motion) → sends info back to Desktop (protocol extension) |
| UC-5 | **Transcript relay** | Lumi receives Desktop transcript → when user asks via voice, Lumi has extra context about what Desktop is doing |

**MVP scope: UC-1 + UC-2 + UC-3 only.** UC-4 and UC-5 are future extensions.

---

## 2. Architecture

```
┌──────────────────┐        BLE (Nordic UART)        ┌──────────────────┐
│  Claude Desktop  │ ◄──────────────────────────────► │     Lumi (Pi4)   │
│  (Mac)           │                                  │                  │
│                  │  heartbeat: state, prompts,      │  buddy-plugin    │
│                  │  transcript, tokens              │  (Go, standalone)│
│                  │                                  │                  │
│                  │  permission decisions,            │    ┌──────────┐  │
│                  │  status acks                      │    │ LeLamp   │  │
│                  │                                  │    │ LED/voice │  │
│                  │                                  │    └──────────┘  │
└──────────────────┘                                  └──────────────────┘
```

### Plugin isolation

`buddy-plugin` runs as a **standalone process** on Pi4:
- Separate binary, separate lifecycle — not linked into Lumi server
- Communicates with LeLamp via HTTP (localhost:5001) — same as every other service
- Communicates with Lumi server via HTTP (localhost:5000) — only when needed (UC-5)
- No Wire DI, no Gin — just BLE stack + HTTP client

```
lumi/
├── cmd/lamp/           # Lumi server (existing)
├── cmd/bootstrap/      # OTA worker (existing)
├── cmd/buddy/          # ← NEW: Claude Desktop Buddy plugin
│   └── main.go
├── internal/buddy/     # ← NEW: plugin logic
│   ├── ble.go          # BLE GATT server (Nordic UART)
│   ├── protocol.go     # Wire protocol parse/serialize
│   ├── state.go        # State machine (sleep/idle/busy/attention/celebrate)
│   ├── bridge.go       # Map state → LeLamp HTTP calls
│   └── approval.go     # Voice approval flow
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

**Ack** (required for any received `cmd`):
```json
{"ack": "owner", "ok": true, "n": 0}
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

---

## 6. State → LeLamp Mapping (MVP)

| Buddy state | LED effect | Servo | Voice |
|-------------|-----------|-------|-------|
| `sleep` | off | neutral | — |
| `idle` | soft white breathing (`/led/effect breathing`) | neutral | — |
| `busy` | blue pulse (`/led/effect pulse`, color blue) | — | — |
| `attention` | red-orange blink (`/led/effect blink`, color red-orange) | tilt toward user | TTS: "Claude needs approval: {tool} on {hint}" |
| `heart` | warm yellow solid 3s | slight nod | — |
| `celebrate` | rainbow burst (`/led/effect rainbow`) 3s | happy bounce | chime sound |

### Approval voice flow (UC-2)

```
1. Heartbeat arrives with prompt != null
2. State → attention
3. LED blink + servo tilt
4. TTS: "Approve {tool}? {hint}"
5. Listen for voice (via LeLamp /voice or local intent):
   - "approve" / "yes" / "ok" → send permission decision "once"
   - "deny" / "no" / "skip"  → send permission decision "deny"
   - timeout 30s             → do nothing, Desktop will timeout
6. State → heart (if approved <5s) or → busy/idle
```

---

## 7. Implementation Plan

### Phase 1: BLE GATT server + state sync (UC-1)

- [ ] Go BLE GATT server using `tinygo.org/x/bluetooth` or `github.com/muka/go-bluetooth`
- [ ] Nordic UART Service with correct UUIDs
- [ ] Advertise as `Claude-Lumi`
- [ ] Parse heartbeat JSON → derive state
- [ ] State machine: sleep/idle/busy/attention
- [ ] Map state → LeLamp LED calls

### Phase 2: Voice approval (UC-2)

- [ ] On attention state, call LeLamp TTS with prompt info
- [ ] Listen for voice command via local intent or LeLamp voice
- [ ] Send permission decision back via BLE TX
- [ ] Track approval stats (approved/denied counts, persist to file)

### Phase 3: Token dashboard (UC-3)

- [ ] Forward token count to LeLamp display endpoint
- [ ] Show: sessions running, tokens today, current state

### Phase 4: Extended features (UC-4, UC-5) — Future

- [ ] Presence signal from Lumi → Desktop (requires protocol extension)
- [ ] Transcript context injection into OpenClaw (requires Lumi server API)

---

## 8. BLE Library Choice

| Library | Pros | Cons |
|---------|------|------|
| `tinygo.org/x/bluetooth` | Pure Go, cross-platform, GATT server support | Pi4 BlueZ support may need testing |
| `github.com/muka/go-bluetooth` | Mature, DBus/BlueZ native | Heavier dependency |
| Python `bleak` + subprocess | Battle-tested BLE on Pi | Not Go, extra process |

Recommendation: start with `tinygo.org/x/bluetooth` — if Pi4 support has issues, fall back to `go-bluetooth`.

---

## 9. Config

Plugin reads its own config file: `config/buddy.json`

```json
{
  "enabled": true,
  "device_name": "Claude-Lumi",
  "lelamp_url": "http://127.0.0.1:5001",
  "lumi_url": "http://127.0.0.1:5000",
  "approval_voice": true,
  "approval_timeout_sec": 30,
  "led_mapping": {
    "sleep": { "effect": "off" },
    "idle": { "effect": "breathing", "color": [255, 255, 255], "speed": 3 },
    "busy": { "effect": "pulse", "color": [0, 100, 255], "speed": 2 },
    "attention": { "effect": "blink", "color": [255, 80, 0], "speed": 1 },
    "heart": { "effect": "solid", "color": [255, 200, 100] },
    "celebrate": { "effect": "rainbow", "speed": 1 }
  }
}
```

---

## 10. Deployment

```bash
# Build
GOOS=linux GOARCH=arm64 go build -o buddy-plugin ./cmd/buddy/

# Run as systemd service
# File: /etc/systemd/system/lumi-buddy.service
[Unit]
Description=Lumi Claude Desktop Buddy
After=bluetooth.target
Wants=bluetooth.target

[Service]
ExecStart=/opt/lumi/buddy-plugin
WorkingDirectory=/opt/lumi
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## 11. Risks & Constraints

| Risk | Impact | Mitigation |
|------|--------|------------|
| Pi4 BLE range ~10m | Mac must be in same room as lamp | OK for desk setup |
| Low BLE bandwidth | Long transcripts truncated (>4KB dropped) | Only receive summary, not full transcript |
| Claude Desktop BLE API not yet stable | Protocol may change | Follow REFERENCE.md, version pin |
| Voice approval latency | STT delay + BLE round trip | Keep prompt short, timeout 30s |
| LED conflict with Lumi | Buddy and ambient both control LED | Buddy takes priority when active, releases on sleep/idle |

---

## 12. Success Criteria

- [ ] Claude Desktop sees "Claude-Lumi" in Hardware Buddy scan
- [ ] Pairing succeeds, auto-reconnects after reboot
- [ ] LED changes reflect Desktop state (idle/busy/attention)
- [ ] Voice approve/deny tool calls works end-to-end
- [ ] Token count displays on Lumi screen
- [ ] Plugin crash does not affect main Lumi server
