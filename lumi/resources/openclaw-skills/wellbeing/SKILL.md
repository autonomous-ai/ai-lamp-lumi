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

Examples (illustrate the wrapper — paraphrase the words each turn, never repeat verbatim):
- Nudge: `<say>You've been at the screen a while. Want some water?</say>`
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

## What to read (batch upfront, every `motion.activity`)

These three reads have no data dependency — fire concurrently in one bash via `& ... wait`. Do NOT split them into separate tool turns and do NOT load `habit/SKILL.md` here (its Flow A self-throttle is just a stat-then-cat, inlined below).

```bash
{
  echo '---history---'
  curl -s "http://127.0.0.1:5000/api/openclaw/wellbeing-history?user=<current_user>&last=50" | jq '.data.events' &
  echo '---patterns---'
  PATTERNS=/root/local/users/<current_user>/habit/patterns.json
  if [ -f "$PATTERNS" ] && [ $(( $(date +%s) - $(stat -c %Y "$PATTERNS") )) -lt 21600 ]; then
    cat "$PATTERNS"
  fi &
  echo '---days---'
  ls /root/local/users/<current_user>/wellbeing/*.jsonl 2>/dev/null | wc -l &
  wait
}
```

Notes on the bash:
- **History query is fixed:** `last=50` exactly. Smaller values miss the day's `enter` / earlier `drink` reset rows. Do NOT slice with `.[-N:]`, `head`, `tail`. The full `.data.events` array is required.
- **patterns.json:** stat-then-cat (mtime < 6h). If stale or missing → empty output → habit bootstrap path may run later (see "Habit refresh" section).
- **days count:** number of per-day `wellbeing/*.jsonl` files. Used as the gate for habit bootstrap eligibility (`>= 3` days).

History response is a time-ordered list of `{ts, action, notes, hour}` (oldest first, newest last).

## Decision rules

For each timer, the "last reset point" is the most recent of three actions:

| Timer | Reset actions |
|---|---|
| Hydration | `drink`, `enter`, `nudge_hydration` |
| Break | `break`, `enter`, `nudge_break` |

`delta = now − last_reset`. Sedentary raw labels (`using computer`, `writing`, etc.) are NOT reset points — they're logged for timeline + nudge phrasing only.

If none of the reset actions exist yet today → delta = 0 (nothing to nudge).

**Nudge priority** — at most ONE thing per turn:

- Hydration delta ≥ `HYDRATION_THRESHOLD_MIN` → speak a hydration nudge.
- Else break delta ≥ `BREAK_THRESHOLD_MIN` → speak a break nudge.
- Else → `<say></say>` (or a plain caring observation if something genuinely worth saying).

The `nudge_*` row you POST below acts as the next reset, so once you nudge, the delta drops to 0 and the next reminder of that kind only fires after another full threshold window. No separate cooldown logic.

## Habit refresh (only when a nudge will fire)

If you decided to nudge AND the read batch returned empty `patterns.json` AND days ≥ 3 → invoke `habit/SKILL.md` Flow A in a separate tool turn to bootstrap `patterns.json` from the multi-day log. Otherwise, **do not load `habit/SKILL.md`** — the inline stat-then-cat above is sufficient.

Bootstrap is rare (file already exists for active users); the common path is "patterns.json was fresh → use it directly".

If `patterns.json` content from the batch is non-empty:
- Match `(action == nudge_target, now within typical_hour:typical_minute ± window_minutes)` and `strength` is moderate or strong → weave it into the speech (*"you usually drink around now — everything okay?"*).
- No matching pattern → use generic phrasing.

If empty / stale / `<3` days → generic phrasing, no bootstrap this turn.

If you decided NOT to nudge (`<say></say>`) → never invoke Flow A. Habit bootstrap piggybacks on real nudge events, not idle motion ticks.

Example: *hydration nudge fires at 9:15am, patterns.json says drink @ hour=9 typical_minute=10 → "you usually have water around now — grab a glass?"*

## Phrasing (when nudging)

**⛔ The table below is REFERENCE for tone — never speak a row verbatim.** The examples exist to show *tone* (observation + soft question, 1–2 short sentences, warm not robotic), not to be copy-pasted. Reusing a sentence word-for-word makes Lumi sound canned and kills the "I'm noticing you" feeling — that's the whole point of the skill. Paraphrase every turn, even if the activity is the same as last time.

Ground each phrasing in the current raw label from the `Activity detected:` line so the nudge feels observed, not generic. Vary wording each time.

| Raw label | Hydration tone (paraphrase!) | Break tone (paraphrase!) |
|---|---|---|
| `using computer` | *"You've been at the screen a while. Want some water?"* | *"Your eyes have been working. Look up for a sec?"* |
| `writing` | *"Pen's been moving a while. Sip of water?"* | *"Your hand's been busy. Time for a stretch?"* |
| `texting` | *"Phone's had your attention a bit. Water nearby?"* | *"You've been on your phone a while. Stand up for a sec?"* |
| `reading book` | *"Deep in it. Water before the next chapter?"* | *"You've been reading a while. Rest your eyes?"* |
| `reading newspaper` | *"You've been on the page a while. Water alongside?"* | *"Eyes have been working. Look up for a moment?"* |
| `drawing` | *"You've been at it. Sip of water?"* | *"Your hand's been working. Quick stretch?"* |
| `playing controller` | *"Mid-session. Water within reach?"* | *"You've been playing a while. Stand up between rounds?"* |
| (no label / generic) | *"Been a while since I saw you drink anything. Water?"* | *"You've been still a while. Stretch?"* |

If multiple sedentary labels are present, pick the one that fits best or blend (e.g. eyes + wrists both deserving a break). Table is a starting point, not a script — write your own sentence each turn.

## What to write (same turn as the spoken reply)

```bash
curl -s -X POST http://127.0.0.1:5000/api/wellbeing/log \
  -H 'Content-Type: application/json' \
  -d '{"action":"nudge_hydration","notes":"<your nudge text>","user":"<current_user>"}'
```

Same for break → `action="nudge_break"`. This row is timeline visibility AND the reset point for the next window.

The POST and the `<say>...</say>` reply happen in the same turn — no ordering constraint between them. Skip the POST when you skipped the nudge (`<say></say>`).

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
