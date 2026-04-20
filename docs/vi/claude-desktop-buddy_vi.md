# Claude Desktop Buddy — Spec Tích Hợp

> Biến Lumi thành Hardware Buddy cho Claude Desktop, chạy như plugin độc lập và tích hợp với hệ thống LED/voice/sensing hiện tại.

**Source**: [anthropics/claude-desktop-buddy](https://github.com/anthropics/claude-desktop-buddy)
**Status**: Spec draft
**Date**: 2026-04-20

---

## 1. Tổng quan & Lý do

Claude Desktop (Cowork) có một BLE API cho phép thiết bị phần cứng kết nối làm "buddy". Reference implementation là ESP32 desk pet — LCD nhỏ, 1 nút bấm, không có brain.

Lumi implement cùng protocol này nhưng là **smart buddy** — có camera, mic, speaker, LED ring, servo, display, và OpenClaw brain riêng. Lumi không chỉ hiện prompt và approve, mà còn suy nghĩ, nói chuyện tự nhiên, và feed context ngược lại.

### Các use case

| # | Use case | Mô tả |
|---|----------|-------|
| UC-1 | **Ambient state** | LED ring phản ánh trạng thái Claude Desktop: idle (breathing), busy (pulse), waiting (blink) |
| UC-2 | **Voice approval** | Claude Desktop cần approve tool call → Lumi đọc prompt → user nói "approve" / "deny" hands-free |
| UC-3 | **Token dashboard** | Lumi display hiện token count, session count qua `/display/info` |
| UC-4 | **Presence feedback** | Lumi biết user có mặt hay vắng (camera/motion) → gửi info ngược về Desktop (mở rộng protocol) |
| UC-5 | **Transcript relay** | Lumi nhận transcript từ Desktop → khi user hỏi voice, OpenClaw có thêm context |

**MVP scope: UC-1 + UC-2 + UC-3.** UC-4, UC-5 mở rộng sau.

---

## 2. Kiến trúc

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

### Thiết kế plugin

`buddy-plugin` chạy như **process độc lập** trên Pi4 (port 5002):
- Binary riêng, lifecycle riêng — không link vào Lumi server
- **BLE server**: advertise tên `Claude-Lumi`, xử lý Nordic UART protocol
- **HTTP server**: expose `/status` endpoint để OpenClaw skill và Lumi query trạng thái buddy
- **Gọi LeLamp** (localhost:5001) cho LED/TTS/display — giống mọi service khác
- **Gọi Lumi** (localhost:5000) để post sensing events cho voice approval flow
- Không cần Wire DI, không cần Gin — binary nhẹ, độc lập

```
ai-lamp-openclaw/
├── lumi/                      # Lumi server (có sẵn, Go, port 5000)
├── lelamp/                    # LeLamp runtime (có sẵn, Python, port 5001)
├── claude-desktop-buddy/      # ← MỚI: Claude Desktop Buddy plugin (Go, port 5002)
│   ├── main.go                # Entry point
│   ├── ble.go                 # BLE GATT server (Nordic UART)
│   ├── protocol.go            # Wire protocol parse/serialize
│   ├── state.go               # State machine (sleep/idle/busy/attention/celebrate)
│   ├── bridge.go              # Map state → LeLamp + Lumi HTTP calls
│   ├── approval.go            # Voice approval flow
│   ├── httpserver.go          # GET /status, POST /approve, /deny
│   ├── go.mod                 # Go module riêng
│   └── config/
│       └── buddy.json         # Config plugin
```

### MỚI: OpenClaw Skill

File `SKILL.md` để OpenClaw agent biết về buddy và phối hợp:

```
lumi/resources/openclaw-skills/claude-desktop-buddy/SKILL.md   # skill nằm trong lumi (deploy qua OTA)
```

---

## 3. Quy trình Pairing

```
┌─────────────┐                              ┌──────────────┐
│ Lumi (Pi4)  │                              │ Claude Desktop│
│             │   1. BLE advertise           │ (Mac)        │
│ buddy-plugin├─────────────────────────────►│              │
│ name:       │   "Claude-Lumi" +            │              │
│ Claude-Lumi │    Nordic UART UUID          │              │
│             │                              │              │
│             │   2. User bấm Connect       │  Developer → │
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
│             │   5. Heartbeats bắt đầu     │              │
│             │◄─────────────────────────────┤              │
│             │   mỗi 10s hoặc khi state đổi               │
└─────────────┘                              └──────────────┘
```

### Điều kiện tiên quyết (1 lần duy nhất)

1. Pi4 bật Bluetooth (`bluetoothctl power on`)
2. Claude Desktop: **Help → Troubleshooting → Enable Developer Mode**
3. Menu mới xuất hiện: **Developer → Open Hardware Buddy...**

### Các bước pairing

1. Lumi chạy buddy-plugin → advertise BLE với tên `Claude-Lumi`
2. Claude Desktop → Developer → Open Hardware Buddy → **Connect**
3. Scan list hiện "Claude-Lumi" → chọn
4. macOS hiện Bluetooth permission popup → Allow
5. OS-level bonding (LE Secure Connections) → link encrypted bằng AES-CCM
6. Claude Desktop gửi init: time sync + owner name
7. Heartbeat bắt đầu chảy → Lumi nhận state

### Tự động kết nối lại

Sau khi pair lần đầu, cả 2 bên lưu bond key (LTK). Khi Lumi reboot hoặc Mac wake up → tự reconnect mà không cần pair lại.

### Hủy pairing

Claude Desktop gửi `{"cmd":"unpair"}` → Lumi xóa stored bond → quay lại advertise chờ pair mới.

---

## 4. BLE Protocol (theo REFERENCE.md)

### Transport

| Thuộc tính | Giá trị |
|------------|---------|
| Service UUID | `6e400001-b5a3-f393-e0a9-e50e24dcca9e` |
| RX (Desktop → Device) | `6e400002-b5a3-f393-e0a9-e50e24dcca9e` |
| TX (Device → Desktop) | `6e400003-b5a3-f393-e0a9-e50e24dcca9e` |
| Wire format | UTF-8 JSON, mỗi object 1 dòng, kết thúc bằng `\n` |
| Tên thiết bị | Phải bắt đầu bằng `Claude` (ví dụ: `Claude-Lumi`) |

### Message: Desktop → Device

**Heartbeat snapshot** (mỗi 10s hoặc khi state đổi):
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

| Field | Type | Mô tả |
|-------|------|-------|
| `total` | number | Tổng số session |
| `running` | number | Session đang generate |
| `waiting` | number | Session đang chờ permission |
| `msg` | string | Tóm tắt cho màn hình nhỏ |
| `entries` | string[] | Transcript gần nhất, mới nhất trước |
| `tokens` | number | Tổng output tokens từ lúc app khởi động |
| `tokens_today` | number | Output tokens từ nửa đêm |
| `prompt` | object hoặc null | Chỉ có khi cần permission |
| `prompt.id` | string | Phải echo lại trong response |
| `prompt.tool` | string | Tên tool (vd: "Edit", "Bash") |
| `prompt.hint` | string | Context ngắn về tool call |

**Init messages** (khi kết nối):
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

### Message: Device → Desktop

**Permission decision**:
```json
{"cmd": "permission", "id": "req_abc123", "decision": "once"}
```
```json
{"cmd": "permission", "id": "req_abc123", "decision": "deny"}
```

| Decision | Hiệu lực |
|----------|----------|
| `"once"` | Approve tool call |
| `"deny"` | Reject tool call |

**Ack** (bắt buộc cho mọi `cmd` nhận được):
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

**Turn event** (device → desktop, sau mỗi completed turn, drop nếu >4KB):
```json
{
  "evt": "turn",
  "role": "assistant",
  "content": [{ "type": "text", "text": "..." }]
}
```

### Timeouts

- Heartbeat keepalive: 10s
- Coi kết nối chết: 30s không nhận heartbeat
- Desktop poll status: ~2s

---

## 5. State Machine

```
                    ┌─────────────┐
         BLE tắt    │    sleep    │   BLE ngắt kết nối
         ──────────►│  LED: tắt   │◄──────────────
                    └──────┬──────┘
                           │ BLE kết nối
                           ▼
                    ┌─────────────┐
      running == 0  │    idle     │   không có session
      ─────────────►│  LED: để   │◄──────────────
                    │  ambient   │
                    └──────┬──────┘
                           │ running > 0
                           ▼
                    ┌─────────────┐
      waiting == 0  │    busy     │   session đang chạy
      ─────────────►│  LED: pulse │
                    └──────┬──────┘
                           │ prompt != null (waiting > 0)
                           ▼
                    ┌─────────────┐
                    │  attention  │   cần approval
                    │  LED: nhấp  │
                    │  nháy+voice │
                    └──────┬──────┘
                           │ user approve/deny
                           ▼
                    ┌─────────────┐
                    │   heart     │   approve nhanh (<5s)
                    │  LED: ấm   │   (3s rồi → busy/idle)
                    └─────────────┘

        Token milestone (mỗi 50K):
                    ┌─────────────┐
                    │  celebrate  │   rainbow burst
                    │  LED: party │   (3s rồi → state trước)
                    └─────────────┘
```

### Suy ra state từ heartbeat

```
if BLE disconnected           → sleep
if prompt != null             → attention
if running > 0                → busy
else                          → idle

// Transient states (overlay, tự hết):
if approved trong <5s         → heart (3s, rồi suy ra lại)
if tokens vượt mốc 50K       → celebrate (3s, rồi suy ra lại)
```

---

## 6. Tích hợp LED Priority

Hệ thống hiện tại có 4 cấp LED:

```
Level 0: Status LED     (error, OTA, booting, connectivity, processing, listening)
Level 1: Agent LED      (emotion qua [HW:/emotion:...])
Level 1.5: Buddy state  ← MỚI (phản ánh trạng thái Desktop)
Level 2: Local Intent   (voice commands: "bật đèn xanh")
Level 3: Ambient        (idle breathing, thấp nhất)
```

### Quy tắc phối hợp

| Tình huống | Ai thắng | Hành vi |
|------------|---------|---------|
| Agent đang express emotion + buddy active | Agent | Buddy tạm dừng LED trong thời gian emotion, tiếp tục sau |
| Buddy attention (approval) + ambient breathing | Buddy | Ambient nhận `led_set` từ buddy → dừng breathing |
| User nói "bật đèn xanh" + buddy active | User | Local intent override, buddy tạm dừng LED |
| Buddy idle/sleep + không có gì khác | Ambient | Buddy không set LED khi idle/sleep → ambient chạy bình thường |
| Status LED error + buddy active | Status LED | Status luôn thắng (level 0) |

### Triển khai: tích hợp monitor bus

Buddy-plugin post event lên Lumi monitor bus qua `POST /api/monitor/event`:

```json
{
  "type": "buddy_state",
  "summary": "buddy: attention (approval pending)",
  "detail": { "state": "attention", "tool": "Edit", "hint": "server.go" }
}
```

Ambient service lắng nghe `buddy_state` events:
- `attention`, `busy` → coi như `led_set` (khóa ambient breathing)
- `idle`, `sleep` → coi như `led_off` (mở khóa ambient breathing)
- `heart`, `celebrate` → tạm thời, tự mở khóa sau 3s

---

## 7. State → LeLamp Mapping (MVP)

Buddy-plugin gọi LeLamp HTTP API trực tiếp cho LED/display. Dùng endpoints có sẵn:

| Buddy state | LeLamp endpoint | Parameters | Display |
|-------------|----------------|------------|---------|
| `sleep` | `/led/off` | — | eyes: `sleepy` |
| `idle` | (không gọi LED — để ambient xử lý) | — | eyes: `neutral` |
| `busy` | `/led/effect` | `{"effect":"pulse","color":[0,100,255],"speed":0.8}` | info: "{running} sessions, {tokens_today} tokens" |
| `attention` | `/led/effect` | `{"effect":"blink","color":[255,80,0],"speed":1.5}` | info: "Approve {tool}?" |
| `heart` | `/led/solid` | `{"color":[255,200,100]}` (3s, rồi resume) | eyes: `happy` |
| `celebrate` | `/led/effect` | `{"effect":"rainbow","speed":2.0,"duration_ms":3000}` | eyes: `excited` |

### Tích hợp display

Token dashboard dùng LeLamp `/display/info`:

```
POST http://127.0.0.1:5001/display/info
{
  "text": "8.2K tokens",
  "subtitle": "2 sessions running"
}
```

Khi buddy ở `idle` hoặc `sleep`, trả display về chế độ eyes:

```
POST http://127.0.0.1:5001/display/eyes-mode
```

---

## 8. Voice Approval Flow (UC-2)

Approval dùng **pipeline sensing event có sẵn** — buddy-plugin post sensing event lên Lumi, Lumi chuyển cho OpenClaw. OpenClaw đọc buddy SKILL.md và biết cách xử lý.

```
1. Heartbeat đến với prompt != null
2. buddy-plugin state → attention
3. buddy-plugin gọi:
   - LeLamp /led/effect (blink cam)
   - LeLamp /display/info ("Approve Edit?", "server.go lines 10-20")
   - Lumi POST /api/sensing/event:
     {
       "type": "buddy_approval",
       "message": "Claude Desktop needs approval: Edit on server.go lines 10-20"
     }

4. OpenClaw nhận sensing event → đọc buddy SKILL.md
5. OpenClaw trả lời qua TTS: "Này, Claude Desktop muốn edit server.go. Approve không?"
6. User nói: "yes" / "approve" / "no" / "deny"

7. OpenClaw match response → gọi buddy-plugin HTTP API:
   POST http://127.0.0.1:5002/approve  {"id": "req_abc123"}
   POST http://127.0.0.1:5002/deny     {"id": "req_abc123"}

8. buddy-plugin nhận → gửi BLE permission decision về Desktop
9. State → heart (nếu approve <5s) hoặc → busy/idle
```

### Tại sao route qua OpenClaw?

- OpenClaw xử lý TTS tự nhiên (strip markdown, nói đúng tính cách)
- OpenClaw phối hợp với voice pipeline hiện tại (busy state, queue)
- OpenClaw có thể quyết định: nếu user vắng mặt, không TTS — chỉ nhấp nháy LED im lặng
- OpenClaw ghi log event vào flow events để monitoring
- Không cần hệ thống voice/intent trùng lặp trong buddy-plugin

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
\`\`\`bash
curl -s -X POST http://127.0.0.1:5002/approve \
  -H "Content-Type: application/json" \
  -d '{"id": "<prompt_id from event>"}'
\`\`\`

**If user says deny/no/skip/cancel:**
\`\`\`bash
curl -s -X POST http://127.0.0.1:5002/deny \
  -H "Content-Type: application/json" \
  -d '{"id": "<prompt_id from event>"}'
\`\`\`

## Buddy state awareness

You can check what Claude Desktop is doing:
\`\`\`bash
curl -s http://127.0.0.1:5002/status
\`\`\`

Response:
\`\`\`json
{
  "state": "busy",
  "connected": true,
  "sessions_running": 2,
  "tokens_today": 8200,
  "pending_prompt": null
}
\`\`\`

## Rules

- When buddy state is `attention`: do NOT start ambient behaviors or proactive conversations — the user is being prompted for approval
- When buddy state is `busy`: the user is actively using Claude Desktop — reduce proactive interruptions (no wellbeing reminders, no music suggestions)
- When buddy state is `idle` or `sleep`: operate normally
- NEVER mention "buddy-plugin", "BLE", "Bluetooth", or technical internals to the user — just say "Claude Desktop" naturally
```

---

## 10. buddy-plugin HTTP API (port 5002)

HTTP server nhẹ để OpenClaw và Lumi query/control trạng thái buddy:

| Method | Path | Mô tả | Request | Response |
|--------|------|-------|---------|----------|
| GET | `/status` | Trạng thái buddy hiện tại | — | `{"state":"busy","connected":true,"sessions_running":2,"tokens_today":8200,"pending_prompt":null}` |
| POST | `/approve` | Approve prompt đang chờ | `{"id":"req_abc123"}` | `{"ok":true}` |
| POST | `/deny` | Deny prompt đang chờ | `{"id":"req_abc123"}` | `{"ok":true}` |
| GET | `/health` | Health check plugin | — | `{"status":"ok","ble_advertising":true}` |

### Chi tiết pending prompt trong `/status`

Khi có approval đang chờ:
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

## 11. Kế hoạch triển khai

### Phase 1: BLE + state sync + LED (UC-1)

- [ ] Go BLE GATT server (Nordic UART Service)
- [ ] Advertise tên `Claude-Lumi`
- [ ] Parse heartbeat JSON → suy ra state
- [ ] State machine: sleep/idle/busy/attention/heart/celebrate
- [ ] Map state → LeLamp LED (`/led/effect`, `/led/solid`, `/led/off`)
- [ ] Map state → LeLamp display (`/display/info`, `/display/eyes`, `/display/eyes-mode`)
- [ ] Post `buddy_state` events lên Lumi monitor bus
- [ ] HTTP server port 5002 với `/status` và `/health`

### Phase 2: Voice approval (UC-2)

- [ ] Khi vào state attention, post sensing event lên Lumi `/api/sensing/event`
- [ ] Thêm SKILL.md vào `resources/openclaw-skills/claude-desktop-buddy/`
- [ ] HTTP endpoints `/approve` và `/deny` trên port 5002
- [ ] Gửi BLE permission decision khi được gọi
- [ ] Theo dõi thống kê approval (đếm, lưu file)

### Phase 3: Token dashboard (UC-3)

- [ ] Cập nhật `/display/info` với token count mỗi heartbeat
- [ ] Hiện: sessions đang chạy, tokens hôm nay, state hiện tại
- [ ] Trả display về eyes-mode khi idle/sleep

### Phase 4: Tính năng mở rộng (UC-4, UC-5) — Tương lai

- [ ] Presence signal từ Lumi → Desktop (cần mở rộng protocol)
- [ ] Inject transcript context vào OpenClaw

---

## 12. Chọn BLE Library

| Library | Ưu điểm | Nhược điểm |
|---------|---------|------------|
| `tinygo.org/x/bluetooth` | Pure Go, cross-platform, hỗ trợ GATT server | Hỗ trợ Pi4 BlueZ cần test |
| `github.com/muka/go-bluetooth` | Mature, native DBus/BlueZ | Dependency nặng hơn |
| Python `bleak` + subprocess | BLE trên Pi đã được chứng minh | Không phải Go, thêm process |

Khuyến nghị: bắt đầu với `tinygo.org/x/bluetooth`. Nếu Pi4 có vấn đề thì fallback sang `go-bluetooth`.

---

## 13. Config

Plugin đọc file config riêng: `config/buddy.json`

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

Lưu ý: `idle` có `action: "none"` — buddy không set LED khi idle, để ambient service xử lý.

---

## 14. Triển khai

```bash
# Build
cd claude-desktop-buddy && GOOS=linux GOARCH=arm64 go build -o buddy-plugin .

# Chạy như systemd service
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

## 15. Rủi ro & Ràng buộc

| Rủi ro | Ảnh hưởng | Giảm thiểu |
|--------|-----------|------------|
| Pi4 BLE tầm phủ ~10m | Mac phải ở cùng phòng với lamp | OK cho setup bàn làm việc |
| BLE bandwidth thấp | Transcript dài bị cắt (>4KB bị drop) | Chỉ nhận summary, không full transcript |
| Claude Desktop BLE API chưa stable | Protocol có thể đổi | Theo REFERENCE.md, pin version |
| Xung đột LED với agent emotion | Buddy LED bị ghi đè khi emotion | Buddy tạm dừng LED khi emotion, tiếp tục sau (qua monitor bus) |
| Xung đột voice với cuộc hội thoại | Approval TTS cắt ngang TTS đang chạy | Route qua OpenClaw sensing → dùng logic busy/queue có sẵn |
| Ambient breathing vs buddy LED | Cả hai cùng điều khiển LED | Buddy post `led_set`/`led_off` events; idle = không gọi LED |

---

## 16. Tiêu chí thành công

- [ ] Claude Desktop thấy "Claude-Lumi" trong Hardware Buddy scan
- [ ] Pair thành công, tự reconnect sau reboot
- [ ] LED thay đổi theo Desktop state mà không xung đột với agent emotion hay ambient
- [ ] Voice approve/deny route qua OpenClaw và hoàn thành end-to-end
- [ ] Token count hiển thị trên LCD tròn qua `/display/info`
- [ ] Plugin crash không ảnh hưởng Lumi server chính
- [ ] OpenClaw giảm hành vi proactive khi Desktop đang busy
