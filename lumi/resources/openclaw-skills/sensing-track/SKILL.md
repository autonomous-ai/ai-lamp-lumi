---
name: sensing-track
description: Query flow event logs to answer questions about past sensing events — "Have you seen anybody between 10pm and 12pm?", "Is there any motion in the last hour?", "What happened while I was away?".
---

# Sensing Event History

## Quick Start

The primary data source is the **flow events JSONL** at `/root/local/flow_events_YYYY-MM-DD.jsonl`. Each file covers one calendar day (30-day retention, no size-rotation mid-day). Use Bash + `jq` to query it.

> **Important:** Always use the absolute path `/root/local/` — the `read` tool cannot access files outside the workspace, so use `exec` (Bash) for all JSONL queries.

Persistent camera snapshots are stored in `/var/log/lumi/snapshots/` (72h TTL, 50 MB cap). Reference these when the user asks what happened visually.

## JSONL format

Each line is a JSON object:

```json
{"kind":"enter","node":"sensing_input","ts":1712345678.123,"seq":42,"trace_id":"run-abc","data":{"type":"presence.enter","message":"Person detected — 1 face(s) visible (owner (gray))\n[snapshot: /var/log/lumi/snapshots/sensing_1712345678123.jpg]"},"version":"1.2.3"}
{"kind":"exit","node":"sensing_input","ts":1712345678.456,"seq":43,"trace_id":"run-abc","duration_ms":332,"data":{"path":"agent","run_id":"run-abc"},"version":"1.2.3"}
```

Key fields:
- `node` — filter on `"sensing_input"` for sensing events
- `kind` — `"enter"` = event received, `"exit"` = event processed (with `duration_ms`)
- `data.type` — event type: `presence.enter`, `presence.leave`, `motion`, `motion.activity`, `sound`, `light.level`, `voice`, `voice_command`, `wellbeing.hydration`, `wellbeing.break`, `music.mood`
- `data.message` — natural-language description; may contain `[snapshot: /var/log/lumi/snapshots/...]`
- `data.path` — in `exit` records: `"agent"` (forwarded), `"local"` (handled locally), or has `"error"` key (failed/dropped)
- `ts` — Unix timestamp (seconds with fractional ms)
- `trace_id` — correlates enter/exit and links to agent turn

## Tools

**Bash** — `jq`, `cat`, date arithmetic. No writes.

---

## Query recipes

### All sensing events in a time range

```bash
DATE="2026-04-03"
FROM_TS=$(date -d "$DATE 22:00:00" +%s)
TO_TS=$(date -d "$DATE 23:59:59" +%s)
jq -c 'select(.node=="sensing_input" and .kind=="enter" and .ts >= '"$FROM_TS"' and .ts <= '"$TO_TS"')' \
  "/root/local/flow_events_${DATE}.jsonl"
```

### Events of a specific type in the last N hours

```bash
SINCE=$(date -d "1 hour ago" +%s)
TODAY=$(date +%Y-%m-%d)
jq -c 'select(.node=="sensing_input" and .kind=="enter" and .ts >= '"$SINCE"' and .data.type=="motion")' \
  "/root/local/flow_events_${TODAY}.jsonl"
```

### Any activity in the last N minutes

```bash
SINCE=$(date -d "30 minutes ago" +%s)
TODAY=$(date +%Y-%m-%d)
jq -c 'select(.node=="sensing_input" and .kind=="enter" and .ts >= '"$SINCE"')' \
  "/root/local/flow_events_${TODAY}.jsonl"
```

### Presence events only (who came by)

```bash
TODAY=$(date +%Y-%m-%d)
jq -c 'select(.node=="sensing_input" and .kind=="enter" and (.data.type=="presence.enter" or .data.type=="presence.leave"))' \
  "/root/local/flow_events_${TODAY}.jsonl"
```

### Events spanning multiple days

```bash
cat /root/local/flow_events_2026-04-02.jsonl /root/local/flow_events_2026-04-03.jsonl \
  | jq -c 'select(.node=="sensing_input" and .kind=="enter" and .ts >= '"$FROM_TS"' and .ts <= '"$TO_TS"')'
```

