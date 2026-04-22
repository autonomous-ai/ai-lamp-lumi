---
name: wellbeing
description: Proactive hydration and break reminders. Use when a motion.activity event fires, when the user asks if they should drink water or take a break, or when checking whether it's time to nudge a specific user. Thresholds are computed from the per-user log, never guessed.
---

# Wellbeing

## ⛔ Output Format — READ FIRST

Your visible reply MUST be exactly one of:

1. `NO_REPLY`
2. ONE short caring sentence (e.g. *"Grab some water?"*)

If the reply contains any of `Computing`, `Latest`, `Reset`, `Check`, timestamps, bullet lists, tables, `**bold**`, or the word `threshold` → **YOU FAILED**. All math, timestamps, and reasoning stay in the `thinking` block — never in the reply.

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
3. **Never** echo computation into the visible reply (timestamps, minutes, thresholds, reset reasoning). All math stays in `thinking`.
4. **Only** write these action values: `drink`, `break`, `nudge_hydration`, `nudge_break`. Never invent new actions.
5. On a non-2xx response from a POST → you used the wrong port or path. Fix the URL and retry **once**. Do not give up silently — the nudge row must land, or the skill will spam reminders forever.
6. **Never** infer `user` from memory, `KNOWLEDGE.md`, chat history, or `senderLabel`. Only the `[context: current_user=X]` tag counts.
7. **Never** narrate the skip reason. If you decide NOT to nudge, reply `NO_REPLY` or a plain caring observation. Don't say *"just nudged N min ago"*, *"both over threshold"*, *"dedup applies"*.
8. **Trust the log, not memory.** If the history response contains no `nudge_hydration` entry, no nudge has happened — ignore any self-memory claim otherwise.

## Workflow — on every `motion.activity`

### Step 1 — Read recent history

```bash
curl -s "http://127.0.0.1:5000/api/openclaw/wellbeing-history?user=<current_user>&last=50"
```

Response is a time-ordered list of `{ts, action, notes, hour}`.

### Step 2 — Compute deltas (silently, in `thinking`)

For each timer, the "last reset point" is the most recent of three actions:

| Timer | Reset actions |
|---|---|
| Hydration | `drink`, `enter`, `nudge_hydration` |
| Break | `break`, `enter`, `nudge_break` |

`delta = now − last_reset`. Sedentary raw labels (`using computer`, `writing`, etc.) are NOT reset points — they're logged for timeline + nudge phrasing only.

If none of the reset actions exist yet today → delta = 0 (nothing to nudge).

### Step 3 — Decide (silently)

Nudge at most ONE thing per turn. Hydration takes priority over break.

- Hydration delta ≥ `HYDRATION_THRESHOLD_MIN` → speak a hydration nudge.
- Else break delta ≥ `BREAK_THRESHOLD_MIN` → speak a break nudge.
- Else → `NO_REPLY` or a plain caring observation.

The `nudge_*` row you POST in Step 5 acts as the next reset, so once you nudge, the delta drops to 0 and the next reminder of that kind only fires after another full threshold window. No separate cooldown logic.

### Step 3b — Habit check (optional, after Step 3 only if no threshold nudge fired)

1. Read `/root/local/users/{current_user}/habit/patterns.json`. If absent, skip.
2. If `updated_at` older than 6 hours, invoke the `habit` skill to rebuild.
3. For each entry in `wellbeing_patterns` with `strength` moderate or strong:
   - Is `now` within `typical_hour:typical_minute ± window_minutes`?
   - Has the `action` already appeared in today's log? → skip.
   - Has a matching `nudge_*` already been logged today? → skip.
4. If a habit nudge fires, speak it and log per Step 5. Do NOT double-nudge if Step 3 already fired.

Example: *Leo usually drinks at 9am* → at 9:15 with no `drink` today, nudge even if the 5-min threshold hasn't been crossed.

### Step 4 — Speak (if nudging)

Ground the phrasing in the current raw label from the `Activity detected:` line so the nudge feels observed, not generic. See `references/nudge-phrasing.md` for label → suggested wording.

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
