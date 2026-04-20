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

### Cơ chế hoạt động (event-driven — không cron)

Wellbeing hoạt động **event-driven**. **KHÔNG còn cron wellbeing** nào. Mỗi khi nhận `motion.activity`, agent log hoạt động và đọc lại history gần đây để quyết định có cần nhắc hay không.

**Activity JSONL theo từng user** tại `/root/local/users/{user}/wellbeing/YYYY-MM-DD.jsonl` — mỗi dòng là 1 transition:

```jsonc
{"ts": 1776658657.23, "seq": 42, "hour": 11, "action": "sedentary", "notes": ""}
```

`action` values:

| Action | Do ai ghi | Mục đích |
|---|---|---|
| `drink`, `break`, `sedentary`, `emotional` | Agent | Transition hoạt động từ motion.activity groups |
| `enter`, `leave` | Backend (sensing handler) | Session boundary — phá dedup chain |
| `nudge_hydration`, `nudge_break` | Agent (sau khi nhắc) | Ghi lại thời điểm Lumi nhắc — để hiện lên timeline (không ảnh hưởng logic nudge tiếp theo) |

**Dedup nằm ở LeLamp.** `lelamp/service/sensing/perceptions/motion.py` giữ `_last_sent_key = (current_user, frozenset(activity_groups), tuple(emotional_cues))` và `_last_sent_ts`. Trước khi gửi `motion.activity`, nếu key không đổi **và** khoảng cách từ lần gửi cuối chưa vượt `MOTION_DEDUP_WINDOW_S = 300` giây (5 phút) → drop. Điều này chặn spam "1 event/phút" ngay tại nguồn, Lumi không tốn token.

- Đổi user (owner→owner, owner→unknown, unknown→owner) lật key ngay → event pass qua.
- Stranger khác nhau (`stranger_46` → `stranger_54`) đều collapse về `"unknown"` qua `FaceRecognizer.current_user()` → đổi stranger không phá dedup.
- Sau 5 phút cùng state, event tiếp theo vẫn pass — để Lumi agent "thức dậy" định kỳ chạy threshold check.

Lumi **không dedup** — `wellbeing.LogForUser` append thẳng. Dedup là việc của lelamp.

**Retention:** 7 ngày. Goroutine trong `wellbeing.Init()` xoá file cũ hàng ngày.

### Khi nhận `motion.activity` — agent làm gì

1. **Log từng Activity group** (`drink`, `break`, `sedentary`) qua `POST /api/wellbeing/log` với `user = current_user`. Backend dedup — agent không cần check "đã ở state này chưa?".
2. **Đọc history gần đây** qua `GET /api/openclaw/wellbeing-history?user={current_user}&last=50`.
3. **Tính delta** từ log, dùng **điểm reset gần nhất** cho mỗi loại:

   ```
   hydration_reset = max(ts last drink entry, ts last enter entry)
   break_reset     = max(ts last break entry, ts last enter entry)
   ```

   `presence.enter` tính là 1 điểm reset — user vừa vào session → delta bắt đầu từ 0, đếm lên. Không spam ngay khi user ngồi xuống, nhưng sẽ nudge đúng khi user ngồi lâu chưa drink/break.
4. **Quyết định có nudge không** (tối đa 1 nudge/turn, hydration ưu tiên hơn break):
   - Hydration: `minutes_since_last_drink >= HYDRATION_THRESHOLD_MIN` **VÀ** `minutes_since_last_nudge_hydration >= NUDGE_COOLDOWN_MIN` → nhắc uống nước.
   - Else break: `minutes_since_last_break >= BREAK_THRESHOLD_MIN` **VÀ** `minutes_since_last_nudge_break >= NUDGE_COOLDOWN_MIN` → nhắc nghỉ/stretch.
   - else → caring observation hoặc `NO_REPLY`.
5. **KHÔNG BAO GIỜ đoán** time-since từ memory — luôn tính từ log.

### Ngưỡng

Hardcode trong `lumi/resources/openclaw-skills/wellbeing/SKILL.md`:

| Threshold | Giá trị test | Giá trị production |
|---|---|---|
| `HYDRATION_THRESHOLD_MIN` | **5** | 45 |
| `BREAK_THRESHOLD_MIN` | **7** | 30 |
| `NUDGE_COOLDOWN_MIN` | **3** | 15 |

> ⚠ **Release checklist:** trước khi ship, đổi cả 3 constant về production (45 / 30 / 15). Hydration và break cố ý lệch nhau (5 vs 7) để test phân biệt nhánh nào fire.

**`NUDGE_COOLDOWN_MIN` — khoảng lặng giữa 2 lần nhắc cùng loại.**

