# Lumi Server API — Tài Liệu

> Lumi Server (Go, Gin framework) chạy trên port 5000.

## Lumi Server Endpoints (Go, :5000)

### Health

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/api/health/live` | Liveness probe |
| GET | `/api/health/readiness` | Readiness probe (OpenClaw connected?) |

### System

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/api/system/info` | CPU, RAM, temp, uptime, version |
| GET | `/api/system/network` | WiFi SSID, IP, signal, internet status |
| GET | `/api/system/dashboard` | Snapshot tổng hợp (OpenClaw + config + HW) |

### Device Setup

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| POST | `/api/device/setup` | Cấu hình WiFi + LLM + channel + MQTT (async, trả về ngay) |
| POST | `/api/device/channel` | Thay đổi messaging channel |

### Network

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/api/network` | Quét WiFi networks |
| GET | `/api/network/current` | SSID + IP hiện tại |
| GET | `/api/network/check-internet` | Kiểm tra kết nối internet |

### Sensing

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| POST | `/api/sensing/event` | Nhận sensing event từ LeLamp |

**Request body:**
```json
{
  "type": "voice_command|voice|motion|sound|presence.enter|presence.leave|light.level",
  "message": "...",
  "image": "<base64 JPEG, optional>"
}
```

**Event types:**

| Type | Nguồn | Có ảnh? | Mô tả |
|------|-------|---------|-------|
| `voice_command` / `voice` | Mic (Deepgram STT) | Không | Lệnh giọng nói |
| `motion` | Camera (frame diff) | Có (large motion) | Phát hiện chuyển động |
| `presence.enter` | Camera (Haar cascade face detection) | Có | Phát hiện khuôn mặt mới |
| `presence.leave` | Camera (3 tick liên tục không thấy mặt) | Không | Người rời đi |
| `light.level` | Camera (mean brightness) | Không | Ánh sáng môi trường thay đổi đáng kể (>30/255) |
| `sound` | Mic (RMS energy) | Không | Tiếng động lớn |

**Flow xử lý:**
1. `voice_command` hoặc `voice` + local intent enabled → match intent → thực thi trực tiếp (~50ms)
2. Không match → forward OpenClaw qua WebSocket `chat.send`
3. Nếu event có `image` → gọi `SendChatMessageWithImage` → gửi ảnh kèm text cho AI vision phân tích

### OpenClaw

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/api/openclaw/status` | Trạng thái kết nối WS |
| GET | `/api/openclaw/events` | SSE stream events real-time |
| GET | `/api/openclaw/recent` | 100 events gần nhất (ring buffer) |

---

## LeLamp Endpoints (Python FastAPI, :5001)

Truy cập qua nginx proxy: `/hw/*` → `127.0.0.1:5001`

### Servo (5 trục Feetech)

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/servo` | Recordings + animation state |
| POST | `/servo/play` | Phát animation (curious, nod, happy_wiggle, idle, sad, excited, shy, shock) |
| POST | `/servo/move` | Gửi joint positions với smooth interpolation |
| POST | `/servo/release` | Tắt torque tất cả servo |
| GET | `/servo/position` | Vị trí servo hiện tại |
| GET | `/servo/aim` | Danh sách aim directions |
| POST | `/servo/aim` | Aim đầu đèn (center, desk, wall, left, right, up, down, user) |

### LED (64 WS2812, grid 8x5)

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/led` | LED strip info |
| GET | `/led/color` | Màu LED hiện tại |
| POST | `/led/solid` | Fill toàn bộ 1 màu |
| POST | `/led/paint` | Set từng pixel (array tối đa 64) |
| POST | `/led/off` | Tắt tất cả LED |
| POST | `/led/effect` | Bật effect (breathing, candle, rainbow, notification_flash, pulse) |
| POST | `/led/effect/stop` | Dừng effect |

### Camera

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/camera` | Availability + resolution |
| GET | `/camera/snapshot` | Chụp 1 frame JPEG |
| GET | `/camera/stream` | MJPEG live stream |

### Audio

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/audio` | Audio device availability |
| POST | `/audio/volume` | Set volume (0-100%) |
| GET | `/audio/volume` | Get volume |
| POST | `/audio/play-tone` | Phát test tone |
| POST | `/audio/record` | Thu âm WAV |

### Emotion

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| POST | `/emotion` | Biểu cảm kết hợp servo + LED + display eyes |

8 emotions: curious, happy, sad, thinking, idle, excited, shy, shock

### Scene

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/scene` | Danh sách scene presets |
| POST | `/scene` | Kích hoạt scene (reading, focus, relax, movie, night, energize) |

### Presence

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/presence` | State hiện tại (present/idle/away) |
| POST | `/presence/enable` | Bật auto presence control |
| POST | `/presence/disable` | Tắt auto presence (manual mode) |

### Display (GC9A01 1.28" LCD tròn)

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/display` | State hiện tại (mode, expression) |
| POST | `/display/eyes` | Set eye expression + pupil position |
| POST | `/display/info` | Chuyển sang info mode (text/subtitle) |
| POST | `/display/eyes-mode` | Chuyển về eyes mode (default) |
| GET | `/display/snapshot` | Frame hiện tại dưới dạng JPEG |

11 expressions: neutral, happy, sad, curious, thinking, excited, shy, shock, sleepy, angry, love

### Voice

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| POST | `/voice/start` | Start voice pipeline (Deepgram STT + TTS) |
| POST | `/voice/stop` | Stop voice pipeline |
| POST | `/voice/speak` | TTS — chuyển text thành giọng nói |
| GET | `/voice/status` | voice_available, voice_listening, tts_available, tts_speaking |

### System

| Method | Endpoint | Mô tả |
|--------|----------|-------|
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

1. Lumi Server khởi động Gin trên :5000
2. Đọc `config/config.json`
3. Nếu `SetUpCompleted`:
   - Kết nối OpenClaw WebSocket
   - Kết nối MQTT
   - Start ambient behaviors
4. Nếu chưa setup: chờ `POST /api/device/setup`

## Local Intent Matching

Khi nhận `voice_command` hoặc `voice` event, Lumi check local intent trước (~50ms):

| Lệnh | Hành động |
|-------|-----------|
| "bật đèn", "turn on light" | `/led/solid` warm + happy emotion |
| "tắt đèn", "turn off light" | `/led/off` + idle emotion |
| "đọc sách", "reading mode" | scene:reading |
| "tập trung", "focus mode" | scene:focus |
| "thư giãn", "relax" | scene:relax |
| "xem phim", "movie mode" | scene:movie |
| "đèn ngủ", "goodnight" | scene:night + sleepy emotion |
| "sáng lên", "brighter" | scene:energize |
| "vui lên", "happy" | emotion:happy |
| "buồn", "sad" | emotion:sad |
| "tăng âm", "volume up" | volume 80 |
| "giảm âm", "volume down" | volume 30 |
| "im", "mute" | volume 0 |

Không match → forward OpenClaw.
