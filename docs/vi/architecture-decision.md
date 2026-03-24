# Quyết Định Kiến Trúc: AI Lamp — Hybrid Hardware Control

## Ngày: 2026-03-24

---

## 1. Bối Cảnh & Hành Trình Quyết Định

Dự án AI Lamp trải qua nhiều giai đoạn tìm hướng kiến trúc trước khi đi đến quyết định cuối cùng:

1. **Ban đầu**: Dự định xây dựng project Go độc lập, sử dụng MCP protocol để giao tiếp với phần cứng.
2. **Phát hiện 1**: openclaw-lobster (Go server, nay đổi tên thành Lumi) chia sẻ ~70-80% kiến trúc với những gì AI Lamp cần. Không có lý do viết lại từ đầu.
3. **Quyết định fork**: Mỗi sản phẩm phần cứng có repo riêng. AI Lamp fork từ lobster và mở rộng cho phần cứng cụ thể.
4. **Phát hiện 2**: LeLamp runtime (Python) **đã chạy** trên Raspberry Pi 4 với đầy đủ hardware drivers — motor, LED, audio. Không cần viết lại driver trong Go.
5. **Phát hiện 3**: OpenClaw sử dụng **SKILL.md** (skill system native), **KHÔNG PHẢI MCP**. Skills là file Markdown mô tả API, LLM tự đọc và gọi.
6. **Quyết định cuối**: Kiến trúc Hybrid — OpenClaw skills gọi Lumi HTTP API, Lumi bridge đến LeLamp Python services.

### Phần Cứng (Raspberry Pi 4)

| Thiết bị | Chi tiết | Chức năng |
|---|---|---|
| 5 Servo Motors | Feetech | Chuyển động 5 trục (xoay, nghiêng, biểu cảm) |
| 64 WS2812 RGB LEDs | Grid 8x5 | Full color, điều khiển từng pixel |
| Camera | Trong lõi đèn | Thị giác máy tính |
| Microphone | — | Đầu vào giọng nói |
| Speaker | — | Đầu ra giọng nói |
| Display | GC9A01 1.28" tròn (SPI) | Mắt hoạt hình, thông tin, trạng thái |

---

## 2. Quyết Định Kiến Trúc Cuối Cùng

**Kiến trúc Hybrid 3 tầng**: OpenClaw (AI) → Lumi Server (Go) → LeLamp Runtime (Python) → Phần cứng.

Nguyên tắc cốt lõi:
- **Tầng hệ thống** (Go Lumi) hoạt động **KHÔNG cần OpenClaw** — thiết bị luôn phản hồi được.
- **Điều khiển hướng người dùng** thông qua OpenClaw skills gọi HTTP API.
- **LeLamp runtime** chỉ làm hardware drivers — không chứa logic AI.
- **Không dùng MCP** — dùng SKILL.md native của OpenClaw.
- **Hardware là plugin** — cắm vào thì play, không cắm thì bỏ qua.

### Hardware Plugin (Plug & Play)

Mọi thiết bị phần cứng là **plugin** — cắm vào thì driver load + skill available, không cắm thì hệ thống vẫn chạy bình thường.

Khi khởi động, Lumi server tự phát hiện phần cứng và:
1. Chỉ load driver cho phần cứng được phát hiện
2. Chỉ bật HTTP API endpoint tương ứng
3. Chỉ deploy SKILL.md liên quan cho OpenClaw

| Plugin | Cách phát hiện | Nếu không có |
|---|---|---|
| Servo Motors | Quét USB serial (Feetech) | Không body language, đèn tĩnh — vẫn là smart light |
| LED (WS2812) | Kiểm tra SPI (`/dev/spidev0.0`) | Không điều khiển ánh sáng — chỉ có system LED |
| Camera | Kiểm tra V4L2 (`/dev/video0`) | Không gesture, presence, tracking — chỉ voice control |
| Microphone | Quét ALSA device | Không voice input — chỉ điều khiển qua app/text |
| Speaker | Quét ALSA device | Không voice output — chế độ im lặng, chỉ LED feedback |
| Display | Quét I2C/SPI (GC9A01/SSD1306) | Không mắt/thông tin — chỉ LED status |

Cùng codebase hỗ trợ nhiều cấu hình:
- **Full lamp**: Tất cả plugin → AI companion đầy đủ
- **Simple lamp**: LED + Mic + Speaker → đèn thông minh có voice
- **Dev/test**: Không hardware → stub drivers, API vẫn hoạt động

