# Quyết Định Kiến Trúc: Hybrid Hardware Control

## Ngày: 2026-03-24

## Bối Cảnh

Dự án AI Lamp chia sẻ ~70-80% kiến trúc phần mềm với [openclaw-lobster](../../../openclaw-lobster) (tên mã "Intern"). Khác biệt chính là AI Lamp có nhiều thiết bị ngoại vi hơn: Servo Motor, Camera, Microphone, Speaker — ngoài LED.

Câu hỏi đặt ra: **Kiến trúc điều khiển phần cứng nên thiết kế thế nào?**

## Quyết Định: Fork Lobster + Kiến Trúc Hybrid

### 1. Mỗi Thiết Bị Có Repo Riêng (Chiến Lược Fork)

Mỗi sản phẩm phần cứng có codebase riêng. AI Lamp fork từ openclaw-lobster và điều chỉnh cho phần cứng cụ thể.

**Lý do**: Đơn giản, rõ ràng, không over-engineering. Mỗi thiết bị phát triển độc lập.

### 2. Hybrid Hardware Control (Tầng Hệ Thống + Tầng MCP)

Thay vì nhúng toàn bộ điều khiển phần cứng vào intern server (như lobster làm với LED), chia thành hai tầng:

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

#### Tầng 2 — MCP Server (chạy cùng Intern, expose cho OpenClaw)

Toàn bộ **điều khiển phần cứng hướng người dùng** được đóng gói thành MCP (Model Context Protocol) server. OpenClaw nhìn phần cứng như tools/skills có thể gọi trực tiếp.

**MCP Tools được expose**:

| Tool | Mô tả | Phần cứng |
|---|---|---|
| `led.set_brightness` | Đặt độ sáng LED (0-100%) | LED |
| `led.set_color` | Đặt màu RGB hoặc nhiệt độ màu | LED |
| `led.set_scene` | Kích hoạt scene (đọc sách, tập trung, thư giãn, phim, đêm, năng lượng) | LED |
| `led.set_effect` | Kích hoạt hiệu ứng (thở, nến, cầu vồng, thông báo) | LED |
| `servo.pan` | Xoay đèn theo chiều ngang (0-180°) | Servo Motor |
| `servo.tilt` | Nghiêng đèn theo chiều dọc (0-90°) | Servo Motor |
| `servo.set_position` | Di chuyển đến vị trí đặt sẵn (bàn, tường, giữa) | Servo Motor |
| `servo.home` | Trở về vị trí mặc định | Servo Motor |
| `camera.get_presence` | Kiểm tra có người trong phòng không | Camera |
| `camera.get_face_position` | Lấy tọa độ khuôn mặt cho tracking | Camera |
| `camera.get_gesture` | Phát hiện cử chỉ tay | Camera |
| `camera.get_light_analysis` | Phân tích ánh sáng trên mặt (cho video call) | Camera |
| `audio.speak` | Chuyển text thành giọng nói | Speaker |
| `audio.play_sound` | Phát âm thanh thông báo/hiệu ứng | Speaker |
| `audio.set_volume` | Đặt âm lượng loa (0-100%) | Speaker |
| `audio.play_ambient` | Phát âm thanh môi trường (mưa, thiên nhiên) | Speaker |

**Cách hoạt động với OpenClaw**:

LLM (qua OpenClaw) nhận đầu vào người dùng và **tự quyết định** gọi tool nào. Không cần intern server parse lệnh.

Ví dụ — Người dùng nói: *"Chiếu đèn xuống bàn, chế độ tập trung"*

OpenClaw LLM gọi:
```json
[
  {"tool": "servo.set_position", "params": {"preset": "desk"}},
  {"tool": "led.set_scene", "params": {"scene": "focus"}}
]
```

Ví dụ — Người dùng nói: *"Có ai trong phòng không?"*

OpenClaw LLM gọi:
```json
[
  {"tool": "camera.get_presence", "params": {}}
]
```
Rồi trả lời bằng giọng nói qua `audio.speak`.

## Sơ Đồ Kiến Trúc

