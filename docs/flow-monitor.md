# Flow Monitor

The Flow Monitor is an observability layer for tracking agent turns end-to-end. It records events to daily JSONL files (`local/flow_events_YYYY-MM-DD.jsonl`) and streams them to the web UI via SSE.

**Important**: The flow monitor is purely observational. It does NOT affect device behavior, agent communication, TTS, LED, or any business logic.

## Architecture

```
LeLamp (Python)                    Lumi Server (Go)                     Web UI (React)
  sensing event ──POST──→ SensingHandler ──flow.Start/End──→ JSONL file
                            │                                    ↓
                            └─ agentGateway.SendChat ──→ OpenClaw (WS)
                                                           │
                          SSE Handler ←── WS events ───────┘
                            │
                            ├─ flow.Log("lifecycle_*") ──→ JSONL file ──→ /flow-stream (SSE)
                            ├─ flow.Log("tool_call")                         ↓
                            ├─ flow.Log("tts_send")                    lumi/web/.../Monitor.tsx
                            └─ monitorBus.Push() ──→ /openclaw/events (SSE)  └─ groupIntoTurns()
```

## Per-Event Run ID (refactored from global trace)

### Before (global trace)
```go
flow.SetTrace(runID)           // set global, affects ALL subsequent events
flow.Log("lifecycle_end", data) // picks up global trace
flow.ClearTrace()              // clear global
```

Problems:
- Concurrent turns override each other's trace
- Server restart loses in-memory trace
- `ClearTrace()` in goroutine races with next `SetTrace()`

### After (per-event run ID)
```go
flow.Log("lifecycle_end", data, payload.RunID)  // explicit per-event
flow.Log("tool_call", data, payload.RunID)      // each event carries its own ID
```

- `Start()`, `End()`, `Log()` accept optional variadic `runID` parameter
- If provided, overrides the global trace for that event only
- Global `SetTrace`/`GetTrace` retained for the Telegram-detection heuristic
- `ClearTrace()` decrements active trace (ref-counted), called after OpenClaw `lifecycle_end`

### Telegram Detection Heuristic

When `lifecycle_start` arrives without an active device trace (`flow.GetTrace() == ""`), the handler checks if it's a channel-initiated turn (Telegram/Slack). Lumi-originated `chat.send` turns are excluded via `lumi-chat-*` (and legacy `lumi-sensing-*`) so they are not mis-labeled as Telegram when the trace was lost.

#### Fetching user message content via `chat.history` RPC

OpenClaw's chat stream **never broadcasts `role:"user"` events** — it only emits `role:"assistant"` (delta/final/error). To get the user message text and sender name, Lumi calls the `chat.history` WebSocket RPC on the same WS connection used for events:

```
→  {"type":"req","id":"history-1","method":"chat.history",
    "params":{"sessionKey":"agent:main:telegram:group:-5139766247","limit":20}}

←  {"type":"res","id":"history-1","ok":true,
    "payload":{"sessionKey":"...","sessionId":"...","messages":[
      {"role":"user","content":[{"type":"text","text":"dừng phát nhạc đi"}],
       "senderLabel":"Leo (158406741)"},
      {"role":"assistant","content":[...]},
      ...
    ],"thinkingLevel":"low"}}
```

Implementation details:

- **Async goroutine**: The fetch runs in a separate goroutine because calling it synchronously inside the WS read loop handler would deadlock (the read loop blocks waiting for the handler to return, but the RPC response can only arrive after the handler returns).
- **Pending RPC tracking**: `pendingRPC map[string]chan json.RawMessage` in `internal/openclaw/service.go` matches `type:"res"` frames to waiting callers by request ID. `dispatchRPCResponse()` hooks into the read loop before event handling.
- **Two-phase emit**: First `chat_input` fires immediately (no message). After the goroutine gets the history, a second `chat_input` fires with the message text and `senderLabel` — the UI picks up the one with content.
- **Best-effort**: 3-second timeout. If the fetch fails, the turn still shows `[telegram]` without message text.
- **Heartbeat noise**: OpenClaw heartbeat cron (every 30m) also triggers `lifecycle_start`. The last `role:"user"` message in those turns will be the heartbeat system prompt (starts with `"System:"`), not a real user message.
- **Token usage**: `chat.history` is also called on `lifecycle_end` to fetch token usage. OpenClaw `lifecycle_end` events do not include `usage` data. The last `role:"assistant"` message in the history response contains `usage: {input, output, totalTokens, cacheRead, cacheWrite}` for the completed turn. This is emitted as a `token_usage` flow event with `source: "chat_history"`.