---

## 3. Software Stack

### OpenClaw — Bộ Não AI

Thay thế hoàn toàn LiveKit + OpenAI của LeLamp gốc.

- Personality & nhân cách cho đèn
- LLM multi-provider (Claude, GPT, Gemini, ...)
- Skill system (SKILL.md)
- Channels (giọng nói, text, ...)
- Memory (nhớ ngữ cảnh, sở thích người dùng)

### LeLamp Runtime (Python) — CHỈ Hardware Drivers

Giữ nguyên từ dự án LeLamp hiện tại, nhưng bỏ phần AI/LiveKit:

- **MotorsService** — điều khiển 5 servo Feetech
- **RGBService** — điều khiển 64 WS2812 LED (rpi_ws281x)
- **Audio** — amixer, phát âm thanh
- Event-driven **ServiceBase** với priority dispatch
- Hiện tại được điều khiển qua LiveKit `@function_tool` → sẽ chuyển sang nhận lệnh từ Lumi Server

### Lumi Server (Go, fork từ openclaw-lobster) — Hệ Thống + HTTP API Bridge

- Tầng hệ thống: LED trạng thái, reset button, mạng, OTA, MQTT
- HTTP API bridge: nhận request từ OpenClaw skills, chuyển tiếp đến LeLamp Python services
- Kế thừa phần lớn code từ lobster

---

## 4. Tầng 1: Hệ Thống (Lumi Server, Go, luôn chạy)

Hoạt động **KHÔNG cần OpenClaw**. Nếu OpenClaw ngừng, thiết bị vẫn khởi động, hiển thị trạng thái, và có thể cấu hình lại.

| Chức năng | Mô tả |
|---|---|
| Trạng thái LED hệ thống | Khởi động, lỗi, mất mạng, factory reset — qua SPI driver trực tiếp |
| Nút reset | GPIO 26 — nhấn giữ để factory reset |
| Quản lý mạng | AP/STA mode, cấu hình WiFi, quét mạng |
| Cập nhật OTA | Kiểm tra version, tải và cài đặt bản cập nhật |
| Giao tiếp MQTT | Kết nối backend, báo cáo trạng thái, nhận lệnh |
| Giám sát internet | Phát hiện mất kết nối, tự khôi phục |
| **Autonomous sensing** | Sensing loop nhẹ, chạy liên tục: camera (presence, light level), mic (sound level, silence, voice tone), time (schedules), plug-in sensors. Đẩy event cho OpenClaw khi phát hiện thay đổi đáng kể. |

### Autonomous Sensing Loop (Tầng 1.5)

Lumi chạy sensing loop liên tục, chi phí thấp, phát hiện sự kiện trên thiết bị (**edge detection**). Khi phát hiện sự kiện đáng kể → đẩy context cho OpenClaw để AI quyết định hành động. Proactive behavior mà không tốn LLM tokens liên tục.

```
Sensing Loop (Lumi Server, luôn chạy):
  Camera → presence.enter / presence.leave / light.level
  Mic    → sound.level / sound.silence / sound.voice_tone
  Time   → time.schedule (cron-like)
  Sensor → sensor.* (plug-in: nhiệt độ, độ ẩm, ...)
       │
       │ event + context (chỉ khi có thay đổi đáng kể)
       ▼
  OpenClaw (AI Brain) → quyết định hành động → gọi Lumi HTTP API → phần cứng
```

**Rule-based** (không cần AI): auto-dim khi vắng, adjust brightness khi trời tối, idle animations.
**AI-driven** (OpenClaw quyết định): chào hỏi, phản ứng mood, empathy, gợi ý theo lịch.

**Kế thừa từ lobster:**

```
server/server.go          — HTTP server (Gin, port 5000)
server/config/            — Quản lý cấu hình JSON
internal/led/             — WS2812 SPI driver + state machine + auto-rollback
internal/resetbutton/     — GPIO 26 nhấn giữ
internal/network/         — WiFi AP/STA
internal/openclaw/        — Cấu hình OpenClaw & WebSocket
internal/beclient/        — Backend client, báo cáo trạng thái
lib/mqtt/                 — MQTT client, tự kết nối lại
bootstrap/                — OTA, kiểm tra version
domain/                   — Struct dùng chung
```

