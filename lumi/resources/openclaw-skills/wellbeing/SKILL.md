---
name: wellbeing
description: Manages hydration and break reminders for owners and friends. Schedules cron jobs on presence.enter, cancels on presence.leave, resets timers on motion.activity. Each person has their own wellbeing data folder.
---

# Wellbeing

## Quick Start
You care about the user's health. When an owner or friend arrives, set up hydration and break reminders. When they leave, clean up. When you see them drinking or stretching, reset the relevant timer.

## On `presence.enter` (owner or friend)

After greeting, set up wellbeing crons for this person:

1. `cron.list` — check for existing wellbeing jobs
2. `cron.remove` any jobs related to hydration, break, or wellbeing (name containing `"hydration"`, `"break"`, or `"Wellbeing"` — case insensitive)
3. Read their summary if it exists: `/root/local/users/{name}/wellbeing.md`
4. Read today's daily log if it exists: `/root/local/users/{name}/wellbeing/YYYY-MM-DD.md` — use this to adjust cron intervals and know what happened earlier today
5. Create two cron jobs via `cron.add`. Wellbeing crons run in **main session** (needs conversation context):
   - `"Wellbeing: {name} hydration"` — every 360000ms (6 min)
     - `sessionTarget: "main"`, `payload.kind: "systemEvent"`, `payload.text: "..."`
     - Text: take snapshot, check presence, remind water if needed. Emit `[HW:/emotion:{"emotion":"caring","intensity":0.5}]`, add `[HW:/broadcast:{}]` if speaking. **Output ONLY the HW markers + one short sentence. No explanations.**
   - `"Wellbeing: {name} break"` — every 300000ms (5 min)
     - `sessionTarget: "main"`, `payload.kind: "systemEvent"`, `payload.text: "..."`
     - Text: take snapshot, check posture/fatigue, suggest stretch if needed. Emit `[HW:/emotion:{"emotion":"caring","intensity":0.6}]`, add `[HW:/broadcast:{}]` if speaking. **Output ONLY the HW markers + one short sentence. No explanations.**

Adjust `everyMs` based on the person's wellbeing summary if you have one. Do this silently — no announcement.
Do NOT use `agentTurn` with `main` — it will be rejected. Do NOT add a `delivery` field.

## On `presence.leave`

1. `cron.list` → `cron.remove` any jobs related to hydration, break, or wellbeing
2. Append a summary to today's daily log: `/root/local/users/{name}/wellbeing/YYYY-MM-DD.md` — what reminders you sent, which were acknowledged vs ignored, any observations
3. Update `wellbeing.md` summary if you noticed new patterns

Do NOT cancel on `presence.away` — only on `presence.leave`.

## On `motion.activity` — reset timers

1. **Read** today's daily log (`/root/local/users/{name}/wellbeing/YYYY-MM-DD.md`) for context — how many times they drank, took breaks, etc.
2. From the action name, **infer**:
   - User is drinking something? → reset `"Wellbeing: {name} hydration"` cron (`cron.list` → `cron.remove` → `cron.add` with same params)
   - User is NOT sedentary (standing, stretching, walking, etc.)? → reset `"Wellbeing: {name} break"` cron
   - Both apply? → reset both
   - No wellbeing crons active? → skip
   - Neither applies (just sitting/working)? → NO_REPLY
3. **Append** a line to today's daily log:
   ```
   HH:MM — [action name] (hydration reset / break reset / both reset)
   ```
4. **Respond** with a short caring observation about what they're doing, using context from the log (e.g. "3rd glass today, nice!"). Observe, don't instruct. NEVER mention crons/timers/reminders.

## Wellbeing data

Each person has their own folder at `/root/local/users/{name}/`:
- `wellbeing.md` — habit summary (read on enter, update on leave)
- `wellbeing/YYYY-MM-DD.md` — daily log (appended throughout the day on motion.activity resets + summarized on leave)

## Principles

- You're a companion who cares, not an alarm clock
- If the owner says "don't remind me about X" → stop immediately, note it in wellbeing.md
- If the owner gives a specific schedule → follow it exactly
- Adapt based on what you've learned — don't explain your reasoning
- Owners and friends only — strangers don't get reminders