## Run ID Format & Mapping

```
sendChat() generates:
  reqID           = "chat-1"                       (WS message ID, local counter)
  idempotencyKey  = "lumi-chat-1-1774841927380"    (sent to OpenClaw, globally unique; not "sensing-only" — any outbound chat from Lumi uses this prefix)

sendChat returns idempotencyKey → used as trace_id in flow events
```

**OpenClaw does NOT use the idempotencyKey as run_id.** It assigns its own UUID (e.g., `a8a51f3c-b44f-434b-a4c9-cd1a2a1e3c30`). This means lifecycle events from OpenClaw have a different ID than the device trace.

**Solution: `runIDMap`** in the SSE handler maps OpenClaw UUIDs back to device idempotencyKeys:
1. Sensing handler allocates `NextChatRunID()`, then calls `flow.SetTrace(idempotencyKey)` **before** `flow.Start("sensing_input", ...)` so the JSONL `enter` line uses the same `trace_id` as `chat_send` for that POST. (Calling `SetTrace` only after `SendChatMessage` used to leave `enter` tagged with the **previous** turn’s id — ghost turns and mismatched Pair exports.)
2. OpenClaw responds with `lifecycle_start` carrying UUID `"a8a51f3c-..."`
3. Handler detects `flow.GetTrace() != "" && trace != UUID` → stores mapping: `"a8a51f3c-..." → "lumi-chat-1-..."`
4. All subsequent **agent-stream** events (`lifecycle`, `tool`, `thinking`, `assistant` deltas, `tts_send`) use `resolveRunID(payload.RunID)` so `trace_id` matches the device key.
5. **Chat stream** events (`case "chat"`: user/assistant text from the parallel chat feed) also call `resolveRunID` for `flow.Log` and monitor `RunID`. Without this, OpenClaw could emit the **UUID** in chat payloads while JSONL from step 4 used the **device id** — the Monitor would split one turn into two IDs.

### Correlation logs (grep: `flow correlation`)

Structured `slog.Info` lines for end-to-end ID alignment (device idempotency key = `lumi-chat-*`):

| `op` | `section` (when set) | When |
|------|------------------------|------|
| `ws_chat_send` | `lumi_to_openclaw_ws` | Every `chat.send` from Lumi (`device_run_id` = idempotency key). |
| `lelamp_agent_out` | `lelamp_to_openclaw` | Sensing handler after `SetTrace` + `agent_call` (same `device_run_id`). |
| `openclaw_uuid_map` | `openclaw` | `lifecycle_start`: OpenClaw UUID stored → device id. |
| `chat_run_resolve` | `openclaw_chat` | Chat stream event where `resolveRunID` changed the id (UUID → device). |

## Turn Grouping (Frontend)

`groupIntoTurns()` in `Monitor.tsx` groups events into turns:

1. **Turn start detection**: `sensing_input`, `chat_input`, `ambient_action`, `schedule_trigger`
2. **Run ID grouping**: events with same `runId` stay in same turn
3. **Fragment merging**: turns sharing same `runId` get merged (handles split events)
4. **Stitching**: orphaned output-only turns merge with nearby input-only turns (handles server restart splits)
5. **Session breaks**: >60s gap between turns marks a session boundary

### Stitching Rules

| Previous Turn | Current Turn | Condition | Action |
|---|---|---|---|
| Telegram fallback (no message) | Agent output | <30s gap | Merge |
| Sensing input (no output) | Orphan output (no input) | <30s gap | Merge |

## Turn Pipeline (SVG `FlowDiagram`)

Rendered by `FlowDiagram` in `lumi/web/src/pages/Monitor.tsx`. The diagram is **observational only** (zoom/pan, node highlights from recent events). Three **tinted cluster** regions group nodes:

