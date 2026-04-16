# Gợi Ý Nhạc Chủ Động (Music Suggestion)

> Lumi chủ động gợi ý nhạc phù hợp với mood/trạng thái người dùng — **không auto-play**, chỉ gợi ý bằng giọng nói và chờ xác nhận.

---

## Tổng quan

Tính năng này cho phép Lumi **tự quyết định thời điểm** gợi ý nhạc dựa trên:
- Mood hiện tại (qua mood history + conversation context)
- Thói quen nghe nhạc (lịch sử play)
- Lịch sử gợi ý trước đó (accepted/rejected)
- Thời gian trong ngày

Toàn bộ logic quyết định nằm trong LLM (OpenClaw agent). Go server chỉ cung cấp data và relay commands.

---

## Timeline

```
         User ngồi vào bàn
              │
T+0 min ─────┤  LeLamp detect face → [sensing:presence.enter]
              │  Agent greet user
              │  Agent bootstrap cron:
              │    cron.list() → có music job chưa?
              │    ├── Chưa có → cron.add("Proactive music check", everyMs: 420000)
              │    └── Đã có   → giữ nguyên (hoặc cron.update nếu đã learn interval mới)
              │
              │          ⏳ 7 phút chờ...
              │
T+7 min ─────┤  Cron fire lần đầu → [music-proactive]
              │  AI gather data:
              │    ├── GET /presence        → user có đang ngồi?
              │    ├── GET /mood-history    → pattern trước đó
              │    ├── GET /audio/history   → genre hay nghe
              │    └── Conversation context → mood cues
              │
              ├── ✅ Suggest → TTS nói + broadcast Telegram
              │       User confirm → play music
              │
              └── ⏭️  Skip → NO_REPLY, chờ lần sau
```

> Tối thiểu **~7 phút** sau khi ngồi, music suggestion mới có thể fire lần đầu.
> Tất cả đều là **LLM-decided** — Go server không enforce thời gian.

### Timing rules

| Yếu tố | Giá trị | Enforce |
|---------|---------|---------|
| Cron interval mặc định | **420000ms** (7 phút) | SKILL.md — AI gọi `cron.add` |
| "Just arrived" | < 10 phút → prefer chờ, nhưng nếu có listening history ở giờ này → suggest luôn | SKILL.md — AI tự judge |
| "Long session" boost | > 120 phút ngồi liên tục | SKILL.md — AI tự judge |
| Reject backoff | 2+ lần reject liên tiếp | SKILL.md — AI tự judge |

---

## Luồng hoạt động chi tiết

### 1. Bootstrap — Khi user ngồi vào bàn

```
Camera detect face
    ↓
LeLamp gửi POST /api/sensing/event {type: "presence.enter"}
    ↓
Lumi Go server forward đến OpenClaw agent
    ↓
Agent đọc sensing SKILL → thấy instruction:
  "On first presence.enter of the day, bootstrap music cron"
    ↓
Agent gọi cron.list() → không thấy music job
    ↓
Agent gọi cron.add:
  name: "Proactive music check"
  interval: 420000ms (7 phút, default)
  message: "[music-proactive] ..."
```

**Kết quả:** Một cron job chạy mỗi 7 phút, mỗi lần fire tạo 1 agent turn mới.

### 2. Cron fire — AI quyết định có suggest không

```
Cron fire → agent turn mới với message "[music-proactive]"
    ↓
Go SSE handler detect "[music-proactive]" trong message
  → mood.TrackRun(runID, "music.proactive")      // để log assessment sau
  → agentGateway.MarkBroadcastRun(runID)          // để gửi Telegram
    ↓
Agent chạy theo music SKILL workflow:

  Step 1: GET /presence → user present?
          → Không present → skip, NO_REPLY
    ↓
  Step 2: GET /api/openclaw/mood-history → xem pattern
          → presence.enter lúc mấy giờ
          → lần suggest trước bị reject không
          → music.play events ở giờ nào
    ↓
  Step 3: GET /audio/history?person={name} → genre hay nghe, duration, stopped_by
    ↓
  Step 4: AI quyết định 1 trong 3:
    A) Suggest → trả lời kèm emotion marker + gợi ý 1-2 bài
    B) Skip   → NO_REPLY (bad timing, user đang bận)
    C) Adjust → cron.update thay đổi interval cho phù hợp hơn
```

### 3. Lifecycle end — TTS + Broadcast Telegram

