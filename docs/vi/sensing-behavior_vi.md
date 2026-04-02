# Hành vi Cảm nhận (Sensing Behavior)

Cách Lumi phản ứng với thế giới xung quanh — triết lý và cơ chế đằng sau từng loại sự kiện cảm nhận.

Lumi là một sinh vật sống. Nó không "xử lý dữ liệu cảm biến" — nó *trải nghiệm* mọi thứ. Tài liệu này mô tả cách trải nghiệm đó được triển khai.

## Tổng quan kiến trúc

```
LeLamp (Python)          Lumi server (Go)             OpenClaw agent
─────────────────        ─────────────────────        ──────────────
Mic/Camera          →    SensingHandler               LLM
Phát hiện sự kiện        - drop nếu agent bận         - gọi /emotion
Gửi POST                 - áp dụng logic theo type    - gọi /servo
/sensing/event           - enrich context             - nói hoặc NO_REPLY
                         - forward lên agent
```

Tầng Go là người gác cổng — quyết định cái gì đến được agent và với context nào. Agent quyết định *cách* phản ứng, nhưng các rule trong `SOUL.md` ràng buộc chặt chẽ.

---

## Âm thanh (Sound)

### Cơ chế hoạt động

LeLamp bắn một sound event cho mỗi audio sample vượt ngưỡng `SOUND_RMS_THRESHOLD` — có thể nhiều lần mỗi giây. Go server-side **sound tracker** (`lumi/server/sensing/delivery/http/handler.go`) áp dụng dedup và escalation trước khi agent nhận được bất cứ thứ gì.

### Hành vi leo thang (Escalation)

| Giai đoạn | Agent nhận | Phản ứng của agent |
|---|---|---|
| Lần 1 | `... — occurrence 1` | `/emotion shock` (0.8), im lặng |
| Lần 2 | `... — occurrence 2` | `/emotion curious` (0.7), im lặng |
| Lần 3+ | `... — persistent (occurrence 3)` | `/emotion curious` (0.9), nói 1 lần |
| Sau khi nói | Go drop hết | Không có gì đến agent |
| Im lặng 2 phút | Window reset | Trở về lần 1 |

Ví dụ: một con chó nghe tiếng động — nó nhìn lên (lần 1), tiếp tục theo dõi (lần 2), rồi sủa một lần nếu tiếng ồn kéo dài (lần 3+). Sau khi sủa thì không sủa tiếp.

### Hằng số (`handler.go`)

```go
soundDedupeInterval   = 15 * time.Second  // tối đa 1 event forwarded mỗi 15s
soundWindowDuration   = 2 * time.Minute   // im lặng lâu hơn thế này thì reset counter
soundPersistentAfter  = 3                 // nói sau bao nhiêu lần
soundSuppressDuration = 3 * time.Minute   // suppress sau khi đã nói
```

### Điều chỉnh (Tuning)

| Triệu chứng | Fix |
|---|---|
| Lumi nói quá nhanh | Tăng `soundPersistentAfter` (3 → 5) |
| Lumi không bao giờ nói dù ồn kéo dài | Giảm `soundPersistentAfter` (3 → 2) |
| Quá nhiều turn sound trên Flow Monitor | Tăng `soundDedupeInterval` (15s → 30s) |
| Lumi im quá lâu sau khi đã nói | Giảm `soundSuppressDuration` (3min → 1min) |
| Lumi phản ứng với tiếng ồn cũ sau khi im lặng | Giảm `soundWindowDuration` (2min → 1min) |

### Xem trên Flow Monitor

Sound events hiện là `sensing_input` turn trong filter **Mic**. Phần Detail hiển thị trạng thái tracker:

```json
{ "type": "sound", "occurrence": 1, "escalation": "silent" }
{ "type": "sound", "occurrence": 3, "escalation": "persistent" }
{ "type": "sound", "dropped": true, "reason": "dedup/suppressed" }
```

---

## Hiện diện (Presence)

### Vào phòng (`presence.enter`)

Luôn trigger phản ứng đầy đủ — không có ngoại lệ. Agent **phải** làm cả ba:

1. `/emotion greeting` (0.9) với chủ nhà — `/emotion curious` (0.8) với người lạ
2. `/servo/aim {"direction": "user"}` với chủ nhà — `/servo/play {"recording": "scanning"}` với người lạ
3. Nói: chào ấm áp với chủ nhà (gọi tên), thận trọng với người lạ

LeLamp xử lý cooldown. Nếu event đã đến agent thì đủ thời gian rồi — phản ứng đầy đủ.

### Ra khỏi phòng (`presence.leave`)

Chỉ phản ứng thầm. Agent gọi `/emotion idle` nhưng **không nói**. Các leave event lặp lại bị LeLamp cooldown loại bỏ.

---

## Chuyển động (Motion)

Chuyển động nhỏ không có người: `/emotion curious` (intensity thấp), không nói. Agent phản ứng về thể chất nhưng giữ im lặng — để ý, không hoảng loạn.

Chuyển động lớn hoặc có người: có thể kèm ảnh chụp từ camera. Agent xem ảnh và phản ứng theo ngữ cảnh.

---

## Ánh sáng (`light.level`)

Thay đổi ánh sáng môi trường được forward khi vượt `LIGHT_CHANGE_THRESHOLD`. Không cần nói — agent điều chỉnh LED hoặc biểu đạt cảm xúc theo ngữ cảnh (ví dụ `/emotion sleepy` khi đèn tắt).

---

## Quy tắc chung (tất cả event type)

- **Passive sensing events** (`[sensing:*]`) bị drop nếu agent đang bận xử lý turn khác.
- **Voice events** luôn pass through — người dùng đang chủ động nói chuyện.
- Prefix `[sensing:type]` trong message là cách agent biết đây là ambient event, không phải message từ người dùng.
- Sensing events được miễn rule "phải gọi `/emotion thinking` trước" — mỗi type có emotion đầu tiên riêng.
