# Claude Desktop Buddy — Spec Tích Hợp

> Biến Lumi thành Hardware Buddy cho Claude Desktop, chạy như một plugin độc lập.

**Source**: [anthropics/claude-desktop-buddy](https://github.com/anthropics/claude-desktop-buddy)
**Status**: Spec draft
**Date**: 2026-04-20

---

## 1. Tổng quan & Lý do

Claude Desktop (Cowork) có một BLE API cho phép thiết bị phần cứng kết nối làm "buddy". Reference implementation là ESP32 desk pet — LCD nhỏ, 1 nút bấm, không có brain.

Lumi implement cùng protocol này nhưng là **smart buddy** — có camera, mic, speaker, LED ring, servo, và OpenClaw brain riêng. Lumi không chỉ hiện prompt và approve, mà còn **feed context ngược lại** cho Claude Desktop.

### Các use case

| # | Use case | Mô tả |
|---|----------|-------|
| UC-1 | **Ambient state** | LED ring phản ánh trạng thái Claude Desktop: idle (breathing), busy (pulse), waiting (blink attention) |
| UC-2 | **Voice approval** | Claude Desktop cần approve tool call → Lumi LED nhấp nháy + đọc prompt → user nói "approve" / "deny" từ xa |
| UC-3 | **Token dashboard** | Lumi display hiện token count, session count real-time |
| UC-4 | **Presence feedback** | Lumi biết user có mặt hay vắng (camera/motion) → gửi info ngược về Desktop (mở rộng protocol) |
| UC-5 | **Transcript relay** | Lumi nhận transcript từ Desktop → khi user hỏi voice, Lumi có thêm context Desktop đang làm gì |

**MVP scope: UC-1 + UC-2 + UC-3.** UC-4, UC-5 mở rộng sau.

---

## 2. Kiến trúc

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

### Tách biệt plugin

`buddy-plugin` chạy như **process độc lập** trên Pi4:
- Binary riêng, lifecycle riêng — không link vào Lumi server
- Giao tiếp với LeLamp qua HTTP (localhost:5001) — giống mọi service khác
- Giao tiếp với Lumi server qua HTTP (localhost:5000) — chỉ khi cần (UC-5)
- Không cần Wire DI, không cần Gin — chỉ cần BLE stack + HTTP client

```
lumi/
├── cmd/lamp/           # Lumi server (có sẵn)
├── cmd/bootstrap/      # OTA worker (có sẵn)
├── cmd/buddy/          # ← MỚI: Claude Desktop Buddy plugin
│   └── main.go
├── internal/buddy/     # ← MỚI: logic plugin
│   ├── ble.go          # BLE GATT server (Nordic UART)
│   ├── protocol.go     # Wire protocol parse/serialize
│   ├── state.go        # State machine (sleep/idle/busy/attention/celebrate)
│   ├── bridge.go       # Map state → LeLamp HTTP calls
│   └── approval.go     # Voice approval flow
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

### Điều kiện tiên quyết (chỉ cần làm 1 lần)

1. Pi4 bật Bluetooth (`bluetoothctl power on`)
2. Claude Desktop: **Help → Troubleshooting → Enable Developer Mode**
3. Menu mới xuất hiện: **Developer → Open Hardware Buddy...**

### Các bước pairing

1. Lumi chạy buddy-plugin → advertise BLE với tên `Claude-Lumi`
2. Claude Desktop → Developer → Open Hardware Buddy → **Connect**
3. Scan list hiện "Claude-Lumi" → chọn
4. macOS hiện Bluetooth permission popup → Allow
5. OS-level bonding (LE Secure Connections) → link được encrypt bằng AES-CCM
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

**Ack** (bắt buộc cho mọi `cmd` nhận được):
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
      ─────────────►│  LED: thở  │◄──────────────
                    │  nhẹ       │
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

---

## 6. State → LeLamp Mapping (MVP)

| Buddy state | LED effect | Servo | Voice |
|-------------|-----------|-------|-------|
| `sleep` | tắt | neutral | — |
| `idle` | trắng nhẹ breathing (`/led/effect breathing`) | neutral | — |
| `busy` | xanh dương pulse (`/led/effect pulse`, màu xanh) | — | — |
| `attention` | cam đỏ nhấp nháy (`/led/effect blink`, màu cam đỏ) | nghiêng về phía user | TTS: "Claude cần approval: {tool} trên {hint}" |
| `heart` | vàng ấm solid 3s | gật nhẹ | — |
| `celebrate` | rainbow burst (`/led/effect rainbow`) 3s | nhún vui | chime |

### Quy trình voice approval (UC-2)

```
1. Heartbeat đến với prompt != null
2. State → attention
3. LED nhấp nháy + servo nghiêng
4. TTS: "Approve {tool}? {hint}"
5. Lắng nghe voice (qua LeLamp /voice hoặc local intent):
   - "approve" / "yes" / "ok" → gửi permission decision "once"
   - "deny" / "no" / "skip"  → gửi permission decision "deny"
   - timeout 30s             → không làm gì, Desktop sẽ timeout
6. State → heart (nếu approve <5s) hoặc → busy/idle
```

---

## 7. Kế hoạch triển khai

### Phase 1: BLE GATT server + state sync (UC-1)

- [ ] Go BLE GATT server dùng `tinygo.org/x/bluetooth` hoặc `github.com/muka/go-bluetooth`
- [ ] Nordic UART Service với đúng UUIDs
- [ ] Advertise tên `Claude-Lumi`
- [ ] Parse heartbeat JSON → suy ra state
- [ ] State machine: sleep/idle/busy/attention
- [ ] Map state → gọi LeLamp LED API

### Phase 2: Voice approval (UC-2)

- [ ] Khi vào state attention, gọi LeLamp TTS đọc prompt
- [ ] Lắng nghe voice command qua local intent hoặc LeLamp voice
- [ ] Gửi permission decision về qua BLE TX
- [ ] Theo dõi thống kê approval (số lần approve/deny, lưu file)

### Phase 3: Token dashboard (UC-3)

- [ ] Chuyển token count tới LeLamp display endpoint
- [ ] Hiện: sessions đang chạy, tokens hôm nay, state hiện tại

### Phase 4: Tính năng mở rộng (UC-4, UC-5) — Tương lai

- [ ] Presence signal từ Lumi → Desktop (cần mở rộng protocol)
- [ ] Inject transcript context vào OpenClaw (cần Lumi server API)

---

## 8. Chọn BLE Library

| Library | Ưu điểm | Nhược điểm |
|---------|---------|------------|
| `tinygo.org/x/bluetooth` | Pure Go, cross-platform, hỗ trợ GATT server | Hỗ trợ Pi4 BlueZ cần test thêm |
| `github.com/muka/go-bluetooth` | Mature, native DBus/BlueZ | Dependency nặng hơn |
| Python `bleak` + subprocess | BLE trên Pi đã được chứng minh | Không phải Go, thêm process |

Khuyến nghị: bắt đầu với `tinygo.org/x/bluetooth` — nếu Pi4 có vấn đề thì fallback sang `go-bluetooth`.

---

## 9. Config

Plugin đọc file config riêng: `config/buddy.json`

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

## 10. Triển khai

```bash
# Build
GOOS=linux GOARCH=arm64 go build -o buddy-plugin ./cmd/buddy/

# Chạy như systemd service
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

## 11. Rủi ro & Ràng buộc

| Rủi ro | Ảnh hưởng | Giảm thiểu |
|--------|-----------|------------|
| Pi4 BLE tầm phủ ~10m | Mac phải ở cùng phòng với lamp | OK cho setup bàn làm việc |
| BLE bandwidth thấp | Transcript dài bị cắt (>4KB bị drop) | Chỉ nhận summary, không full transcript |
| Claude Desktop BLE API chưa stable | Protocol có thể đổi | Theo REFERENCE.md, pin version |
| Độ trễ voice approval | STT delay + BLE round trip | Giữ prompt ngắn, timeout 30s |
| Xung đột LED với Lumi | Buddy và ambient cùng điều khiển LED | Buddy ưu tiên khi active, nhả khi sleep/idle |

---

## 12. Tiêu chí thành công

- [ ] Claude Desktop thấy "Claude-Lumi" trong Hardware Buddy scan
- [ ] Pair thành công, tự reconnect sau reboot
- [ ] LED thay đổi theo Desktop state (idle/busy/attention)
- [ ] Voice approve/deny tool call hoạt động end-to-end
- [ ] Token count hiển thị trên màn hình Lumi
- [ ] Plugin crash không ảnh hưởng Lumi server chính