---

## 5. Tầng 2: OpenClaw Skills (SKILL.md + HTTP API)

Toàn bộ **điều khiển phần cứng hướng người dùng** thông qua skill system native của OpenClaw:

1. File **SKILL.md** trong `workspace/skills/` mô tả API cho LLM
2. OpenClaw tự phát hiện skills (`skills.load.watch: true`)
3. **LLM đọc SKILL.md** → hiểu API → tự gọi `curl` đến Lumi HTTP API tại `127.0.0.1:5000`
4. Lumi HTTP API bridge đến LeLamp Python services → điều khiển phần cứng

Đây **KHÔNG phải MCP**. Cùng pattern với `led-control/SKILL.md` hiện có của lobster.

### Cấu trúc Skills

```
workspace/skills/
├── led-control/SKILL.md       ← kế thừa từ lobster (mở rộng cho 64 LED grid)
├── servo-control/SKILL.md     ← MỚI
├── camera/SKILL.md            ← MỚI
├── audio/SKILL.md             ← MỚI
├── display/SKILL.md            ← MỚI (dual-mode: eyes + info)
└── emotion/SKILL.md           ← MỚI (quan trọng nhất, kết hợp tất cả)
```

### HTTP API Endpoints

#### LED Control

| Endpoint | Method | Mô tả |
|---|---|---|
| `/api/led` | GET | Lấy trạng thái LED hiện tại |
| `/api/led` | POST | Đặt màu, độ sáng, scene, hiệu ứng, pattern |

#### Servo Control

| Endpoint | Method | Mô tả |
|---|---|---|
| `/api/servo` | GET | Lấy vị trí servo hiện tại |
| `/api/servo` | POST | Đặt xoay, nghiêng, preset, biểu cảm |
| `/api/servo/home` | POST | Đưa servo về vị trí mặc định |

#### Camera

| Endpoint | Method | Mô tả |
|---|---|---|
| `/api/camera/presence` | GET | Kiểm tra có người trong phòng |
| `/api/camera/face` | GET | Lấy tọa độ khuôn mặt |
| `/api/camera/gesture` | GET | Phát hiện cử chỉ tay |
| `/api/camera/light-analysis` | GET | Phân tích ánh sáng môi trường |

#### Audio

| Endpoint | Method | Mô tả |
|---|---|---|
| `/api/audio/speak` | POST | Chuyển text thành giọng nói |
| `/api/audio/sound` | POST | Phát âm thanh thông báo/hiệu ứng |
| `/api/audio/volume` | POST | Đặt âm lượng loa |
| `/api/audio/ambient` | POST | Phát/dừng âm thanh môi trường |

#### Emotion (Kết hợp)

| Endpoint | Method | Mô tả |
|---|---|---|
#### Display

| Endpoint | Method | Mô tả |
|---|---|---|
| `/api/display` | GET | Lấy trạng thái display hiện tại |
| `/api/display` | POST | Dual-mode: hiển thị mắt cảm xúc (default) hoặc thông tin (giờ, thời tiết, timer, notification, trạng thái) |

#### Emotion (Kết hợp tất cả)

| Endpoint | Method | Mô tả |
|---|---|---|
| `/api/emotion` | POST | Biểu cảm cảm xúc kết hợp servo + LED + audio + display |

---

## 6. Sơ Đồ Kiến Trúc

