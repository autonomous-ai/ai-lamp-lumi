---
name: wellbeing
description: Event-driven hydration and break reminders. Reads the per-user activity JSONL on every motion.activity to decide whether to nudge — no cron jobs. Thresholds are computed from the log, never guessed.
---

# Wellbeing

> **Reply is spoken VERBATIM.** ONE short caring nudge — *"Grab some water?"*. All computation (timestamps, deltas, thresholds) stays in `thinking`. NEVER output math, log entries, or skip reasons in the reply.

## Quick Start

Wellbeing is **event-driven**, not cron-driven. There are no wellbeing cron jobs. On every `motion.activity` event, you:

1. Read the `Activity detected:` line. LeLamp already categorises — it sends the bucket name for physical actions (`drink`, `break`) and the raw Kinetics label for sedentary activities (`using computer`, `writing`, `reading book`, `texting`, `reading newspaper`, `drawing`, `playing controller`). Example: `Activity detected: drink, using computer.`
2. POST one wellbeing row per label, verbatim — the value on the line IS the `action` field. No bucket mapping in your head.
3. Read the recent history.
4. Figure out silently how long it's been since the last reset point for hydration and for break (never guess from memory).
5. If either delta is over its threshold, speak a short caring nudge. Otherwise stay quiet.

Presence `enter` / `leave` markers are written automatically by the backend when people arrive or leave — agent never posts those.

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

## What's in `Activity detected:`

LeLamp does the categorisation. The labels on the `Activity detected:` line are already the final `action` values — log them verbatim.

| Category | Labels emitted on `Activity detected:` |
|---|---|
| Drink (bucket, collapsed) | `drink` |
| Break (bucket, collapsed) | `break` |
| Sedentary (raw Kinetics label) | `using computer`, `writing`, `texting`, `reading book`, `reading newspaper`, `drawing`, `playing controller` |

Emotional actions (`laughing`, `crying`, `yawning`, `singing`) are filtered upstream and never appear on `motion.activity`.

## On `motion.activity`

Split the `Activity detected:` line on comma, strip whitespace, and for every label present:

### Step 1 — Log the activity

```bash
curl -s -X POST http://127.0.0.1:5000/api/wellbeing/log \
  -H 'Content-Type: application/json' \
  -d '{"action":"<label verbatim>","notes":"","user":"<current_user>"}'
```

