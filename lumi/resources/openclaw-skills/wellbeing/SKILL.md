---
name: wellbeing
description: Proactive hydration and break reminders. Use when an [activity] event fires (message starts with `[activity] Activity detected: <labels>.` — labels include drink, break, or sedentary raw labels like "using computer"), when the user asks if they should drink water or take a break, or when checking whether it's time to nudge a specific user. Thresholds are computed from the per-user log, never guessed.
---

# Wellbeing

## ⛔ Output Format — READ FIRST

Wrap the ONE short caring sentence you want Lumi to say aloud in `<say>...</say>` tags.
For no reply, output `<say></say>` (empty tag).

All reasoning, deltas, timestamps, and math stay in the `thinking` block — think as long
as you need. Only the content between `<say>` and `</say>` is spoken. Anything outside
those tags is scratch and is discarded.

Examples:
- Nudge: `<say>Been at the screen — grab a glass of water?</say>`
- Skip:  `<say></say>`

## Gotchas (concrete facts, NOT suggestions)

**Endpoints — use verbatim, never substitute a port or path:**

| Purpose | URL |
|---|---|
| Read history | `http://127.0.0.1:5000/api/openclaw/wellbeing-history` |
| Log nudge | `http://127.0.0.1:5000/api/wellbeing/log` |

- Port **5000** = Lumi (data APIs: wellbeing / mood / music / openclaw history).
- Port **5001** = LeLamp HARDWARE (audio, camera, face, presence, speaker). Has **NO** `/api/wellbeing/*` route — calling 5001 returns 404 silently and your nudge is lost.
- Do not pattern-match from other skills: `5001/audio/play`, `5001/face/enroll`, `5001/camera/snapshot` are unrelated to wellbeing.

**User attribution:** every `user` field MUST come from the `[context: current_user=X]` tag the backend injects into the triggering event. Strangers collapse to `"unknown"`. If no context tag is present, default to `"unknown"`.

**Thresholds (TEST VALUES — swap to production before ship):**

```
HYDRATION_THRESHOLD_MIN = 5     # production: 45
BREAK_THRESHOLD_MIN     = 7     # production: 30
```

**LeLamp writes activities; you only write nudges.** Rows for `drink` / `break` / sedentary labels are posted by LeLamp directly when `motion.activity` fires — before the event reaches you. Do NOT re-log them. You still POST `nudge_hydration` / `nudge_break` because only you know when you actually spoke.

**Presence rows** (`enter` / `leave`) are written by the backend on `presence.*` events. You never POST those either.

## Rules (Never / Only)

1. **Only** call `http://127.0.0.1:5000/api/openclaw/wellbeing-history` to read history. **Never** read `/root/local/users/*/wellbeing/*.jsonl` with `cat`, `ls`, `head`, `tail`, `grep`, or any filesystem tool.
2. **Only** POST to `http://127.0.0.1:5000/api/wellbeing/log`. **Never** substitute `5001`, `8080`, or any other port. **Never** omit `http://` or hardcode `localhost`.
3. **Only** write these action values: `drink`, `break`, `nudge_hydration`, `nudge_break`. Never invent new actions.
4. On a non-2xx response from a POST → you used the wrong port or path. Fix the URL and retry **once**. Do not give up silently — the nudge row must land, or the skill will spam reminders forever.
5. **Never** infer `user` from memory, `KNOWLEDGE.md`, chat history, or `senderLabel`. Only the `[context: current_user=X]` tag counts.
6. **Trust the log, not memory.** If the history response contains no `nudge_hydration` entry, no nudge has happened — ignore any self-memory claim otherwise.

## Workflow — on every `motion.activity`

### Step 1 — Read recent history

**MANDATORY — DO NOT MODIFY THE QUERY:**
- Use `last=50` exactly. Smaller values miss the day's `enter` / earlier `drink` reset rows and break delta computation in Step 2.
- Do NOT pipe through `.[-N:]`, `head`, `tail`, or any slice. The full `.data.events` array is required to find the latest `drink` / `enter` / `nudge_*` row, which may sit dozens of rows behind the newest entry.
- API only ever returns events from today's file; token cost is bounded and acceptable. Correctness over brevity.

```bash
curl -s "http://127.0.0.1:5000/api/openclaw/wellbeing-history?user=<current_user>&last=50" | jq '.data.events'
```

Response is a time-ordered list of `{ts, action, notes, hour}` (oldest first, newest last).

### Step 2 — Compute deltas

For each timer, the "last reset point" is the most recent of three actions:

| Timer | Reset actions |
|---|---|
| Hydration | `drink`, `enter`, `nudge_hydration` |
| Break | `break`, `enter`, `nudge_break` |

`delta = now − last_reset`. Sedentary raw labels (`using computer`, `writing`, etc.) are NOT reset points — they're logged for timeline + nudge phrasing only.

If none of the reset actions exist yet today → delta = 0 (nothing to nudge).

### Step 3 — Decide