| Region | Color (theme) | Stages |
|--------|----------------|--------|
| **Lumi Server** | Teal (`--lm-teal`) | `intent_check`, `local_match`, `schedule_trigger`, `lumi_gate` |
| **LeLamp** | Amber (`--lm-amber`) | `mic_input`, `cam_input`, `hw_emotion`, `hw_led`, `hw_servo`, `tts_speak` |
| **OpenClaw** | Blue (`--lm-blue`) | `agent_call`, `telegram_input`, `tool_exec`, `agent_thinking`, `agent_response`, `tg_out` |

### Lumi Server (top band)

- **Intent** and **Local** sit on the **same top row** (left to right).
- **Cron** (`schedule_trigger`) is a **Lumi** stage (timer owned by Lumi, not OpenClaw). It shares the **same top `y`** as Intent / Local but uses **`x` aligned with `agent_call`** so Cron → Agent reads as a **vertical column** in the SVG.
- Cron is **not** inside the OpenClaw cluster; only the shared `x` is for layout.

### LeLamp (left column)

- **MIC** and **CAM** are input nodes (top of LeLamp section).
- Output nodes are stacked vertically in a single column:
  - **EMO** (`hw_emotion`) — `/emotion` calls (coordinated LED + servo + display eyes)
  - **LED** (`hw_led`) — `/led/solid`, `/led/effect`, `/scene`, `/led/off`
  - **SERVO** (`hw_servo`) — `/servo/aim`, `/servo/play`
  - **TTS** (`tts_speak`) — `/voice/speak`, text-to-speech output
- These represent direct hardware calls from OpenClaw tools that bypass Lumi.

### OpenClaw layout rules (column + row)

These are the **stable rules** for nodes inside the OpenClaw rectangle; `positions` in `Monitor.tsx` follow this grid.

**Columns (left → right)**

| Col | Stages |
|-----|--------|
| **1** | Tool Exec, Response (stacked — Response under Tool) |
| **2** | Agent Call, Thinking (stacked — Think under Agent) |
| **3** | Telegram In (`TG IN`) |

**Rows (top → bottom)**

| Row | Rule |
|-----|------|
| **1** | **Agent** and **TG In** share one horizontal row (TG → Agent). |
| **2** | **Thinking** and **Tool** share one horizontal row (flow Think → Tool, left to right). |
| **3** | **Response** under column 1 (below Tool). |

**ASCII grid (OpenClaw only)**

```
              Col1        Col2        Col3
         ┌──────────┬──────────┬──────────┐
    Row1 │          │  Agent   │  TG In   │
         ├──────────┼──────────┼──────────┤
    Row2 │   Tool   │ Thinking │          │
         ├──────────┴──────────┴──────────┤
    Row3 │   Response (under Tool)        │
         └────────────────────────────────┘
```

### Approximate coordinates (for layout maintenance)

Values are the **node center** `(x, y)` in the SVG view box (see `positions` in `Monitor.tsx`). Adjust clusters if you move nodes.

| Stage | `(x, y)` | Note |
|-------|----------|------|
| `intent_check` | `(80, 50)` | Lumi top |
| `local_match` | `(200, 50)` | Lumi top |
| `schedule_trigger` | `(800, 50)` | Lumi top; `x` = Agent column |
| `lumi_gate` | `(400, 570)` | Lumi; between LeLamp and OpenClaw |
| `mic_input` | `(-40, 240)` | LeLamp input |
| `cam_input` | `(80, 240)` | LeLamp input |
| `hw_emotion` | `(200, 390)` | LeLamp output; emotion calls |
| `hw_led` | `(200, 510)` | LeLamp output; LED control |
| `hw_servo` | `(200, 630)` | LeLamp output; servo motor |
| `tts_speak` | `(200, 750)` | LeLamp output; TTS |
| `agent_call` | `(800, 240)` | OpenClaw row 1 |
| `telegram_input` | `(1000, 240)` | OpenClaw row 1 |
| `tool_exec` | `(600, 390)` | OpenClaw row 2, col 1 |
| `agent_thinking` | `(800, 390)` | OpenClaw row 2, col 2 |
| `agent_response` | `(600, 570)` | OpenClaw row 3, col 1 |
| `tg_out` | `(1000, 570)` | OpenClaw row 3; Telegram output |

### Edges

