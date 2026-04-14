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

Agent gọi `/emotion idle` (0.4) và trả lời **NO_REPLY** (im lặng — không TTS). Tránh vòng lặp ồn ào khi người ra vào liên tục. Agent vẫn xử lý event nội bộ để cancel wellbeing crons và ghi daily log.

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

Khi guard mode được bật (`guard_mode: true` trong config), Lumi trở thành **chó canh gác cảnh giác** — phản ứng mạnh mẽ với người lạ và broadcast alert lên Telegram.

### Luồng xử lý
1. Sự kiện `presence.enter` hoặc `motion` đến khi `guard_mode: true`.
2. Go handler gắn tag `[guard-active]` và đánh dấu runID là guard run (kèm snapshot path). Nếu `guard_instruction` có trong config, nó được thêm vào dưới dạng `[guard-instruction: ...]`.
3. Agent xử lý event — emotion **mạnh mẽ** (shock + curious), servo, TTS, cộng thêm custom instruction nếu có (vd: play nhạc, flash LED).

### Cảm xúc Guard Mode (dramatic)

Khi guard mode bật, stranger/motion events trigger cảm xúc **mạnh hơn nhiều** so với sensing thường:

| Guard event | HW markers | Voice |
|---|---|---|
| Stranger detected | `shock` (1.0) → `curious` (0.9) + servo shock | Hoảng sợ, giật mình, nghi ngờ |
| Motion (unknown) | `shock` (0.9) → `curious` (0.8) + servo scanning | Lo lắng, cảnh giác |
| Stranger left | `curious` (0.7) + scanning | Báo cáo đã rời đi, vẫn cảnh giác |
| Owner/friend về | `greeting` (0.9) + servo aim | Chào + kể lại chuyện gì xảy ra + hỏi tắt guard |

**Lời nói cũng phải đầy cảm xúc** — không phải báo cáo khô khan. Agent phải thể hiện sợ hãi, nghi ngờ, run rẩy thật sự.
4. Khi agent response trả về (SSE lifecycle end), Go SSE handler phát hiện guard run.
5. Text tự nhiên của agent + ảnh camera được gửi thẳng qua **Telegram Bot API** (`sendPhoto`) đến tất cả Telegram chat.
6. Delivery 100% đáng tin — bypass hoàn toàn OpenClaw agent.

### Custom guard instruction
Chủ nhà có thể đưa instruction tùy chỉnh khi bật guard mode (vd: "play tiếng rùn rợn khi có người lạ"). Instruction được lưu trong `guard_instruction` trong config và inject vào mỗi guard sensing event dưới dạng `[guard-instruction: ...]`. Agent sẽ thực hiện instruction này bằng các skill có sẵn (music, LED, v.v.).

### Tại sao approach này?
Sau khi thử 6 approaches khác nhau, hybrid này đáng tin nhất:
- **Agent viết message** → tự nhiên, có ngữ cảnh, có tính cách
- **Go side delivery** → Telegram Bot API trực tiếp, đảm bảo gửi, không rủi ro NO_REPLY
- **Agent thực hiện custom guard instruction** → chủ nhà có thể kết hợp guard mode với skill bất kỳ (music, LED, v.v.)

### Quá trình thử nghiệm (2026-04-07)
| # | Approach | Tại sao fail |
|---|----------|--------------|
| 1 | `BroadcastAlert` qua WS `chat.send` RPC | `chat.send` đi qua agent → 2/3 NO_REPLY |
| 2 | Agent-driven qua tag `[guard-active]` | Haiku bỏ qua SKILL instruction (chôn ở dòng 222) |
| 3 | Đưa instruction lên đầu SKILL.md | Haiku vẫn bỏ qua |
| 4 | Go-side template + `BroadcastAlert` | Agent nhận ra `sender: node-host` → ignore. Không có ảnh |
| 5 | Agent-driven + ép buộc trong SOUL.md | Tốt hơn nhưng không 100%. Lỗi token |
| 6 | **Hook agent response + Telegram Bot API** | ✅ Agent viết tự nhiên, Go gửi 100% |

> **Ghi chú:** `BroadcastAlert` (WS RPC) đã bị xóa. Tất cả broadcast giờ dùng `Broadcast()` gửi trực tiếp qua Telegram Bot API.

### Cảnh báo thủ công
Vẫn có thể gửi cảnh báo thủ công qua `POST /api/guard/alert` với message và ảnh tùy chọn. Giờ dùng `Broadcast()` (Bot API trực tiếp) thay vì `BroadcastAlert` cũ.

