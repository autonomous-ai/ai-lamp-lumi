# AI Lamp — Tầm Nhìn Sản Phẩm

> **Chiếc đèn bàn tốt nhất thế giới.**
> Không chỉ chiếu sáng — nó hiểu bạn, sống cùng bạn, và thực sự hữu ích.

**Phiên bản:** 1.0
**Ngày:** 24/03/2026
**Trạng thái:** Draft

---

## Mục Lục

1. [Tầm Nhìn & Sứ Mệnh](#1-tầm-nhìn--sứ-mệnh)
2. [3 Trụ Cột — Điều Gì Làm AI Lamp Hơn 10 Lần](#2-ba-trụ-cột--điều-gì-làm-ai-lamp-hơn-10-lần)
3. [Phân Tích Cạnh Tranh](#3-phân-tích-cạnh-tranh)
4. [Thông Số Phần Cứng](#4-thông-số-phần-cứng)
5. [Kiến Trúc Phần Mềm](#5-kiến-trúc-phần-mềm)
6. [Các Trường Hợp Sử Dụng](#6-các-trường-hợp-sử-dụng)
7. [Đối Tượng Người Dùng](#7-đối-tượng-người-dùng)
8. [Yêu Cầu Phi Chức Năng](#8-yêu-cầu-phi-chức-năng)
9. [Câu Hỏi Mở](#9-câu-hỏi-mở)

---

## 1. Tầm Nhìn & Sứ Mệnh

### Tầm nhìn

Tạo ra chiếc đèn bàn đầu tiên trên thế giới kết hợp được cả bốn yếu tố mà chưa sản phẩm nào làm được:

```
AI Lamp = Đèn bàn tốt nhất thế giới
        + Companion robot biểu cảm nhất
        + AI assistant thông minh nhất (OpenClaw)
        + Open source platform
```

### Sứ mệnh

Biến chiếc đèn bàn — vật dụng quen thuộc nhất trên mọi bàn làm việc — thành một người bạn đồng hành thông minh, giàu cảm xúc, và thực sự hữu ích trong cuộc sống hàng ngày. Không phải gadget để khoe, mà là thứ bạn không thể thiếu sau một tuần sử dụng.

### Nguyên tắc thiết kế

| Nguyên tắc | Giải thích |
|---|---|
| **Hữu ích trước, cute sau** | Mọi tính năng phải giải quyết vấn đề thực. Biểu cảm dễ thương là phần thưởng, không phải mục đích. |
| **AI sâu, không AI nông** | Hiểu ngữ cảnh, nhớ lâu dài, phản ứng cá nhân hóa — không phải chatbot trả lời một câu rồi quên. |
| **Mở và mở rộng được** | Open source platform. Cộng đồng tạo skills, personality, animations mới. |
| **Hoạt động không cần cloud** | Điều khiển cơ bản (đèn, servo) hoạt động offline. AI cần internet, nhưng đèn thì không. |
| **Tôn trọng quyền riêng tư** | Camera/mic là opt-in. Người dùng kiểm soát hoàn toàn dữ liệu. |

---

## 2. Ba Trụ Cột — Điều Gì Làm AI Lamp Hơn 10 Lần

Mỗi đối thủ có thể làm tốt một yếu tố. Không ai kết hợp được cả ba.

### Trụ cột 1: "Nó hiểu tôi" — Deep Personal AI

AI Lamp không chỉ nghe lệnh. Nó **hiểu ngữ cảnh cuộc sống** của bạn.

| Tình huống | AI Lamp phản ứng |
|---|---|
| Bạn đang stress (nhận biết qua giọng nói) | Tự giảm sáng, bật nhạc nhẹ, nghiêng đầu lại gần bạn |
| Bạn đang focus (gõ phím liên tục, im lặng lâu) | Im lặng hoàn toàn, đèn tập trung, không quấy rầy |
| Bạn vừa về nhà (phát hiện hiện diện + nhận diện khuôn mặt) | Vui vẻ chào, hỏi ngày hôm nay thế nào |
| Bạn thức khuya quá (sau 23:00, vẫn hoạt động) | Nhắc nhở nhẹ nhàng, từ từ giảm ánh sáng xanh |
| Tuần trước bạn nói đang deadline | "Deadline tuần trước xong chưa? Hôm nay có vẻ thoải mái hơn nè!" |

**Tại sao không ai match được:**

- **OpenClaw long-term memory** — nhớ qua ngày, tuần, tháng. Không phải mỗi lần nói chuyện là bắt đầu lại từ đầu.
- **Multi-provider LLM** — không bị khóa vào một nhà cung cấp AI. Dùng GPT-4, Claude, Gemini, local LLM — tùy chọn.
- **Personality engine** — tính cách nhất quán, phát triển theo thời gian, không phải "generic assistant".

### Trụ cột 2: "Nó sống thật" — Generative Body Language

Đây là điểm khác biệt lớn nhất so với Ongo và mọi đối thủ: AI Lamp **không replay animation cố định**. Mỗi phản ứng là duy nhất, được LLM quyết định real-time.

| Cảm xúc | Servo (5 trục) | LED (64 RGB) | Âm thanh |
|---|---|---|---|
| Tò mò | Nghiêng đầu sang bên | Vàng nhẹ, nhấp nháy chậm | Tiếng "hmm?" nhỏ |
| Buồn | Cúi xuống chậm rãi | Xanh dương mờ, tối dần | Im lặng hoặc thở dài nhẹ |
| Ngạc nhiên | Giật lên nhanh | Trắng sáng, flash | "Ồ!" |
| Đang nghĩ | Xoay nhẹ qua lại | Tím, chạy vòng tròn | Tiếng "hmm..." kéo dài |
| Vui | Lắc lư nhẹ nhàng | Cam/vàng ấm, sáng đều | Tiếng cười nhẹ |
| Tập trung giúp bạn | Hướng thẳng vào bàn | Trắng ấm, ổn định | Im lặng |

**Cơ chế hoạt động:**

```
LLM phân tích ngữ cảnh
    → Quyết định "cảm xúc" phù hợp
    → Gọi skill với parameters cụ thể
    → Servo position + LED color/pattern + Audio
    → Kết quả: phản ứng unique mỗi lần, không bao giờ lặp lại
```

**So với Ongo:** Ongo có ~10-20 animation được lập trình sẵn. Sau một tuần, bạn đã thấy hết. AI Lamp tạo phản ứng mới mỗi lần vì LLM quyết định parameters, không phải replay clip.

### Trụ cột 3: "Nó hữu ích thật sự" — Không Chỉ Cute

Một chiếc đèn bàn cute mà vô dụng sẽ bị bỏ xó sau 2 tuần. AI Lamp phải là thứ **không thể thiếu**.

**Đèn bàn tốt nhất:**
- Ánh sáng circadian — tự động điều chỉnh nhiệt độ màu theo thời gian trong ngày
- Focus mode — ánh sáng tối ưu cho làm việc, đọc sách, code
- Video call lighting — tự động bật đèn đẹp khi nhận diện bạn đang họp online
- 64 LED độc lập — patterns, hiệu ứng, ambient không giới hạn

**Trợ lý thực sự:**
- Quản lý lịch, đọc email tóm tắt, nhắc deadline
- Tóm tắt tin tức buổi sáng
- Điều khiển smart home (qua skills mở rộng)
- Trả lời câu hỏi, brainstorm, dịch thuật — mọi thứ LLM làm được

**Platform mở:**
- Community tạo skills mới (qua SKILL.md — không cần biết code backend)
- Personality mới — muốn đèn nói giọng Huế? Tạo personality mới
- Animations mới — ai cũng có thể đóng góp LED patterns
- Multi-channel — nói chuyện qua Telegram/Slack/Discord khi bạn không ở nhà, nó vẫn "ở đó"

### Trụ cột 4: "Nó tự hành" — Autonomous Sensing & Proactive Behavior

Hầu hết thiết bị thông minh là **reactive** — chờ lệnh. Lumi là **proactive** — liên tục cảm nhận môi trường và tự hành động mà không cần ai hỏi.

Đây là sự khác biệt giữa công cụ và người bạn. Công cụ thì chờ. Bạn đồng hành thì chú ý.

#### Kiến trúc Hybrid Sensing

```
┌─────────────────────────────────────────────────────────────────┐
│  Lumi Server (Go) — Sensing Loop nhẹ, chạy liên tục            │
│                                                                 │
│  Edge detection on-device, chi phí thấp:                        │
│  • Camera: có người / vắng / độ sáng môi trường                │
│  • Mic: mức âm / im lặng / tông giọng                          │
│  • Time: giờ, lịch, thời gian từ lần tương tác cuối            │
│  • Sensors: nhiệt độ, độ ẩm (nếu có plug-in)                  │
│                                                                 │
│  Khi phát hiện sự kiện đáng kể → đẩy context cho OpenClaw      │
└──────────────────────────┬──────────────────────────────────────┘
                           │ event + context
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  OpenClaw (AI Brain) — Quyết định & Hành động                  │
│                                                                 │
│  Nhận context từ sensor → LLM quyết định:                      │
│  • Điều chỉnh ánh sáng? Di chuyển servo? Nói? Im lặng?        │
│  • Kết hợp: thời gian, lịch sử người dùng, mood hiện tại,     │
│    long-term memory, personality                                │
│  • Thực thi qua SKILL.md → curl đến Lumi HTTP API              │
└─────────────────────────────────────────────────────────────────┘
```

**Lumi = giác quan (rẻ, chạy liên tục).** **OpenClaw = bộ não (thông minh, gọi khi cần).**

#### Các hành vi tự hành

| Trigger | Lumi cảm nhận | Lumi tự làm | Ai quyết định |
|---|---|---|---|
| **Có người** | Camera: người vào khung hình | Bật đèn, chào, adjust ánh sáng | OpenClaw (personality) |
| **Vắng người** | Camera: không có ai 15 phút | Dim → sleep → tắt | Lumi (rule-based, tuỳ chỉnh) |
| **Trời tối** | Camera: ánh sáng môi trường giảm | Tăng brightness từ từ | Lumi (auto) + OpenClaw (chọn scene) |
| **Focus** | Mic: im lặng lâu + tiếng gõ phím | Giữ ổn định, không làm phiền | Lumi (detect) → OpenClaw (confirm) |
| **Stress** | Mic: thở dài, giọng căng | Ánh sáng ấm, gợi ý nghỉ | OpenClaw (empathy, memory) |
| **Vui** | Mic: tiếng cười | Lumi bounce, flash ấm, vui theo | OpenClaw (emotion skill) |
| **Khuya** | Time: quá giờ ngủ thường ngày | Giảm blue light, nhắc nhẹ | OpenClaw (memory: biết lịch user) |
| **Idle** | Không tương tác 30+ phút | Idle animation — LED thở nhẹ, nháy mắt | Lumi (built-in, không cần AI) |
| **Sáng** | Time: lịch buổi sáng | Sunrise simulation, chime nhẹ | Lumi (schedule) + OpenClaw (chào) |
| **Video call** | Camera: mặt centered + screen glow | Auto tối ưu ánh sáng mặt | Lumi (detect) → OpenClaw (adjust) |

#### Loại sự kiện sensing

| Event | Nguồn | Tần suất | Chi phí |
|---|---|---|---|
| `presence.enter` | Camera (face/body) | Khi thay đổi | Thấp (simple CV) |
| `presence.leave` | Camera (timeout không có mặt) | Khi thay đổi | Thấp |
| `light.level` | Camera (brightness frame) | Mỗi 30s | Rất thấp |
| `sound.level` | Mic (RMS amplitude) | Mỗi 5s | Rất thấp |
| `sound.silence` | Mic (thời gian im lặng > threshold) | Khi thay đổi | Rất thấp |
| `sound.voice_tone` | Mic (phân tích pitch/energy) | Khi có giọng nói | Trung bình |
| `time.schedule` | Clock (cron-like) | Theo lịch | Không |
| `sensor.*` | Sensor plug-in (nhiệt độ, độ ẩm) | Tuỳ chỉnh | Thấp |

Events rất nhẹ — không tốn LLM tokens. Chỉ khi sự kiện đủ đáng kể thì Lumi mới đẩy context cho OpenClaw để AI quyết định.

#### Quyền riêng tư & Kiểm soát

- Người dùng có thể tắt riêng từng kênh sensing (camera off, mic off, sensors off)
- Chế độ "Không làm phiền": tất cả hành vi proactive tạm dừng, Lumi chỉ phản hồi lệnh trực tiếp
- Toàn bộ sensing chạy **on-device** — không stream video/audio lên cloud cho ambient processing
- Privacy indicator: LED đổi màu khi camera/mic đang sensing

---

## 3. Phân Tích Cạnh Tranh

### Bảng so sánh chi tiết

| Tiêu chí | AI Lamp | Ongo (Interaction Labs) | LeLamp | Philips Hue | Dyson Lightcycle | Amazon Echo |
|---|---|---|---|---|---|---|
| **Ánh sáng chất lượng** | 64 RGB LED, circadian, focus mode | LED cơ bản | LED WS2812 | Hệ sinh thái đèn tốt nhất | LED cao cấp, CRI cao | Không phải đèn |
| **Chuyển động** | 5 trục servo, generative | 3+ trục, animation cố định | 5 trục servo | Không | Không | Không |
| **AI depth** | OpenClaw multi-provider, long-term memory | ChatGPT đơn, nông | OpenAI + LiveKit, cơ bản | Không AI | Thuật toán cố định | Alexa, nông |
| **Personality** | Engine tùy biến, phát triển theo thời gian | "Con mèo trong đèn", cố định | Cơ bản | Không | Không | Alexa, generic |
| **Body language** | Generative, unique mỗi lần | ~10-20 animation replay | 10 preset animations | Không | Không | Không |
| **Camera/Vision** | Face tracking, gesture, presence | Camera, privacy sunglasses | Camera | Không | Ambient light sensor | Camera (Echo Show) |
| **Voice** | STT + TTS + emotion analysis | Có | Có (LiveKit) | Không | Không | Alexa |
| **Long-term memory** | Ngày/tuần/tháng | Không rõ | Không | Không | Không | Giới hạn |
| **Skills/Ecosystem** | SKILL.md, community mở rộng | Closed source | Open source, giới hạn | Hue API, app ecosystem | Không | Alexa Skills (closed) |
| **Multi-channel** | Telegram, Slack, Discord | Không | Không | Hue App | Dyson App | Alexa App |
| **Open source** | Hoàn toàn | Không | Có | Không | Không | Không |
| **Offline** | Điều khiển cơ bản OK | Không rõ | Không rõ | Có (Zigbee) | Có | Giới hạn |
| **Multi-LLM** | GPT-4, Claude, Gemini, local | Chỉ ChatGPT | Chỉ OpenAI | N/A | N/A | Chỉ Alexa |
| **Giá dự kiến** | Trung bình-cao | Cao (~$299+) | Thấp (DIY) | Trung bình | Cao (~$650) | Trung bình |

### Rào cản cạnh tranh — Tại sao đối thủ không dễ bắt kịp

| Đối thủ | Nếu họ muốn cạnh tranh | Vấn đề họ gặp |
|---|---|---|
| **Philips/Dyson** | Thêm AI + body language | Không có robot hardware, thiếu personality engine, văn hóa công ty không phù hợp |
| **Ongo** | Nâng cấp AI, thêm smart lamp | AI bị khóa vào ChatGPT, closed source = không có ecosystem, thiếu long-term memory sâu |
| **Amazon Echo** | Thêm đèn + body language | Alexa personality nhạt, không body language, privacy concerns nghiêm trọng |
| **Startup mới** | Xây từ đầu | Không có OpenClaw ecosystem, phải tự xây AI brain từ zero — mất 1-2 năm |

### Công thức chiến thắng

```
┌──────────────────────────────────────────────────────────┐
│                    AI Lamp = 4 in 1                      │
│                                                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │
│  │  Đèn bàn    │  │ Companion   │  │  AI Assistant   │  │
│  │  tốt nhất   │ +│ robot biểu  │ +│  thông minh     │  │
│  │  thế giới   │  │ cảm nhất    │  │  nhất (OpenClaw)│  │
│  └─────────────┘  └─────────────┘  └─────────────────┘  │
│                          +                               │
│              ┌─────────────────────┐                     │
│              │  Open Source        │                     │
│              │  Platform           │                     │
│              └─────────────────────┘                     │
│                                                          │
│         Không sản phẩm nào kết hợp được cả 4.           │
└──────────────────────────────────────────────────────────┘
```

---

## 4. Thông Số Phần Cứng

### Nền tảng: Raspberry Pi 4

| Thành phần | Chi tiết | Vai trò |
|---|---|---|
| **SBC** | Raspberry Pi 4 (4GB RAM) | Bộ não xử lý chính |
| **Servo motors** | 5x Feetech servo | 5 trục chuyển động khớp nối — nghiêng, xoay, cúi, ngẩng, lắc |
| **LED** | 64x WS2812 RGB LED (ma trận 8x5) | Ánh sáng chính, hiệu ứng, patterns, trạng thái cảm xúc |
| **Camera** | Camera module (bên trong lõi đèn) | Nhận diện khuôn mặt, theo dõi, nhận diện cử chỉ, phát hiện hiện diện |
| **Microphone** | Microphone module | Nhận giọng nói, phân tích cảm xúc qua giọng |
| **Speaker** | Speaker module | Phát giọng nói TTS, thông báo, nhạc ambient, hiệu ứng âm thanh |
| **Display** | GC9A01 1.28" LCD tròn (SPI) | Dual-mode: mắt cảm xúc pixel art (default) + hiển thị thông tin (giờ, thời tiết, timer, notification) |

### Sơ đồ kết nối phần cứng

```
                    ┌─────────────────────┐
                    │   Raspberry Pi 4    │
                    │                     │
          GPIO/PWM ─┤  ┌───────────────┐  │
    ┌───────────────┤  │               │  ├─── USB Audio ──┐
    │               │  │   CPU/GPU     │  │                │
    │          I2C ─┤  │               │  ├─── CSI ───┐    │
    │               │  └───────────────┘  │           │    │
    │               │                     │           │    │
    │               └─────────────────────┘           │    │
    │                                                 │    │
    ▼                                                 ▼    ▼
┌────────┐  ┌────────┐                          ┌────┐ ┌─────────┐
│ Servo  │  │ 64x    │                          │Cam │ │ Mic +   │
│ 5x     │  │ WS2812 │                          │    │ │ Speaker │
│Feetech │  │ 8x5    │                          └────┘ └─────────┘
└────────┘  └────────┘

Servo 1-5: Vai, khuỷu, cổ tay, xoay, nghiêng
LED 8x5:   Ma trận 64 pixel, mỗi pixel RGB độc lập
```

---

## 5. Kiến Trúc Phần Mềm

### Tổng quan: Kiến trúc Hybrid 2 tầng

Kiến trúc được thiết kế theo nguyên tắc **tách biệt rõ ràng**: tầng hệ thống luôn chạy và không phụ thuộc AI, tầng AI skills mở rộng không giới hạn.

> **Lưu ý quan trọng:** Hệ thống sử dụng **OpenClaw Skills (SKILL.md)** — KHÔNG phải MCP (Model Context Protocol). SKILL.md là hệ thống skill native của OpenClaw, mô tả HTTP API endpoints để LLM gọi phần cứng qua curl.

### Sơ đồ kiến trúc

```
┌─────────────────────────────────────────────────────────────────┐
│                         NGƯỜI DÙNG                              │
│         Giọng nói │ Cử chỉ │ Telegram │ Slack │ Discord        │
└────────┬───────────────────────────────────────┬────────────────┘
         │                                       │
         ▼                                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│                    OPENCLAW (AI Brain)                           │
│                                                                 │
│  ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌──────────────────┐  │
│  │Personality│ │Multi-LLM │ │ Long-term │ │   Multi-channel  │  │
│  │ Engine   │ │ Provider │ │  Memory   │ │ Telegram/Slack/  │  │
│  │          │ │GPT/Claude│ │           │ │ Discord          │  │
│  └──────────┘ └──────────┘ └───────────┘ └──────────────────┘  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                   SKILL.md Files                         │   │
│  │                                                          │   │
│  │  led-control.md    servo-control.md    audio-control.md  │   │
│  │  mood-lighting.md  focus-mode.md       camera-track.md   │   │
│  │  circadian.md      presence.md         gesture.md        │   │
│  │                                                          │   │
│  │  Mỗi SKILL.md mô tả HTTP API endpoints                  │   │
│  │  → LLM đọc → quyết định gọi endpoint nào → curl         │   │
│  └──────────────────────────────┬───────────────────────────┘   │
│                                 │                               │
└─────────────────────────────────┼───────────────────────────────┘
                                  │ HTTP (curl)
         ┌────────────────────────┼────────────────────────┐
         │            TẦNG 2: OPENCLAW SKILLS              │
         │                                                  │
         │         HTTP API @ 127.0.0.1:5000                │
         │                                                  │
         │  POST /led/color    POST /servo/position         │
         │  POST /led/pattern  POST /servo/gesture          │
         │  POST /audio/play   POST /audio/tts              │
         │  GET  /camera/face  POST /camera/track           │
         │  GET  /presence     POST /mood                   │
         │                                                  │
         └────────────────────────┬─────────────────────────┘
                                  │ Calls
┌─────────────────────────────────┼─────────────────────────────┐
│                                 ▼                             │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │              LUMI SERVER (Go)                            │ │
│  │         Fork từ openclaw-lobster                         │ │
│  │                                                          │ │
│  │  ┌─────────┐ ┌─────────┐ ┌──────┐ ┌──────┐ ┌────────┐  │ │
│  │  │  Boot   │ │ Network │ │ OTA  │ │ MQTT │ │  HTTP  │  │ │
│  │  │ Manager │ │ Manager │ │Update│ │Bridge│ │  API   │  │ │
│  │  └─────────┘ └─────────┘ └──────┘ └──────┘ └────────┘  │ │
│  │                                                          │ │
│  │  System LED states (boot, error, connecting...)          │ │
│  │  Reset button handler                                    │ │
│  └──────────────────────────┬───────────────────────────────┘ │
│               TẦNG 1: HỆ THỐNG (luôn chạy)                   │
│                             │                                 │
│  ┌──────────────────────────▼───────────────────────────────┐ │
│  │              LELAMP RUNTIME (Python)                     │ │
│  │          Hardware drivers ONLY                           │ │
│  │                                                          │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐               │ │
│  │  │  Servo   │  │   LED    │  │  Audio   │               │ │
│  │  │ Driver   │  │  Driver  │  │ Driver   │               │ │
│  │  │(Feetech) │  │ (WS2812) │  │(ALSA/PW) │               │ │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘               │ │
│  │       │              │              │                     │ │
│  └───────┼──────────────┼──────────────┼─────────────────────┘ │
│          │              │              │                       │
└──────────┼──────────────┼──────────────┼───────────────────────┘
           ▼              ▼              ▼
     ┌──────────┐  ┌──────────┐  ┌──────────────┐
     │  5x Servo│  │ 64x LED  │  │  Mic/Speaker │
     │  Motors  │  │  WS2812  │  │              │
     └──────────┘  └──────────┘  └──────────────┘
```

### Chi tiết từng thành phần

#### OpenClaw — AI Brain

OpenClaw là bộ não AI của toàn bộ hệ thống. Nó thay thế hoàn toàn phần AI/personality của LeLamp (vốn chỉ dùng OpenAI + LiveKit cơ bản).

| Khả năng | Chi tiết |
|---|---|
| **Personality Engine** | Tính cách tùy biến, nhất quán qua mọi cuộc hội thoại, phát triển theo thời gian |
| **Multi-provider LLM** | GPT-4, Claude, Gemini, local models — chuyển đổi linh hoạt |
| **Long-term Memory** | Nhớ ngữ cảnh qua ngày/tuần/tháng, xây dựng hiểu biết về người dùng |
| **Multi-channel** | Telegram, Slack, Discord — nói chuyện với đèn khi bạn không ở nhà |
| **Voice I/O** | STT (Speech-to-Text) + TTS (Text-to-Speech) + emotion detection |
| **Skills Ecosystem** | SKILL.md files mô tả API → LLM tự quyết định gọi khi nào |

#### Lumi Server — Tầng Hệ Thống (Go)

Fork từ openclaw-lobster. Đây là tầng **luôn chạy**, hoạt động **không cần OpenClaw**.

**Trách nhiệm:**
- Quản lý boot sequence (LED trạng thái: booting → connecting → ready)
- Quản lý kết nối mạng (WiFi setup, fallback AP mode)
- OTA updates (cập nhật firmware từ xa)
- MQTT bridge (giao tiếp giữa các thành phần)
- HTTP API server tại `127.0.0.1:5000` — expose hardware control cho OpenClaw Skills
- System LED states (không phụ thuộc AI)
- Reset button handler

**Nguyên tắc quan trọng:** Nếu OpenClaw chết, đèn vẫn sáng, LED vẫn hiển thị trạng thái, nút reset vẫn hoạt động. Tầng hệ thống là nền tảng không bao giờ được phép fail.

#### LeLamp Runtime — Hardware Drivers (Python)

Giữ lại **chỉ phần hardware drivers** từ dự án LeLamp gốc. Toàn bộ AI/personality/animation logic của LeLamp bị loại bỏ và thay thế bởi OpenClaw.

**Drivers:**
- **Servo Driver (Feetech):** Điều khiển 5 servo motors, calibration, limits, smooth movement
- **LED Driver (WS2812):** Điều khiển 64 LED RGB, per-pixel control, patterns, brightness
- **Audio Driver:** Playback, recording, TTS output, ambient sounds

#### OpenClaw Skills — SKILL.md

Mỗi skill là một file SKILL.md mô tả HTTP API endpoints để LLM có thể gọi. Đây là pattern giống hệt skill `led-control` đã có trong lobster.

**Ví dụ cấu trúc SKILL.md:**

```markdown
# Skill: LED Control

## Mô tả
Điều khiển 64 LED WS2812 RGB trên AI Lamp.

## Endpoints

### Đặt màu toàn bộ
POST http://127.0.0.1:5000/led/color
Body: {"r": 255, "g": 100, "b": 0, "brightness": 80}

### Đặt pattern
POST http://127.0.0.1:5000/led/pattern
Body: {"pattern": "breathing", "color": "#FF6600", "speed": 2}

### Đặt pixel cụ thể
POST http://127.0.0.1:5000/led/pixel
Body: {"x": 3, "y": 2, "r": 255, "g": 0, "b": 0}
```

**LLM flow:**
1. Người dùng nói: "Chuyển đèn sang màu cam ấm"
2. OpenClaw LLM đọc SKILL.md → biết có endpoint `/led/color`
3. LLM quyết định parameters: `{"r": 255, "g": 165, "b": 0, "brightness": 70}`
4. Gọi `curl -X POST http://127.0.0.1:5000/led/color -d '...'`
5. Lumi server nhận request → gọi LeLamp runtime → LED thay đổi

---

## 6. Các Trường Hợp Sử Dụng

### Phân loại ưu tiên

| Ưu tiên | Ý nghĩa | Số lượng |
|---|---|---|
| **P0** | Bắt buộc cho MVP — sản phẩm không hoạt động nếu thiếu | 3 |
| **P1** | Quan trọng — tạo giá trị cốt lõi, cần có cho bản ra mắt | 5 |
| **P2** | Nâng cao — tạo sự khác biệt, có thể ra sau | 7 |

---

### P0 — Bắt buộc cho MVP

#### UC-01: Điều khiển giọng nói

| | |
|---|---|
| **Ưu tiên** | P0 |
| **Mô tả** | Người dùng nói lệnh bằng giọng nói tự nhiên, AI Lamp hiểu và thực hiện |
| **Ví dụ** | "Bật đèn", "Tắt đèn", "Sáng hơn", "Tối đi", "Chuyển sang màu xanh" |
| **Luồng** | Mic → STT → OpenClaw LLM → phân tích intent → gọi skill → thực hiện |
| **Yêu cầu** | Hỗ trợ tiếng Anh và tiếng Việt. Độ trễ < 1 giây. |

#### UC-02: Điều khiển màu sắc

| | |
|---|---|
| **Ưu tiên** | P0 |
| **Mô tả** | Thay đổi màu sắc LED qua giọng nói hoặc API |
| **Ví dụ** | "Đèn vàng ấm", "Đèn trắng lạnh", "Đèn đỏ", "Màu hoàng hôn" |
| **Luồng** | OpenClaw LLM hiểu ngữ cảnh màu → gọi `/led/color` với RGB phù hợp |
| **Đặc biệt** | Hiểu màu trừu tượng: "màu hoàng hôn" → gradient cam-hồng-tím |

#### UC-14: Phản hồi âm thanh

| | |
|---|---|
| **Ưu tiên** | P0 |
| **Mô tả** | AI Lamp trả lời bằng giọng nói tự nhiên, kết hợp body language |
| **Ví dụ** | Trả lời câu hỏi, xác nhận lệnh, chào hỏi, nhắc nhở |
| **Luồng** | OpenClaw LLM → TTS → Speaker + đồng thời servo gesture + LED expression |
| **Yêu cầu** | Giọng nói tự nhiên, đồng bộ với body language |

---

### P1 — Quan trọng cho bản ra mắt

#### UC-03: Scene (Cảnh)

| | |
|---|---|
| **Ưu tiên** | P1 |
| **Mô tả** | Kích hoạt bộ preset ánh sáng + hành vi cho các tình huống cụ thể |
| **Ví dụ** | "Chế độ làm việc", "Chế độ thư giãn", "Chế độ xem phim", "Chế độ ngủ" |
| **Chi tiết** | Mỗi scene = LED color/brightness + servo position + ambient sound + behavior rules |

#### UC-04: Hẹn giờ

| | |
|---|---|
| **Ưu tiên** | P1 |
| **Mô tả** | Đặt lịch tự động cho đèn và hành vi |
| **Ví dụ** | "7 giờ sáng bật đèn từ từ", "11 giờ tối nhắc tôi đi ngủ", "30 phút nữa tắt đèn" |
| **Chi tiết** | Kết hợp với personality — nhắc nhẹ nhàng, không như alarm |

#### UC-06: Trợ lý AI

| | |
|---|---|
| **Ưu tiên** | P1 |
| **Mô tả** | Sử dụng AI Lamp như trợ lý thông minh cho công việc và cuộc sống |
| **Ví dụ** | "Lịch hôm nay có gì?", "Đọc email mới", "Thời tiết hôm nay", "Dịch câu này sang tiếng Anh" |
| **Chi tiết** | OpenClaw xử lý — đây là khả năng core, không cần skill phần cứng |

#### UC-08: Hướng đèn Servo

| | |
|---|---|
| **Ưu tiên** | P1 |
| **Mô tả** | Điều chỉnh hướng chiếu sáng bằng giọng nói |
| **Ví dụ** | "Chiếu sang trái", "Hướng xuống bàn", "Ngẩng lên" |
| **Luồng** | LLM → `/servo/position` với tọa độ 5 trục |

#### UC-11: Phát hiện hiện diện

| | |
|---|---|
| **Ưu tiên** | P1 |
| **Mô tả** | Tự động nhận biết khi có người đến/đi |
| **Ví dụ** | Bật đèn khi bạn ngồi vào bàn, tắt sau 10 phút không ai, chào khi nhận diện khuôn mặt |
| **Luồng** | Camera → face detection → OpenClaw → phản ứng phù hợp |

#### UC-13: Trạng thái

| | |
|---|---|
| **Ưu tiên** | P1 |
| **Mô tả** | Hiển thị trạng thái hệ thống và thông báo qua LED + body language |
| **Ví dụ** | LED xanh nhấp nháy = đang nghe, LED đỏ = lỗi, nghiêng đầu = tò mò, gật = hiểu rồi |
| **Chi tiết** | Tầng hệ thống xử lý boot/error states. Tầng AI xử lý expression states. |

---

### P2 — Nâng cao

#### UC-05: Nhịp sinh học (Circadian)

| | |
|---|---|
| **Ưu tiên** | P2 |
| **Mô tả** | Tự động điều chỉnh nhiệt độ màu và độ sáng theo thời gian trong ngày |
| **Chi tiết** | Sáng: trắng mát, tỉnh táo. Chiều: trắng ấm, thoải mái. Tối: vàng cam, giảm ánh sáng xanh. Khuya: rất tối, đỏ cam. |

#### UC-07: Hiệu ứng

| | |
|---|---|
| **Ưu tiên** | P2 |
| **Mô tả** | Chạy hiệu ứng LED đặc biệt |
| **Ví dụ** | "Hiệu ứng cầu vồng", "Hiệu ứng lửa", "Hiệu ứng biển", "Nhấp nháy theo nhạc" |
| **Chi tiết** | Ma trận 8x5 cho phép patterns phức tạp — không chỉ đổi màu toàn bộ |

#### UC-09: Tự động theo dõi (Face Tracking)

| | |
|---|---|
| **Ưu tiên** | P2 |
| **Mô tả** | Servo tự động xoay theo khuôn mặt người dùng |
| **Chi tiết** | Camera phát hiện vị trí khuôn mặt → servo điều chỉnh → đèn luôn hướng về phía bạn |
| **Cảm giác** | Đèn "nhìn" bạn, tạo cảm giác đang lắng nghe |

#### UC-10: Cử chỉ (Gesture Control)

| | |
|---|---|
| **Ưu tiên** | P2 |
| **Mô tả** | Điều khiển đèn bằng cử chỉ tay |
| **Ví dụ** | Vẫy tay = bật/tắt, xòe bàn tay = tăng sáng, nắm tay = giảm sáng, ngón cái lên = OK |
| **Luồng** | Camera → gesture recognition → OpenClaw → thực hiện lệnh |

#### UC-12: Video call lighting

| | |
|---|---|
| **Ưu tiên** | P2 |
| **Mô tả** | Tự động tối ưu ánh sáng khi nhận diện bạn đang họp video |
| **Chi tiết** | Phát hiện webcam active hoặc Zoom/Meet đang chạy → chuyển sang ánh sáng đẹp cho camera: trắng ấm, CRI cao, hướng vào mặt |

#### UC-15: Điều khiển từ xa

| | |
|---|---|
| **Ưu tiên** | P2 |
| **Mô tả** | Điều khiển AI Lamp khi không ở nhà qua Telegram/Slack/Discord |
| **Ví dụ** | Nhắn Telegram: "Bật đèn phòng làm việc", "Đèn đang bật không?", "Hôm nay có ai về nhà chưa?" |
| **Chi tiết** | OpenClaw multi-channel — cùng personality, cùng memory, khác kênh giao tiếp |

---

## 7. Đối Tượng Người Dùng

### Phân khúc theo thứ tự ưu tiên

#### 1. Người đam mê công nghệ / Maker — Ưu tiên CAO

| | |
|---|---|
| **Đặc điểm** | Thích tự tay build, tùy biến, đóng góp cho open source |
| **Nhu cầu** | Platform mở, API rõ ràng, tài liệu tốt, community sôi nổi |
| **Giá trị AI Lamp mang lại** | Nền tảng mở để thử nghiệm AI + robotics + IoT. Tạo skills, personality, animations mới. |
| **Kênh tiếp cận** | GitHub, Hacker News, Reddit r/homeautomation, YouTube tech channels |
| **Rủi ro** | Kỳ vọng cao về chất lượng code và documentation |

#### 2. Người làm việc từ xa / Home office — Ưu tiên CAO

| | |
|---|---|
| **Đặc điểm** | Ngồi bàn làm việc 8+ giờ/ngày, cần ánh sáng tốt và trợ lý |
| **Nhu cầu** | Focus mode, circadian lighting, nhắc nhở nghỉ ngơi, trợ lý quản lý lịch |
| **Giá trị AI Lamp mang lại** | Bạn đồng hành suốt ngày làm việc — hiểu khi nào cần im lặng, khi nào cần nhắc nhở |
| **Kênh tiếp cận** | Product Hunt, remote work communities, LinkedIn |
| **Rủi ro** | Nhạy cảm với camera/mic tại nơi làm việc — cần privacy controls rõ ràng |

#### 3. Sinh viên — Ưu tiên TRUNG BÌNH

| | |
|---|---|
| **Đặc điểm** | Học tập nhiều giờ, ngân sách hạn chế, thích công nghệ mới |
| **Nhu cầu** | Đèn học tập tốt, nhắc nhở học bài, trợ lý dịch thuật/tóm tắt |
| **Giá trị AI Lamp mang lại** | Bạn học tập — nhắc nghỉ mắt, pomodoro timer, giải đáp thắc mắc |
| **Kênh tiếp cận** | TikTok, Instagram, university tech clubs |
| **Rủi ro** | Giá thành có thể cao cho phân khúc này |

#### 4. Người quan tâm sức khỏe — Ưu tiên TRUNG BÌNH

| | |
|---|---|
| **Đặc điểm** | Quan tâm đến giấc ngủ, mắt, sức khỏe tinh thần |
| **Nhu cầu** | Circadian lighting, giảm blue light, nhắc nghỉ, ambient relaxation |
| **Giá trị AI Lamp mang lại** | Đèn thông minh nhất cho sức khỏe — tự điều chỉnh theo sinh học |
| **Kênh tiếp cận** | Wellness blogs, health-tech communities |
| **Rủi ro** | Cần bằng chứng khoa học / testimonials để thuyết phục |

---

## 8. Yêu Cầu Phi Chức Năng

### Hiệu năng

| Yêu cầu | Chỉ số | Ghi chú |
|---|---|---|
| Độ trễ giọng nói → hành động | < 1 giây | Từ lúc người dùng nói xong đến lúc đèn phản ứng |
| Thời gian khởi động | < 30 giây | Từ cắm điện đến sẵn sàng nhận lệnh |
| LED response time | < 100ms | Thay đổi LED phải tức thì |
| Servo response time | < 200ms | Bắt đầu di chuyển sau khi nhận lệnh |

### Khả dụng

| Yêu cầu | Chi tiết |
|---|---|
| Hoạt động | 24/7 liên tục |
| Offline mode | Điều khiển cơ bản (bật/tắt, màu, servo) không cần internet |
| Graceful degradation | Mất internet → vẫn là đèn bàn tốt. OpenClaw chết → tầng hệ thống vẫn chạy. |
| Auto-recovery | Tự khởi động lại nếu crash. OTA update không gây downtime kéo dài. |

### Ngôn ngữ

| Yêu cầu | Chi tiết |
|---|---|
| Ngôn ngữ hỗ trợ | Tiếng Anh, Tiếng Việt |
| Voice recognition | Nhận diện tốt cả 2 ngôn ngữ, có thể mix |
| TTS | Giọng tự nhiên cho cả 2 ngôn ngữ |
| UI/Docs | Tài liệu song ngữ |

### Bảo mật & Quyền riêng tư

| Yêu cầu | Chi tiết |
|---|---|
| Camera/Mic | Opt-in, có indicator rõ ràng khi đang hoạt động |
| Dữ liệu | Xử lý local khi có thể, mã hóa khi truyền cloud |
| API | Chỉ listen trên 127.0.0.1, không expose ra mạng ngoài |
| Privacy mode | Một lệnh/cử chỉ để tắt hoàn toàn camera + mic |

### Phần cứng

| Yêu cầu | Chi tiết |
|---|---|
| Nhiệt độ hoạt động | Raspberry Pi không quá 80°C dưới tải AI |
| Tiêu thụ điện | < 25W toàn bộ hệ thống |
| Tiếng ồn | Servo phải êm, không nghe thấy ở khoảng cách > 1m |
| Độ bền servo | > 100,000 chu kỳ |

---

## 9. Câu Hỏi Mở

Những vấn đề cần quyết định trong quá trình phát triển:

### Phần cứng

| # | Câu hỏi | Tác động | Trạng thái |
|---|---|---|---|
| H-01 | Raspberry Pi 4 có đủ hiệu năng cho vision + AI local không? Cần Pi 5? | Hiệu năng, giá thành | Cần benchmark |
| H-02 | 64 LED (8x5) có đủ sáng làm đèn bàn chính không? Cần LED trắng bổ sung? | Chất lượng ánh sáng | Cần test thực tế |
| H-03 | Feetech servo có đủ êm không? Cần upgrade servo? | Trải nghiệm người dùng | Cần test thực tế |
| H-04 | Thiết kế vỏ ngoài — in 3D? Gia công CNC? Injection mold? | Giá thành, thẩm mỹ, quy mô sản xuất | Chưa quyết định |

### Phần mềm

| # | Câu hỏi | Tác động | Trạng thái |
|---|---|---|---|
| S-01 | OpenClaw chạy trên Pi hay cần server riêng? | Kiến trúc, độ trễ, chi phí | Cần xác định |
| S-02 | LLM nào làm default? Self-hosted model hay cloud? | Chi phí vận hành, độ trễ, privacy | Cần benchmark |
| S-03 | Wake word engine nào? Porcupine? OpenWakeWord? Custom? | Trải nghiệm, licensing | Cần đánh giá |
| S-04 | Giao thức giao tiếp giữa Lumi server và LeLamp runtime? REST? gRPC? Unix socket? | Hiệu năng, complexity | Cần quyết định |

### Sản phẩm

| # | Câu hỏi | Tác động | Trạng thái |
|---|---|---|---|
| P-01 | Bán kit DIY hay sản phẩm hoàn chỉnh? Hay cả hai? | Go-to-market, giá, target user | Cần chiến lược |
| P-02 | Giá mục tiêu bao nhiêu? $99 kit? $199 assembled? $299 premium? | Thị trường, margin | Cần nghiên cứu |
| P-03 | Tên sản phẩm chính thức? "AI Lamp" là tên tạm. | Branding, SEO, trademark | Chưa quyết định |
| P-04 | Privacy sunglasses như Ongo? Hay cách khác để handle camera privacy? | UX, trust | Cần thiết kế |
| P-05 | Cần mobile app không? Hay chỉ voice + Telegram? | Scope, development cost | Cần quyết định |

---

> **Tài liệu này là nền tảng định nghĩa sản phẩm AI Lamp.**
> Mọi quyết định thiết kế, phát triển, và ưu tiên đều nên tham chiếu về đây.
>
> Cập nhật lần cuối: 24/03/2026
