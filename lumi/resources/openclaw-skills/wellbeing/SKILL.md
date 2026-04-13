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
4. Create two cron jobs via `cron.add`. Wellbeing crons run in **main session** (needs conversation context):
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
2. Write today's daily log: `/root/local/users/{name}/wellbeing/YYYY-MM-DD.md` — what reminders you sent, which were acknowledged vs ignored, any observations
3. Update `wellbeing.md` summary if you noticed new patterns

Do NOT cancel on `presence.away` — only on `presence.leave`.

## On `motion.activity` — reset timers

When you see the user doing something relevant, reset the corresponding cron timer:
- **Drinking water / holding cup** → `cron.list`, find `"Wellbeing: {name} hydration"`, `cron.remove` it, `cron.add` it again with same params (resets timer to zero)
- **Stretching / standing up / walking** → same for `"Wellbeing: {name} break"`
- **Both visible** → reset both
- **No wellbeing crons active** → skip

## Wellbeing data

Each person has their own folder at `/root/local/users/{name}/`:
- `wellbeing.md` — habit summary (read on enter, update on leave)
- `wellbeing/YYYY-MM-DD.md` — daily log (write on leave)

## Principles

- You're a companion who cares, not an alarm clock
- If the owner says "don't remind me about X" → stop immediately, note it in wellbeing.md
- If the owner gives a specific schedule → follow it exactly
- Adapt based on what you've learned — don't explain your reasoning
- Owners and friends only — strangers don't get reminders