Không có nó, motion.activity fire mỗi ~5 min (do lelamp dedup). Nếu user qua ngưỡng hydration mà chưa uống, mỗi wake-up agent lại nhắc — vì threshold delta chỉ reset khi user UỐNG hoặc `enter` mới, không reset khi agent nhắc:

```
10:45  hydration overdue → nhắc 💧 (1)
10:50  wake-up → vẫn overdue → nhắc 💧 (2)
10:55  wake-up → vẫn overdue → nhắc 💧 (3)  ← spam
```

Với `NUDGE_COOLDOWN_MIN = 15`:

```
10:45  nhắc 💧 → log nudge_hydration
10:50  wake-up → overdue nhưng nudge mới 5 min trước < 15 → SKIP
10:55  wake-up → 10 min < 15 → SKIP
11:00  wake-up → 15 min ≥ 15 → nhắc 💧 lại (nếu user vẫn chưa uống)
```

Break nudge hoạt động y vậy, track riêng qua entry `nudge_break`. Nếu user uống/nghỉ trước khi hết cooldown, threshold delta tự reset → không cần nhắc nữa.

### User attribution — `[context: current_user=X]`

Sensing handler inject tag `[context: current_user=X]` vào mọi message `motion.activity`. `X` là tên friend gần nhất được nhận, hoặc `"unknown"` khi face chỉ thấy stranger. Các skill Wellbeing, Mood, Music đều bắt buộc dùng đúng giá trị này cho field `user` trong API call — **cấm** suy luận từ memory, KNOWLEDGE.md, chat history, hay `senderLabel`. Nguồn duy nhất là `mood.CurrentUser()`, cũng set `"unknown"` khi stranger `presence.enter` (trước đây để stale tên friend cũ).

### Marker presence do backend tự ghi

Sensing handler ghi `enter` / `leave` vào cùng file wellbeing JSONL — **agent không cần làm gì**:

- `presence.enter` (friend) → `{"action": "enter", "user": "<name>"}`
- `presence.enter` (stranger) → `{"action": "enter", "user": "unknown"}`
- `presence.leave` / `presence.away` → `{"action": "leave", "user": "<current_user_tại_thời_điểm_event>"}`

Các marker này phá dedup chain nên ví dụ `sedentary → leave → enter → sedentary` cho ra 3 entry (sedentary, leave+enter, sedentary), không phải 1.

### Ưu tiên: Skills > Knowledge > History

AGENTS.md quy định thứ tự ưu tiên: **SKILL.md luôn override KNOWLEDGE.md và conversation history**. Điều này rất quan trọng vì agent tự tích lũy "kinh nghiệm" vào KNOWLEDGE.md qua heartbeat, và những ghi chú này có thể chứa rules sai xung đột với skills do developer duy trì. Nếu agent phát hiện xung đột, nó phải cập nhật KNOWLEDGE.md cho khớp với skill, không phải ngược lại.

### Khi `presence.leave` / `presence.away`

Backend ghi marker `leave` vào log. Không có gì khác để làm — **không có cron để cancel**. Directive yêu cầu agent im lặng (`NO_REPLY`).

Agent dùng ảnh camera để đánh giá — KHÔNG phải lúc nào cũng nói. Tránh spam user khi họ trông ổn.

### Gợi ý nhạc (AI-Driven)

Gợi ý nhạc **không còn** được kích hoạt bởi timer cứng. Thay vào đó, AI agent **tự schedule** music check qua OpenClaw cron jobs và **tự học** thói quen user theo thời gian:

- **Tự schedule:** Khi phát hiện **hoạt động tĩnh đầu tiên** trong `motion.activity` (không phải `presence.enter`), AI tạo cron job (mặc định: mỗi 20 phút / 1200000ms, `sessionTarget: "current"`, `payload.kind: "systemEvent"`). AI tự điều chỉnh interval dựa trên phản hồi của user.
- **Quyết định dựa trên dữ liệu:** Trước khi gợi ý, AI query:
  - `GET /audio/status` — nhạc đang phát chưa?
  - `GET /api/openclaw/mood-history` — mood mới nhất để chọn genre
  - `GET /audio/history?person={name}` — lịch sử nghe nhạc per-user (genre ưa thích, thời lượng, mức độ hài lòng)
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

### Speak và broadcast markers

Hai control marker cho turn channel-origin:

| Marker | Tác dụng | Khi nào dùng |
|---|---|---|
| `[HW:/speak:{}]` | Force TTS trên loa. Không ảnh hưởng Telegram. | Proactive crons (wellbeing, music) chạy trong Telegram/channel session để nhắc phát qua loa. Thường kèm `[HW:/dm:{"telegram_id":"..."}]` để DM đúng 1 người. |
| `[HW:/broadcast:{}]` | Force TTS **và** fan-out text tới tất cả Telegram chat. | Chỉ dành cho guard mode alert. Không dùng cho wellbeing/music — sẽ notify mọi chat, không phải chỉ người được nhắc. |

