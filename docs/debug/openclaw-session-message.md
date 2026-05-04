# OpenClaw 5.2 — `session.message` discrimination

Tracking doc for the iterative fix to surface Telegram + channel turns in
the Flow Monitor after upgrading from 5.1 to 5.2. Lists each solution
attempted in chronological order so a regression can be traced and any
layer reverted if needed.

## Problem

OpenClaw 2026.5.2 stopped fanning out the `agent` event stream
(lifecycle / tool / thinking / chat-delta) for runs whose
`messageProvider != "webchat"`. The gate is
`auto-reply/reply/agent-runner-execution.ts:980` —
`isControlUiVisible = isInternalMessageChannel(provider)` is `true` only
for `webchat`. Telegram and most other channels therefore never light up
the Flow Monitor pipeline (`chat_input` / `agent_call` / `tool_exec` /
`agent_response`) and hardware markers like `[HW:/led/solid]` in
Telegram replies are silently dropped because `lifecycle_end` never
fires for those runs on Lumi's connection.

Lumi continues to receive `session.message`, `session.tool`,
`sessions.changed`, and other `session.*` events because those broadcast
sites are unconditional, but the payload of `session.message` carries
**only** `messageId` + `sessionKey` + content + cached session row —
no `runId` or `idempotencyKey`. Discriminating the source of any given
broadcast (Lumi outbound echo vs real channel inbound vs OpenClaw
self-replay) was therefore the central problem of every solution below.

## Solution log

Each entry: commit · what it does · why it was tried · current status.

### S1 — `case "session.message"` skeleton (initial)
- Commit: `eae1c907` — `fix(openclaw): drive Telegram channel turns from session.message`
- What: parse `session.message`, on user-role create `tg-<messageId>` synthetic run id, on assistant-role finalize on `stopReason in {stop, end_turn}`, emit `chat_input` + `tts_suppressed` + `fireHWCalls`.
- Filter: `session.origin.provider == "telegram"`.
- Status: ⚠️ Active, but filter too narrow — `entry.origin` can be undefined on shared sessions; private DMs and group sessions with stale origin missed.

### S2 — Widen Telegram filter + handle `/speak,/broadcast,/dm`
- Commit: `c8990f6f` — `fix(openclaw): widen Telegram channel filter + handle /speak,/broadcast,/dm`
- What: skip `origin.provider=="heartbeat"` up front; treat as Telegram channel when **any** of `sessionKey` starts `agent:main:telegram:`, `origin.provider=="telegram"`, or `deliveryContext.channel=="telegram"`. Final assistant message also escalates HW markers `/speak`, `/broadcast`, `/dm` to `SendToLeLampTTS` / `Broadcast` / `SendToUser`.
- Why: the strict `provider=="telegram"` filter was rejecting valid Telegram broadcasts because `entry.origin` wasn't always populated for that session.
- Status: ⚠️ Active — sessionKey prefix is the most stable signal across OpenClaw versions; `origin.provider` and `deliveryContext.channel` remain best-effort.

### S3 — Synthesise lifecycle/thinking/tool/token flow events
- Commit: `26414c8b` — `fix(openclaw): synth lifecycle/thinking/token flow events for Telegram`
- What: for Telegram channel turns the agent stream is gone, so the AGENT / THINK / RESP pipeline nodes had no triggers. Emit `lifecycle_start` (alongside `chat_input`), `agent_thinking` per `{type:"thinking", thinking}` content block, `tool_call` (phase `start` so `helpers.ts:664` renders args) per `{type:"toolCall"}` block, and `lifecycle_end` + cumulative `token_usage` on `stopReason in {stop, end_turn}`.
- Status: ✅ Active. Required for Flow Monitor parity with sensing/webchat turns.

### S4 — Drop `sessionKey == GetSessionKey()` filter
- Commit: `97ac7c07` — `fix(openclaw): drop sessionKey filter that skipped private Telegram DMs`
- What: private 1:1 Telegram chats land on `agent:main:main` (the same key Lumi uses for `chat.send`). The previous filter discarded every DM as if it were a Lumi-originated sensing event. Removed.
- Status: ✅ Active — required for DM visibility.

### S5 — Outbound-echo queue + content-prefix fallback
- Commit: `fdb51a21` — `fix(openclaw): suppress Lumi chat.send echoes on shared default session`
- What: dropping S4's filter exposed the inverse bug — every Lumi `chat.send` (web chat user input, sensing prompts, system injections) echoed back as a `session.message` and was treated as inbound channel turn on `agent:main:main`. Added two layered checks:
  1. `Service.RecordOutboundEcho()` / `ConsumeOutboundEcho()` — FIFO timestamp queue; Lumi enqueues on every `chat.send`, the session.message handler pops one entry per matching user-role arrival.
  2. `isLumiInjectedUserMessage()` — content-prefix fallback: `[system]`, `[sensing:`, `[ambient]`, `(system)`, `Read HEARTBEAT.md`, `You just woke up`. Cheap defensive filter for paths that bypass `RecordOutboundEcho()`.