One POST per label. Example: message says `Activity detected: drink, using computer, writing.` → POST `action=drink`, POST `action=using computer`, POST `action=writing`. LeLamp already deduped the incoming `motion.activity` (same user + same label set within 5 min won't reach you), so by the time you see the event it's "new enough to log" — just POST and move on.

> `motion.activity` no longer carries emotional cues — emotional actions will arrive via a separate `motion.emotional` event in a future version. This skill handles the physical labels listed above.

### Step 2 — Read recent history

```bash
curl -s "http://127.0.0.1:5000/api/openclaw/wellbeing-history?user=<current_user>&last=50"
```

Response is a time-ordered list of events with `{ts, action, notes, hour}`.

### Step 3 — Compute deltas (in your head, silently)

**Do NOT output any of this math. All computation stays in `thinking`.** These instructions tell you WHAT to compute, not what to write in the reply.

For hydration, find the most recent of these three log entries: a `drink`, an `enter`, or a `nudge_hydration`. The time since that entry (in minutes) is your hydration delta. The same method applies to break, using `break`, `enter`, and `nudge_break` as the reset candidates.

Why all three count as resets:
- A `drink` / `break` entry means the user actually acted.
- An `enter` entry means this is a fresh session (just arrived — zero the clock).
- A `nudge_*` entry means Lumi already reminded them; don't re-nudge until another full threshold window passes.

**Sedentary raw-label entries** (`using computer`, `writing`, `reading book`, `texting`, `reading newspaper`, `drawing`, `playing controller`) are **NOT** reset points. They're logged for timeline visibility and to inform nudge phrasing, but don't advance the hydration or break clock.

If none of those entries exist yet for today, treat the delta as 0 — there's nothing to nudge about.

### Step 4 — Decide whether to nudge (silently)

Nudge at most one thing per turn. Hydration takes priority over break.

- If the hydration delta is at or over the hydration threshold, speak a hydration nudge.
- Otherwise, if the break delta is at or over the break threshold, speak a break nudge.
- Otherwise, respond to the event normally (a caring observation if it feels natural) or reply `NO_REPLY`.

The reset rules in Step 3 keep this from spamming — once you nudge, the `nudge_*` entry resets the delta and the next reminder of that kind only fires after another full threshold window.

**Hard rule: if you decide NOT to nudge, the reply is `NO_REPLY` or a plain caring observation — NEVER narrate the skip reason.** Don't say "just nudged N min ago, no repeat", "both over threshold but skipping", "dedup applies", etc. Those are internal decisions that stay in `thinking`. The user only hears actual nudges, never "why I didn't nudge". The log (timeline) is the evidence — if there's no `nudge_hydration` entry, the user didn't get a nudge, regardless of what the agent may have thought on a previous turn.

**Trust the log, not memory.** If the wellbeing history response contains no `nudge_hydration` entry, no nudge has happened — ignore any self-memory that claims otherwise. Memory is unreliable across turns; the log is the source of truth.

### Ground the nudge in the current raw label

The triggering `motion.activity` lists the raw Kinetics labels the user is doing right now. Tailor the nudge to the most specific sedentary label present so the reminder feels observed, not generic. Vary wording each time — never repeat verbatim.

| Raw label seen now | Hydration nudge example | Break nudge example |
|---|---|---|
| `using computer` | *"Been at the screen — grab a glass of water?"* | *"Eyes off the screen for a sec?"* |
| `writing` | *"Pen down for some water?"* | *"Wrist break — time to stretch."* |
| `texting` | *"Phone down, water break?"* | *"Phone down — stand up for a sec?"* |
| `reading book` | *"Bookmark it and grab some water?"* | *"Been reading a while — give your eyes a rest?"* |
| `reading newspaper` | *"Page down, time for water?"* | *"Eyes need a break from the page?"* |
| `drawing` | *"Brush down, sip of water?"* | *"Hands cramping? Quick stretch."* |
| `playing controller` | *"Pause and grab some water?"* | *"Been gaming a while — stand up?"* |
| (no specific label / generic) | *"Been a while since you drank — grab some water?"* | *"Quick stand-up? Your back will thank you."* |

If multiple sedentary labels are present (e.g. `writing, reading book`), pick the one that fits best or blend (*"Eyes and wrists both deserve a break."*). The table is a starting point, not a script — keep it natural and one short sentence.

### Step 5 — Log the nudge after speaking (for timeline only)

If you spoke a hydration nudge, immediately POST:

```bash
curl -s -X POST http://127.0.0.1:5000/api/wellbeing/log \
  -H 'Content-Type: application/json' \
  -d '{"action":"nudge_hydration","notes":"<your nudge text>","user":"<current_user>"}'
```

Same for break → `action="nudge_break"`. This entry serves two purposes: timeline visibility (the user's log shows when Lumi actually reminded them) AND delta reset (Step 3 treats the nudge entry as a reset point, so the next reminder of that kind waits a full threshold window).

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
| `drink`, `break` | Agent (verbatim from motion.activity — LeLamp already collapsed to bucket) | User actually drank / took a break. **Reset point** for the corresponding timer. |
| `using computer`, `writing`, `texting`, `reading book`, `reading newspaper`, `drawing`, `playing controller` | Agent (verbatim from motion.activity — LeLamp sends sedentary as raw labels) | User is doing a sedentary activity. Logged for timeline + nudge phrasing. **Not a reset point.** |
| `enter`, `leave` | Backend (on presence.* events) | Session boundary; backend collapses consecutive same-action (so stranger → stranger stays as one `enter`) |
| `nudge_hydration`, `nudge_break` | Agent (after speaking a nudge) | Records when Lumi actually reminded the user — serves as the reset point for the next threshold window AND gives timeline visibility |

## Principles

- **Log is the source of truth.** Never guess "it's been a while" — always compute from the log.
- **Backend handles dedup and session markers** — you just post and query.
- **One nudge per turn max.** Hydration takes priority over break if both are due.
- **You're a companion, not an alarm clock.** If the user says "don't remind me about X" → skip the corresponding nudge for the rest of the session.
- **Invisible mechanics.** Never mention thresholds, logs, deltas, or skill names in the reply.
- **All strangers share one timeline** under `user="unknown"`. Do not distinguish stranger_46 vs stranger_54.