```
┌─────────────────────────────────────────────────────────────────────┐
│                        NGƯỜI DÙNG                                   │
│                  (Giọng nói / Cử chỉ / App)                        │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     OpenClaw (Bộ não AI/LLM)                        │
│                                                                     │
│  • Personality & nhân cách        • Memory                          │
│  • LLM multi-provider             • Channels (giọng nói, text)      │
│                                                                     │
│  workspace/skills/                                                  │
│  ├── led-control/SKILL.md                                           │
│  ├── servo-control/SKILL.md                                         │
│  ├── camera/SKILL.md                                                │
│  ├── audio/SKILL.md                                                 │
│  └── emotion/SKILL.md             ← skill quan trọng nhất          │
│                                                                     │
│  LLM đọc SKILL.md → gọi curl → 127.0.0.1:5000                     │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ HTTP (curl)
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Lumi Server (Go, port 5000)                      │
│                                                                     │
│  ┌──────────────────────┐    ┌────────────────────────────────────┐ │
│  │  TẦNG 1: HỆ THỐNG    │    │  HTTP API (Tầng 2)                 │ │
│  │  (luôn chạy)         │    │                                    │ │
│  │                      │    │  /api/led      → LED control       │ │
│  │  • LED trạng thái    │    │  /api/servo    → Servo control     │ │
│  │  • Nút reset GPIO 26 │    │  /api/camera/* → Camera            │ │
│  │  • Quản lý mạng      │    │  /api/audio/*  → Audio             │ │
│  │  • Cập nhật OTA      │    │  /api/emotion  → Emotion (kết hợp) │ │
│  │  • MQTT backend      │    │                                    │ │
│  │  • Giám sát internet │    │  Bridge đến LeLamp Python ──────┐  │ │
│  │                      │    │                                 │  │ │
│  │  Hoạt động KHÔNG     │    │                                 │  │ │
│  │  cần OpenClaw        │    │                                 │  │ │
│  └──────────────────────┘    └─────────────────────────────────┘  │ │
│                                                                │  │ │
└────────────────────────────────────────────────────────────────┼──┘ │
                                                                 │
                            ┌────────────────────────────────────┘
                            │ HTTP/gRPC/subprocess (bridge)
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  LeLamp Runtime (Python, Raspberry Pi 4)            │
│                                                                     │
│  • MotorsService  — 5 servo Feetech (xoay, nghiêng, biểu cảm)     │
│  • RGBService     — 64 WS2812 LED grid 8x5 (rpi_ws281x)           │
│  • Audio          — amixer, phát âm thanh                           │
│  • ServiceBase    — Event-driven, priority dispatch                 │
│                                                                     │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        PHẦN CỨNG                                    │
│                                                                     │
│  🔧 5 Servo Motors (Feetech)    💡 64 WS2812 RGB LEDs (grid 8x5)  │
│  📷 Camera (trong lõi đèn)      🎤 Microphone                     │
│  🔊 Speaker                                                        │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 7. Emotion Skill — Điểm Khác Biệt Quan Trọng

Emotion là skill **mới quan trọng nhất** — kết hợp tất cả phần cứng để tạo **generative body language** cho đèn.

### API

```
POST /api/emotion
{"emotion": "curious", "intensity": 0.8}
```

### Cách Hoạt Động

Lumi server nhận emotion request → chuyển đổi thành tổ hợp:

| Thành phần | Ví dụ "curious" (intensity 0.8) |
|---|---|
| **Servo** | Nghiêng nhẹ sang phải, ngẩng lên một chút |
| **LED** | Chuyển sang tông vàng ấm, nhấp nháy nhẹ |
| **Audio** | Phát âm thanh "hmm" nhỏ (tùy chọn) |

Mỗi lần gọi tạo ra biểu cảm **unique** — không lặp lại y hệt nhờ randomized parameters trong preset.

### Tại Sao Quan Trọng

- LLM chỉ cần gọi **1 endpoint** thay vì phối hợp 3 endpoint riêng lẻ (servo + LED + audio)
- Biểu cảm tự nhiên, không máy móc — nhờ randomization
- Mở rộng dễ dàng: thêm emotion preset mới không cần thay đổi SKILL.md

### Ví Dụ Sử Dụng

Người dùng nói: *"Bạn nghĩ gì về bức tranh này?"*

OpenClaw LLM:
1. Gọi `POST /api/emotion {"emotion": "curious", "intensity": 0.7}` — đèn nghiêng, đổi màu
2. Gọi `GET /api/camera/face` — phân tích biểu cảm người dùng
3. Trả lời bằng giọng nói + gọi `POST /api/emotion {"emotion": "thoughtful", "intensity": 0.5}`

---

## 8. Luồng Giao Tiếp

```
Người dùng nói
    │
    ▼
OpenClaw (AI/LLM)
    │ đọc SKILL.md, quyết định hành động
    │
    ▼
curl HTTP API (127.0.0.1:5000)
    │
    ▼
Lumi Server (Go)
    │ bridge đến LeLamp
    │
    ▼
LeLamp Python Services
    │ MotorsService / RGBService / Audio
    │
    ▼
Phần cứng (Servo / LED / Camera / Speaker)
```

**Ví dụ cụ thể:**

Người dùng: *"Chiếu đèn xuống bàn, chế độ tập trung"*

```bash
# OpenClaw LLM đọc servo-control/SKILL.md + led-control/SKILL.md, rồi gọi:

