# Đăng ký giọng nói (Speaker Enrollment) — Tài liệu kỹ thuật

**Trạng thái: ĐÃ TRIỂN KHAI** (2026-04)

## Tổng quan

Lumi nhận diện người nói qua **WeSpeaker ResNet34** (vector nhúng 256 chiều, ONNX Runtime). Khi không nhận ra người nói, LeLamp lưu audio và tuỳ điều kiện sẽ yêu cầu AI agent đăng ký giọng nói. Đăng ký chỉ áp dụng **tự phục vụ** — mỗi người tự đăng ký giọng nói của mình.

## Kiến trúc

```
┌─────────────────────────────────────────────────────────────────────┐
│  LeLamp (Python, port 5001)                                         │
│                                                                     │
│  VoiceService._stream_session()                                     │
│    ├─ STT chuyển giọng nói → văn bản                                │
│    ├─ _identify_and_decorate(transcript)                            │
│    │   ├─ audio_buffer → WAV bytes → base64                        │
│    │   ├─ POST /audio-recognizer/embed → dlbackend (RunPod)        │
│    │   │   └─ WeSpeaker ResNet34 ONNX → vector 256 chiều           │
│    │   ├─ Bình chọn theo từng chunk so với embedding đã đăng ký     │
│    │   ├─ Khớp ≥ 0.7 → "Speaker - Tên: transcript"                 │
│    │   └─ Không khớp → _format_unknown_speaker()                   │
│    │       ├─ _should_request_enroll() kiểm tra điều kiện           │
│    │       │   ├─ ≥ 25 từ trong transcript                          │
│    │       │   └─ ≥ 5 giây audio                                    │
│    │       ├─ ĐẠT → "Unknown Speaker: ... (audio save at <path>,   │
│    │       │          auto enroll ...)"                              │
│    │       └─ KHÔNG ĐẠT → "Unknown Speaker: ..." (không kèm yêu   │
│    │          cầu đăng ký)                                          │
│    └─ POST /api/sensing/event → Lumi (Go)                          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  Lumi (Go, port 5000)                                               │
│                                                                     │
│  Hai đường đi (cả hai gọi domain.AppendEnrollNudge):                │
│                                                                     │
│  1. Đường trực tiếp (handler.go)                                    │
│     └─ Agent rảnh → gửi thẳng tới OpenClaw                         │
│                                                                     │
│  2. Đường hàng đợi (service.go)                                     │
│     └─ Agent bận → xếp hàng → phát lại khi agent rảnh              │
│                                                                     │
│  AppendEnrollNudge(msg) — domain/voice.go:                          │
│    ├─ Kiểm tra: chứa "Unknown Speaker:" + "audio save at"          │
│    ├─ Cooldown: bỏ qua nếu < 5 phút kể từ lần nhắc trước          │
│    └─ Chèn: "[REQUIRED: Follow speaker-recognizer/SKILL.md ...]"   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  OpenClaw Agent                                                     │
│                                                                     │
│  speaker-recognizer/SKILL.md                                        │
│    ├─ Phát hiện tự giới thiệu ("I'm X", "tôi là X", "mình là X")  │
│    ├─ curl POST /speaker/enroll với wav_path + tên                  │
│    ├─ Hai lượt: hỏi "Bạn là ai?" → đăng ký với cả hai path        │
│    └─ Xác nhận: "Rất vui được biết bạn, Tên!"                      │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Chống spam — Ba lớp bảo vệ

Ba lớp ngăn agent hỏi "bạn là ai?" liên tục:

| Lớp | Vị trí | Điều kiện | Mục đích |
|-----|--------|-----------|----------|
| **Thời lượng audio** | LeLamp `voice_service.py` | `duration_s < SPEAKER_MIN_AUDIO_S` (0.8s) | Bỏ qua nhận diện hoàn toàn cho audio quá ngắn |
| **Yêu cầu đăng ký** | LeLamp `_should_request_enroll()` | `≥ 25 từ VÀ ≥ 5s audio` | Không kèm instruction đăng ký cho câu ngắn |
| **Cooldown nhắc nhở** | Lumi `domain/voice.go` | `5 phút kể từ lần nhắc trước` | Không chèn SKILL.md instruction quá 1 lần mỗi 5 phút |

## Model & Embedding

| Thuộc tính | Giá trị |
|------------|---------|
| Model | WeSpeaker ResNet34 (huấn luyện trên VoxCeleb) |
| Chiều embedding | 256 |
| Runtime | ONNX Runtime (CPU) trên dlbackend (RunPod) |
| Endpoint | `POST {DL_BACKEND_URL}/lelamp/api/dl/audio-recognizer/embed` |
| Xác thực | Header `X-API-Key` |
| Timeout | 15 giây |

### Thuật toán nhận diện

1. Audio → tiền xử lý (giảm nhiễu, VAD, lọc cao tần, chuẩn hoá RMS)
2. Trích xuất embedding theo từng chunk `[M, 256]`
3. Cosine similarity với tất cả embedding người nói đã đăng ký
4. Bình chọn theo chunk: mỗi chunk vote cho người khớp nhất
5. Người thắng = nhiều vote nhất (hoà thì so trung bình confidence)
6. `confidence ≥ 0.7` → khớp; ngược lại → không xác định

### Chất lượng đăng ký

1. Mỗi file WAV → embedding qua dlbackend
2. Lọc theo ngưỡng consistency `0.7` (cosine similarity giữa các mẫu)
3. Tổng hợp embedding còn lại qua trung bình có trọng số
4. Lưu vector chuẩn hoá L2 tại `/root/local/users/{tên}/voice/embedding.npy`

## Cấu hình

| Tham số | Mặc định | Biến môi trường | Mô tả |
|---------|----------|-----------------|-------|
| Ngưỡng khớp | 0.7 | `SPEAKER_MATCH_THRESHOLD` | Confidence tối thiểu để khớp |
| Ngưỡng consistency khi đăng ký | 0.7 | `SPEAKER_ENROLL_CONSISTENCY_THRESHOLD` | Cosine similarity tối thiểu giữa các mẫu |
| Timeout API | 15s | `SPEAKER_EMBEDDING_API_TIMEOUT_S` | Timeout HTTP cho embedding API |
| Audio tối thiểu cho nhận diện | 0.8s | `LELAMP_SPEAKER_MIN_AUDIO_S` | Bỏ qua nhận diện dưới ngưỡng này |
| Số từ tối thiểu cho nudge đăng ký | 25 | Hardcoded trong `_should_request_enroll()` | Cổng số từ transcript |
| Thời lượng tối thiểu cho nudge đăng ký | 5.0s | Hardcoded trong `_should_request_enroll()` | Cổng thời lượng audio |
| Cooldown nhắc nhở | 5 phút | Hardcoded trong `domain/voice.go` | Cooldown phía Lumi giữa các lần nhắc đăng ký |
| Bật/tắt nhận diện giọng nói | false | `LELAMP_SPEAKER_RECOGNITION_ENABLED` | Công tắc tổng |

## Lưu trữ

```
/root/local/users/{tên}/
  metadata.json                      # Danh tính chung (telegram, display_name)
  voice/
    embedding.npy                    # Vector chuẩn hoá L2 [256]
    metadata.json                    # num_samples, dim, timestamps
    sample_{origin}_{ts}_{uuid}.wav  # Các mẫu đăng ký (16kHz mono)

