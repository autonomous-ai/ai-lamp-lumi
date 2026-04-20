---
name: wellbeing
description: Event-driven hydration and break reminders. Reads the per-user activity JSONL on every motion.activity to decide whether to nudge — no cron jobs. Thresholds are computed from the log, never guessed.
---

# Wellbeing

## Quick Start

Wellbeing is **event-driven**, not cron-driven. There are no wellbeing cron jobs. On every `motion.activity` event, you:

1. Log the activity (drink/break/sedentary) — backend dedups consecutive same-action entries automatically.
2. Read the recent history.
3. Compute `minutes_since_last_drink` and `minutes_since_last_break` from the log (NEVER guess from memory or vibes).
4. If either is over its threshold, speak a short caring nudge. Otherwise stay quiet.

Presence `enter` / `leave` events are logged automatically by the backend — they break the dedup chain so same-action entries across different sittings are preserved.

## User attribution — hard rule

Every `user` field in this skill MUST come from the `[context: current_user=X]` tag that the backend injects into the triggering `motion.activity` message.

- Strangers collapse to `"unknown"` — all strangers share one timeline.
- **NEVER** infer `{user}` from memory, KNOWLEDGE.md, chat history, `senderLabel`, or any other source.
- If no context tag is present, default to `"unknown"`.

## Thresholds

**USE THESE EXACT VALUES — do not substitute anything else:**

```
HYDRATION_THRESHOLD_MIN = 5
BREAK_THRESHOLD_MIN     = 7
```

> ⚠ **Release checklist (NOT ACTIVE YET):** before shipping to production, edit this SKILL to change `HYDRATION_THRESHOLD_MIN` to `45` and `BREAK_THRESHOLD_MIN` to `30`. Until that edit lands, the active values are **5 / 7**. Do not use 45 or 30 — those are future values, not current ones.

`HYDRATION_THRESHOLD_MIN` and `BREAK_THRESHOLD_MIN` are intentionally different in test so you can tell which path fired. There is no separate nudge cooldown — nudging itself counts as a "reset", so after Lumi reminds, the delta goes back to 0 and the next nudge of the same kind only fires after another full threshold window.

## On `motion.activity`

For each `Activity detected:` group in the message (zero or more of `drink`, `break`, `sedentary`):

### Step 1 — Log the activity

```bash
curl -s -X POST http://127.0.0.1:5000/api/wellbeing/log \
  -H 'Content-Type: application/json' \
  -d '{"action":"<group>","notes":"<optional>","user":"<current_user>"}'
```

One POST per group. Backend dedups automatically — if the previous entry has the same action, the new POST is silently dropped. You don't need to check before posting.

> `Emotional cue:` is handled by the **Emotion Detection** skill — not this skill. Do not log emotional cues here.

### Step 2 — Read recent history

```bash
curl -s "http://127.0.0.1:5000/api/openclaw/wellbeing-history?user=<current_user>&last=50"
```

Response is a time-ordered list of events with `{ts, action, notes, hour}`.

### Step 3 — Compute deltas

For each of hydration and break, the delta is measured from the **most recent reset point**. A "reset point" is any of:
- The last actual activity of that type (`drink` for hydration, `break` for break).
- The last `enter` entry — a fresh session counts as a reset because the user just arrived.
- The last nudge of that type (`nudge_hydration` / `nudge_break`) — after reminding, the clock resets as if the user had acted. This avoids re-nudging every wake-up event while the user hasn't drunk/broken yet; they'll get reminded again after another full threshold window.

```
hydration_reset_ts = max(
    last drink entry ts,
    last enter entry ts,
    last nudge_hydration entry ts,
)
minutes_since_last_drink = (now - hydration_reset_ts) / 60

break_reset_ts = max(
    last break entry ts,
    last enter entry ts,
    last nudge_break entry ts,
)
minutes_since_last_break = (now - break_reset_ts) / 60
```

If none of these entries exist for the user today, treat the delta as 0 — nothing to nudge yet.

### Step 4 — Decide whether to nudge

Apply in this order — nudge at most **one** thing per turn:

1. `minutes_since_last_drink >= HYDRATION_THRESHOLD_MIN` → speak a hydration nudge.
2. `else if minutes_since_last_break >= BREAK_THRESHOLD_MIN` → speak a break nudge.
3. `else` → respond to the event normally (caring observation if natural) or `NO_REPLY` if nothing to add.

