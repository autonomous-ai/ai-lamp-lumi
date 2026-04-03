---
name: sensing-track
description: Query the system log to answer questions about past sensing events — "Have you seen anybody between 10pm and 12pm?", "Is there any motion in the last hour?", "What happened while I was away?".
---

# Sensing Event History

## Quick Start

The system log at `${LUMI_LOG:-/var/log/lumi.log}` records every sensing event that reached Lumi server. Use Bash to grep it and answer history questions conversationally. The file is **read-only** — never write to it.

## Log format

The file contains ANSI color codes. Strip them before parsing:

```bash
sed 's/\x1b\[[0-9;]*m//g' "${LUMI_LOG:-/var/log/lumi.log}"
```

After stripping, sensing event lines look like this:

```
2026-04-03 09:12:18 INFO  sensing event received component=sensing type=presence.enter message=Person detected — 1 face(s) visible (stranger (stranger_1))
2026-04-03 09:29:32 INFO  sensing event received component=sensing type=motion message=Large movement detected in camera view — someone may have entered or left the room
2026-04-03 09:50:04 INFO  sensing event received component=sensing type=light.level message=Ambient light decreased significantly (level: 139/255, change: -30)
```

Fields:
- `$1` — date: `YYYY-MM-DD`
- `$2` — time: `HH:MM:SS`
- `$1 " " $2` — full sortable timestamp
- `type=VALUE` — event type: `presence.enter`, `motion`, `sound`, `light.level`, `voice`
- `message=...` — description (rest of the line); may continue onto the next line as `[snapshot: /tmp/...]`

When the agent was busy and dropped the event, an additional line appears right after:

```
2026-04-03 09:59:01 INFO  sensing event received component=sensing type=presence.enter message=Person detected — 1 face(s) visible (owner (gray))
2026-04-03 09:59:01 INFO  sensing event dropped — agent busy component=sensing type=presence.enter
```

Use `"sensing event received"` as your primary grep target — it captures all events regardless of whether they were forwarded or dropped. The message field carries useful context (who was seen, what moved).

## Tools

**Bash** — grep, sed, awk. No writes.

---

## Query recipes

### All sensing events in a time range

```bash
LOG="${LUMI_LOG:-/var/log/lumi.log}"
sed 's/\x1b\[[0-9;]*m//g' "$LOG" \
  | grep "sensing event received" \
  | awk -v from="2026-04-03 22:00:00" -v to="2026-04-04 00:00:00" \
      '($1 " " $2) >= from && ($1 " " $2) <= to'
```

### Events of a specific type in the last N hours/minutes

```bash
LOG="${LUMI_LOG:-/var/log/lumi.log}"
SINCE=$(date -d "1 hour ago" "+%Y-%m-%d %H:%M:%S")
sed 's/\x1b\[[0-9;]*m//g' "$LOG" \
  | grep "sensing event received" \
  | grep "type=motion" \
  | awk -v since="$SINCE" '($1 " " $2) >= since'
```

### Any activity in the last N minutes

```bash
LOG="${LUMI_LOG:-/var/log/lumi.log}"
SINCE=$(date -d "30 minutes ago" "+%Y-%m-%d %H:%M:%S")
sed 's/\x1b\[[0-9;]*m//g' "$LOG" \
  | grep "sensing event received" \
  | awk -v since="$SINCE" '($1 " " $2) >= since'
```

### Presence events only (who came by)

```bash
LOG="${LUMI_LOG:-/var/log/lumi.log}"
sed 's/\x1b\[[0-9;]*m//g' "$LOG" \
  | grep "sensing event received" \
  | grep "type=presence.enter"
```

### What happened since a specific timestamp

```bash
LOG="${LUMI_LOG:-/var/log/lumi.log}"
SINCE="2026-04-03 15:14:00"
sed 's/\x1b\[[0-9;]*m//g' "$LOG" \
  | grep "sensing event received" \
  | awk -v since="$SINCE" '($1 " " $2) > since'
```

---

## Log rotation

Lumi rotates logs automatically (lumberjack, 1 MB cap). For questions spanning more than a few hours, include backup files:

```bash
LOG="${LUMI_LOG:-/var/log/lumi.log}"
cat "$LOG" "$LOG.1" "$LOG.2" "$LOG.3" 2>/dev/null \
  | sed 's/\x1b\[[0-9;]*m//g' \
  | grep "sensing event received" \
  | awk -v from="DATE TIME" -v to="DATE TIME" '($1 " " $2) >= from && ($1 " " $2) <= to'
```

---

## Rules

- **Never write to the log** — it is owned by the system.
- **Answer conversationally** — translate results into natural language. Never dump raw log lines to the user.
- **Handle empty results** — if no matching lines, say "I didn't detect any [type] events in that window."
- **Mention dropped events when relevant** — a dropped event means something happened physically but the agent was busy at the time. Mention it if the user is asking about missed events: "There was motion at 10:45 PM but I was mid-conversation and missed it."
- **Resolve relative times** — translate "last hour", "this morning", "while I was away" into concrete `YYYY-MM-DD HH:MM:SS` timestamps using `date -d` before filtering.
- **Check backup logs** for questions spanning several hours — lumi.log rotates at 1 MB.
- **Parse the message field** for who/what details — `owner (gray)`, `stranger (stranger_1)`, `Large movement detected`, etc. Use these to give specific answers.

---

## Examples

**Input:** "Have you seen anybody between 10pm and 12pm?"
**Action:** Query `type=presence.enter` between `22:00:00` and `00:00:00` on today's date.
**Response:** "Yes — I detected a stranger at 10:03 PM and again at 10:07 PM." or "No one came by between 10 PM and midnight."

---

**Input:** "Is there any motion in the last hour?"
**Action:** Query `type=motion` with `SINCE=$(date -d "1 hour ago" ...)`.
**Response:** "Yes, I detected large movement 3 times — at 9:29, 9:59, and 10:12." or "No motion in the last hour."

---

**Input:** "What happened while I was away?"
**Action:** Ask the user when they left, or estimate from when the last `presence.enter` was followed by a long gap. Query all events after that timestamp.
**Response:** "After around 3 PM — I saw motion at 4:30 PM and again at 5:15 PM. No one was identified though."