Trường hợp sử dụng: Lumi hoạt động như trợ lý an ninh nhà. Khi chủ nhà rời đi và bật guard mode, mọi sự hiện diện hoặc chuyển động được báo cáo đến Telegram với message có cảm xúc và nhận biết ngữ cảnh.

---

## Theo dõi người lạ (Stranger Visit Tracking)

LeLamp (port 5001) theo dõi số lần mỗi stranger đã xuất hiện:

- Mỗi sự kiện `presence.enter` chứa stranger ID (ví dụ `stranger_5`), số lần xuất hiện được tăng lên.
- Stats bao gồm `count`, `first_seen`, và `last_seen` timestamps cho mỗi stranger.
- Lưu trữ tại thư mục data của LeLamp (giữ qua restart).
- Truy vấn stats qua `GET http://127.0.0.1:5001/face/stranger-stats`.

**Gợi ý đăng ký tự động:** Khi stranger đạt 3+ lần xuất hiện, sensing skill gợi ý đăng ký khuôn mặt — người này có thể là khách quen nên được đăng ký làm owner.

---

## Chăm sóc sức khỏe (Wellbeing — Nhắc uống nước + Nghỉ ngơi, AI-Driven)

Lumi chủ động chăm sóc sức khỏe người dùng bằng cron jobs do AI agent tự quản lý qua OpenClaw. Thay vì timer cứng, agent tự quyết interval dựa trên khoa học và thói quen user.

### Cơ chế hoạt động

Agent duy trì **dữ liệu wellbeing cho từng người** tại `/root/local/users/{name}/`:

- **`wellbeing.md`** — tóm tắt thói quen tích lũy (ví dụ: "hay bỏ qua nhắc uống nước trước bữa trưa", "phản hồi tốt với nhắc nghỉ sau 15:00")
- **`wellbeing/YYYY-MM-DD.md`** — daily log, được ghi liên tục trong ngày khi `motion.activity` reset cron (ví dụ: `14:30 — drinking beer (hydration reset)`) và tóm tắt khi `presence.leave`

Agent đọc summary + daily log hôm nay khi `presence.enter` để nhớ nhanh và biết chuyện gì đã xảy ra trước đó (ví dụ user đi ra rồi quay lại). Daily log được cập nhật liên tục trong `motion.activity` và hoàn tất khi `presence.leave`.

Khi người quen đến (`presence.enter`), agent:

1. **Đọc notebook** (`wellbeing.md`) để nhớ lại những gì đã học.
2. **Đọc daily log hôm nay** (`wellbeing/YYYY-MM-DD.md`) để biết chuyện gì đã xảy ra — uống bao nhiêu lần, nghỉ mấy lần, v.v. Dùng để điều chỉnh interval.
3. **Quyết định interval và cách tiếp cận** dựa trên quan sát tích lũy, thời gian trong ngày, và trạng thái khi đến. Lần đầu dùng mặc định theo khoa học (~25 phút hydration, ~50 phút break), nhưng agent tự điều chỉnh qua các session.
4. **Dọn cron cũ** — xóa wellbeing crons còn sót từ session trước (phục hồi sau crash).
5. **Schedule 2 cron jobs** qua `cron.add` (kind: `every`), đặt tên theo user để tránh trùng:
   - `"Wellbeing: {name} hydration"` — mỗi 6 phút (360000ms), chụp ảnh camera, check presence, nhắc nếu phù hợp
   - `"Wellbeing: {name} break"` — mỗi 5 phút (300000ms), chụp ảnh camera, đánh giá tư thế/mệt mỏi, nhắc nếu phù hợp

> **Ghi chú:** Wellbeing giờ là skill riêng (`wellbeing/SKILL.md`). Sensing handler inject nudge message vào `presence.enter` events nhắc agent follow Wellbeing và Music skill.

### Quy tắc sessionTarget cho cron

OpenClaw cron có 2 combo hợp lệ — KHÔNG được trộn:

| sessionTarget | payload.kind | payload field | Use case |
|---|---|---|---|
| `main` | `systemEvent` | `text` | Cần conversation context (music, wellbeing) |
| `isolated` | `agentTurn` | `message` | Session mới mỗi lần fire |

`main` + `agentTurn` **bị reject** bởi OpenClaw. KHÔNG thêm field `delivery` — gây lỗi.

**Hạn chế quan trọng:** Payload `systemEvent` bị OpenClaw wrap thành "Handle this reminder internally. Do not relay it to the user unless explicitly requested." — khiến agent NO_REPLY. **Workaround:** Prefix payload text với `[MUST-SPEAK]` để force agent phải reply dù có wrapper. Tất cả wellbeing và music cron payload phải bắt đầu bằng `[MUST-SPEAK]`.

