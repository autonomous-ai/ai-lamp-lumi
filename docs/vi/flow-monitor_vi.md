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
| **Lumi Server** | Teal | Intent, Local, Cron |
| **LeLamp** | Amber | Sensing, TTS |
| **OpenClaw** | Blue | Agent, TG In, Tool, Think, Response |

### Lumi (hàng trên)

- **Cron** là stage **Lumi** (lịch/timer thuộc Lumi), **không** nằm trong cụm OpenClaw. Trên SVG, Cron cùng hàng với Intent/Local nhưng **`x` trùng cột Agent** để cạnh Cron→Agent là **đường dọc**.

### LeLamp

- **Sensing** và **TTS** cùng **`y` với Tool** (hàng Tool/Think bên OpenClaw) để thẳng hàng ngang giữa LeLamp và OpenClaw.

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

**Tải để so sánh:** nút **↓ Pair** trên Flow Panel tải cùng lúc JSONL tail server và snapshot UI (xem bảng *Turns list vs downloaded log* trong `docs/flow-monitor.md`).

Chi tiết run ID, `runIDMap`, stitching turn, edge case: đọc bản tiếng Anh.