### Dropped events (agent was busy)

```bash
TODAY=$(date +%Y-%m-%d)
jq -c 'select(.node=="sensing_input" and .kind=="exit" and .data.error != null)' \
  "/root/local/flow_events_${TODAY}.jsonl"
```

### List snapshots for a time range

```bash
ls -lt /var/log/lumi/snapshots/ | head -20
```

---

## Fallback: system log

For detailed debugging or when you need Go-side log context (errors, warnings, lifecycle details), fall back to `${LUMI_LOG:-/var/log/lumi.log}`:

```bash
LOG="${LUMI_LOG:-/var/log/lumi.log}"
sed 's/\x1b\[[0-9;]*m//g' "$LOG" | grep "sensing event received"
```

The system log uses lumberjack rotation (1 MB cap, 3 backups) — it may miss data during high traffic. Use it only when JSONL doesn't have enough detail, or when investigating bugs.

---

## Mood history

A dedicated mood history log tracks **user mood** per user. Only the user's emotional state is logged — not system events or lamp emotions. Each user's mood data lives in their own directory.

**Read API:**
```bash
# Current user's mood history (auto-detects who's present)
curl -s "http://127.0.0.1:5000/api/openclaw/mood-history?date=$(date +%Y-%m-%d)&last=100"

# Specific user's mood history
curl -s "http://127.0.0.1:5000/api/openclaw/mood-history?user=gray&date=$(date +%Y-%m-%d)&last=100"
```

**Write API** (call this when you detect user mood from camera or conversation):
```bash
curl -s -X POST http://127.0.0.1:5000/api/mood/log \
  -H 'Content-Type: application/json' \
  -d '{"mood":"happy","source":"camera","trigger":"laughing"}'
```

Each entry has: `mood` (happy, sad, stressed, tired, excited, etc.), `source` (camera or conversation), `trigger` (what caused it).

```json
{"ts":1776138500,"seq":1,"hour":10,"mood":"happy","source":"camera","trigger":"laughing"}
{"ts":1776139200,"seq":2,"hour":10,"mood":"stressed","source":"conversation","trigger":"user said feeling overwhelmed"}
```

Storage: `/root/local/users/{name}/mood/YYYY-MM-DD.jsonl` (30-day retention).

---

## Rules

- **Never write to any log file** — they are owned by the system.
- **Answer conversationally** — translate results into natural language. Never dump raw JSON to the user.
- **Handle empty results** — if no matching events, say "I didn't detect any [type] events in that window."
- **Mention dropped events when relevant** — check `exit` records with `data.error` for events the agent missed. Mention it: "There was motion at 10:45 PM but I was mid-conversation and missed it."
- **Resolve relative times** — translate "last hour", "this morning", "while I was away" into concrete Unix timestamps using `date -d` before filtering.
- **Span multiple days** — for questions covering more than today, `cat` multiple JSONL files together.
- **Parse the message field** for who/what details — `owner (gray)`, `friend (chloe)`, `stranger (stranger_1)`, `Large movement detected`, etc.
- **Reference snapshots** — when the user asks "what did you see?", extract the `[snapshot: ...]` path from the message and mention it. The snapshot is viewable at `/var/log/lumi/snapshots/`.

---

## Examples

**Input:** "Have you seen anybody between 10pm and 12pm?"
**Action:** Query `data.type` in `["presence.enter"]` between 22:00 and 00:00 from today's JSONL.
**Response:** "Yes — I detected a stranger at 10:03 PM and again at 10:07 PM." or "No one came by between 10 PM and midnight."

---

**Input:** "Is there any motion in the last hour?"
**Action:** Query `data.type=="motion"` with `SINCE=$(date -d "1 hour ago" +%s)`.
**Response:** "Yes, I detected large movement 3 times — at 9:29, 9:59, and 10:12." or "No motion in the last hour."

---

**Input:** "What happened while I was away?"
**Action:** Ask the user when they left, or find the last `presence.leave` and query all events after that timestamp.
**Response:** "After around 3 PM — I saw motion at 4:30 PM and again at 5:15 PM. No one was identified though. I have snapshots from those moments if you want to see."