```
┌──────────────────────────────────────────────────────────┐
│                     Intern Server (Go)                    │
│                                                          │
│  ┌─────────────────────┐   ┌──────────────────────────┐  │
│  │  Tầng 1: Hệ Thống   │   │  Tầng 2: MCP Server      │  │
│  │  (luôn chạy)        │   │  (expose cho OpenClaw)   │  │
│  │                     │   │                          │  │
│  │  • LED khởi động/lỗi│   │  Tools:                  │  │
│  │  • Nút reset        │   │  • led.set_brightness()  │  │
│  │  • Quản lý mạng     │   │  • led.set_color()       │  │
│  │  • Cập nhật OTA     │   │  • led.set_scene()       │  │
│  │  • MQTT dispatch    │   │  • servo.pan()           │  │
│  │  • Giám sát internet│   │  • servo.tilt()          │  │
│  │                     │   │  • camera.get_presence() │  │
│  │  Hoạt động KHÔNG    │   │  • camera.get_gesture()  │  │
│  │  cần OpenClaw       │   │  • audio.speak()         │  │
│  │                     │   │  • audio.set_volume()    │  │
│  └─────────────────────┘   └────────────┬─────────────┘  │
│                                          │                │
└──────────────────────────────────────────┼────────────────┘
                                           │ MCP (stdio/SSE)
                                           ▼
                                   ┌──────────────┐
                                   │   OpenClaw    │
                                   │   (AI/LLM)   │
                                   │              │
                                   │  Gọi tools   │
                                   │  qua MCP     │
                                   └──────┬───────┘
                                          │
                                          ▼
                                   ┌──────────────┐
                                   │ Người dùng    │
                                   │ (Giọng nói/   │
                                   │  Cử chỉ/App) │
                                   └──────────────┘
```

## Phần Cứng ↔ Tầng Mapping

| Phần cứng | Tầng 1 (Hệ thống) | Tầng 2 (MCP Tools) |
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
2. **AI-native**: LLM tự quyết định điều khiển phần cứng nào — không cần parse lệnh thủ công
3. **Dễ mở rộng**: Thêm phần cứng mới = thêm MCP tool definition
4. **Phân tách rõ ràng**: Tầng hệ thống vs tầng người dùng được định nghĩa rõ
5. **Kế thừa từ lobster**: 70-80% code Tầng 1 đã được kiểm chứng, production-ready

## Kế Thừa Từ Lobster (openclaw-lobster)

Các thành phần fork trực tiếp:

| Thành phần | Đường dẫn Lobster | Ghi chú |
|---|---|---|
| HTTP Server | `server/server.go` | Gin framework, port 5000 |
| Quản lý cấu hình | `server/config/` | JSON config với reload |
| LED driver | `internal/led/` | WS2812 SPI driver (pure Go) |
| LED state machine | `internal/led/engine.go` | States, effects, auto-rollback |
| Nút reset | `internal/resetbutton/` | GPIO 26 nhấn giữ |
| Dịch vụ mạng | `internal/network/` | WiFi AP/STA, quét mạng |
| Dịch vụ OpenClaw | `internal/openclaw/` | Tạo config, WebSocket |
| Backend client | `internal/beclient/` | Báo cáo trạng thái |
| MQTT client | `lib/mqtt/` | Tự kết nối lại, dispatch |
| OTA bootstrap | `bootstrap/` | Kiểm tra version, cài đặt |
| Domain models | `domain/` | Struct dùng chung |
| Build & deploy | `scripts/`, `Makefile` | Cross-compile, systemd |

## Mới Cho AI Lamp

| Thành phần | Đường dẫn (dự kiến) | Mô tả |
|---|---|---|
| MCP Server | `mcp/` | Xử lý giao thức MCP, đăng ký tool |
| Servo driver | `internal/servo/` | Điều khiển PWM cho servo xoay/nghiêng |
| Dịch vụ camera | `internal/camera/` | OpenCV/GoCV hoặc V4L2 cho thị giác |
| Dịch vụ audio | `internal/audio/` | ALSA/PulseAudio cho mic + speaker |
| MCP tool definitions | `mcp/tools/` | LED, servo, camera, audio tool handlers |

## Câu Hỏi Mở

- [ ] MCP transport: stdio hay SSE? (phụ thuộc cách OpenClaw khởi chạy MCP server)
- [ ] Xử lý camera: trên thiết bị (GoCV) hay giao cho OpenClaw xử lý vision?
- [ ] Đầu vào audio: OpenClaw xử lý mic trực tiếp, hay intern thu rồi chuyển tiếp?
- [ ] Phần cứng servo: model servo nào? Bao nhiêu trục (1 xoay hay xoay+nghiêng)?
- [ ] Loại LED: WS2812 như lobster, hay LED khác cho đèn?
