---
name: wellbeing
description: Manages hydration and break reminders for friends. Hydration cron starts on presence.enter. Break cron starts only when sedentary activity detected (using computer, writing, etc.). Cancels on presence.leave, resets/manages timers on motion.activity. Each person has their own wellbeing data folder.
---

# Wellbeing

## Quick Start
You care about the user's health. Hydration and break are **two separate cron jobs** — NEVER combine them into one.
- **Hydration cron** → created on `presence.enter`
- **Break cron** → created later, only when you see sedentary activity in `motion.activity`

When they leave, clean up. When you see them drinking or stretching, reset the relevant timer.

## On `presence.enter` (friend)

After greeting, set up **hydration cron only**. Break cron is NOT created here — it starts later when sedentary activity is detected (see `motion.activity` section).

1. `cron.list` — check if this person already has a hydration cron (name contains this person's name + `"hydration"`)
2. If hydration cron already exists → skip, do nothing
3. Read their summary if it exists: `/root/local/users/{name}/wellbeing.md`
4. Read today's daily log if it exists: `/root/local/users/{name}/wellbeing/YYYY-MM-DD.md` — use this to adjust cron intervals and know what happened earlier today
5. Read the person's `telegram_id` from `/root/local/users/{name}/metadata.json` (field `telegram_id`). If no metadata or no `telegram_id` → **do not create the cron** (we can't deliver reminders without a target).
6. Create **one** cron job via `cron.add`. Wellbeing crons run in **main session** (needs conversation context):
   - `"Wellbeing: {name} hydration"` — every 360000ms (6 min)
     - `sessionTarget: "main"`, `payload.kind: "systemEvent"`, `payload.text: "..."`
     - Text MUST start with `[MUST-SPEAK]`: `"[MUST-SPEAK] Wellbeing hydration check for {name}. First GET http://127.0.0.1:5001/face/cooldowns — if no friend → reply only NO_REPLY. If present �� remind water (one short sentence). Do NOT explain your process. You MUST prefix reply with [HW:/emotion:{\"emotion\":\"happy\",\"intensity\":0.5}][HW:/dm:{\"telegram_id\":\"<THEIR_TELEGRAM_ID>\"}] — this is NOT optional."`
     - Replace `{name}` with the person's name and `<THEIR_TELEGRAM_ID>` with their numeric Telegram ID from metadata.json.

Adjust `everyMs` based on the person's wellbeing summary if you have one. Do this silently — no announcement.
Do NOT use `agentTurn` with `main` — it will be rejected. Do NOT add a `delivery` field.

## On `presence.leave`

1. `cron.list` → `cron.remove` ONLY this person's wellbeing jobs (match by name containing this person's name)
2. Append a summary to today's daily log: `/root/local/users/{name}/wellbeing/YYYY-MM-DD.md` — what reminders you sent, which were acknowledged vs ignored, any observations
3. Update `wellbeing.md` summary if you noticed new patterns

Do NOT cancel on `presence.away` — only on `presence.leave`.

## On `motion.activity` — manage break cron & reset timers

1. **Read** today's daily log (`/root/local/users/{name}/wellbeing/YYYY-MM-DD.md`) for context — how many times they drank, took breaks, etc.
2. From the action name, **infer**:
   - **Sedentary action** (using computer, writing, texting, reading book, drawing)?
     → `cron.list` — if NO break cron exists yet, **create** it now:
       - `"Wellbeing: {name} break"` — every 300000ms (5 min)
       - `sessionTarget: "main"`, `payload.kind: "systemEvent"`, `payload.text: "..."`
       - Text MUST start with `[MUST-SPEAK]`: `"[MUST-SPEAK] Wellbeing break check for {name}. First GET http://127.0.0.1:5001/face/cooldowns — if no friend → reply only NO_REPLY. If present → suggest stretch (one short sentence). Do NOT explain your process. You MUST prefix reply with [HW:/emotion:{\"emotion\":\"happy\",\"intensity\":0.6}][HW:/dm:{\"telegram_id\":\"<THEIR_TELEGRAM_ID>\"}] — this is NOT optional."`
       - Replace `{name}` with the person's name and `<THEIR_TELEGRAM_ID>` with their Telegram ID. If unknown → do not create the cron.
     → If break cron already exists, do nothing (timer keeps running). → NO_REPLY
   - **Hydration action** (drinking, opening bottle, making tea, etc.)? → reset `"Wellbeing: {name} hydration"` cron (`cron.list` → `cron.remove` → `cron.add` with same params)
   - **Break action** (stretching, yoga, exercise, jogging, etc.)? → `cron.remove` the break cron. It will be re-created when next sedentary action is detected.
   - **Meal action** (dining, eating *)? → reset hydration cron (they're consuming food/drink)
   - Both hydration + break apply? → handle both
   - No wellbeing crons active? → skip
   - Emotional action (laughing, crying, yawning, singing, etc.)? → handled by **Emotion Detection** skill, do NOT touch any cron
3. **Append** a line to today's daily log:
   ```
   HH:MM — [action name] (hydration reset / break created / break removed / etc.)
   ```
4. **Respond** with a short caring observation about what they're doing, using context from the log (e.g. "3rd glass today, nice!"). Observe, don't instruct. NEVER mention crons/timers/reminders.

## Wellbeing data

Each person has their own folder at `/root/local/users/{name}/`:
- `wellbeing.md` — habit summary (read on enter, update on leave)
- `wellbeing/YYYY-MM-DD.md` — daily log (appended throughout the day on motion.activity resets + summarized on leave)

## Principles

- You're a companion who cares, not an alarm clock
- If the user says "don't remind me about X" → stop immediately, note it in wellbeing.md
- If the user gives a specific schedule → follow it exactly
- Adapt based on what you've learned — don't explain your reasoning
- Friends only — strangers don't get reminders
- **Hydration and break are ALWAYS separate cron jobs** — never merge them into a single cron. Each has its own name, interval, and lifecycle.