The reset rules in Step 3 are what prevent spam: after Lumi nudges, the `nudge_hydration` (or `nudge_break`) entry counts as a reset, so the delta drops back to 0 and the next nudge of that kind only fires after another full threshold window. A fresh arrival (`enter`) works the same way — the delta starts at 0 and counts up.

**Hard rule: if you decide NOT to nudge, the reply is `NO_REPLY` or a plain caring observation — NEVER narrate the skip reason.** Do not say *"just nudged 1 min ago, no repeat"*, *"both over threshold but skipping"*, *"dedup applies"*, etc. These are internal decisions that stay in `thinking`. The user only hears actual nudges, never "why I didn't nudge". The log (timeline) is the evidence — if there's no `nudge_hydration` entry, the user didn't get a nudge, regardless of what the agent may have said in a previous turn's thinking.

**Also: trust the log, not memory.** If the wellbeing history response contains NO `nudge_hydration` entry, then no nudge has happened — ignore any self-memory that claims otherwise. Memory is unreliable across turns; the log is the source of truth.

Example nudges (vary your wording each time — never repeat verbatim):

- Hydration: *"Been a while since you drank — grab some water?"*, *"Hydration check — time for a glass?"*
- Break: *"You've been at it for a while — stretch break?"*, *"Quick stand-up? Your back will thank you."*

### Step 5 — Log the nudge after speaking (for timeline only)

If you spoke a hydration nudge, immediately POST:

```bash
curl -s -X POST http://127.0.0.1:5000/api/wellbeing/log \
  -H 'Content-Type: application/json' \
  -d '{"action":"nudge_hydration","notes":"<your nudge text>","user":"<current_user>"}'
```

Same for break → `action="nudge_break"`. This is purely for **timeline visibility** — so the user's activity log shows when Lumi actually reminded them. It does NOT affect the next nudge decision (threshold check stays based on `drink`/`break` entries only).

### Step 6 — Never narrate the mechanics

Your reply is spoken aloud verbatim. The ONLY thing the user should hear is the one caring sentence — never the reasoning behind it.

**FORBIDDEN in the reply text** (put these in `thinking` only):

- Any number of minutes (e.g. *"76.7 min"*, *"over 45 min threshold"*, *"it's been 2 hours"*).
- Any comparison to thresholds (e.g. *"way over"*, *"almost due"*, *"under the limit"*).
- Any plan-talk (*"Need to nudge for both"*, *"Now I'll remind about…"*).
- Any log/data references (*"Drink:"*, *"Break:"*, *"Last entry:"*).

**Correct:** *"Hey, grab some water — it's been a while."*
**Wrong:** *"Drink: 76.7 min — way over 45 min threshold! Hey, drink water!"*

If you see yourself writing numbers, colons, or the word "threshold" in the reply, delete it and rewrite in natural caring language. One sentence. Nothing more.

## On `presence.enter` / `presence.leave` / `presence.away`

Backend handles the log writes automatically. You don't need to call `/api/wellbeing/log` for these.

- `presence.leave`: stay silent (NO_REPLY) unless there's something worth saying.
- `presence.away`: stay silent.

There are NO crons to cancel. Wellbeing is stateless at the timer level — the log IS the state.

## API Reference

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `http://127.0.0.1:5000/api/wellbeing/log` | POST | Append activity entry `{"action","notes","user"}` — backend dedups |
| `http://127.0.0.1:5000/api/openclaw/wellbeing-history?user=X&date=YYYY-MM-DD&last=N` | GET | Read activity history |
| `http://127.0.0.1:5001/user/info?name=X` | GET | Get telegram_id, is_friend (only needed if you DM via Telegram) |

`action` values:

| Action | Written by | Meaning |
|---|---|---|
| `drink`, `break`, `sedentary`, `emotional` | Agent (from motion.activity groups) | User activity transition |
| `enter`, `leave` | Backend (on presence.* events) | Session boundary — breaks dedup chain |
| `nudge_hydration`, `nudge_break` | Agent (after speaking a nudge) | Records when Lumi actually reminded the user — powers cooldown + timeline visibility |

## Principles

- **Log is the source of truth.** Never guess "it's been a while" — always compute from the log.
- **Backend handles dedup and session markers** — you just post and query.
- **One nudge per turn max.** Hydration takes priority over break if both are due.
- **You're a companion, not an alarm clock.** If the user says "don't remind me about X" → skip the corresponding nudge for the rest of the session.
- **Invisible mechanics.** Never mention thresholds, logs, deltas, or skill names in the reply.
- **All strangers share one timeline** under `user="unknown"`. Do not distinguish stranger_46 vs stranger_54.