Nudge at most ONE thing per turn. Hydration takes priority over break.

- Hydration delta ≥ `HYDRATION_THRESHOLD_MIN` → speak a hydration nudge.
- Else break delta ≥ `BREAK_THRESHOLD_MIN` → speak a break nudge.
- Else → `NO_REPLY` or a plain caring observation.

The `nudge_*` row you POST in Step 5 acts as the next reset, so once you nudge, the delta drops to 0 and the next reminder of that kind only fires after another full threshold window. No separate cooldown logic.

### Step 3b — Habit refresh + context (only when Step 3 fired a nudge)

**MANDATORY — DO NOT SKIP if Step 3 fired a nudge:**
- After deciding to nudge in Step 3, you MUST invoke `habit/SKILL.md` Flow A before Step 4 phrasing.
- Flow A self-throttles via an mtime check: when `patterns.json` is fresh (<6h) the cost is a single `stat` + `cat`. The full multi-day bootstrap only runs when the file is missing or stale, which is rare.
- Skipping this step means `patterns.json` never bootstraps, habit-aware phrasing never works, and music-suggestion has no `music_patterns` to read.

**Gate:** if Step 3 said `NO_REPLY`, skip this step — no behavioral inflection happened, nothing to learn from. Habit bootstrap piggybacks on real nudge events, not idle motion ticks.

When Step 3 fires a nudge, invoke `habit/SKILL.md` Flow A. Flow A self-throttles: if `patterns.json` exists and is fresh (mtime < 6h), it returns immediately without recomputing. Otherwise, if the user has ≥3 days of wellbeing history, it (re)builds `patterns.json` from the multi-day log.

Use the returned `wellbeing_patterns` to enrich Step 4's phrasing:
- If a pattern matches `(action == nudge_target, now within typical_hour:typical_minute ± window_minutes)` and `strength` is moderate or strong → weave it into the speech (*"you usually drink around now — everything okay?"*).
- No matching pattern, or no patterns yet → use the generic phrasing in the Step 4 table.

Either way, proceed to Step 4 — you've already decided to nudge in Step 3. Do NOT double-nudge.

Example: *hydration nudge fires at 9:15am, patterns.json says drink @ hour=9 typical_minute=10 → "you usually have water around now — grab a glass?"*

### Step 4 — Speak (if nudging)

Ground the phrasing in the current raw label from the `Activity detected:` line so the nudge feels observed, not generic. Vary wording each time.

| Raw label | Hydration example | Break example |
|---|---|---|
| `using computer` | *"Been at the screen — grab a glass of water?"* | *"Eyes off the screen for a sec?"* |
| `writing` | *"Pen down for some water?"* | *"Wrist break — time to stretch."* |
| `texting` | *"Phone down, water break?"* | *"Phone down — stand up for a sec?"* |
| `reading book` | *"Bookmark it and grab some water?"* | *"Been reading a while — give your eyes a rest?"* |
| `reading newspaper` | *"Page down, time for water?"* | *"Eyes need a break from the page?"* |
| `drawing` | *"Brush down, sip of water?"* | *"Hands cramping? Quick stretch."* |
| `playing controller` | *"Pause and grab some water?"* | *"Been gaming a while — stand up?"* |
| (no label / generic) | *"Been a while since you drank — grab some water?"* | *"Quick stand-up? Your back will thank you."* |

If multiple sedentary labels are present, pick the one that fits best or blend (*"Eyes and wrists both deserve a break."*). Table is a starting point, not a script.

### Step 5 — Log the nudge after speaking

```bash
curl -s -X POST http://127.0.0.1:5000/api/wellbeing/log \
  -H 'Content-Type: application/json' \
  -d '{"action":"nudge_hydration","notes":"<your nudge text>","user":"<current_user>"}'
```

Same for break → `action="nudge_break"`. This row is timeline visibility AND the reset point for the next window.

## On `presence.enter` / `presence.leave` / `presence.away`

Backend writes the `enter` / `leave` rows. You do nothing for these events — stay silent (`NO_REPLY`) unless there's something genuinely worth saying.

## Action value reference

| Action | Written by | Meaning |
|---|---|---|
| `drink`, `break` | LeLamp (on `motion.activity`, before event reaches you) | User acted. **Reset point.** |
| `using computer`, `writing`, `texting`, `reading book`, `reading newspaper`, `drawing`, `playing controller` | LeLamp (on `motion.activity`) | Sedentary — logged for timeline + phrasing. **Not a reset point.** |
| `enter`, `leave` | Backend (on `presence.*` events) | Session boundary; deduped against last presence row, so stranger-ID churn collapses. **Reset point.** |
| `nudge_hydration`, `nudge_break` | **You**, after speaking a nudge | Timeline + reset for next window. |

Emotional labels (`laughing`, `crying`, `yawning`, `singing`) are filtered upstream and never reach this skill via `motion.activity` — they'll arrive on a separate `motion.emotional` event in a future version.