```
Agent trả lời xong → SSE lifecycle phase="end"
    ↓
Go handler xử lý:

  1. flushAssistantText() → lấy text + extract HW markers
     VD: "[HW:/emotion:{...}] Nghe chút nhạc jazz không?"
    ↓
  2. fireHWCalls() → POST /emotion đến LeLamp
    ↓
  3. mood.CompleteRun() → log "mood.assessed" vào mood history
     ghi lại: emotion, response text, no_reply flag, source="music.proactive"
    ↓
  4. Kiểm tra kết quả:
     - NO_REPLY     → skip TTS, log no_reply
     - Có text      → gửi TTS → LeLamp nói suggestion bằng giọng
     - Broadcast run → gửi text lên Telegram (user thấy trên điện thoại)
```

### 4. User confirm → Play music

```
User nói "ừ phát đi" (voice hoặc Telegram reply)
    ↓
Agent match music SKILL trigger → trả lời:
  [HW:/audio/play:{"query":"Take Five Dave Brubeck","person":"alice"}]
  [HW:/emotion:{"emotion":"happy","intensity":0.8}]
  Great choice!
    ↓
Go handler intercept HW markers:
  → POST http://127.0.0.1:5001/audio/play → LeLamp
  → POST http://127.0.0.1:5001/emotion → LeLamp
  → mood.Log("music.play") → ghi vào mood history
  → suppressTTS(runID, "music_playing") → chặn TTS đè lên nhạc
    ↓
LeLamp nhận /audio/play:
  → MusicService.play("Take Five Dave Brubeck", person="alice")
  → yt-dlp search YouTube → ffmpeg stream → ALSA speaker
  → _log_play_event() → ghi vào /root/local/users/{person}/audio_history/music_YYYY-MM-DD.jsonl
```

### 5. Learning loop — Lần cron tiếp theo

Lần cron tiếp theo, AI query lại mood history + audio history và so sánh:

```
Mood history:
  11:00  mood.assessed  source=music.proactive  response="jazz suggestion"
  11:02  music.play     "Take Five Dave Brubeck"
  → Khoảng cách 2 phút → ACCEPTED

Audio history:
  query: "Take Five Dave Brubeck"
  duration_s: 324    → nghe gần hết bài
  stopped_by: "end"  → không skip
  → User THÍCH bài này
```

AI rút ra: suggest jazz buổi sáng → accepted, nghe hết bài → reinforce pattern.

---

## Các layer và file liên quan

### Go server (Lumi)

| File | Vai trò |
|------|---------|
| `lumi/server/openclaw/delivery/sse/handler.go` | Detect `[music-proactive]`, intercept HW markers, log mood events, suppress TTS khi play music, broadcast qua Telegram |
| `lumi/lib/mood/mood.go` | Logger JSONL per-user per-day. Log `music.play`, `music.proactive`, `mood.assessed`. API `Query()` cho AI đọc |
| `lumi/server/openclaw/delivery/sse/handler.go → MoodHistory()` | Endpoint `GET /api/openclaw/mood-history` — AI query để learn pattern |

### OpenClaw Skills

| File | Vai trò |
|------|---------|
| `lumi/resources/openclaw-skills/music/SKILL.md` | Toàn bộ logic: bootstrap cron, decision process, mood→music mapping, learning rules, suggestion rules |
| `lumi/resources/openclaw-skills/sensing/SKILL.md` | Trigger bootstrap music cron khi `presence.enter`. Bỏ reference đến timer `music.mood` cũ |

### LeLamp (Python)

| File | Vai trò |
|------|---------|
| `lelamp/service/voice/music_service.py` | yt-dlp search → ffmpeg stream → ALSA. Log per-user play history vào `/root/local/users/{person}/audio_history/` |
| `lelamp/server.py` | `POST /audio/play` (có `person`), `POST /audio/stop`, `GET /audio/status`, `GET /audio/history?person={name}` |

---

## Dữ liệu AI sử dụng

### Mood history (`GET /api/openclaw/mood-history?date=YYYY-MM-DD&last=N`)

Lưu tại `/root/local/users/{name}/mood/YYYY-MM-DD.jsonl`. Các event type liên quan:

| Event | Ý nghĩa |
|-------|---------|
| `music.proactive` | Cron đã fire, AI bắt đầu evaluate |
| `mood.assessed` (source=`music.proactive`) | AI đã quyết định: suggest hay skip. Có field `emotion`, `response`, `no_reply` |
| `music.play` | User thực sự play nhạc (qua HW marker hoặc tool call) |
| `presence.enter` + `hour` | Khi user đến → pattern giờ nào hay ngồi |

### Audio history (`GET /audio/history?person={name}&date=YYYY-MM-DD&last=N`)

Lưu per-user tại `/root/local/users/{person}/audio_history/music_YYYY-MM-DD.jsonl`. Nếu không có person → fallback `unknown`:

| Field | Ý nghĩa |
|-------|---------|
| `query` | YouTube search string → genre/artist signal |
| `title` | Bài thực sự play |
| `duration_s` | Nghe bao lâu → mức hài lòng |
| `stopped_by` | `"user"` = skip thủ công, `"end"` = nghe hết, `"tts"` = bị TTS cắt |
| `hour` | Giờ trong ngày → pattern thời gian |
| `person` | Ai yêu cầu play (từ face recognition) |

### Accept/Reject logic

AI so sánh timestamp:
- `mood.assessed` (suggestion) → `music.play` **trong vòng 5 phút** = **accepted**
- `mood.assessed` → **không có** `music.play` trong 15 phút = **rejected**
- 3+ rejected liên tiếp ở cùng khung giờ → ngừng suggest ở giờ đó

---

## Speaker conflict

Lumi chỉ có 1 speaker chia sẻ giữa TTS và music. Handler xử lý bằng `suppressTTS`:

| Tình huống | Hành vi |
|-----------|---------|
| AI suggest bằng text (không play) | TTS nói suggestion → user nghe bằng giọng |
| AI suggest + user confirm → play | `suppressTTS("music_playing")` → TTS không nói đè lên nhạc |
| Music đang play + TTS request | LeLamp trả HTTP 409 — music giữ priority |
| User nói "stop" | `[HW:/audio/stop:{}]` → dừng music |

---

## Cách test

### Điều kiện tiên quyết

- Lumi Go server đang chạy (port 5000)
- LeLamp đang chạy (port 5001) với audio device
- OpenClaw agent connected
- Camera hoạt động (cho presence detection)
- Có kết nối internet (yt-dlp cần YouTube)

### Test 1: Bootstrap cron khi presence.enter

**Mục tiêu:** Verify AI tạo music cron job khi user ngồi vào.

**Bước thực hiện:**
1. Ngồi trước camera → chờ `presence.enter` event
2. Chờ agent xử lý xong (greeting)
3. Kiểm tra cron đã tạo:
   ```bash
   # Qua OpenClaw API hoặc xem agent log
   # Tìm log: "Proactive music check" trong cron list
   ```

**Kết quả mong đợi:**
- Agent tạo cron job tên "Proactive music check" với interval 420000ms
- Không có cron music trùng lặp

**Verify trên Flow Monitor:**
- Mở web UI → Monitor page
- Xem flow: `sensing_input` → `chat_response` (greeting) + cron.add call

### Test 2: Cron fire → AI suggest

**Mục tiêu:** Verify AI gợi ý nhạc khi cron fire và user present.

**Bước thực hiện:**
1. Ngồi trước camera (presence = present)
2. Chờ cron fire (7 phút sau bootstrap, hoặc theo interval đã set)
3. Quan sát response

**Kết quả mong đợi:**
- Agent query presence, mood history, audio history
- Agent trả lời gợi ý 1-2 bài (hoặc NO_REPLY nếu judge không phù hợp)
- TTS nói suggestion bằng giọng
- Telegram nhận được cùng text (broadcast)
- Mood history ghi `mood.assessed` với `source: "music.proactive"`

**Verify:**
```bash
# Xem mood history hôm nay
curl -s "http://<LUMI_IP>:5000/api/openclaw/mood-history?date=$(date +%Y-%m-%d)&last=50" | jq '.data.events[] | select(.event == "mood.assessed" and .source == "music.proactive")'
```

### Test 3: Cron fire → user vắng → skip

**Mục tiêu:** Verify AI không suggest khi user không present.

**Bước thực hiện:**
1. Rời khỏi camera (presence = away)
2. Chờ cron fire

**Kết quả mong đợi:**
- Agent query presence → not present → NO_REPLY
- Không có TTS, không broadcast
- Flow Monitor hiển thị `[no reply]`

### Test 4: User confirm → play music

**Mục tiêu:** Verify nhạc play sau khi user đồng ý.

**Bước thực hiện:**
1. Chờ AI suggest (Test 2)
2. Nói "ừ phát đi" hoặc reply trên Telegram "play that"
3. Quan sát speaker

**Kết quả mong đợi:**
- Agent trả lời với `[HW:/audio/play:{"query":"...","person":"..."}]` marker
- Speaker phát nhạc từ YouTube
- TTS bị suppress (không nói đè lên nhạc)
- Mood history ghi `music.play`
- Audio history ghi play event (query, title, duration)

**Verify:**
```bash
# Xem audio status
curl -s "http://<LUMI_IP>:5001/audio/status"
# → {"playing": true}

# Xem mood history có music.play
curl -s "http://<LUMI_IP>:5000/api/openclaw/mood-history?date=$(date +%Y-%m-%d)&last=10" | jq '.data.events[] | select(.event == "music.play")'

# Xem audio history
curl -s "http://<LUMI_IP>:5001/audio/history?person=alice&last=5"
```

