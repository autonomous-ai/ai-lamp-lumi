# Reactive turn speed-up — 2 phases (2026-05-07)

Cùng mục tiêu: giảm latency tool turn cho `motion.activity` (wellbeing) và `emotion.detected` (mood + music-suggestion + user-emotion-detection). Cả hai pipeline đều có pattern "read tuần tự → think → write tuần tự" gây ~30-85s/turn.

## Insight gốc

**Bottleneck là LLM think, không phải tool call.** Mỗi tool turn gánh ~5-10s think pass. Tool call thật sự chỉ ~100-300ms. Giảm số tool turn = giảm số think pass.

## Phase 1 — Parallel batch trong cùng 1 tool turn

Kill "Step 1, 2, 3, 4" sequential framing trong SKILL.md. Replace bằng group "What to read / Decision rules / What to write". Backend inject mới cho `emotion.detected`: `[REQUIRED — run both skills, fire concurrent reads/writes in one bash with & wait]`.

**Đụng:**
- Backend `handler.go` + `service_events.go`: rewrite emotion.detected inject
- `user-emotion-detection/SKILL.md`, `mood/SKILL.md`, `music-suggestion/SKILL.md`: drop step numbering
- `wellbeing/SKILL.md`: gộp 3 reads (history + patterns stat + days count) vào 1 bash, bỏ load `habit/SKILL.md`
- `sensing/SKILL.md`: cập nhật event matrix
- Cleanup `<say>...</say>` wrapper khỏi 2 skill (consistency với 19 skill khác)

**Verified trên Pi:**

| Turn | Trước | Sau Phase 1 |
|---|---|---|
| `emotion.detected` (Sad) | ~36s | ~26s |
| `motion.activity` (using computer) | ~50s | ~23s |

Read batch chạy ~700-950ms cho 3-5 reads concurrent (với `& wait`). Write batch chạy ~500ms cho 2-3 POSTs concurrent.

**Save thực:** chủ yếu từ kill think pass khi gộp tool turn (3 turns → 2 turns = save ~9s think). `&` parallel curl chỉ save ~1s thuần network — phụ.

**Commit Phase 1:**
- `b00ee869` parallel-batch (3 emotion skill + backend inject)
- `45db216c` snapshot path fix (lelamp đổi `/tmp/lumi-snapshots` → `/root/.openclaw/media/lumi-snapshots`)
- `249e63ee` patterns.json fold vào read batch
- `f3b4b046` wellbeing batch + drop habit cache miss
- `2fc1c515` drop `<say>` wrapper
- `170db493` drop Output Format header

## Phase 2 — Pre-inject data từ Lumi backend

**Insight tiếp:** mỗi turn vẫn còn ~9s think "between tools" (giữa read batch và write batch) để: đọc 5 read response → synthesize mood → decide skip/genre → plan POST commands. Không loại bỏ được decision logic, nhưng có thể loại bỏ **plan-reads pass** nếu Lumi đọc data sẵn rồi đính vào prompt.

**Cách:**
- Backend handler.go khi nhận `motion.activity` / `emotion.detected`: pre-fetch toàn bộ data skill cần (wellbeing-history, mood-history, audio/status, music-suggestion-history, audio/history, patterns.json, days count).
- Encode JSON, inject vào message dạng `[wellbeing_context: history=[...], patterns=..., days=N]` hoặc `[emotion_context: ...]`.
- SKILL.md đổi "What to read" thành "Use pre-fetched context. DO NOT re-GET unless block missing".
- Fallback giữ — nếu context block thiếu (pre-fetch fail), agent vẫn GET như Phase 1 → graceful degradation.

**Estimated speedup:**

| Turn | Phase 1 | Phase 2 |
|---|---|---|
| `emotion.detected` | ~26s | ~12-13s (~50%) |
| `motion.activity` | ~23s | ~12s (~48%) |

**Trade-off:**
- Tight coupling Lumi backend ↔ skill data needs (backend phải biết shape data của skill).
- Token cost +2-3KB/event in prompt (cache stable, prompt cache absorb được).
- Race condition lý thuyết (pre-fetch lúc T+0, agent đọc lúc T+8s → data có thể stale 1-5s) — chấp nhận được cho wellbeing/mood (slow-changing).
- Iteration: skill đổi data needs → phải update Lumi binary + redeploy.

**Mitigation:**
- Fallback GET trong SKILL.md nếu context block thiếu/hỏng.
- Document tight coupling trong handler.go comment, link tới SKILL.md.

**Order:**
1. `motion.activity` trước (1 skill, đơn giản, test được nhanh).
2. Đo 1-2 ngày production.
3. Mở rộng `emotion.detected` (3-skill chain).

**Phase 2 status:** đang implement (chưa commit).