- Status: ⚠️ **Pending replacement by S7.** Heuristic: FIFO mismatch under interleaved order would cascade. Content prefix is fragile for arbitrary user text.

### S6 — `messageId` dedup
- Commit: `af3fb113` — `fix(openclaw): dedupe session.message broadcasts by messageId`
- What: OpenClaw rebroadcasts the same user message a second time when a queued `chat.send` is absorbed into an in-flight embedded run (`source=pi-embedded-runner`, observed during back-to-back web chat sends). Without dedup the second broadcast bypassed the (already-drained) echo queue and created a phantom `tg-<messageId>` channel turn. Added 2-min `shouldDedupeMessageID()` map at top of `case "session.message"`.
- Status: ⚠️ **Pending replacement by S7.** Dedup is order-independent so 1 mismatch no longer cascades, but only catches duplicates with identical messageId — different messageIds for the "same" user message would still leak.

### S7 — `sessions.changed` deterministic discrimination
- Commit: pending (build at `lumi/lumi-server` 14:47).
- What: read `sessions.changed` events (already broadcast unconditionally with `runId` for every embedded run start/end at `gateway/server-chat.ts:719-735` and `gateway/server-chat.ts:358-372`). Maintain `activeRunIDs: map[sessionKey] -> runId`. Set on `phase=="start"`. Don't clear on end — overwritten on the next start, late session.message arrivals can still discriminate against the most recent runId. In `session.message` handler look up `activeRunIDs[sessionKey]`:
  - `runId` starts `lumi-chat-` → Lumi outbound, suppress (deterministic, replaces S5 outbound-echo queue + content-prefix in the common case).
  - `runId` is UUID → channel inbound, process under the **real OpenClaw runId** instead of the synthetic `tg-<messageId>`. Lets the same runId unify with future `agent` / `session.tool` events should OpenClaw later loosen `isControlUiVisible`.
- S5/S6 layers retained as fallback when `activeRunID == ""` (sessions.changed hasn't arrived yet, e.g. startup race or `dropIfSlow:true` dropped the broadcast).
- Why: deterministic, no FIFO, no content match, no race window. Pre-emptive: `sessions.changed phase=start` arrives **before** the `session.message` echo, so the discriminator is ready in time.
- Status: built, awaiting deploy + test on Pi.

### Revert plan for S7

If S7 introduces regressions:
1. Set `activeRunIDs` map to never-populate (comment out the `case "sessions.changed"` body) — S5/S6 layers take over completely. No code removal needed.
2. Or hard revert the file changes via the commit hash once landed.

### S8 — Tighten `pendingChatTrace` TTL (proposed, separate concern)
- Commit: pending.
- What: separate from S1–S7, blocks the OpenClaw self-replay TTS spam. Each ~10s OpenClaw fires a fresh UUID `messageChannel=webchat` follow-up run on `agent:main:main`. The current `lifecycle_start` handler consumes the FIFO `pendingChatTrace` head and maps the self-replay UUID → `lumi-chat-N`, after which `isChannelRun=false` and TTS fires on the lamp speaker. Tighten `pendingChatTTL` from 2 min → 3-5 s so a self-replay 10 s+ after the original `chat.send` no longer claims the slot, leaves the UUID unmapped, and the TTS gets suppressed as a channel run.
- Risk: under high OpenClaw load `lifecycle_start` may legitimately arrive >3 s after `chat.send` and miss its mapping. Need to confirm typical timing on Pi before shipping.
- Status: planned (after S7 is verified).

## Removed / superseded layers

When S7 lands and is verified:
- Remove `Service.outboundEchoQueue` and the `RecordOutboundEcho` / `ConsumeOutboundEcho` calls (S5).
- Remove `isLumiInjectedUserMessage()` (S5).
- Keep `shouldDedupeMessageID()` as a small safety net against duplicate broadcasts of an identical messageId (cheap).

If S7 turns out to break a path we haven't anticipated, revert S7 alone and the S5+S6 layers continue to function as before — they are independent and additive.

## Cross-reference

- OpenClaw 5.2 source mirror: `/Users/gray/Downloads/openclaw-2026.5.2`.
- Broadcast site for `sessions.changed` lifecycle: `src/gateway/server-chat.ts:358-372` (end), `:719-735` (start).
- `isControlUiVisible` gate: `src/auto-reply/reply/agent-runner-execution.ts:970-981`.
- Related Lumi memory: `feedback_no_auto_deploy.md`, `project_openclaw_selfreplay.md`.