### Ưu tiên: Skills > Knowledge > History

AGENTS.md quy định thứ tự ưu tiên: **SKILL.md luôn override KNOWLEDGE.md và conversation history**. Điều này rất quan trọng vì agent tự tích lũy "kinh nghiệm" vào KNOWLEDGE.md qua heartbeat, và những ghi chú này có thể chứa rules sai xung đột với skills do developer duy trì. Nếu agent phát hiện xung đột, nó phải cập nhật KNOWLEDGE.md cho khớp với skill, không phải ngược lại.

Rule này được thêm sau khi phát hiện agent đã ghi sai rules về cron format vào KNOWLEDGE.md ("NEVER use systemEvent") và override hướng dẫn đúng trong Scheduling SKILL.

Khi rời đi (`presence.leave`), agent im lặng cancel cả 2 cron jobs, append tóm tắt vào daily log (`wellbeing/YYYY-MM-DD.md`), và cập nhật summary (`wellbeing.md`) nếu phát hiện pattern mới.

### Hành vi khi cron fire

Mỗi lần cron fire, agent:
1. Chụp ảnh camera (`GET http://127.0.0.1:5001/camera/snapshot`)
2. Check presence (`GET http://127.0.0.1:5001/presence`)
3. Nếu user đang ngồi và cần nhắc → một câu ngắn, đổi cách nói mỗi lần
4. Nếu user vắng mặt, đang uống nước, hoặc trông ổn → không nói
5. Luôn emit `[HW:/emotion:{...}]` marker
6. Nếu nói, thêm `[HW:/broadcast:{}]` — force TTS + gửi text lên Telegram để user thấy trên điện thoại

### Hành vi của agent

| Nhắc nhở | Emotion | Nói |
|---|---|---|
| Hydration cron | `caring` (0.5) | CÓ (nhắc uống nước) hoặc im lặng |
| Break cron | `caring` (0.6) | CÓ (nhắc stretch/đi bộ) hoặc im lặng |

Agent dùng ảnh camera để đánh giá — KHÔNG phải lúc nào cũng nói. Tránh spam user khi họ trông ổn.

### Gợi ý nhạc (AI-Driven)

Gợi ý nhạc **không còn** được kích hoạt bởi timer cứng. Thay vào đó, AI agent **tự schedule** music check qua OpenClaw cron jobs và **tự học** thói quen user theo thời gian:

- **Tự schedule:** Khi nhận `presence.enter` đầu tiên trong ngày, AI tạo cron job (mặc định: mỗi 7 phút / 420000ms, `sessionTarget: "main"`, `payload.kind: "systemEvent"`). AI tự điều chỉnh interval dựa trên phản hồi của user.
- **Quyết định dựa trên dữ liệu:** Trước khi gợi ý, AI query:
  - `GET /presence` — user có đang ở đó không?
  - `GET /camera/snapshot` — đánh giá mood bằng hình ảnh
  - `GET /api/openclaw/mood-history` — pattern hiện diện, kết quả gợi ý trước đó
  - `GET /audio/history` — lịch sử nghe nhạc (genre ưa thích, thời lượng, mức độ hài lòng)
- **Vòng lặp học:** AI so sánh thời điểm gợi ý với `music.play` events trong mood history. Gợi ý được chấp nhận → củng cố timing/genre; bị từ chối → điều chỉnh schedule.
- **Cá nhân hóa:** Theo thời gian, AI học được khi nào user thích nghe nhạc, thể loại nào, nghe bao lâu — và điều chỉnh gợi ý cho phù hợp.

**Dữ liệu AI sử dụng để học thói quen:**

| Câu hỏi | Nguồn dữ liệu |
|----------|----------------|
| User ngồi vào bàn mấy giờ? | `presence.enter` events → field `hour` |
| Ngồi bao lâu thì muốn nghe nhạc? | Khoảng cách giữa `presence.enter` và `music.play` |
| Nghe thể loại gì? | `audio/history` → fields `query`, `title` |
| Nghe bao lâu thì tắt? | `audio/history` → field `duration_s` |
| Thời điểm nào thích nghe nhạc nhất? | `music.play` events → field `hour` |

Xem skill Music (`resources/openclaw-skills/music/SKILL.md`) để biết chi tiết implementation.

### Chăm sóc chủ động (piggyback trên sensing events)

