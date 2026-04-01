# Flow Monitor (tiếng Việt)

Tài liệu đầy đủ bằng tiếng Anh: [`docs/flow-monitor.md`](../flow-monitor.md).

## Tóm tắt

Flow Monitor là lớp quan sát end-to-end cho agent turn: ghi JSONL (`local/flow_events_YYYY-MM-DD.jsonl`), stream SSE tới UI. **Chỉ quan sát** — không đổi hành vi thiết bị hay business logic.

**Run ID từ Lumi (`chat.send`):** idempotency dùng tiền tố `lumi-chat-*` (trước đây `lumi-sensing-*`). Đó là **mọi** tin gửi qua WebSocket từ Lumi (sensing POST, wake greeting, …), **không** có nghĩa log đó chỉ là sound/voice — đừng nhầm với Telegram chỉ vì thấy chữ “sensing” trong log cũ.

**Map UUID → `lumi-chat-*`:** OpenClaw gán UUID khác idempotency; handler map trên `lifecycle_start` rồi `resolveRunID` dùng cho agent stream **và** luồng `chat` (user/assistant), tránh cùng một turn bị hai `run_id` trên Monitor.

**Sensing `enter` vs `chat_send`:** Handler gọi `NextChatRunID` + `flow.SetTrace` **trước** `flow.Start` để dòng `enter` trong JSONL cùng `trace_id` với `chat_send`. Trước đây `SetTrace` chỉ chạy sau khi gửi WS nên `enter` còn dính turn trước (turn “ma” / export Pair lệch).

**Log tương quan:** grep `flow correlation` — các `op`: `ws_chat_send`, `lelamp_agent_out`, `openclaw_uuid_map`, `chat_run_resolve`. Chi tiết bảng trong `docs/flow-monitor.md`.

## Sơ đồ Turn Pipeline (SVG)

Component `FlowDiagram` trong `lumi/web/src/pages/Monitor.tsx` vẽ **ba vùng** (màu viền nền):

| Vùng | Màu | Node |
|------|-----|------|
| **Lumi Server** | Teal | Intent, Local, Cron, Gate |
| **LeLamp** | Amber | MIC, CAM, EMO, LED, SERVO, TTS |
| **OpenClaw** | Blue | Agent, TG In, Tool, Think, Response, TG Out |

### Lumi (hàng trên)

- **Cron** là stage **Lumi** (lịch/timer thuộc Lumi), **không** nằm trong cụm OpenClaw. Trên SVG, Cron cùng hàng với Intent/Local nhưng **`x` trùng cột Agent** để cạnh Cron→Agent là **đường dọc**.

### LeLamp

- **MIC** và **CAM** là input nodes (hàng trên LeLamp).
- Output nodes xếp dọc trong 1 cột:
  - **EMO** (`hw_emotion`) — `/emotion` (phối hợp LED + servo + display eyes)
  - **LED** (`hw_led`) — `/led/solid`, `/led/effect`, `/scene`, `/led/off`
  - **SERVO** (`hw_servo`) — `/servo/aim`, `/servo/play`
  - **TTS** (`tts_speak`) — `/voice/speak`, text-to-speech
- Đây là hardware calls trực tiếp từ OpenClaw tools, không qua Lumi.
- Đường nối từ LOCAL → output nodes dùng **elbow routing** (gấp khúc bên trái) để tránh cắt qua node trung gian.

### Lumi Gate

- **Lumi Gate** nằm giữa OpenClaw output và LeLamp TTS. Lumi listen WS events để phối hợp:
  - Tool có `/audio/play` → suppress TTS (không speak chồng nhạc)
  - Tool có `/led/*` → pause ambient breathing (không ghi đè màu agent set)
  - Assistant text accumulate → flush sang TTS khi lifecycle_end

### OpenClaw (lưới 3 cột)

- **Cột 1:** Tool + Response (Response dưới Tool).
- **Cột 2:** Agent + Thinking (Think dưới Agent).
- **Cột 3:** Telegram In.
- **Hàng 1:** Agent và TG In cùng hàng.
- **Hàng 2:** Thinking và Tool cùng hàng (Think → Tool).
- **Hàng 3:** Response dưới cột 1.

Bảng tọa độ gần đúng và ASCII grid: xem mục *Turn Pipeline* và *Approximate coordinates* trong `docs/flow-monitor.md`.

## File liên quan

