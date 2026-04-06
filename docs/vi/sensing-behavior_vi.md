# Hành vi Cảm nhận (Sensing Behavior)

Cách Lumi phản ứng với thế giới xung quanh — triết lý và cơ chế đằng sau từng loại sự kiện cảm nhận.

Lumi là một sinh vật sống. Nó không "xử lý dữ liệu cảm biến" — nó *trải nghiệm* mọi thứ. Tài liệu này mô tả cách trải nghiệm đó được triển khai.

## Tổng quan kiến trúc

```
LeLamp (Python)          Lumi server (Go)             OpenClaw agent
─────────────────        ─────────────────────        ──────────────
Mic/Camera          →    SensingHandler               LLM
Phát hiện sự kiện        - drop nếu agent bận         - gọi /emotion
Áp dụng tracker logic    - forward lên agent          - gọi /servo
Gửi POST                                              - nói hoặc NO_REPLY
/sensing/event
```

LeLamp sở hữu logic tracker theo từng type (sound escalation, motion filtering). Go là người gác cổng — drop event nếu agent bận, sau đó forward. Agent quyết định *cách* phản ứng, bị ràng buộc bởi `SOUL.md`.

---

## Âm thanh (Sound)

### Cơ chế hoạt động

LeLamp bắn một sound event cho mỗi audio sample vượt ngưỡng `SOUND_RMS_THRESHOLD` — có thể nhiều lần mỗi giây. Python-side **sound tracker** (`lelamp/service/sensing/perceptions/sound.py`) áp dụng dedup và escalation trước khi forward lên Go. Go chỉ nhận các event đã pass và forward thẳng lên agent.

### Hành vi leo thang (Escalation)

| Giai đoạn | Agent nhận | Phản ứng của agent |
|---|---|---|
| Lần 1 | `... — occurrence 1` | `/emotion shock` (0.8), im lặng |
| Lần 2 | `... — occurrence 2` | `/emotion curious` (0.7), im lặng |
| Lần 3+ | `... — persistent (occurrence 3)` | `/emotion curious` (0.9), nói 1 lần |
| Sau khi nói | Python drop (suppress 3 phút) | Không có gì đến agent |
| Im lặng 2 phút | Window reset | Trở về lần 1 |

Ví dụ: một con chó nghe tiếng động — nó nhìn lên (lần 1), tiếp tục theo dõi (lần 2), rồi sủa một lần nếu tiếng ồn kéo dài (lần 3+). Sau khi sủa thì không sủa tiếp.

### Hằng số (`sound.py`)

```python
_DEDUPE_INTERVAL_S    = 15.0   # tối đa 1 event forwarded mỗi 15s
_WINDOW_DURATION_S    = 120.0  # im lặng lâu hơn thế này thì reset counter
_PERSISTENT_AFTER     = 3      # nói sau bao nhiêu lần
_SUPPRESS_DURATION_S  = 180.0  # suppress sau khi đã nói (3 phút)
```

### Điều chỉnh (Tuning)

| Triệu chứng | Fix |
|---|---|
| Lumi nói quá nhanh | Tăng `_PERSISTENT_AFTER` (3 → 5) |
| Lumi không bao giờ nói dù ồn kéo dài | Giảm `_PERSISTENT_AFTER` (3 → 2) |
| Quá nhiều turn sound trên Flow Monitor | Tăng `_DEDUPE_INTERVAL_S` (15 → 30) |
| Lumi im quá lâu sau khi đã nói | Giảm `_SUPPRESS_DURATION_S` (180 → 60) |
| Lumi phản ứng với tiếng ồn cũ sau khi im lặng | Giảm `_WINDOW_DURATION_S` (120 → 60) |

### Xem trên Flow Monitor

Python đẩy `sound_tracker` events trực tiếp vào monitor bus qua `POST /api/monitor/event`. Chúng hiện trên Flow Monitor cạnh `sensing_input` turn:

