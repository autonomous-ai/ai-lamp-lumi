# DEV — Debugging the Sensing → Mood → Wellbeing → TTS Pipeline

Playbook for reproducing and diagnosing agent compliance bugs on the `motion.activity` pipeline (emotional cues, wellbeing cron creation, mood logging, TTS output).

This guide assumes you have shell access and can run `sshpass` / `curl` / `python3` locally. All `<IP>` below is the Pi's LAN address (e.g. `172.168.20.125`).

---

## 1. Prerequisites

```bash
# Pi credentials (per CLAUDE.md — always ask the user before SSH'ing)
PI=pi@<IP>
PASS=12345
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no $PI"
```

Pi services:
- `lumi-server` on `:5000` (Go backend — event ingress, mood/wellbeing APIs, flow monitor)
- `nginx` on `:80` (proxy for browser UI at `http://<IP>/monitor`)
- `lelamp` on `:5001` (Python sensing + face recognition)

---

## 2. Key Files

| Path | Content | Rotation |
|---|---|---|
| `/var/log/lumi.log` | Live backend log (needs `sudo`) | rotates to `/var/log/lumi-<ts>.log` |
| `/root/local/flow_events_YYYY-MM-DD.jsonl` | Structured pipeline trace (one line per flow node: `sensing_input`, `chat_send`, `agent_thinking`, `tool_call`, `tts_send`, `hw_emotion`, etc.) | daily |
| `/root/local/users/<user>/mood/YYYY-MM-DD.jsonl` | Per-user mood log (both `signal` + `decision` rows) | daily |
| `/root/local/users/<user>/wellbeing/YYYY-MM-DD.jsonl` | Per-user wellbeing activity log | daily |
| `/root/local/users/<user>/music-suggestions/YYYY-MM-DD.jsonl` | Per-user music suggestion history | daily |
| `/root/.openclaw/cron/jobs.json` | Current crons | replaced atomically |
| `/root/.openclaw/cron/jobs.json.bak` | Previous state of jobs.json | |
| `/var/log/lumi/snapshots/` | Camera snapshots per event | |

`<user>` is `alex`, `gray`, or `unknown` (all strangers collapse to `unknown`).

---

## 3. When `motion.activity` actually fires

LeLamp dedups the outbound stream so Lumi only sees events that matter. Understanding the rule is essential before reading any log or running any test.

### Dedup key

```
key = (current_user, frozenset(raw_actions))
```