| File | Vai trò |
|------|---------|
| `lumi/lib/flow/flow.go` | Emit flow, JSONL, API runID từng event |
| `lumi/server/sensing/delivery/http/handler.go` | Sensing → flow.Start/End |
| `lumi/server/openclaw/delivery/sse/handler.go` | Agent → flow.Log, map runID |
| `lumi/internal/openclaw/service.go` | sendChat / idempotencyKey |
| `lumi/web/src/pages/Monitor.tsx` | `groupIntoTurns`, `FlowDiagram`, v.v. |

**Tải để so sánh:** nút **↓ Bundle** trên Flow Panel tải cùng lúc JSONL tail server, snapshot UI và OpenClaw debug payload (xem bảng *Turns list vs downloaded log* trong `docs/flow-monitor.md`).

### Lấy tin nhắn user từ Telegram

OpenClaw chat stream **không bao giờ broadcast `role:"user"`** — chỉ emit `role:"assistant"`. Để lấy nội dung tin nhắn + tên người gửi, Lumi gọi `chat.history` **WebSocket RPC** trên cùng WS connection đang dùng nhận events:

```
→  {"type":"req","id":"history-1","method":"chat.history",
    "params":{"sessionKey":"agent:main:telegram:group:...","limit":20}}

←  {"type":"res","id":"history-1","ok":true,
    "payload":{"messages":[
      {"role":"user","content":[{"type":"text","text":"dừng phát nhạc đi"}],
       "senderLabel":"Leo (158406741)"},
      ...
    ]}}
```

Chi tiết:
- **Async goroutine**: Fetch chạy trong goroutine riêng (gọi đồng bộ trong read loop sẽ deadlock).
- **Pending RPC tracking**: `pendingRPC` map match response về đúng caller qua request ID.
- **Hai phase emit**: `chat_input` đầu tiên fire ngay (chưa có text). Goroutine lấy xong → fire `chat_input` thứ 2 với message + `senderLabel` → UI pick event có content.
- **Best-effort**: timeout 3 giây, fail thì vẫn hiện `[telegram]` không có text.
- **Heartbeat**: Cron 30 phút cũng trigger `lifecycle_start` — last user message sẽ là system prompt, không phải user thật.
- **Token usage**: `chat.history` cũng được gọi lúc `lifecycle_end` để lấy token usage. OpenClaw `lifecycle_end` không có field `usage`. Token nằm trong last `role:"assistant"` message của history response: `usage: {input, output, totalTokens, cacheRead, cacheWrite}`. Emit thành `token_usage` flow event với `source: "chat_history"`.

### NO_REPLY suppression

OpenClaw agent trả `NO_REPLY` (hoặc dạng cắt ngắn `NO`, `NO_RE`, `NO_...`) khi quyết định không cần trả lời — thường cho passive sensing events (sound, motion). `isAgentNoReply()` trong `handler.go` suppress: không phát TTS, không hiện output. Match: `"NO"` chính xác, hoặc bắt đầu bằng `"NO_"` / `"NO_RE"` (case-insensitive).

### Tool call display

- Chỉ hiện tool events phase `"start"` (có args). Phase `update`/`result` không có args nên bỏ qua.
- Hiện full curl command từ `args.command` (OpenClaw agent tự generate).
- Mỗi tool entry có nút 📋 copy riêng — click copy curl command.
- OpenClaw gửi tool name ở `data.name` (không phải `data.tool`), args là object `data.args` (e.g. `{"command":"curl ..."}`).

Chi tiết run ID, `runIDMap`, stitching turn, edge case: đọc bản tiếng Anh.

## Issue đang mở

### OpenClaw không thấy `tool_call` dù có action
Đã gặp nhiều turn (nhất là Telegram): user yêu cầu action (ví dụ đổi màu đèn), kết quả OUT/TTS xác nhận đã đổi, nhưng flow/debug không có `tool_call`.

- **Ảnh hưởng**: node `TOOL` có thể không sáng dù nhìn như đã có action.
- **Trạng thái hiện tại**: đã bật raw dump full-stream (`source: "openclaw_raw"`), nhưng vẫn có run không thấy payload `stream:"tool"`.
- **Chưa chốt**: có thể OpenClaw chạy nhánh nội bộ không emit tool stream, hoặc action chỉ được suy ra từ assistant text mà không có tool invocation tường minh.