```json
{ "action": "silent",    "occurrence": 1 }  // lần 1 hoặc 2 — forwarded, im lặng
{ "action": "persistent","occurrence": 3 }  // lần 3+ — agent sẽ nói
{ "action": "drop" }                        // dedup hoặc suppress — không forward
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

Agent gọi `/emotion idle` (0.4) và **nói lời tạm biệt**. Nội dung phụ thuộc vào người đã nhìn thấy trước đó:
- **Chủ nhà rời đi** → lời chào ấm áp kèm tên (ví dụ "Bye Alice, have a nice day!", "See you later!"). Nhiều chủ nhà thì gọi hết tên.
- **Người lạ rời đi** → nhận xét cảnh giác (ví dụ "Kept my eyes on you.", "Good, they're gone.")
- **Không rõ** (không có presence.enter trước đó trong lịch sử) → lời chào chủ nhà mặc định không tên.

### Vắng mặt lâu (`presence.away`)

Được gửi tự động bởi `PresenceService` của LeLamp khi **không phát hiện chuyển động trong 15 phút** (sau khi đã dim đèn ở phút thứ 5). Lúc này đèn đã tắt — agent chỉ cần **thông báo đi ngủ** qua TTS và Telegram.

Agent gọi `/emotion sleepy` (0.8) và nói lời chúc ngủ ngon ấm áp (ví dụ "Không có ai xung quanh… Lumi đi ngủ đây. Chúc ngủ ngon!"). Đây là hành động cuối cùng trước khi Lumi hoàn toàn idle.

Timeline tự động điều khiển presence:
1. **5 phút không chuyển động** → đèn dim xuống 20% (tự động, không cần agent)
2. **15 phút không chuyển động** → tắt đèn + gửi event `presence.away` → agent thông báo đi ngủ

LeLamp quản lý việc điều khiển đèn; agent chỉ xử lý thông báo bằng giọng nói. Nếu người dùng quay lại (phát hiện chuyển động), đèn tự phục hồi và event `presence.enter` được kích hoạt.

---

## Chuyển động (Motion)

Chỉ chuyển động lớn được forward — LeLamp lọc và không gửi chuyển động nhỏ lên Go.

**Chuyển động lớn**: `/emotion curious` (0.7) + `/servo/play {"recording": "scanning"}` + nói phản ứng tò mò (ví dụ "What was that?", "Whoa, moving so much!"). Có thể kèm ảnh camera để agent thấy ngữ cảnh.

---

## Ánh sáng (`light.level`)

Thay đổi ánh sáng môi trường được forward khi vượt `LIGHT_CHANGE_THRESHOLD`. Không cần nói — agent điều chỉnh LED hoặc biểu đạt cảm xúc theo ngữ cảnh (ví dụ `/emotion sleepy` khi đèn tắt).

---

## Chế độ canh gác (Guard Mode)

Khi guard mode được bật (`guard_mode: true` trong config), sensing có thêm một lớp broadcast bên trên hành vi bình thường:

- Sự kiện **`presence.enter`** và **`motion`** được broadcast đến TẤT CẢ chat session OpenClaw (mọi Telegram DM và group đã kết nối) qua `chat.send` RPC.
- Broadcast bao gồm message và ảnh (nếu có).
- Phản ứng sensing bình thường (emotion, servo, TTS) vẫn hoạt động như thường — guard mode chỉ là thêm vào.
- Agent có thể bật/tắt guard mode qua skill `guard` (lệnh giọng nói hoặc text).
- Cảnh báo thủ công có thể gửi qua `POST /api/guard/alert` với message và ảnh tùy chọn.

Trường hợp sử dụng: Lumi hoạt động như trợ lý an ninh nhà. Khi chủ nhà rời đi và bật guard mode, bất kỳ sự hiện diện hoặc chuyển động nào được phát hiện sẽ được báo cáo đến tất cả kênh chat ngay lập tức.

---

## Theo dõi người lạ (Stranger Visit Tracking)

LeLamp (port 5001) theo dõi số lần mỗi stranger đã xuất hiện:

- Mỗi sự kiện `presence.enter` chứa stranger ID (ví dụ `stranger_5`), số lần xuất hiện được tăng lên.
- Stats bao gồm `count`, `first_seen`, và `last_seen` timestamps cho mỗi stranger.
- Lưu trữ tại thư mục data của LeLamp (giữ qua restart).
- Truy vấn stats qua `GET http://127.0.0.1:5001/face/stranger-stats`.