curl -s -X POST http://127.0.0.1:5000/api/servo \
  -H "Content-Type: application/json" \
  -d '{"preset": "desk"}'

curl -s -X POST http://127.0.0.1:5000/api/led \
  -H "Content-Type: application/json" \
  -d '{"scene": "focus"}'
```

Không cần logic parse lệnh — **LLM tự hiểu từ mô tả trong SKILL.md**.

---

## 9. Kế Thừa Từ Lobster (openclaw-lobster)

| Thành phần | Đường dẫn | Ghi chú |
|---|---|---|
| HTTP Server | `server/server.go` | Gin framework, port 5000 |
| Quản lý cấu hình | `server/config/` | JSON config với reload |
| LED driver | `internal/led/` | WS2812 SPI driver (pure Go) |
| LED state machine | `internal/led/engine.go` | States, effects, auto-rollback |
| LED skill | `resources/openclaw-skills/led-control/SKILL.md` | Mở rộng cho grid 64 LED |
| Nút reset | `internal/resetbutton/` | GPIO 26 nhấn giữ |
| Dịch vụ mạng | `internal/network/` | WiFi AP/STA, quét mạng |
| Dịch vụ OpenClaw | `internal/openclaw/` | Tạo config, WebSocket |
| Backend client | `internal/beclient/` | Báo cáo trạng thái |
| MQTT client | `lib/mqtt/` | Tự kết nối lại, dispatch |
| OTA bootstrap | `bootstrap/` | Kiểm tra version, cài đặt |
| Domain models | `domain/` | Struct dùng chung |
| Build & deploy | `scripts/`, `Makefile` | Cross-compile, systemd |

---

## 10. Cần Xây Dựng Mới

| Thành phần | Mô tả | OpenClaw sử dụng |
|---|---|---|
| `server/servo/delivery/` | Servo HTTP handlers, bridge đến LeLamp MotorsService | `servo-control/SKILL.md` → `POST /api/servo` |
| `server/camera/delivery/` | Camera HTTP handlers | `camera/SKILL.md` → `GET /api/camera/*` |
| `server/audio/delivery/` | Audio HTTP handlers | `audio/SKILL.md` → `POST /api/audio/*` |
| `server/emotion/delivery/` | Emotion HTTP handler (kết hợp servo + LED + audio) | `emotion/SKILL.md` → `POST /api/emotion` |
| `resources/openclaw-skills/` | SKILL.md cho mỗi thiết bị | Deploy vào `workspace/skills/` |
| Bridge layer | Giao tiếp giữa Go Lumi server và Python LeLamp services | HTTP/gRPC/subprocess |

### Phần Cứng ↔ Tầng Mapping

| Phần cứng | Tầng 1 (Hệ thống) | Tầng 2 (OpenClaw Skills) |
|---|---|---|
| **LED (64 WS2812)** | Khởi động, lỗi, trạng thái hệ thống | Màu, độ sáng, scene, hiệu ứng, pattern |
| **Servo (5 trục)** | — | Xoay, nghiêng, preset, biểu cảm |
| **Camera** | — | Hiện diện, khuôn mặt, cử chỉ, ánh sáng |
| **Microphone** | — | Đầu vào giọng nói (OpenClaw xử lý) |
| **Speaker** | — | TTS, thông báo, âm thanh môi trường |
| **Nút Reset** | Nhấn giữ → factory reset | — |
| **Mạng** | AP/STA, WiFi, giám sát internet | — |

---

## 11. Câu Hỏi Mở

- [ ] **Bridge Go ↔ Python**: LeLamp expose HTTP API riêng? Hay Lumi server gọi Python subprocess/pipe? Hay gRPC?
- [ ] **Xử lý camera**: Trên thiết bị (OpenCV) hay giao cho OpenClaw vision? Latency vs capability trade-off.
- [ ] **Đầu vào audio**: OpenClaw xử lý mic trực tiếp, hay Lumi server thu âm rồi chuyển tiếp stream?
- [ ] **LED driver**: Adapt SPI driver Go của lobster cho grid 64 LED, hay dùng rpi_ws281x Python driver của LeLamp (đã chạy)?
- [ ] **Generative body language**: LLM tạo servo positions thế nào? Emotion presets với randomized parameters? Hay LLM tự generate raw positions?
