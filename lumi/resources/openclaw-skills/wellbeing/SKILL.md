---
name: wellbeing
description: Proactive hydration and break reminders. Use when an [activity] event fires (message starts with `[activity] Activity detected: <labels>.` — labels include drink, break, or sedentary raw labels like "using computer"), when the user asks if they should drink water or take a break, or when checking whether it's time to nudge a specific user. Thresholds are computed from the per-user log, never guessed.
---

# Wellbeing

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

## Read pre-fetched context (do not re-fetch)

The backend injects a `[wellbeing_context: {...JSON...}]` block into this turn's message. **Do NOT fire any tool calls to re-fetch this data.** Saves the entire read tool turn.

Schema (every field is pre-computed in Lumi Go — agent only applies thresholds and picks phrasing):

```json
{
  "hydration_delta_min": 8,        // minutes since last drink/enter/nudge_hydration; -1 if no reset today
  "break_delta_min": 23,           // minutes since last break/enter/nudge_break; -1 if no reset today
  "latest_activity": "using computer",  // most recent action label (sedentary or reset); "" if no events
  "patterns": {                    // wellbeing patterns from patterns.json (mtime < 6h, strength >= moderate); omitted if none
    "drink": {"typical_hour": 9, "typical_minute": 15, "strength": "moderate"}
  },
  "bootstrap_needed": false        // true → patterns missing/stale AND days >= 3; only invoke habit Flow A when also nudging
}
```

Notes:
- Delta = `-1` means no reset action has happened today yet → treat as "no nudge" (delta undefined).
- `patterns` only surfaces moderate/strong matches. Weak patterns are filtered out by the backend.
- `bootstrap_needed=true` does NOT mean run Flow A unconditionally — only if THIS turn fires a nudge.

### Fallback (only if context block is missing)

If the message has no `[wellbeing_context: ...]` block (pre-fetch failed), fall back to the bash batch:

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

In the fallback path, compute deltas yourself by scanning `history` for the latest reset action.

## Decision rules

The deltas in `[wellbeing_context: ...]` are already computed in Lumi (resets = `drink` / `enter` / `nudge_hydration` for hydration; `break` / `enter` / `nudge_break` for break). You only apply the threshold:

- `hydration_delta_min` ≥ `HYDRATION_THRESHOLD_MIN` → speak a hydration nudge.
- Else `break_delta_min` ≥ `BREAK_THRESHOLD_MIN` → speak a break nudge.
- Else (or any delta == `-1` → no reset today yet) → `NO_REPLY` (or a plain caring observation if something genuinely worth saying).

At most ONE nudge per turn. Hydration takes priority over break.

The `nudge_*` row you POST below acts as the next reset, so once you nudge, the delta drops to 0 and the next reminder of that kind only fires after another full threshold window. No separate cooldown logic.

## Habit refresh (only when a nudge will fire)

If you decided to nudge AND the context block has `bootstrap_needed=true` → invoke `habit/SKILL.md` Flow A in a separate tool turn to bootstrap `patterns.json` from the multi-day log. Otherwise, **do not load `habit/SKILL.md`** — the `patterns` field in the context block is sufficient (or no patterns yet, that's fine).

Bootstrap is rare (file already exists for active users); the common path is "patterns object present → use it directly".

If the context's `patterns` map has an entry for the action you are about to nudge:
- Match `(action == nudge_target, now within typical_hour:typical_minute ± ~30min)` → weave it into the speech (*"you usually drink around now — everything okay?"*).
- No matching pattern (or `patterns` omitted) → use generic phrasing.

If you decided NOT to nudge (`NO_REPLY`) → never invoke Flow A. Habit bootstrap piggybacks on real nudge events, not idle motion ticks.

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

The POST and the spoken reply happen in the same turn — no ordering constraint between them. Skip the POST when you skipped the nudge (`NO_REPLY`).

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
