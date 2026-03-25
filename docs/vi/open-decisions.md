# Quyết Định Chưa Chốt — AI Lamp (Lumi)

> Các quyết định cần đưa ra trước khi bắt đầu code. Mỗi cái chặn các tính năng cụ thể.
> Khi chốt xong, chuyển xuống phần "Đã chốt" kèm quyết định và ngày.

## Chưa chốt

### 1. Nội dung SKILL.md cho các skill mới

**Câu hỏi**: Viết gì trong 5 file SKILL.md mới (servo-control, camera, audio, display, emotion)?

**Bối cảnh**: LLM của OpenClaw đọc SKILL.md để hiểu API. `led-control/SKILL.md` đã có (kế thừa từ lobster). 5 skill mới cần mô tả HTTP API endpoints đã define trong `architecture-decision.md` mục 5.

**Chặn**: OpenClaw không điều khiển được hardware mới nào nếu thiếu.

**Hướng đề xuất**: Draft dựa trên API endpoints đã có. Chỉnh sửa sau khi test với OpenClaw.

---

### 2. OpenClaw Event Push — Lumi thông báo OpenClaw bằng cách nào?

**Câu hỏi**: Khi sensing loop của Lumi phát hiện sự kiện (người đến, ánh sáng thay đổi, stress), đẩy context cho OpenClaw bằng cách nào?

**Lựa chọn**:
- A. WebSocket message đến OpenClaw
- B. HTTP callback đến API endpoint của OpenClaw
- C. Ghi vào shared file/pipe, OpenClaw watch
- D. OpenClaw poll endpoint `/api/events` của Lumi

**Bối cảnh**: OpenClaw có WebSocket connection với Lumi (kế thừa từ lobster `internal/openclaw/`). Có thể gửi message qua channel đó.

**Chặn**: Toàn bộ hành vi tự hành/proactive (Trụ cột 4).

---

### 3. Xử lý Camera — On-device hay OpenClaw?

**Câu hỏi**: Vision processing (face detection, presence, gesture, light analysis) chạy trên Pi 4 hay giao cho OpenClaw?

**Lựa chọn**:
- A. On-device với OpenCV — nhanh, không cần mạng, nhưng Pi 4 GPU hạn chế
- B. OpenClaw vision — thông minh hơn, nhưng thêm latency
- C. Hybrid — simple CV on-device (presence, light level), phức tạp (gesture, face emotion) qua OpenClaw

**Chặn**: Camera skill, sensing loop, auto-tracking, video call optimization.

---

### 4. Audio Input — Ai sở hữu Microphone?

**Câu hỏi**: OpenClaw hay Lumi own microphone?

**Lựa chọn**:
- A. OpenClaw own mic trực tiếp (voice pipeline: STT → LLM → TTS)
- B. Lumi capture audio, forward stream cho OpenClaw
- C. Chia sẻ — OpenClaw own voice pipeline, Lumi tap mic riêng cho ambient sensing (sound level, silence)

**Chặn**: Voice pipeline, sensing loop audio events.

---

### 5. LED Driver — Go hay Python?

**Câu hỏi**: User-facing LED control (scenes, effects, colors) dùng driver nào?

**Lựa chọn**:
- A. Go SPI driver (lobster `internal/led/`) — Lumi own LED trực tiếp
- B. Python rpi_ws281x (LeLamp) — bridge qua HTTP
- C. Cả hai — Go cho system states (boot, error), Python cho user-facing (scenes, effects)

**Bối cảnh**: Lobster đã có Go WS2812 SPI driver. LeLamp có Python rpi_ws281x cho 64-LED grid. Dùng cả hai có thể conflict SPI bus.

**Chặn**: LED skill implementation.

---

### 6. Emotion Presets — Tham số cụ thể

**Câu hỏi**: Mỗi emotion cụ thể tham số hardware bao nhiêu?

**Ví dụ**: "curious" intensity 0.8 = servo angle bao nhiêu? LED color gì? Audio file nào? Eye animation nào? Randomization range?

**Chặn**: Emotion skill. Có thể defer — bắt đầu với 3-4 emotion cơ bản, mở rộng sau.

---

### 7. Display Rendering — GC9A01 Driver & Eye Animation

**Câu hỏi**: Dùng Python lib nào cho GC9A01? Render pixel-art eyes bằng gì?

**Lựa chọn driver**: `luma.lcd`, ST7789 compatible libs, Pillow direct SPI
**Lựa chọn rendering**: Sprite sheets, Pillow draw, pygame

**Chặn**: Display skill. Có thể defer — bắt đầu không có display, thêm sau (plugin architecture hỗ trợ).

---

## Đã chốt (2026-03-24)

| Quyết định | Kết quả | Docs |
|---|---|---|
| Bridge Go ↔ Python | HTTP proxy. LeLamp FastAPI `127.0.0.1:5001`, Lumi proxy từ port 5000. | `architecture-decision.md` §11, `bootstrap-ota.md` §6 |
| LeLamp source | Mono-repo. Copy drivers từ `humancomputerlab/lelamp_runtime` vào `lelamp/`. Track upstream qua `UPSTREAM.md`. | `bootstrap-ota.md` §6 |
| Tên project/character | **Lumi** (from "luminous"). Binary: `lumi-server`. Service: `lumi.service`. Wake word: "Hey Lumi". | Tất cả docs |
| Display concept | Dual-mode: pixel-art eyes (default) + info display (giờ, thời tiết, timer, notifications). | `architecture-decision.md` §3, `product-vision.md` §4 |
| Autonomous sensing | Hybrid. Lumi chạy edge detection nhẹ. Đẩy event cho OpenClaw khi cần AI quyết định. | `product-vision.md` §2 Pillar 4, `architecture-decision.md` §4 |
| OTA components | 5 thành phần: lumi, bootstrap, web, openclaw, lelamp. LeLamp = stage 2b. | `bootstrap-ota.md` §1-§3 |
| Product pillars | 4 Trụ cột: "Hiểu tôi", "Sống thật", "Hữu ích thật", "Tự hành". | `product-vision.md` §2 |

---

> Khi chốt quyết định, chuyển từ "Chưa chốt" xuống "Đã chốt" kèm ngày và cập nhật docs liên quan.
