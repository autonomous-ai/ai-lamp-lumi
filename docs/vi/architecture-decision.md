# Quyết Định Kiến Trúc: Hybrid Hardware Control

## Ngày: 2026-03-24

## Bối Cảnh

Dự án AI Lamp chia sẻ ~70-80% kiến trúc phần mềm với [openclaw-lobster](../../../openclaw-lobster) (tên mã "Intern"). Khác biệt chính là AI Lamp có nhiều thiết bị ngoại vi hơn: Servo Motor, Camera, Microphone, Speaker — ngoài LED.

Câu hỏi đặt ra: **Kiến trúc điều khiển phần cứng nên thiết kế thế nào?**

## Quyết Định: Fork Lobster + Kiến Trúc Hybrid

### 1. Mỗi Thiết Bị Có Repo Riêng (Chiến Lược Fork)

Mỗi sản phẩm phần cứng có codebase riêng. AI Lamp fork từ openclaw-lobster và điều chỉnh cho phần cứng cụ thể.

**Lý do**: Đơn giản, rõ ràng, không over-engineering. Mỗi thiết bị phát triển độc lập.

### 2. Hybrid Hardware Control (Tầng Hệ Thống + Tầng OpenClaw Skills)

Thay vì nhúng toàn bộ điều khiển phần cứng chỉ trong intern server, chia thành hai tầng:

#### Tầng 1 — Hệ Thống (Intern Server, luôn chạy)

Xử lý các chức năng **quan trọng cho hệ thống**, phải hoạt động **trước và không cần OpenClaw**:

- Trạng thái LED hệ thống (khởi động, lỗi, mất mạng, factory reset)
- Nút reset (GPIO)
- Quản lý mạng (AP/STA, cấu hình WiFi)
- Cập nhật OTA
- Giao tiếp MQTT với backend
- Giám sát internet

Kế thừa trực tiếp từ kiến trúc lobster:
- `internal/led/` — State machine LED với auto-rollback
- `internal/resetbutton/` — Phát hiện nhấn giữ GPIO
- `internal/network/` — Quản lý WiFi
- `internal/openclaw/` — Cấu hình OpenClaw & WebSocket
- `lib/mqtt/` — MQTT client

**Nguyên tắc chính**: Nếu OpenClaw ngừng hoạt động, thiết bị vẫn khởi động, hiển thị trạng thái qua LED, và có thể được cấu hình lại.

#### Tầng 2 — OpenClaw Skills (SKILL.md + Intern HTTP API)

Toàn bộ **điều khiển phần cứng hướng người dùng** theo đúng pattern của lobster với skill `led-control`:

1. **Intern server** expose HTTP API endpoint cho mỗi thiết bị phần cứng
2. **SKILL.md** mô tả API cho LLM của OpenClaw hiểu
3. **LLM đọc SKILL.md** → hiểu API có gì → tự gọi qua `curl`

Đây **KHÔNG phải MCP**. Sử dụng hệ thống skill native của OpenClaw:
- Skills là file Markdown (`SKILL.md`) đặt trong `workspace/skills/`
- OpenClaw tự phát hiện (`skills.load.watch: true`)
- LLM đọc mô tả skill và tự quyết định khi nào/cách nào gọi API

**Tham khảo**: Skill LED hiện tại của lobster tại `resources/openclaw-skills/led-control/SKILL.md`:
```
POST http://127.0.0.1:5000/api/led  →  {"state": "thinking"}
GET  http://127.0.0.1:5000/api/led  →  {"state": "idle"}
```

### Skills cho AI Lamp

Mỗi thiết bị phần cứng có thư mục skill riêng + HTTP API:

```
workspace/skills/
├── led-control/SKILL.md        ← kế thừa từ lobster (điều chỉnh)
├── servo-control/SKILL.md      ← MỚI
├── camera/SKILL.md             ← MỚI
└── audio/SKILL.md              ← MỚI
```

**HTTP API endpoint tương ứng trên Intern**:

| Endpoint | Method | Mô tả | Skill |
|---|---|---|---|
| `/api/led` | GET | Lấy trạng thái LED hiện tại | led-control |
| `/api/led` | POST | Đặt trạng thái/độ sáng/màu/scene/hiệu ứng | led-control |
| `/api/servo` | GET | Lấy vị trí servo hiện tại | servo-control |
| `/api/servo` | POST | Đặt servo xoay/nghiêng/vị trí đặt sẵn | servo-control |
| `/api/servo/home` | POST | Đưa servo về vị trí mặc định | servo-control |
| `/api/camera/presence` | GET | Kiểm tra có người trong phòng | camera |
| `/api/camera/face` | GET | Lấy tọa độ khuôn mặt | camera |
| `/api/camera/gesture` | GET | Phát hiện cử chỉ tay | camera |
| `/api/camera/light-analysis` | GET | Phân tích ánh sáng mặt | camera |
| `/api/audio/speak` | POST | Chuyển text thành giọng nói | audio |
| `/api/audio/sound` | POST | Phát âm thanh thông báo/hiệu ứng | audio |
| `/api/audio/volume` | POST | Đặt âm lượng loa | audio |
| `/api/audio/ambient` | POST | Phát/dừng âm thanh môi trường | audio |

**Cách hoạt động — Ví dụ**:

Người dùng nói: *"Chiếu đèn xuống bàn, chế độ tập trung"*

OpenClaw LLM đọc `servo-control/SKILL.md` và `led-control/SKILL.md`, rồi thực thi:
```bash
curl -s -X POST http://127.0.0.1:5000/api/servo \
  -H "Content-Type: application/json" \
  -d '{"preset": "desk"}'

curl -s -X POST http://127.0.0.1:5000/api/led \
  -H "Content-Type: application/json" \
  -d '{"scene": "focus"}'
```

Không cần logic parse lệnh — **LLM tự hiểu từ mô tả trong SKILL.md**.

## Sơ Đồ Kiến Trúc

```
┌──────────────────────────────────────────────────────────────┐
│                      Intern Server (Go)                       │
│                                                              │
│  ┌─────────────────────┐    ┌──────────────────────────────┐ │
│  │  Tầng 1: Hệ Thống   │    │  HTTP API (port 5000)        │ │
│  │  (luôn chạy)        │    │                              │ │
│  │                     │    │  /api/led    → internal/led/  │ │
│  │  • LED khởi động/lỗi│    │  /api/servo  → internal/servo/│ │
│  │  • Nút reset        │    │  /api/camera → internal/cam/  │ │
│  │  • Quản lý mạng     │    │  /api/audio  → internal/audio/│ │
│  │  • Cập nhật OTA     │    │                              │ │
│  │  • MQTT dispatch    │    │  Được OpenClaw LLM gọi       │ │
│  │  • Giám sát internet│    │  qua curl (mô tả trong       │ │
│  │                     │    │  các file SKILL.md)          │ │
│  │  Hoạt động KHÔNG    │    │                              │ │
│  │  cần OpenClaw       │    │                              │ │
│  └─────────────────────┘    └──────────────┬───────────────┘ │
│                                             │                 │
└─────────────────────────────────────────────┼─────────────────┘
                                              │ HTTP (127.0.0.1:5000)
                                              │
                        ┌─────────────────────▼──────────────────────┐
                        │              OpenClaw (AI/LLM)              │
                        │                                            │
                        │  workspace/skills/                         │
                        │  ├── led-control/SKILL.md                  │
                        │  ├── servo-control/SKILL.md                │
                        │  ├── camera/SKILL.md                       │
                        │  └── audio/SKILL.md                        │
                        │                                            │
                        │  LLM đọc SKILL.md → gọi intern HTTP API   │
                        └────────────────────┬───────────────────────┘
                                             │
                                             ▼
                                     ┌──────────────┐
                                     │ Người dùng    │
                                     │ (Giọng nói/   │
                                     │  Cử chỉ/App) │
                                     └──────────────┘
```

## Phần Cứng ↔ Tầng Mapping

