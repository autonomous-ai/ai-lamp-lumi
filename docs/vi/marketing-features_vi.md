# AI Lamp — Các Tính Năng Đề Xuất Từ Marketing

> Được đề xuất bởi đội marketing. Các tính năng này **chưa có trong product vision** và cần team review trước khi đưa vào triển khai.

Trạng thái: **Đang Xem Xét** — chưa lên lịch, chưa implement.

---

## UC-M1: Nhận Diện Cảm Xúc & Phát Hiện Sức Khỏe Từ Khuôn Mặt [Đề Xuất]

**Actor**: Hệ thống (tự động, camera)
**Mô tả**: Camera liên tục phân tích biểu cảm khuôn mặt của người dùng để phát hiện trạng thái cảm xúc, mức độ stress và mệt mỏi — Lumi phản ứng chủ động để hỗ trợ sức khỏe người dùng.

**Ví dụ**:
- Người dùng trông căng thẳng/stress → Lumi giảm độ sáng, chuyển sang màu ấm, nhẹ nhàng gợi ý nghỉ ngơi
- Người dùng trông buồn ngủ/mệt mỏi → Lumi tăng độ sáng, phát âm thanh kích thích, gợi ý đi bộ ngắn
- Người dùng trông tập trung và bình tĩnh → Lumi giữ nguyên môi trường, tắt tất cả thông báo

**Điểm khác biệt so với hiện tại**:
- "Stress" detection hiện tại (bảng Pillar 4) dùng **mic (giọng nói)** — UC này dùng **camera (biểu cảm khuôn mặt)**
- Bổ sung cho voice tone detection; camera phát hiện stress ngay cả khi người dùng đang im lặng

**Phù hợp kiến trúc**:
- Thêm emotion classifier model lên trên InsightFace face detection hiện có tại `lelamp/service/sensing/perceptions/facerecognizer.py`
- Phát sensing event mới `expression.detected` → Lumi → OpenClaw phản ứng qua SOUL.md
- Cần ONNX emotion model nhẹ (~150MB, ~50ms/frame trên Pi 4)

**Câu hỏi mở**:
- [ ] Dùng model nào? (MobileNet-based FER, EfficientNet-lite, hay cloud vision API)
- [ ] Ngưỡng độ chính xác trước khi trigger — tránh false positive (người dùng chỉ đang nheo mắt nhìn màn hình)
- [ ] Privacy: dữ liệu biểu cảm khuôn mặt phải ở hoàn toàn on-device, không upload
- [ ] Kết hợp với voice-tone stress detection như thế nào? Cần logic fusion?

**Tiêu chí nghiệm thu**:
- Phát hiện tối thiểu 3 trạng thái: bình thường, căng thẳng/stress, mệt mỏi/buồn ngủ
- Cooldown: tối thiểu 60 giây giữa các event expression liên tiếp
- Inference chạy trên Pi 4 mà không làm chậm sensing loop xuống dưới chu kỳ 2 giây
- Người dùng có thể tắt expression detection độc lập với các tính năng camera khác

---

## UC-M2: Nhắc Nhở Sức Khỏe Chủ Động [Đề Xuất]

**Actor**: Hệ thống (tự động, thời gian + camera)
**Mô tả**: Lumi tự động theo dõi thời gian người dùng ngồi làm việc và chủ động nhắc nhở đứng dậy, uống nước, hoặc nghỉ ngơi — không cần người dùng yêu cầu.

**Ví dụ**:
- Người dùng ngồi liên tục 45 phút → Lumi nhẹ nhàng nói "Bạn đã ngồi một lúc rồi — muốn đứng dậy vươn vai không?"
- Người dùng làm việc 2 tiếng không uống nước → "Đừng quên uống nước nhé"
- Người dùng làm việc quá nửa đêm → Giảm ánh sáng xanh + gợi ý nghỉ ngơi nhẹ nhàng

**Điểm khác biệt so với hiện tại**:
- UC-06 có "Remind me to take a break in 25 minutes" — người dùng **chủ động yêu cầu** Pomodoro
- UC này **hoàn toàn chủ động** — Lumi tự theo dõi thời gian ngồi và khởi xướng mà không cần được nhờ

**Phù hợp kiến trúc**:
- Theo dõi timestamp `presence.enter`; tính thời gian ngồi liên tục trong sensing loop
- Phát event `wellness.sitting_too_long` sau ngưỡng cấu hình được (mặc định: 45 phút)
- Dùng presence detection hiện có (FaceRecognizer) — không cần model mới
- OpenClaw xử lý giọng điệu/thời điểm nhắc dựa trên lịch sử và tính cách người dùng

