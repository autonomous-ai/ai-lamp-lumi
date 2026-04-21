# AI Lamp — Các Tính Năng Đề Xuất Từ Marketing

> Được đề xuất bởi đội marketing. Trạng thái cập nhật 21-04-2026 dựa trên codebase hiện tại.

---

## UC-M1: Nhận Diện Cảm Xúc & Phát Hiện Sức Khỏe Từ Khuôn Mặt [DONE]

**Trạng thái: Đã triển khai** (2026-04)

**Actor**: Hệ thống (tự động, camera)
**Mô tả**: Camera phân tích biểu cảm khuôn mặt để phát hiện trạng thái cảm xúc — Lumi phản ứng chủ động hỗ trợ sức khỏe người dùng.

**Triển khai**:
- Emotion classifier chạy qua **dlbackend WebSocket** (remote inference server), không phải on-device ONNX. LeLamp gửi camera frames, nhận emotion predictions.
- `lelamp/service/sensing/perceptions/emotion.py` — `RemoteEmotionChecker` kết nối dlbackend, fire event `emotion.detected` (Angry, Disgust, Fear, Happy, Sad, Surprise, Neutral).
- Lumi `user-emotion-detection/SKILL.md` map cảm xúc khuôn mặt → mood signal qua `POST /api/mood/log`.
- Lumi `mood/SKILL.md` fusion signals (camera emotion, conversation, voice tone) thành mood decisions.
- Mood decisions trigger downstream: `music-suggestion` (nhạc chủ động), `wellbeing` (nhắc uống nước/nghỉ), `emotion` (biểu cảm đèn).

**Câu hỏi đã giải quyết**:
- [x] Model nào? → Remote dlbackend (không ONNX on-device). Offload inference, không ảnh hưởng Pi 4.
- [x] Ngưỡng accuracy → Configurable `EMOTION_CONFIDENCE_THRESHOLD` trong LeLamp config.
- [x] Privacy → Frames chỉ gửi tới self-hosted dlbackend, không qua cloud bên thứ ba.
- [x] Kết hợp voice-tone → Cả hai feed vào Mood skill fusion logic.

---

## UC-M2: Nhắc Nhở Sức Khỏe Chủ Động [DONE]

**Trạng thái: Đã triển khai** (2026-04)

**Actor**: Hệ thống (tự động, sensing-driven)
**Mô tả**: Lumi tự theo dõi hoạt động sedentary và chủ động nhắc đứng dậy, uống nước, nghỉ ngơi.

**Triển khai**:
- **Event-driven, không dùng timer cố định.** `wellbeing/SKILL.md` trigger mỗi event `motion.activity` (từ action recognition).
- Action recognition qua dlbackend phân loại: `using computer`, `writing`, `reading book`, `texting` (sedentary) vs `drink`, `break` (reset activities).
- Mỗi activity logged vào per-user JSONL timeline qua `POST /api/openclaw/wellbeing/log`.
- Per-user tracking: `current_user` từ sensing context tag, stranger dùng chung timeline `"unknown"`.

**Câu hỏi đã giải quyết**:
- [x] Khoảng thời gian nhắc → AI-driven thresholds tính từ activity log.
- [x] "Đang ngồi làm việc" vs "vừa xuất hiện" → Action recognition phân biệt sedentary labels.
- [x] Nhắc uống nước → Theo thời gian từ lần `drink` activity cuối.
- [x] DND mode → Agent personality tự điều chỉnh ngữ cảnh.

---

## UC-M3: Gợi Ý Nhạc Chủ Động Theo Tâm Trạng [DONE]

**Trạng thái: Đã triển khai** (2026-04)

**Actor**: Hệ thống (tự động, mood + sensing-driven)
**Mô tả**: Lumi chủ động gợi ý nhạc dựa trên tâm trạng, hoạt động sedentary, và lịch sử nghe.

**Triển khai**:
- `lumi/resources/openclaw-skills/music-suggestion/SKILL.md` — skill chủ động riêng (tách khỏi reactive `music/SKILL.md`).
- **Hai triggers**:
  1. **Mood-driven**: Sau khi `mood/SKILL.md` log mood decision (sad, stressed, tired, excited, happy, bored).
  2. **Sedentary-driven**: `motion.activity` với sedentary labels (using computer, writing, etc.).
- Checks trước khi gợi ý: audio đang chạy? cooldown gợi ý gần đây (7 min)? mood decision cũ (>30 min)?
- Genre mapping: stressed → soft jazz, tired → calm piano, happy → upbeat pop, sedentary → lo-fi.
- Luôn gợi ý qua TTS trước, play sau khi user xác nhận.

**Câu hỏi đã giải quyết**:
- [x] Sở thích nhạc → Query `hw_audio` flow log + `/audio/history`.
- [x] Hỏi trước vs auto-play → Luôn gợi ý trước.
- [x] Sensing-triggered → Done: mood decisions + sedentary activity.
- [ ] Phone call / video meeting detection → Chưa (cần UC-12 hoặc screen awareness).

---

## UC-M4: Nhận Thức Thời Gian Nhìn Màn Hình & Hỗ Trợ Cử Chỉ [CHƯA LÀM]

**Trạng thái: Chưa triển khai** — cần models mới chưa có trong codebase.

**Sub-feature A — Theo Dõi Thời Gian Nhìn Màn Hình**:
- Cần gaze estimation model — chưa implement trong LeLamp sensing pipeline.

**Sub-feature B — Hỗ Trợ Cử Chỉ Sức Khỏe**:
- Cần gesture/pose model (MediaPipe Hand Lite) — chưa implement.
- Phức tạp cao, ~300-500MB RAM. Có thể cần Pi 5.

---

## Bonus: Nhận Diện Giọng Nói [DONE]

**Trạng thái: Đã triển khai** (2026-04)

**Mô tả**: Lumi nhận diện ai đang nói bằng voice embedding. Transcript có prefix `Tên:` (đã enroll) hoặc `Unknown:` (chưa enroll). Tự enroll qua voice intro hoặc Telegram voice note.

**Triển khai**:
- `lelamp/speaker_recognizer.py` + `lelamp/service/voice/speaker_recognizer/speaker_recognizer.py`
- `lumi/resources/openclaw-skills/speaker-recognizer/SKILL.md` — self-enrollment skill.
- Voice profiles lưu per-user cùng face data tại `/root/local/users/{name}/`.
- Telegram identity linked khi voice enrollment để DM targeting.

---

## Tóm Tắt

| UC | Tính Năng | Trạng Thái | Triển Khai |
|---|---|---|---|
| UC-M1 | Nhận diện cảm xúc khuôn mặt | **DONE** | dlbackend emotion WS + `user-emotion-detection` + `mood` skills |
| UC-M2 | Nhắc nhở sức khỏe chủ động | **DONE** | `wellbeing` skill, event-driven từ `motion.activity` |
| UC-M3 | Gợi ý nhạc chủ động | **DONE** | `music-suggestion` skill, mood + sedentary triggers |
| UC-M4a | Thời gian nhìn màn hình | **CHƯA LÀM** | Cần gaze estimation model |
| UC-M4b | Cử chỉ sức khỏe | **CHƯA LÀM** | Cần gesture model (MediaPipe) |
| Bonus | Nhận diện giọng nói | **DONE** | LeLamp voice embeddings + Lumi enrollment skill |

---

*Đề xuất bởi đội marketing 06-04-2026. Trạng thái cập nhật 21-04-2026.*
