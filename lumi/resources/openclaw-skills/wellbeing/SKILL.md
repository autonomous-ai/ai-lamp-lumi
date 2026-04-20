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

```
HYDRATION_THRESHOLD_MIN = 5   # test value — production: 45
BREAK_THRESHOLD_MIN     = 5   # test value — production: 30
```

> ⚠ **Release checklist:** before shipping, change both thresholds to the production values (45 / 30). Test values are for rapid iteration during development.

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

From the list, find the timestamp of:

- The most recent entry with `action="drink"` → `minutes_since_last_drink = (now - ts) / 60`
- The most recent entry with `action="break"` → `minutes_since_last_break = (now - ts) / 60`

If no matching entry exists today, treat the delta as infinite (fresh session).

### Step 4 — Decide whether to nudge

Apply in this order — nudge at most **one** thing per turn:

1. **No prior entry today?** → NO nudge. Infinite delta = fresh session, not overdue. Wait until the user has at least one `drink` or `break` entry before you start nudging.
2. `minutes_since_last_drink >= HYDRATION_THRESHOLD_MIN` **and a prior `drink` entry exists** → speak a hydration nudge (one short sentence, caring, varied).
3. `else if minutes_since_last_break >= BREAK_THRESHOLD_MIN` **and a prior `break` entry exists** → speak a break nudge (stretch, stand up, walk).
4. `else` → respond to the event normally (caring observation if natural) or `NO_REPLY` if nothing to add.

The "prior entry exists" guard prevents spamming the user the moment they sit down. Once they've drunk or broken once today, the threshold-based nudges kick in normally.

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

Your reply is spoken aloud. Do NOT write things like *"Last drink was 47 min ago, over the threshold, so I should remind…"* — that belongs in `thinking` only. The reply is just the one caring sentence.

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