Ngoài nhắc nhở theo lịch, agent được khuyến khích **chú ý** khi nhận bất kỳ event nào có user visible (presence.enter, motion.activity). Dựa vào giờ, thời gian ngồi, và hình ảnh → agent có thể chủ động nhắc ăn, nghỉ, hoặc hỏi thăm. Một câu ngắn, chỉ khi tự nhiên. Không bắt buộc nhưng khuyến khích.

Ví dụ: "Ăn sáng chưa?" khi presence.enter sáng sớm, "Trưa rồi, ăn gì chưa?" khi motion.activity lúc 12:20, "Khuya rồi đó..." khi motion.activity khuya.

### Broadcast marker (`[HW:/broadcast:{}]`)

HW marker đặc biệt — force text agent nói cũng được gửi lên tất cả Telegram channels. Dùng cho wellbeing crons, music suggestions, và bất kỳ cron turn nào cần user thấy trên điện thoại. Cũng force TTS cho non-voice turns. Hoạt động giống guard mode alerts.

### Mood history per-user

Mood history lưu per-user tại `/root/local/users/{name}/mood/YYYY-MM-DD.jsonl` (30 ngày retention). Hệ thống tracking ai đang ngồi qua `presence.enter` (face recognition) và log mood events vào thư mục user đó. API mood history hỗ trợ `?user=` parameter (mặc định: user hiện tại):

```bash
GET /api/openclaw/mood-history?user=gray&date=2026-04-09&last=100
```

### Nhận diện cross-channel

Agent liên kết tên face recognition với Telegram username bằng cách quan sát timing và context (ví dụ: "gray" đang ngồi và "@GrayDev" nhắn Telegram cùng lúc). Mapping được lưu vào USER.md (cho owner) hoặc notes trong folder user. Agent hỏi xác nhận nếu chưa chắc.

---

## Phân tích Motion Activity (khi đang có mặt)

Khi user đang ở trạng thái PRESENT và camera phát hiện chuyển động, hệ thống gửi event `motion.activity` thay vì `motion`. Hệ thống gửi tên action đã detect (không kèm ảnh — tên action đủ để agent suy luận).

### Cách hoạt động

`MotionPerception` buffer snapshots và action names, flush theo interval (`MOTION_FLUSH_S`). Khi flush, check `PresenceService.state`:
- **PRESENT** → gửi `motion.activity` chỉ có tên action (ví dụ: `'drinking', 'stretching'`). Không gửi ảnh — tiết kiệm tokens.
- **NOT PRESENT** (AWAY/IDLE) → gửi `motion` có kèm ảnh (cần xác nhận bằng mắt cho enter/leave)

### Reset wellbeing cron (LLM-driven)

Agent suy luận từ **tên action** (không cần ảnh) để quyết định reset cron nào:

1. **Đọc daily log hôm nay** để có context — uống bao nhiêu lần, nghỉ mấy lần
2. **Suy luận từ tên action:**
   - User đang uống gì (nước, bia, cà phê, v.v.) → reset hydration cron
   - User KHÔNG ngồi yên (đứng dậy, vươn vai, đi lại, v.v.) → reset break cron
   - Cả hai → reset cả hai
   - Ngồi yên (gõ phím, v.v.) → NO_REPLY
3. **Ghi vào daily log:** `HH:MM — [action] (hydration reset / break reset / both reset)`
4. **Phản hồi caring** dựa trên context từ log (ví dụ: "ly thứ 3 hôm nay rồi á, tốt lắm!"). Quan sát, không chỉ dẫn. KHÔNG BAO GIỜ nhắc cron/timer/reminder.

### Hành vi Agent

| Event | Emotion | Voice |
|---|---|---|
| `motion.activity` | `curious` (0.4) | CÓ (nhận xét caring có context) hoặc NO_REPLY (ngồi yên) |

---

## Nhận diện cảm xúc người dùng — User Emotion (Lightweight UC-M1)

Lumi nhận diện trạng thái cảm xúc **của người dùng** từ `motion.activity` actions bằng model X3D có sẵn — không cần model nhận diện biểu cảm khuôn mặt riêng. Đây là phiên bản lightweight của UC-M1 (Facial Expression & Wellness Detection).

> **Đừng nhầm lẫn với Emotion Expression** (`emotion/SKILL.md`) — cái đó điều khiển cảm xúc đầu ra của Lumi (servo + LED + eyes). Emotion Detection là cảm nhận *user* đang cảm thấy gì; Emotion Expression là cách *Lumi* thể hiện cảm xúc của chính nó.

### Các action cảm xúc được nhận diện