```
mic_input → intent_check → local_match → hw_emotion / hw_led / hw_servo / tts_speak
cam_input → intent_check → agent_call
schedule_trigger → agent_call
telegram_input → agent_call
agent_call → agent_thinking → tool_exec → agent_response
                             → agent_response
tool_exec → hw_emotion         (OpenClaw /emotion call → LeLamp)
tool_exec → hw_led             (OpenClaw /led/* or /scene call → LeLamp)
tool_exec → hw_servo           (OpenClaw /servo/* call → LeLamp)
tool_exec → lumi_gate          (Lumi listens: suppress TTS if music, pause ambient if LED)
agent_response → lumi_gate     (Lumi accumulates assistant text for TTS)
agent_response → tts_speak     (Direct TTS from response)
agent_response → tg_out        (Telegram/Slack output)
lumi_gate → tts_speak          (Gate passes if not suppressed → LeLamp TTS)
```

**Elbow routing**: Edges from `local_match` to output nodes (hw_emotion, hw_led, hw_servo, tts_speak) use elbow paths routed to the **left** of the output column to avoid crossing intermediate nodes.

### Event → node labels (runtime detail boxes)

Node info extracted from turn events:
- `sensing_input` → Sensing node (type + message). Detail: `{ type }`.
- `sound_tracker` → pushed by LeLamp Python directly via `POST /api/monitor/event`. Appears alongside `sensing_input` turns to show escalation state:
  - `{ action: "silent", occurrence: 1 }` — forwarded, agent stays silent
  - `{ action: "persistent", occurrence: 3 }` — forwarded, agent will speak
  - `{ action: "drop" }` — dropped by dedup or suppression window
- `chat_input` → Telegram In node
- `intent_match` → Local Match node
- `lifecycle_start` → Agent Call + Thinking nodes
- `tool_call` → Tool Exec node. Only `phase:"start"` events shown (has args). Displays full curl command from `args.command`. Each tool entry has a 📋 copy button for the curl command. OpenClaw sends tool name in `data.name` (not `data.tool`); args as object in `data.args` (e.g. `{"command":"curl ..."}`).
- `lifecycle_end` → Response node
- `tts_send` → TTS Speak + Output nodes (text from `detail.data.text`)
- `token_usage` → Response node (token counts).

### NO_REPLY suppression

OpenClaw agent may respond with `NO_REPLY` (or truncated forms `NO`, `NO_RE`, `NO_...`) when it decides not to respond — typically for passive sensing events like sound/motion. These are suppressed by `isAgentNoReply()` in `handler.go`: no TTS playback, no output display. Matches: exact `"NO"`, or any string starting with `"NO_"` or `"NO_RE"` (case-insensitive after trim). Source: `lifecycle_end` payload if available, otherwise fetched from `chat.history` RPC on `lifecycle_end` (async goroutine, best-effort). OpenClaw `lifecycle_end` currently does not include usage data, so `chat.history` is the primary source.

## Turn Item Display

```
[icon] TYPE  PATH  ● time
id: run-id
IN   <input text>
OUT  🔊 <output text>
N events
```

- **IN**: extracted from `sensing_input` summary or `chat_input` detail.message
- **OUT**: from `intent_match` (local) or `tts_send` (agent). Intent match is authoritative and won't be overwritten by stale tts_send from different runs.
- **Path badge**: LOCAL (green) / AGENT (blue) — only set from events belonging to the same run

## Known Edge Cases

### 1. OpenClaw assigns different run_id
OpenClaw always assigns its own UUID, ignoring the `idempotencyKey` we send.
- **Fix**: `runIDMap` in SSE handler maps OpenClaw UUID → device idempotencyKey on `lifecycle_start`.
- **Edge case**: If server restarts between `sendChat` and `lifecycle_start`, the global trace is lost and no mapping is created. Frontend stitching handles this as a fallback.
- **Status**: Fixed for normal operation. Fallback stitching for restart edge case.

### 2. sensing_input enter has no run_id
`flow.Start("sensing_input")` fires before `sendChat()` returns the run ID. The first event of a turn has no trace_id.
- **Mitigation**: Frontend assigns turn's runId from subsequent events (`sensing_input` exit has the ID).
- **Status**: Working. `isTurnStart` detects the event, `extractEventRunId` from later events fills in the ID.