/tmp/lumi-unknown-voice/
  incoming_{ts}_{uuid}.wav           # Audio chưa nhận diện (tự dọn dẹp)
```

## API Endpoints (LeLamp, port 5001)

| Method | Path | Mô tả |
|--------|------|-------|
| `POST` | `/speaker/enroll` | Đăng ký giọng nói từ wav_paths + tên |
| `POST` | `/speaker/recognize` | Nhận diện người nói từ wav_path |
| `POST` | `/speaker/identity` | Liên kết Telegram với profile giọng nói |
| `POST` | `/speaker/remove` | Xoá profile giọng nói theo tên |
| `POST` | `/speaker/reset` | Xoá tất cả profile giọng nói |
| `GET`  | `/speaker/list` | Liệt kê người nói đã đăng ký |

### Hợp đồng lỗi (error contract)

`/speaker/enroll` phân biệt hai loại thất bại:

| HTTP | Khi nào | Hành vi skill |
|------|---------|---------------|
| `400` | Audio bị reject (quá ngắn, im lặng, VAD không tìm thấy speech, dlbackend trả 4xx) | Yêu cầu user thu lại / nói rõ hơn |
| `503` | Embedding service không reachable (network, 5xx, response malformed) | Báo user thử lại sau — disk không bị thay đổi gì |

`/speaker/recognize` **không bao giờ** trả 5xx khi embedding API chết — nó trả `200` với `{name: "unknown", error: "<lý do>"}` để skill tự xử graceful. Chỉ lỗi input (thiếu WAV, base64 sai) mới trả `400`.

## Vị trí code chính

| Thành phần | File | Hàm/Struct |
|------------|------|------------|
| STT → nhận diện người nói | `lelamp/service/voice/voice_service.py` | `_identify_and_decorate()` |
| Cổng đăng ký | `lelamp/service/voice/voice_service.py` | `_should_request_enroll()` |
| Định dạng message | `lelamp/service/voice/voice_service.py` | `_format_unknown_speaker()` |
| Bộ nhận diện giọng nói | `lelamp/service/voice/speaker_recognizer/speaker_recognizer.py` | `SpeakerRecognizer` |
| Chèn instruction + cooldown | `lumi/domain/voice.go` | `AppendEnrollNudge()` |
| Đường trực tiếp | `lumi/server/sensing/delivery/http/handler.go` | `PostEvent()` |
| Đường hàng đợi/phát lại | `lumi/internal/openclaw/service.go` | `drainPendingEvents()` |
| Skill agent | `lumi/resources/openclaw-skills/speaker-recognizer/SKILL.md` | — |
| Model embedding | `dlbackend/src/core/audio_recognition/audio_recognizer.py` | `WeSpeakerResNet34Recognizer` |
| Endpoint embedding | `dlbackend/src/protocols/htpp/audio_recognizer.py` | `embed_audio()` |
| Cấu hình | `lelamp/config.py` | Các hằng số `SPEAKER_*` |

## Ví dụ luồng message

### Câu ngắn (bị chặn)
```
User nói: "hey" (2 từ, 0.9s audio)
→ LeLamp: bỏ qua nhận diện (< SPEAKER_MIN_AUDIO_S)
→ Message: "hey" (không prefix, không instruction đăng ký)
```

### Câu trung bình (nhận diện nhưng không nudge đăng ký)
```
User nói: "bật đèn lên đi" (4 từ, 3s audio)
→ LeLamp: nhận diện → unknown, _should_request_enroll(4 từ, 3s) = false
→ Message: "Unknown Speaker: bật đèn lên đi"
→ Lumi: không có "audio save at" → AppendEnrollNudge giữ nguyên
→ Agent: phản hồi bình thường, không hỏi user là ai
```

### Câu dài (luồng đăng ký đầy đủ)
```
User nói: "Xin chào mình là Leo, mình vừa đi làm về..." (30 từ, 8s audio)
→ LeLamp: nhận diện → unknown, _should_request_enroll(30 từ, 8s) = true
→ Message: "Unknown Speaker: Xin chào mình là Leo... (audio save at /tmp/lumi-unknown-voice/incoming_xxx.wav, auto enroll...)"
→ Lumi: AppendEnrollNudge → cooldown OK → chèn "[REQUIRED: Follow speaker-recognizer/SKILL.md...]"
→ Agent: phát hiện "mình là Leo" → POST /speaker/enroll → "Rất vui được biết bạn, Leo!"
```

### Cooldown (bị chặn)
```
Cùng unknown speaker, 2 phút sau:
→ LeLamp: _should_request_enroll = true (đủ dài)
→ Message có "audio save at"
→ Lumi: AppendEnrollNudge → cooldown CHƯA hết (< 5 phút) → bỏ qua instruction
→ Agent: thấy "Unknown Speaker: ..." không có SKILL instruction → phản hồi bình thường
```