> **Ghi chú triển khai (2026-04)**: UC này đã được cover bằng cách tiếp cận AI-driven linh hoạt hơn. Thay vì dùng timer cố định `wellness.sitting_too_long` từ sensing loop, Wellbeing SKILL dùng OpenClaw cron jobs được kích hoạt khi `motion.activity` phát hiện hành vi sedentary (using computer, writing, reading, v.v.). Break cron chỉ được tạo khi xác nhận người dùng đang ngồi làm việc — không phải chỉ vì có mặt trong khung hình. Agent có đầy đủ conversation context, lịch sử per-person, và personality awareness, giúp nhắc nhở tự nhiên và thích ứng hơn so với timer cố định. Xem `lumi/resources/openclaw-skills/wellbeing/SKILL.md`.

**Câu hỏi mở**:
- [ ] Khoảng thời gian nhắc nhở mặc định là bao nhiêu? (45 phút? 60 phút? Người dùng tùy chỉnh?)
- [ ] Làm sao Lumi phân biệt "đang ngồi làm việc" với "vừa xuất hiện trong frame"?
- [ ] Nhắc uống nước theo thời gian hay cần sensor riêng?
- [ ] Chế độ "Do Not Disturb" có tắt wellness reminders không?

**Tiêu chí nghiệm thu**:
- Tính thời gian ngồi từ event `presence.enter` đầu tiên; reset khi `presence.leave` > 5 phút
- Nhắc nhở theo khoảng thời gian cấu hình được (mặc định: 45 phút, 90 phút, 150 phút)
- Giọng điệu nhắc nhở thích nghi theo ngữ cảnh (nhẹ nhàng hơn vào ban đêm, năng động hơn buổi sáng)
- Người dùng có thể cấu hình khoảng thời gian hoặc tắt hoàn toàn qua giọng nói hoặc web UI

---

## UC-M3: Gợi Ý Nhạc Chủ Động Theo Tâm Trạng [Đề Xuất]

**Actor**: Hệ thống (tự động, ngữ cảnh hội thoại + sensing)
**Mô tả**: Lumi chủ động gợi ý hoặc phát nhạc dựa trên tâm trạng được phát hiện, thời gian trong ngày, và ngữ cảnh hội thoại đang diễn ra — mà không cần người dùng yêu cầu.

**Ví dụ**:
- Người dùng nghe có vẻ stress (giọng nói) → Lumi nhẹ nhàng phát nhạc ambient/lo-fi mà không cần được hỏi
- Phát hiện tập trung sâu (im lặng liên tục, không chuyển động) → Lumi hỏi "Muốn nghe nhạc nền không?"
- Phát hiện buổi sáng → Lumi phát playlist năng động
- Người dùng nói đang buồn trong hội thoại → Lumi gợi ý nhạc an ủi

**Điểm khác biệt so với hiện tại**:
- Music playback (SKILL.md + music_service.py) đã **hoàn chỉnh và hoạt động tốt**
- Hành vi hiện tại: **chỉ reactive** — người dùng phải yêu cầu "phát nhạc cho tôi"
- UC này thêm **lớp trigger chủ động** — Lumi tự quyết định gợi ý/phát mà không cần được nhờ

**Trạng thái implement** (một phần):
- ✅ **Gợi ý từ lịch sử nghe** — Music SKILL.md đã cập nhật section "Music Suggestion (Proactive)". Query `hw_audio` events từ flow log API (`GET /api/openclaw/flow-events`) để build listening history. Gợi ý 1–2 bài qua TTS mà không auto-play; chỉ play sau khi user xác nhận.
- ⬜ **Gợi ý từ sensing** — Proactive trigger từ stress/focus/morning context chưa wire (cần sensing event → suggestion pipeline)

**Phù hợp kiến trúc**:
- Effort thấp nhất trong 4 features đề xuất — không cần model hardware mới
- Music SKILL.md đã cập nhật suggestion workflow, bash recipes query flow logs, và suggestion rules
- Sensing events đã có sẵn: `sound.voice_tone` (stress), `sound.silence` (tập trung), `time.schedule` (sáng/tối)
- OpenClaw map: stress → ambient/lo-fi, tập trung → instrumental, buổi sáng → upbeat

**Câu hỏi mở**:
- [x] Sở thích nhạc của người dùng: Lumi học theo thời gian như thế nào? → **Đã giải quyết: query `hw_audio` flow log history**
- [x] Lumi có nên hỏi trước hay phát thẳng? → **Luôn gợi ý trước, chỉ play sau khi user xác nhận**
- [ ] Làm sao tránh làm phiền — nhạc cắt ngang cuộc gọi điện thoại hay video meeting?
- [ ] Tích hợp với UC-16 (Screen Awareness) để phát hiện Spotify/YouTube đang chạy → không gợi ý

**Tiêu chí nghiệm thu**:
- Trigger nhạc chủ động khi: phát hiện stress, tập trung liên tục (>15 phút im lặng), lịch buổi sáng
- Luôn hỏi trước khi phát (lần đầu) — "phát thẳng" chỉ sau khi người dùng xác nhận sở thích
- Tôn trọng chế độ video call (UC-12) — không phát nhạc trong cuộc gọi đang diễn ra
- Người dùng có thể nói "đừng gợi ý nhạc nữa" và Lumi ghi nhớ qua long-term memory của OpenClaw