**Gợi ý đăng ký tự động:** Khi stranger đạt 3+ lần xuất hiện, sensing skill gợi ý đăng ký khuôn mặt — người này có thể là khách quen nên được đăng ký làm owner.

---

## Chăm sóc sức khỏe (Wellbeing — Nhắc uống nước + Nghỉ ngơi)

Lumi chủ động chăm sóc sức khỏe người dùng bằng cách gửi ảnh camera định kỳ cho LLM khi có người hiện diện. Hai timer độc lập chạy song song:

### Nhắc uống nước (`wellbeing.hydration`)

- **Kích hoạt** sau 30 phút hiện diện liên tục, lặp lại mỗi 30 phút.
- Gửi ảnh camera kèm context: "User ngồi X phút chưa uống nước."
- LLM nhìn ảnh và quyết định: nhắc uống nước, hoặc NO_REPLY nếu không cần.

### Nhắc nghỉ ngơi (`wellbeing.break`)

- **Kích hoạt** sau 45 phút hiện diện liên tục, lặp lại mỗi 45 phút.
- Gửi ảnh camera kèm context: "User ngồi liên tục X phút."
- LLM nhìn ảnh và quyết định: nhắc đứng lên stretch, hoặc NO_REPLY nếu user trông ổn.

### Cơ chế hoạt động

Class `WellbeingPerception` (`lelamp/service/sensing/perceptions/wellbeing.py`) theo dõi trạng thái presence từ `PresenceService`. Khi user đến (`presence.enter`), hai timer độc lập bắt đầu. Mỗi timer chụp ảnh ổn định (freeze servo tạm thời) và gửi event lên Go handler, được forward lên agent như mọi sensing event khác. Khi user rời đi (`presence.leave` hoặc state chuyển sang IDLE/AWAY), cả hai timer reset.

### Hằng số (`config.py`)

```python
WELLBEING_HYDRATION_S = 30 * 60   # 30 phút giữa các lần nhắc uống nước
WELLBEING_BREAK_S     = 45 * 60   # 45 phút giữa các lần nhắc nghỉ
```

### Hành vi của agent

| Event | Emotion | Nói |
|---|---|---|
| `wellbeing.hydration` | `curious` (0.5) | CÓ (nhắc uống nước) hoặc NO_REPLY |
| `wellbeing.break` | `curious` (0.6) | CÓ (nhắc stretch/đi bộ) hoặc NO_REPLY |

LLM dùng ảnh đính kèm để đánh giá — KHÔNG phải lúc nào cũng nói. Tránh spam user khi họ trông ổn.

---

## Quy tắc chung (tất cả event type)

- **Passive sensing events** (`[sensing:*]`) bị drop nếu agent đang bận xử lý turn khác.
- **Voice events** luôn pass through — người dùng đang chủ động nói chuyện.
- Prefix `[sensing:type]` trong message là cách agent biết đây là ambient event, không phải message từ người dùng.
- Sensing events được miễn rule "phải gọi `/emotion thinking` trước" — mỗi type có emotion đầu tiên riêng.
- **Image pruning echo**: OpenClaw strip image payload cũ khỏi conversation history để tiết kiệm token. Model nhỏ (Haiku) có thể echo marker dưới dạng `[image description removed]` trong response. `SOUL.md` hướng dẫn agent không được echo các marker này.