| Phần cứng | Tầng 1 (Hệ thống) | Tầng 2 (OpenClaw Skills) |
|---|---|---|
| **LED** | Khởi động, lỗi, trạng thái hệ thống | Độ sáng, màu sắc, scene, hiệu ứng |
| **Servo Motor** | — | Xoay, nghiêng, vị trí đặt sẵn, theo dõi |
| **Camera** | — | Phát hiện hiện diện, cử chỉ, theo dõi mặt, phân tích ánh sáng |
| **Microphone** | — | Đầu vào giọng nói (OpenClaw xử lý trực tiếp) |
| **Speaker** | — | Đầu ra TTS, thông báo, âm thanh môi trường |
| **Nút Reset** | Nhấn giữ tắt nguồn / factory reset | — |
| **Mạng** | AP/STA, cấu hình WiFi, giám sát internet | — |

## Lợi Ích

1. **Đáng tin cậy**: Chức năng quan trọng (LED trạng thái, mạng, OTA) hoạt động không cần OpenClaw
2. **AI-native**: LLM đọc SKILL.md và tự quyết định gọi API nào — không cần parse lệnh thủ công
3. **Dễ mở rộng**: Thêm phần cứng mới = thêm package `internal/` + HTTP endpoint + SKILL.md
4. **Pattern đã chứng minh**: Cùng kiến trúc với LED control của lobster, đã chạy production
5. **Hot-reload**: OpenClaw theo dõi thư mục skills — thêm/sửa SKILL.md không cần restart
6. **Kế thừa từ lobster**: 70-80% code Tầng 1 đã được kiểm chứng, production-ready

## Kế Thừa Từ Lobster (openclaw-lobster)

| Thành phần | Đường dẫn Lobster | Ghi chú |
|---|---|---|
| HTTP Server | `server/server.go` | Gin framework, port 5000 |
| Quản lý cấu hình | `server/config/` | JSON config với reload |
| LED driver | `internal/led/` | WS2812 SPI driver (pure Go) |
| LED state machine | `internal/led/engine.go` | States, effects, auto-rollback |
| LED skill | `resources/openclaw-skills/led-control/SKILL.md` | Điều chỉnh cho đèn lamp |
| Nút reset | `internal/resetbutton/` | GPIO 26 nhấn giữ |
| Dịch vụ mạng | `internal/network/` | WiFi AP/STA, quét mạng |
| Dịch vụ OpenClaw | `internal/openclaw/` | Tạo config, WebSocket |
| Backend client | `internal/beclient/` | Báo cáo trạng thái |
| MQTT client | `lib/mqtt/` | Tự kết nối lại, dispatch |
| OTA bootstrap | `bootstrap/` | Kiểm tra version, cài đặt |
| Domain models | `domain/` | Struct dùng chung |
| Build & deploy | `scripts/`, `Makefile` | Cross-compile, systemd |

## Mới Cho AI Lamp

| Thành phần | Cần xây dựng | OpenClaw sử dụng thế nào |
|---|---|---|
| `internal/servo/` | Servo PWM driver (xoay/nghiêng) | `servo-control/SKILL.md` → `POST /api/servo` |
| `internal/camera/` | Xử lý hình ảnh (OpenCV/V4L2) | `camera/SKILL.md` → `GET /api/camera/*` |
| `internal/audio/` | Mic + Speaker (ALSA/PulseAudio) | `audio/SKILL.md` → `POST /api/audio/*` |
| `server/servo/delivery/` | Servo HTTP handlers | Gin routes cho `/api/servo` |
| `server/camera/delivery/` | Camera HTTP handlers | Gin routes cho `/api/camera/*` |
| `server/audio/delivery/` | Audio HTTP handlers | Gin routes cho `/api/audio/*` |
| `resources/openclaw-skills/` | SKILL.md cho mỗi thiết bị | Deploy vào `workspace/skills/` |

## Câu Hỏi Mở

- [ ] Xử lý camera: trên thiết bị (GoCV) hay giao cho OpenClaw xử lý vision?
- [ ] Đầu vào audio: OpenClaw xử lý mic trực tiếp, hay intern thu rồi chuyển tiếp?
- [ ] Phần cứng servo: model servo nào? Bao nhiêu trục (1 xoay hay xoay+nghiêng)?
- [ ] Loại LED: WS2812 như lobster, hay LED khác cho đèn?
- [ ] LED skill: mở rộng SKILL.md hiện tại của lobster hay viết lại cho tính năng lamp (scene, hiệu ứng, màu sắc)?
