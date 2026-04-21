# DEV — RunId Mis-attribution Between Sensing `chat.send` and Concurrent Telegram Message

Playbook for diagnosing the case where Lumi's `chat.send` idempotency key (e.g. `lumi-chat-26-1776759969005`) ends up wrapping an agent turn that actually processed a *different* user message — typically a Telegram reply that arrived ~1–2 s later on the same session lane.

First seen: 2026-04-21 on OpenClaw gateway `2026.4.9`, session `agent:main:main`, runId `lumi-chat-26-1776759969005`.

---

## 1. Symptom

- Flow monitor / TTS pipeline shows a response that does not match the input of the run it is attributed to.
- Example: Lumi sent `[sensing:presence.enter] stranger_75`; Lumi attributed the resulting TTS text to that run but the actual text was a ~400-token explanation answering a Telegram question from Leo about `[node-host]`.
- The real sensing message is processed in a *later* turn with a UUID runId (not `lumi-chat-*`).
- Possible downstream effects:
  - Wrong text spoken on the lamp speaker (TTS suppressed for channel run is the only reason it didn't reach the speaker in this specific case).
  - Double-reaction: sensing event gets responded to twice (once via mis-attributed turn — content wrong; once via the actual later UUID turn).
  - `agent_thinking` + `tts_send` events on the flow monitor appear semantically disconnected from the `chat_send` / `chat_input` of the same run.

---

## 2. Root cause (hypothesis, verified from session JSONL)

**Race condition inside OpenClaw gateway's per-session queue (`lane=session:agent:main:main`).**

1. Lumi sends `chat.send` (sensing) → OpenClaw ACKs and enqueues it in the session lane.
2. Before the agent starts the turn, a Telegram inbound arrives for the same session (~1–2 s later).
3. OpenClaw starts an agent turn for the Telegram message but binds the `lifecycle` UUID to the **pending `idempotencyKey` of Lumi's earlier `chat.send`** (`lumi-chat-*`).
4. The turn's output (matching the Telegram question) streams back under Lumi's runId.
5. Lumi maps the UUID → `lumi-chat-*` via the lifecycle mapper and drops the assistant text into the sensing run's flow/TTS pipeline.
6. The sensing message is processed in the *next* turn and gets a fresh UUID runId (e.g. `9bb9339e-…`), which Lumi sees as an OpenClaw-initiated run.

This is a gateway-side bug: the `idempotencyKey` of a pending send should only ever label the turn that actually consumed *that* message. Correlation logic must not reuse an unresolved `idempotencyKey` for an unrelated queued input (e.g. Telegram inbound).

Relevant Lumi correlation log (confirms the mapping happens):

```
mapped OpenClaw runId to device trace
  openclawId=3a5b3d9f-8e42-4a66-a11f-60c9b39ada1c
  deviceId=lumi-chat-26-1776759969005
```

---

## 3. Evidence sources on the Pi

| Source | What it proves |
|---|---|
| `journalctl -u lumi` grep for the runId | Lumi's `chat.send` payload (what it intended to send) + the UUID→device runId mapping |
| `/root/local/flow_events_YYYY-MM-DD.jsonl` | What actually fired under that runId: `tts_send`, `agent_thinking`, `token_usage` — content that may not match the `chat_send` under the same `trace_id` |
| **`/root/.openclaw/agents/main/sessions/<sessionId>.jsonl`** | Ground truth of the session: every user message + assistant message with `thinking` blocks + signatures. Timestamps are UTC. |
| `journalctl -u openclaw` | Session lane diagnostics (e.g. `lane wait exceeded`), `chat.send` / `chat.history` ACKs, connId. |

The session file (`/root/.openclaw/agents/main/sessions/*.jsonl`) is the deciding one — it shows both the sensing message and the Telegram message as separate `user` entries with their own timestamps, making the race obvious.

---

## 4. Detection queries

Assuming Pi SSH is authorized (per `CLAUDE.md`, always ask first):

```bash
PI=pi@<IP>
PASS=12345
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no $PI"
RUN=lumi-chat-<N>-<ms>
```

### 4.1 Confirm the mis-attribution

```bash
# What Lumi sent under this runId
$SSH "sudo journalctl -u lumi --no-pager | grep '\[chat.send\] full payload' | grep '$RUN'"

# What actually came back under this runId (flow events)
$SSH "sudo grep '$RUN' /root/local/flow_events_$(date +%F).jsonl \
      | jq -c 'select(.node==\"tts_send\" or .node==\"agent_thinking\") | {node, data}'"
```

If the `tts_send.text` / `agent_thinking.text` is semantically unrelated to the `chat.send.message`, you are looking at this bug.

### 4.2 Find the actual Telegram message that got answered

```bash
SESSION=$($SSH "sudo ls -t /root/.openclaw/agents/main/sessions/*.jsonl" \
          | grep -v checkpoint | head -1)

# Replace TS_LOW / TS_HIGH with the UTC window around the lifecycle
$SSH "sudo jq -c 'select(.type==\"message\" and .message.role==\"user\" \
                  and .timestamp >= \"<TS_LOW>\" and .timestamp <= \"<TS_HIGH>\") \
                  | {ts:.timestamp, preview:(.message.content | tostring | .[:250])}' \
      $SESSION"
```

Look for a `Conversation info` block with a Telegram `sender_id` arriving within ~2 s of the Lumi `chat.send` — that is the message whose answer was mis-attributed.

### 4.3 Check session lane contention

```bash
$SSH "sudo journalctl -u openclaw --no-pager | grep 'lane wait exceeded'"
```

Recurring `lane=session:agent:main:main waitedMs=…` lines confirm the queue is piling up and race windows are frequent.

---

## 5. Mitigations

Listed from cheapest / most targeted to most invasive.

### 5.1 Update OpenClaw (try first, non-invasive)

Gateway on the Pi was `2026.4.9`; the connect handshake reports `updateAvailable.latestVersion=2026.4.15`. Update and check whether the lifecycle→idempotencyKey binding logic is tightened upstream.

```bash
$SSH "npm -g install openclaw@2026.4.15 && sudo systemctl restart openclaw"
```

Re-run the detection queries after a fresh race window to confirm.

### 5.2 Lumi-side sanity check (plaster, cheap)

In `lumi/server/openclaw/delivery/sse/handler.go`, when accumulating assistant deltas for a `lumi-chat-*` run, keep a copy of the `chat.send` message that Lumi sent. On `lifecycle_end`:

- If the final assistant text has no token overlap with the original `chat.send` message **and** the run was a sensing run (message starts with `[sensing:`), log a warning and suppress TTS / downstream publishing for that run.
- Emit a monitor event `runid_mismatch_suspected` with both texts.

This does not fix the root cause but prevents speaking the wrong text.

### 5.3 Serialize Lumi sends with Telegram inbound (invasive)

Have Lumi subscribe to OpenClaw's `session.message` events and defer outbound `chat.send` when there is an unacked Telegram inbound within the last N ms on the same session. Requires coordination state on the Lumi side; only worth it if 5.1 upstream fix is not available and 5.2 plaster is not enough.

---

## 6. Related memory / context

- `project_runid_uuid_vs_lumi_chat.md` — sensing always uses `lumi-chat-*`; UUID runs are Telegram / cron / OpenClaw-initiated. This bug violates that invariant: a `lumi-chat-*` runId ends up wrapping what is effectively a Telegram turn.
- `project_guard_broadcast_evolution.md` — prior instability around chat.send reliability on Haiku; unrelated cause but overlapping surface area.
- Native thinking is confirmed firing for this session (assistant messages carry `thinking` + `thinkingSignature`), so this bug is orthogonal to the "reasoning leaked into text" issue documented elsewhere.

---

## 7. Status

- **Detected**: 2026-04-21 on `lumi-chat-26-1776759969005` (session `agent:main:main`).
- **Upstream fix**: not verified — update to `2026.4.15` and re-test before writing a Lumi-side mitigation.
- **Workaround landed**: none yet.