Model X3D đã phân loại được các action cảm xúc từ motion activity whitelist:

| Action | Trạng thái suy luận | Emotion của agent |
|---|---|---|
| `laughing` | Vui vẻ | `laugh` (0.8) |
| `crying` | Buồn/khó chịu | `caring` (0.9) |
| `yawning` | Mệt mỏi | `sleepy` (0.6) |
| `singing` | Vui/thư giãn | `happy` (0.7) |

### Luôn phải nói

Khác với `motion.activity` thường (có thể NO_REPLY khi ngồi yên), emotional actions **luôn phải có phản hồi bằng giọng nói**. Im lặng không phù hợp khi Lumi nhận thấy user đang cười, khóc, ngáp, hay hát.

### Cường độ theo ngữ cảnh

Phản hồi mặc định là nhẹ nhàng (một câu ngắn). Ngữ cảnh sẽ tăng cường độ:

- **Thời gian trong ngày**: ngáp sau 22:00 → gợi ý đi ngủ + dim đèn. Ngáp trước 10:00 → chỉ nhận xét nhẹ.
- **Thời gian ngồi**: ngáp sau 2+ tiếng ngồi → gợi ý nghỉ ngơi.
- **Lặp lại**: khóc lần 2 trong session → nhẹ nhàng hỏi muốn tâm sự không. Cười 3+ lần → nhận xét mood tốt.
- **Cross-skill**: hát mà không có nhạc đang phát → gợi ý nhạc qua Music skill.

### Logging

- **Mood history** (tự động): `motion.activity` events được server tự động ghi vào mood JSONL per-user. Emotion và response của agent được ghi qua `mood.assessed`. Agent không cần làm gì.
- **Wellbeing daily log** (agent tự ghi): Agent append `HH:MM — [emotion] {action} detected (quan sát)` vào wellbeing daily log, cùng chỗ với các entry hydration/break.

### Hạn chế (so với full UC-M1)

- Chỉ 4 action rời rạc — không có phổ cảm xúc liên tục (surprise, anger, fear, disgust không detect được)
- Cần thấy body movement (X3D là video-based action recognition, không phải close-up khuôn mặt)
- Không phát hiện micro-expression hay stress nhẹ
- Full UC-M1 cần thêm model FER (Facial Expression Recognition) ONNX vào pipeline nhận diện khuôn mặt

Xem `emotion-detection/SKILL.md` để biết rules phản hồi đầy đủ.

---

## Lưu trữ Snapshot (hai tầng)

Các sensing event có kèm camera frame (motion, presence.enter, presence.leave, music.mood) lưu snapshot ở hai nơi. Lưu ý: `motion.activity` không còn gửi ảnh — chỉ gửi tên action.

| Tầng | Đường dẫn | Rotation | Giữ qua reboot |
|------|-----------|----------|-----------------|
| **Tmp buffer** | `/tmp/lumi-sensing-snapshots/` | Theo số lượng (tối đa 50 file) | Không |
| **Persistent** | `/var/log/lumi/snapshots/` | TTL (72h) + dung lượng (tối đa 50 MB) | Có |

Mỗi snapshot được lưu vào tmp trước, sau đó copy sang persistent dir. Đường dẫn persistent được ghi trong event message (`[snapshot: /var/log/lumi/snapshots/...]`) để agent có thể xem lại — kể cả sau khi thiết bị reboot.

Các hằng số cấu hình nằm trong `lelamp/config.py`:
- `SNAPSHOT_TMP_MAX_COUNT` — số file tối đa trong tmp (mặc định 50)
- `SNAPSHOT_PERSIST_TTL_S` — TTL file persistent tính bằng giây (mặc định 72h)
- `SNAPSHOT_PERSIST_MAX_BYTES` — dung lượng tối đa thư mục persistent (mặc định 50 MB)

---

## Quy tắc chung (tất cả event type)

- **Passive sensing events** (`[sensing:*]`) bị drop nếu agent đang bận xử lý turn khác.
- **Voice events** luôn pass through — người dùng đang chủ động nói chuyện.
- Prefix `[sensing:type]` trong message là cách agent biết đây là ambient event, không phải message từ người dùng.
- Sensing events được miễn rule "phải gọi `/emotion thinking` trước" — mỗi type có emotion đầu tiên riêng.
- **Image pruning echo**: OpenClaw strip image payload cũ khỏi conversation history để tiết kiệm token. Model nhỏ (Haiku) có thể echo marker dưới dạng `[image description removed]` trong response. `SOUL.md` hướng dẫn agent không được echo các marker này.