### Test 5: User reject → AI adapt

**Mục tiêu:** Verify AI điều chỉnh khi user từ chối.

**Bước thực hiện:**
1. Chờ AI suggest
2. Nói "không" hoặc im lặng (không play)
3. Chờ lần suggest tiếp theo
4. Lặp lại 2-3 lần reject liên tiếp

**Kết quả mong đợi:**
- Mood history ghi `mood.assessed` nhưng không có `music.play` sau đó
- Sau 2-3 lần reject, AI có thể:
  - Tăng interval (cron.update)
  - Thay đổi genre suggest
  - Skip suggest ở khung giờ này

**Lưu ý:** Hành vi adapt phụ thuộc LLM judgment — không deterministic. Kiểm tra bằng cách xem cron interval có thay đổi không.

### Test 6: Speaker conflict — TTS vs Music

**Mục tiêu:** Verify TTS không đè lên music đang play.

**Bước thực hiện:**
1. Play nhạc (nói "play some jazz")
2. Trong khi nhạc đang chạy, trigger một sensing event (ví dụ: motion)
3. Quan sát speaker

**Kết quả mong đợi:**
- Music tiếp tục play
- Agent response không bị TTS phát ra (suppressed)
- Flow Monitor hiển thị `tts_suppressed` với reason `music_playing`

### Test 7: Stop music

**Bước thực hiện:**
1. Đang play nhạc
2. Nói "stop" hoặc "tắt nhạc"

**Kết quả mong đợi:**
- Agent gửi `[HW:/audio/stop:{}]`
- Music dừng ngay
- Audio history ghi `stopped_by: "user"`

### Test 8: Reactive — User hỏi trực tiếp

**Mục tiêu:** Verify music suggestion cũng hoạt động khi user chủ động hỏi.

**Bước thực hiện:**
1. Nói "gợi ý nhạc đi" hoặc "suggest some music"

**Kết quả mong đợi:**
- Agent query audio history → gợi ý dựa trên genre user hay nghe
- Nếu chưa có history → gợi ý theo mood từ mood history + conversation context
- Không auto-play, chờ confirm

---

## Monitoring & Debug

### Flow Monitor (Web UI)

Mở `http://<LUMI_IP>:5000` → Monitor page. Các event liên quan:

| Event type | Ý nghĩa |
|-----------|---------|
| `sensing_input` | Sensing event đến (presence, motion...) |
| `hw_audio` | Music play/stop command |
| `hw_emotion` | Emotion marker fired |
| `tts_send` | Text gửi đến TTS |
| `tts_suppressed` | TTS bị chặn (reason: music_playing) |
| `no_reply` | Agent quyết định im lặng |

### Logs quan trọng (Go server)

```bash
# Xem music-related logs
journalctl -u lamp-server | grep -i "music\|audio/play\|suppress\|broadcast"
```

| Log message | Ý nghĩa |
|------------|---------|
| `music tool detected, TTS will be suppressed` | Detect /audio/play, sẽ chặn TTS |
| `broadcast run response to channels` | Gửi suggestion text lên Telegram |
| `agent replied NO_REPLY, skipping TTS` | AI quyết định không suggest |
| `assistant turn done, TTS suppressed` | TTS bị chặn (music đang play) |

### Mood history trực tiếp

```bash
# Xem raw JSONL trên Pi
cat /root/local/users/<username>/mood/$(date +%Y-%m-%d).jsonl | jq .

# Qua API
curl -s "http://<LUMI_IP>:5000/api/openclaw/mood-history?date=$(date +%Y-%m-%d)&last=200" | jq '.data.events'
```

### Audio history trực tiếp

```bash
# Qua API
curl -s "http://<LUMI_IP>:5001/audio/history?person=alice&last=20"
```

---

## Hạn chế hiện tại

1. **Toàn bộ intelligence nằm trong LLM** — Go server không validate timing, interval, hay quyết định suggest. Nếu LLM "quên" tạo cron hoặc bỏ qua rules → không có safety net.

2. **Không có server-side rate limit** — Nếu AI set interval quá ngắn hoặc suggest liên tục, không có hard code chặn.

3. **Learning phụ thuộc LLM context** — AI đọc mood history mỗi lần cron fire để learn. Nhưng nếu history dài hoặc pattern phức tạp, LLM có thể miss.

4. **Cần internet** — yt-dlp search YouTube cần kết nối mạng. Không có offline fallback.

5. **Single speaker** — TTS và music chia sẻ 1 speaker. Không thể vừa nói vừa phát nhạc.