- `current_user` comes from `FaceRecognizer.current_user()` — the most recent friend still within the forget window, else `"unknown"` if any stranger is visible, else empty (in which case the event isn't sent anyway — no presence).
- `raw_actions` is the set of raw Kinetics labels that passed the whitelist (e.g. `using computer`, `drinking`, `eating burger`). Emotional labels are filtered out upstream and never reach the dedup key. Keying on raw labels is intentionally looser than the old bucket-level key — `writing` → `drawing` now flips the key so the agent sees the new label.

### Send / drop rule

```
SEND if:
  key != last_sent_key                 # state changed (user / raw action set)
  OR (key == last_sent_key and now - last_sent_ts >= 5 min)   # wake-up

DROP if:
  key == last_sent_key and gap < 5 min
```

A user change always flips the key. Different strangers collapse to `"unknown"` so swapping strangers alone does **not** flip the key — the dedup keeps holding.

### Basic timeline (user Alex sits down and works)

| Time | State | Result |
|---|---|---|
| 09:00 | Alex enters → using computer | SEND (first) |
| 09:01 | Alex still using computer | DROP (key same, <5 min) |
| 09:04 | Alex still using computer | DROP |
| 09:05 | Alex still using computer | **SEND** (≥5 min wake-up) |
| 09:06 | Alex switches to writing | SEND (raw action set changed) |
| 09:07 | Alex still writing | DROP |
| 09:10 | Alex + drinking | SEND (action set changed) |
| 09:15 | Alex gone, stranger arrives | SEND (current_user flipped to "unknown") |

### Quick mental model

- Raw action appears, changes, or disappears → SEND.
- User changes (friend↔friend, friend↔unknown, unknown↔friend) → SEND.
- Everything identical for 5 min straight → SEND anyway (so the wellbeing threshold check still runs).
- Otherwise → DROP.

---

## 4. Simulate an Event

The backend accepts fake sensing events on `POST /api/sensing/event`. You don't need real camera input — just craft the message and curl it.

```bash
$SSH "curl -s -X POST http://127.0.0.1:5000/api/sensing/event \
  -H 'Content-Type: application/json' \
  -d '{\"type\":\"motion.activity\",\"message\":\"Activity detected: using computer.\"}'"
# → {"status":1,"data":{"runId":"lumi-chat-<seq>-<ms>"},"message":null}
```

Emotional cues (`laughing`, `crying`, `yawning`, `singing`) are filtered at LeLamp and never reach Lumi — there is no way to inject them via `motion.activity` anymore. A future `motion.emotional` event will carry them.

Common test payloads (raw Kinetics labels — agent maps each to `drink`/`break`/`sedentary` bucket):

```jsonc
// Sedentary only — agent logs "sedentary", may nudge if drink/break threshold elapsed
{"type":"motion.activity","message":"Activity detected: using computer. If nothing noteworthy, reply NO_REPLY."}

// Mixed sedentary — agent logs one "sedentary" entry (bucket-dedup at agent level)
{"type":"motion.activity","message":"Activity detected: writing, reading book."}

// Drink action — agent logs a "drink" bucket entry
{"type":"motion.activity","message":"Activity detected: drinking."}

// Break action — agent logs a "break" bucket entry
{"type":"motion.activity","message":"Activity detected: eating burger."}

// Mixed bucket — agent logs both "drink" and "sedentary"
{"type":"motion.activity","message":"Activity detected: drinking, using computer."}

// Friend enters — should set current_user to their name
{"type":"presence.enter","message":"Person detected — 1 face(s) visible (friend (leo))"}

// Stranger enters — should set current_user to "unknown"
{"type":"presence.enter","message":"Person detected — 1 face(s) visible (stranger (stranger_99))"}
```

**Save the `runId` from the response — everything downstream is keyed on it.**

---

## 5. Trace a Specific Run

### 4.1 Raw flow trace (structured)

```bash
$SSH "echo $PASS | sudo -S grep '<runId_ms_suffix>' /root/local/flow_events_$(date +%Y-%m-%d).jsonl"
```

Filter by node type to understand what happened:

```bash
# Full trace
grep '<runId>' flow_events.jsonl | python3 -c '
import json, sys
for line in sys.stdin:
    d = json.loads(line)
    print(d["node"], "|", d["kind"], "|", str(d.get("data",{}))[:200])
'

# What the agent saw (input)
grep '<runId>' flow_events.jsonl | python3 -c '…' # filter node=="chat_send"

# What the agent thought
grep '<runId>' flow_events.jsonl | python3 -c '…' # filter node=="agent_thinking"

# What tools the agent called
grep '<runId>' flow_events.jsonl | python3 -c '…' # filter node=="tool_call" and phase=="start"

# What the agent actually said aloud
grep '<runId>' flow_events.jsonl | python3 -c '…' # filter node=="tts_send"
```

### 4.2 Aggregated flow API (for UI)

```bash
$SSH "curl -s 'http://127.0.0.1:5000/api/openclaw/flow-events?last=200'" \
  | python3 -c 'import json,sys; [print(e["id"], e.get("runId","-")[-12:], e["summary"][:80]) for e in json.load(sys.stdin)["data"]["events"]]'
```

### 4.3 Browser Flow Monitor

`http://<IP>/monitor` — refresh (F5) to see new events. Groups by `runId` into "turns".

---

## 6. Verify Each Stage

For a single motion.activity event, the expected chain is:

| Stage | Expected | How to verify |
|---|---|---|
| Ingress | `sensing event received type=motion.activity` in lumi.log | `sudo grep 'sensing event received' /var/log/lumi.log \| tail` |
| Forward | `chat_send` node with `[context: current_user=X]` + `[MANDATORY: …]` | grep flow JSONL for `chat_send` |
| Agent lifecycle | `lifecycle_start` → `lifecycle_end` | same |
| Mood signal log | POST to `/api/mood/log` with `kind=signal` | check `tool_call` with `curl .*mood/log` in args |
| Mood decision log | POST to `/api/mood/log` with `kind=decision` | same (should see 2 separate POSTs) |
| Mood file updated | new lines in `/root/local/users/<current_user>/mood/YYYY-MM-DD.jsonl` | `sudo tail` the file |
| Wellbeing log (sedentary/drink/break) | POST to `/api/wellbeing/log` per group → new line in `/root/local/users/<current_user>/wellbeing/YYYY-MM-DD.jsonl`. Backend dedups consecutive same-action entries silently. | `sudo tail <jsonl>` |
| Wellbeing nudge (threshold) | If prior drink/break exists and delta > threshold, `tts_send` contains a one-sentence nudge. No cron involved. | grep `tts_send` + inspect wellbeing log deltas |
| Presence markers | `presence.enter` / `presence.leave` / `presence.away` each write an `enter` or `leave` line to the same wellbeing JSONL (backend auto — agent not involved) | `sudo tail <jsonl>` |
| TTS | `tts_send` node with **only** the caring observation (1 sentence). No plan narration. | filter `tts_send` |
| HW marker | `hw_emotion` node with args matching the emotion mapping | same |

---

## 7. Common Compliance Failures We've Hit

The agent is LLM-driven so "the code is correct" doesn't guarantee "the agent complies". These are real bugs we diagnosed via this playbook (see commit history around 2026-04-20 for fixes).

### 6.1 Agent skips mood logging entirely
**Symptom:** `tool_call` trace contains no `/api/mood/log` call. Mood JSONL empty despite events firing.
**Diagnose:** grep `tool_call` for `mood/log` — zero hits.
**Fix path:** strengthen MANDATORY directive in `lumi/server/sensing/delivery/http/handler.go` and `user-emotion-detection/SKILL.md` to explicitly chain to Mood skill.

### 6.2 Agent bijas mood payload schema
**Symptom:** `POST /api/mood/log` returns `Field validation for 'Mood' failed on the 'required' tag`.
**Diagnose:** inspect `tool_call` args — payload has `{"signal":"...","decision":"..."}` instead of `{"kind":"signal","mood":"...",...}`.
**Fix path:** directive must say "TWO separate POSTs, first kind=signal then kind=decision" — not "log signal + decision" (which reads as one call with both fields).

### 6.3 Agent hallucinates user name
**Symptom:** Face system saw only `stranger_XX` all day, but wellbeing cron is named `Wellbeing: Leo break` and mood is logged under `user=leo`.
**Diagnose:** grep presence.enter events — verify all are strangers. Check `jobs.json` and `/root/local/users/leo/`.
**Root cause:** agent pulled "Leo" from KNOWLEDGE.md / chat history / senderLabel instead of trusting presence detection.
**Fix path:** backend injects `[context: current_user=X]` tag into motion.activity messages; Wellbeing SKILL forbids inferring from any other source. `mood.SetCurrentUser("unknown")` must be called on stranger `presence.enter` (not just friends).

### 6.4 Agent narrates plan/thinking into TTS
**Symptom:** TTS says *"Leo's hydration cron exists but no break cron. Need to create break cron for unknown + hydration & break for unknown, then post mood decision. Now create both wellbeing crons + log activity: Someone's having a good laugh! 😄"*
**Diagnose:** grep `tts_send` nodes — look for "Need to…", "Now I'll…", "Since X, I should…" patterns before the caring line.
**Fix path:** explicit rule in `SOUL.md` and `sensing/SKILL.md` — reply text is spoken verbatim, all planning MUST stay in `thinking`.

### 6.5 Wellbeing nudge logic (historical evolution)
**Original:** cron-based — the agent created 2 cron jobs on first sedentary and frequently created only one.
**Interim:** event-driven with a "prior entry exists" guard — never nudged a user who sat down and never got up.
**Now:** event-driven with `presence.enter` as the session baseline. `reset_ts = max(last <kind> entry, last enter entry)`, delta counts up from 0 after arrival. A fresh sit-down doesn't spam (delta = 0); a long sit-down without break/drink does nudge once the threshold passes.
**Failure modes to watch:**
- Nudge fires at t=0 with no `enter` or prior activity in the log → backend isn't writing the `enter` marker, or the agent is ignoring the reset rule and guessing from memory.
- No nudge after a long sit without drink/break → the agent may have reintroduced a "prior entry exists" guard; re-read the SKILL Step 4.

### 6.6 Music suggestion didn't fire after sedentary
**Symptom:** `sedentary` event but no new row in `users/<user>/music-suggestions/`.
**Diagnose:** check last suggestion timestamp — if `< 30 min ago`, this is **correct** (30-min cooldown per `music/SKILL.md:117`). Not a bug.

---

## 8. Cleanup After Testing

```bash
# Remove a specific cron by ID
$SSH "curl -s -X POST http://127.0.0.1:5000/api/openclaw/cron -d '{\"action\":\"remove\",\"id\":\"<cron-id>\"}'"

# Clear mood for a user (manual — no API, just truncate)
$SSH "echo $PASS | sudo -S truncate -s 0 /root/local/users/<user>/mood/$(date +%Y-%m-%d).jsonl"

# Restart lumi-server (picks up new binary after OTA deploy)
$SSH "echo $PASS | sudo -S systemctl restart lumi"
```

---

## 9. When to Just Ask the User

- Anything that changes production state outside this pipeline (face enrollments, config edits, telegram bindings) — ask first.
- Before rebuilding + pushing a new binary — confirm deploy path (OTA vs scp vs make).
- When SSH'ing for the first time in a session — `sshpass` is a destructive-adjacent tool; per `CLAUDE.md` always ask.

---

## 10. Reference: Agent Compliance is the Fragile Part

The Go backend is deterministic. The Python sensing layer is deterministic. The **agent layer** (OpenClaw → LLM) is where behavior drifts. When a pipeline stops working end-to-end despite no code change:

1. **First check the directive text** actually injected into the chat_send message. Did you deploy? Is the new directive present?
2. **Then check agent_thinking** — does the LLM acknowledge the directive and plan the right steps?
3. **Then check tool_call args** — did it call the right endpoints with the right payloads?
4. **Then check side-effects** (JSONL files, cron list).

Most "the feature broke" reports resolve at step 2 or 3 — the LLM read the directive but decided to do something else. Fix by making the directive more imperative, giving exact payloads, or moving the work into deterministic code so the agent can't skip it.