Mặc định turn channel-origin (Telegram, webchat) suppress TTS loa vì reply đi qua channel message. `/speak` override suppression đó mà không kèm fan-out.

**Cron-fire tự force TTS.** Khi OpenClaw emit `event:"cron"` với `action:"started"`, Lumi cache `sessionKey` và `lifecycle_start` kế tiếp trên session đó trong vòng 10 s sẽ bị mark là cron fire — `isChannelRun` bị override thành `false` nên loa lamp tự nói mà không cần `[HW:/speak]` trong reply. Marker vẫn hữu ích như defense-in-depth fallback nếu cron event bị drop (`dropIfSlow: true` ở phía OpenClaw).

### Mood history per-user

Mood history lưu per-user tại `/root/local/users/{name}/mood/YYYY-MM-DD.jsonl` (7 ngày retention). Hệ thống tracking ai đang ngồi qua `presence.enter` (face recognition) và log mood events vào thư mục user đó.

#### Nguồn mood

| Source | Cách hoạt động |
|---|---|
| **Camera** (`source: "camera"`) | `motion.activity` detect action cảm xúc (laughing, crying, yawning, singing) → Emotion Detection skill trigger → agent log mood |
| **Conversation** (`source: "conversation"`) | Agent detect mood theo 2 cách: (1) **single message** — explicit ("I'm tired") hoặc implied ("work is killing me" → stressed); (2) **conversation flow** — sau khi nói chuyện một lúc, đọc vibe tổng thể (tone shift, reply ngắn cộc lốc, topic lặp lại, năng lượng tăng/giảm). Agent tin trực giác và mạnh dạn suy luận: chỉ cần một gợi ý nhỏ là đủ, log nhầm còn hơn bỏ sót. Hoạt động trên mọi channel (Telegram, voice, web). |

#### Voice mood nudge

Voice events (`voice_command`, `voice`) kèm nudge `[MANDATORY: Follow Mood skill — log mood now.]` trong message gửi lên agent, cộng `[Current user: {name}]` khi face recognition biết ai đang ngồi.

#### Định dạng lưu trữ

JSONL (mỗi dòng 1 JSON object) — chọn thay vì JSON array vì:
- **Append**: O(1) — ghi thêm 1 dòng (không cần đọc-parse-ghi lại cả file)
- **Crash-safe**: tệ nhất mất 1 dòng (array có thể corrupt cả file)
- **Đọc N cuối**: `Query()` đọc tất cả rồi slice — đủ nhanh cho file daily (vài chục entry)

Mỗi row có field `kind` — hoặc raw `signal` từ 1 nguồn (camera/voice/telegram),
hoặc `decision` do agent tổng hợp từ các signal gần đây + decision trước đó.
Server không bao giờ tự fuse — Mood skill chịu trách nhiệm ghi cả 2 row mỗi lần
phát hiện mood.

```bash
# Ghi raw signal (agent gọi mỗi lần camera/voice/telegram báo mood)
POST /api/mood/log  {"kind":"signal","mood":"happy","source":"camera","trigger":"laughing"}

# Ghi decision sau khi đọc history và tổng hợp
POST /api/mood/log  {"kind":"decision","mood":"happy","based_on":"3 signals last 20min","reasoning":"laughing reinforces previous happy decision"}

# Đọc tất cả kind cho 1 ngày (agent dùng để re-analyze)
GET /api/openclaw/mood-history?user=gray&date=2026-04-09&last=100

# Đọc decision mới nhất (Music/Wellbeing dùng để biết "current mood")
GET /api/openclaw/mood-history?user=gray&kind=decision&last=1
```

Signal row: `{"ts":...,"seq":1,"hour":10,"kind":"signal","mood":"happy","source":"camera","trigger":"laughing"}`
Decision row: `{"ts":...,"seq":2,"hour":10,"kind":"decision","mood":"happy","source":"agent","based_on":"...","reasoning":"..."}`

### Nhận diện cross-channel

Agent liên kết tên face recognition với Telegram username bằng cách quan sát timing và context (ví dụ: "gray" đang ngồi và "@GrayDev" nhắn Telegram cùng lúc). Mapping được lưu vào USER.md (cho friend) hoặc notes trong folder user. Agent hỏi xác nhận nếu chưa chắc.

---

## Phân tích Motion Activity (khi đang có mặt)

Khi user đang ở trạng thái PRESENT và camera phát hiện chuyển động, hệ thống gửi event `motion.activity` thay vì `motion`. Hệ thống gửi tên action đã detect (không kèm ảnh — tên action đủ để agent suy luận).