---

## UC-M4: Nhận Thức Thời Gian Nhìn Màn Hình & Hỗ Trợ Qua Cử Chỉ [Đề Xuất]

**Actor**: Hệ thống (tự động, camera)
**Mô tả**: Camera theo dõi thời gian người dùng nhìn chằm chằm vào màn hình mà không nhìn đi chỗ khác, và chủ động gợi ý chăm sóc mắt. Ngoài ra, cử chỉ tay có thể kích hoạt các hành động hỗ trợ.

**Sub-feature A — Theo Dõi Thời Gian Nhìn Màn Hình / Chăm Sóc Mắt**:
- Camera phát hiện hướng nhìn của người dùng (liên tục nhìn vào màn hình)
- Sau thời gian cấu hình được (ví dụ: 20 phút) không nhìn đi chỗ khác → Lumi gợi ý quy tắc 20-20-20 ("Nhìn vật cách 6 mét trong 20 giây")
- Theo dõi sự kiện "nhìn đi chỗ khác" để reset bộ đếm thời gian

**Sub-feature B — Hỗ Trợ Qua Cử Chỉ Sức Khỏe**:
- Người dùng liếc nhìn Lumi trong lúc trông có vẻ căng thẳng/quá tải → Lumi chủ động hỏi thăm
- Người dùng dụi mắt (cử chỉ mệt mỏi) → Lumi giảm độ sáng và gợi ý nghỉ ngơi
- Lưu ý: khác với UC-10 (cử chỉ điều khiển đèn) — UC này hướng đến **chăm sóc sức khỏe**, không phải điều khiển

**Điểm khác biệt so với hiện tại**:
- UC-10 là cử chỉ điều khiển đèn (vẫy tay = bật/tắt, ngón cái lên = chuyển scene) — đã định nghĩa nhưng chưa implement
- UC này là **cử chỉ sức khỏe** (dụi mắt, nhìn vào Lumi) → Lumi hỗ trợ
- UC-16 theo dõi màn hình qua desktop agent — UC này dùng **chỉ camera**, không cần desktop agent

**Phù hợp kiến trúc**:
- Sub-feature A: Theo dõi face-present + thời gian hướng nhìn. Gaze estimation là bổ sung phức tạp vừa cho FaceRecognizer
- Sub-feature B: Phức tạp cao — cần gesture/pose model (MediaPipe Hand Lite hoặc tương đương), tác động ~300-500MB RAM
- Khả năng Pi 4: Sub-feature A khả thi; Sub-feature B cần benchmark trước khi cam kết

**Câu hỏi mở**:
- [ ] Sub-feature A: Phát hiện hướng nhìn có đủ chính xác không khi không có eye-tracking hardware chuyên dụng?
- [ ] Sub-feature B: MediaPipe trên Pi 4 — cần benchmark. Có thể cần Pi 5 hoặc USB accelerator (Coral)
- [ ] Tích hợp với UC-10 (cử chỉ điều khiển đèn) như thế nào? Cùng model, phân loại intent khác nhau?
- [ ] Có nên tách Sub-feature A và B thành UC riêng do độ phức tạp khác nhau?

**Tiêu chí nghiệm thu (Sub-feature A)**:
- Bộ đếm thời gian nhìn màn hình kích hoạt sau 20 phút face-present liên tục không có chuyển động đầu đáng kể
- Nhắc nhở theo quy tắc 20-20-20
- Bộ đếm reset khi người dùng nhìn đi chỗ khác (xoay đầu > 30 độ) trong > 5 giây
- Người dùng có thể cấu hình ngưỡng hoặc tắt

**Tiêu chí nghiệm thu (Sub-feature B)**:
- Chờ kết quả benchmark Pi 4 — xác định sau khi tính khả thi được xác nhận
- Nếu khả thi: tối thiểu 2 cử chỉ sức khỏe được nhận diện với độ chính xác > 80%

---

## Tóm Tắt & Độ Ưu Tiên Đề Xuất

| UC | Tính năng | Effort | Rủi ro Pi 4 | Độ ưu tiên đề xuất |
|---|---|---|---|---|
| UC-M3 | Gợi ý nhạc chủ động | Thấp (SKILL.md + SOUL.md) | Không có | **P1 — một phần (gợi ý từ history done)** |
| UC-M2 | Nhắc nhở sức khỏe chủ động | Thấp (logic sensing loop) | Không có | **P1 — làm trước** |
| UC-M1 | Nhận diện cảm xúc khuôn mặt | Trung bình (ONNX model mới) | Thấp | P2 |
| UC-M4a | Thời gian nhìn màn hình / chăm sóc mắt | Trung bình (gaze estimation) | Trung bình | P2 |
| UC-M4b | Cử chỉ sức khỏe | Cao (MediaPipe, cần benchmark) | Cao | P3 — benchmark trước |

---

*Đề xuất bởi đội marketing ngày 06-04-2026. Cần product owner phê duyệt trước khi lên lịch triển khai.*