### 3. Concurrent sensing events
Two sensing events arriving close together: turn B's `SetTrace` overwrites turn A's global trace. Turn A's lifecycle events may land with turn B's trace.
- **Mitigation**: Per-event runID means each `flow.Log` carries its own ID regardless of global state. The global trace is only used for the Telegram heuristic.
- **Status**: Mostly fixed. The `sensing_input enter` still has no per-event ID (pre-sendChat).

### 4. Double TTS
Both agent stream (`lifecycle_end` flush) and chat stream (`chat final assistant`) can send TTS for the same response.
- **Status**: Known bug, documented as TODO in handler.go. Fix: deduplicate with per-runID guard.

### 5. Server restarts every ~20s
WebSocket reconnects cause process-level restarts (seq counter resets). This is likely a separate stability issue, not a monitor bug.
- **Impact**: Trace lost mid-turn, events split across restarts.
- **Mitigation**: Per-event runID + frontend stitching handles most cases.

### 6. OpenClaw built-in `tts` tool bypasses LeLamp speaker (FIXED)
Agent called OpenClaw's built-in `tts` tool instead of responding with assistant text. OpenClaw generated audio server-side (`"Generated audio reply."`) but never routed it to the physical speaker (`/voice/speak` on LeLamp). Agent then returned `NO_REPLY`, so Lumi had no assistant text to flush → silent.
- **Root cause**: OpenClaw provides a built-in `tts` tool when `tools.profile = "full"`. The sensing SKILL.md instructed the agent to call `/voice/speak`, which the agent mapped to the built-in `tts` tool instead of using `curl` to LeLamp.
- **Fix**: (1) Disabled OpenClaw built-in `tts` tool via `tools.disabled.tts = true` in config generation (`service.go`). (2) Updated sensing SKILL.md and SOUL.md to instruct the agent to respond with plain text — Lumi's assistant-delta accumulation pipeline routes it to LeLamp TTS automatically.
- **Status**: Fixed in v0.0.138.

### 7. OpenClaw tool-call visibility gap (action without `tool_call`)
Observed on multiple Telegram turns: user asks for a device action (e.g. LED color change) and the lamp state/output confirms the action, but flow/debug logs contain only lifecycle + assistant/tts and no `tool_call` event.

- **Impact**: `TOOL` node can stay off even when an action appears to be executed.
- **Current status**: OpenClaw raw payload logging is enabled (`source: "openclaw_raw"`), but some runs still show no `stream:"tool"` payload.
- **Open question**: OpenClaw may be executing an internal path that does not emit tool stream, or action may be inferred from assistant text without explicit tool invocation.

## Turns list vs downloaded log

| Source | Scope |
|--------|--------|
| **Turns list** (Monitor) | Built from the **last 500** `flow_events_*.jsonl` lines (`GET /openclaw/flow-events?last=500`), then `groupIntoTurns` keeps at most **100** turns. |
| **↓ Bundle** button | One click downloads **three**: (1) `GET /openclaw/flow-logs?last=500` via `fetch` + blob save (`lumi_flow_YYYY-MM-DD_last500.jsonl`) — **same tail** as the UI feed; (2) client JSON of `events[]` + grouped `turns[]` (`lumi_flow_ui_snapshot_*.json`); (3) OpenClaw debug payload JSONL (`GET /openclaw/debug-logs`, file: `openclaw_debug_payloads_*.jsonl`). A short delay between saves avoids browsers only allowing one download per gesture. |
| **full day** link | `GET /openclaw/flow-logs` — entire day file; can be **longer** than the UI window, so Turns are **not** a reconstruction of the full file. |

Turns limits are explicit: comparing server to what you see should use **↓ Bundle** (or the same three artifacts manually: `flow-logs?last=500` + UI snapshot JSON + `debug-logs`).

## Files

| File | Role |
|---|---|
| `lumi/lib/flow/flow.go` | Flow event emission, JSONL persistence, per-event runID API |
| `lumi/server/sensing/delivery/http/handler.go` | Sensing input → flow.Start/End with runID |
| `lumi/server/openclaw/delivery/sse/handler.go` | Agent events → flow.Log with payload.RunID, turn detection |
| `lumi/internal/openclaw/service.go` | sendChat returns idempotencyKey as runID |
| `lumi/web/src/pages/Monitor.tsx` | `groupIntoTurns`, `turnIO`, `extractNodeInfo`, `FlowDiagram` |

Vietnamese summary: `docs/vi/flow-monitor_vi.md`.