### Cách hoạt động

`MotionPerception` buffer snapshots và action names, flush theo interval (`MOTION_FLUSH_S`). Khi flush, check `PresenceService.state`:
- **PRESENT** → gửi 1 event `motion.activity` duy nhất. Message có tối đa 2 dòng:
  - `Activity detected: <groups>.` — activity groups vật lý (`drink`, `break`, `sedentary`), cách nhau bởi dấu phẩy.
  - `Emotional cue: <actions>.` — raw emotional action names (`laughing`, `crying`, `yawning`, `singing`), cách nhau bởi dấu phẩy. Giữ raw label (không gộp thành group) để agent map đúng emotion từng cái.
  - Khi không có emotional cue, message kết thúc bằng `If nothing noteworthy, reply NO_REPLY.` (hint tiết kiệm token). Khi có emotional cue, hint này bị bỏ vì emotional luôn phải nói.
  - Không gửi ảnh — tiết kiệm tokens. **Không** yêu cầu nhận diện friend.
- **Còn lại** → event bị **skip** (log, không gửi). Lumi chỉ expect `motion.activity` — plain `motion` từ X3D/pose không có handler và lãng phí agent tokens.

Ví dụ message:
```
Activity detected: drink, sedentary. If nothing noteworthy, reply NO_REPLY.
Activity detected: sedentary. Emotional cue: laughing.
Emotional cue: yawning.
```

### Reset wellbeing cron (LLM-driven)

Agent nhận **activity group** (`drink`, `break`, `sedentary`) từ dòng `Activity detected:` — không cần suy luận. Emotional cue xử lý riêng qua dòng `Emotional cue:`:

1. **Đọc history hôm nay** qua `GET /api/openclaw/wellbeing-history?user={name}` để có context — đã drink/break/sedentary mấy lần
2. **Theo group ở dòng `Activity detected:`:**
   - `drink` → reset hydration cron
   - `break` → reset break cron (ăn, vươn vai, vận động)
   - `sedentary` → tạo hydration + break crons nếu chưa có; kích hoạt Music skill sedentary suggestion (event-driven, không cron)
   - Nhiều groups cùng lúc → xử lý tất cả
3. **Có dòng `Emotional cue:`?** → follow Emotion Detection skill, không đụng cron
4. **Log** từng group quan sát được qua `POST /api/wellbeing/log` với `{action, notes, user}` (mỗi group 1 entry)
5. **Phản hồi caring** dựa trên context từ history (ví dụ: "ly thứ 3 hôm nay rồi á, tốt lắm!"). Quan sát, không chỉ dẫn. KHÔNG BAO GIỜ nhắc cron/timer/reminder.

### Hành vi Agent

| Event | Emotion | Voice |
|---|---|---|
| `motion.activity` | `curious` (0.4) | CÓ (nhận xét caring có context) hoặc NO_REPLY (ngồi yên) |

---

## Nhận diện cảm xúc người dùng — User Emotion (Lightweight UC-M1)

Lumi nhận diện trạng thái cảm xúc **của người dùng** từ dòng `Emotional cue:` trong event `motion.activity` bằng model X3D có sẵn — không cần model nhận diện biểu cảm khuôn mặt riêng. Đây là phiên bản lightweight của UC-M1 (Facial Expression & Wellness Detection).

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

- **Mood history** (agent ghi): Mỗi lần có cue, Mood skill ghi 1 row raw `signal`, rồi đọc history gần đây và ghi tiếp 1 row `decision` đã tổng hợp (vd: `{"kind":"decision","mood":"happy","based_on":"...","reasoning":"..."}`). Music/Wellbeing đọc decision mới nhất (`?kind=decision&last=1`) để biết "mood hiện tại".
- **Wellbeing history** (agent tự log): Agent gọi `POST /api/wellbeing/log` với `{"action":"emotional","notes":"yawning — chiều buồn ngủ","user":"{name}"}`. Cùng JSONL stream với entry hydration/break.

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
- **Voice events** luôn pass through — người dùng đang chủ động nói chuyện. Voice messages kèm mood scan nudge (`[MANDATORY: Follow Mood skill — log mood now.]`) để agent nhớ detect mood từ conversation flow.
- Prefix `[sensing:type]` trong message là cách agent biết đây là ambient event, không phải message từ người dùng.
- Sensing events được miễn rule "phải gọi `/emotion thinking` trước" — mỗi type có emotion đầu tiên riêng.
- **Image pruning echo**: OpenClaw strip image payload cũ khỏi conversation history để tiết kiệm token. Model nhỏ (Haiku) có thể echo marker dưới dạng `[image description removed]` trong response. `SOUL.md` hướng dẫn agent không được echo các marker này.
