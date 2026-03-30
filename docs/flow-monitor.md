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
- Global `SetTrace`/`GetTrace` retained solely for the Telegram-detection heuristic
- `ClearTrace()` removed from all callers

### Telegram Detection Heuristic

When `lifecycle_start` arrives without an active device trace (`flow.GetTrace() == ""`), the handler checks if it's a channel-initiated turn (Telegram/Slack). Device-originated turns are excluded via `strings.HasPrefix(runID, "lumi-sensing-")`.

## Run ID Format & Mapping

```
sendChat() generates:
  reqID           = "sensing-1"                    (WS message ID, local counter)
  idempotencyKey  = "lumi-sensing-1-1774841927380" (sent to OpenClaw, globally unique)

sendChat returns idempotencyKey → used as trace_id in flow events
```

**OpenClaw does NOT use the idempotencyKey as run_id.** It assigns its own UUID (e.g., `a8a51f3c-b44f-434b-a4c9-cd1a2a1e3c30`). This means lifecycle events from OpenClaw have a different ID than the device trace.

**Solution: `runIDMap`** in the SSE handler maps OpenClaw UUIDs back to device idempotencyKeys:
1. Sensing handler calls `flow.SetTrace(idempotencyKey)` → global trace = `"lumi-sensing-1-..."`
2. OpenClaw responds with `lifecycle_start` carrying UUID `"a8a51f3c-..."`
3. Handler detects `flow.GetTrace() != "" && trace != UUID` → stores mapping: `"a8a51f3c-..." → "lumi-sensing-1-..."`
4. All subsequent events for this UUID resolve to the device idempotencyKey via `resolveRunID()`
5. Flow events, monitor bus, and JSONL all use the consistent device ID

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
| **Lumi Server** | Teal (`--lm-teal`) | `intent_check`, `local_match`, `schedule_trigger` |
| **LeLamp** | Amber (`--lm-amber`) | `sensing`, `tts_speak` |
| **OpenClaw** | Blue (`--lm-blue`) | `agent_call`, `telegram_input`, `tool_exec`, `agent_thinking`, `agent_response` |

### Lumi Server (top band)

- **Intent** and **Local** sit on the **same top row** (left to right).
- **Cron** (`schedule_trigger`) is a **Lumi** stage (timer owned by Lumi, not OpenClaw). It shares the **same top `y`** as Intent / Local but uses **`x` aligned with `agent_call`** so Cron → Agent reads as a **vertical column** in the SVG.
- Cron is **not** inside the OpenClaw cluster; only the shared `x` is for layout.

### LeLamp (bottom-left)

- **Sensing** and **TTS** share the **same `y` as OpenClaw Tool** (`tool_exec`) so the LeLamp row lines up with the **Tool + Thinking** row in OpenClaw (horizontal alignment across clusters).

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
| `intent_check` | `(100, 100)` | Lumi top |
| `local_match` | `(240, 100)` | Lumi top |
| `schedule_trigger` | `(625, 100)` | Lumi top; `x` = Agent column |
| `sensing` | `(100, 480)` | LeLamp; `y` = Tool row |
| `tts_speak` | `(240, 480)` | LeLamp; `y` = Tool row |
| `agent_call` | `(625, 350)` | OpenClaw row 1 |
| `telegram_input` | `(775, 350)` | OpenClaw row 1 |
| `tool_exec` | `(500, 480)` | OpenClaw row 2, col 1 |
| `agent_thinking` | `(625, 480)` | OpenClaw row 2, col 2 |
| `agent_response` | `(500, 630)` | OpenClaw row 3, col 1 |

### Edges (unchanged)

`intent_check` / `schedule_trigger` → `agent_call`; `telegram_input` → `agent_call`; `sensing` → `intent_check`; `intent_check` → `local_match` → `tts_speak` / `agent_call`; `agent_call` → `agent_thinking` → `tool_exec` & `agent_response`; `tool_exec` → `agent_response`; `tool_exec` / `agent_response` → `tts_speak`.

### Event → node labels (runtime detail boxes)

Node info extracted from turn events:
- `sensing_input` → Sensing node (type + message)
- `chat_input` → Telegram In node
- `intent_match` → Local Match node
- `lifecycle_start` → Agent Call + Thinking nodes
- `tool_call` → Tool Exec node (tool name from `detail.data.tool`)
- `lifecycle_end` → Response node
- `tts_send` → TTS Speak + Output nodes (text from `detail.data.text`)
- `token_usage` → Response node (token counts)

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

## Files

| File | Role |
|---|---|
| `lumi/lib/flow/flow.go` | Flow event emission, JSONL persistence, per-event runID API |
| `lumi/server/sensing/delivery/http/handler.go` | Sensing input → flow.Start/End with runID |
| `lumi/server/openclaw/delivery/sse/handler.go` | Agent events → flow.Log with payload.RunID, turn detection |
| `lumi/internal/openclaw/service.go` | sendChat returns idempotencyKey as runID |
| `lumi/web/src/pages/Monitor.tsx` | `groupIntoTurns`, `turnIO`, `extractNodeInfo`, `FlowDiagram` |

Vietnamese summary: `docs/vi/flow-monitor_vi.md`.
