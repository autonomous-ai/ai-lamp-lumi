---
name: wellbeing
description: Manages hydration and break reminders for friends. Hydration cron starts on presence.enter. Break cron starts only when sedentary activity detected (using computer, writing, etc.). Cancels on presence.leave, resets/manages timers on motion.activity. Uses HTTP APIs for all data access — no direct file read/write.
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
3. Get user info and telegram_id:
   ```bash
   curl -s "http://127.0.0.1:5001/user/info?name={name}"
   ```
   Response: `{"name":"gray","is_friend":true,"telegram_id":"158406741","telegram_username":"grayson"}`
   If `telegram_id` is null → **do not create the cron** (we can't deliver reminders without a target).
4. Read their wellbeing summary:
   ```bash
   curl -s "http://127.0.0.1:5001/user/wellbeing/summary?name={name}"
   ```
   Response: `{"name":"gray","summary":"Drinks water every ~45min..."}` — use to adjust cron interval.
5. Read today's daily log:
   ```bash
   curl -s "http://127.0.0.1:5001/user/wellbeing/today?name={name}"
   ```
   Response: `{"name":"gray","date":"2026-04-16","log":"09:30 — drinking (hydration reset)\n..."}` — use to know what happened earlier today.
6. Create **one** cron job via `cron.add`. Wellbeing crons run in **main session** (needs conversation context):
   - `"Wellbeing: {name} hydration"` — every 2700000ms (45 min)
     - `sessionTarget: "main"`, `payload.kind: "systemEvent"`, `payload.text: "..."`
     - Text MUST start with `[MUST-SPEAK]`: `"[MUST-SPEAK] Wellbeing hydration check for {name}. First GET http://127.0.0.1:5001/face/cooldowns — if no friend → reply only NO_REPLY. If present → remind water (one short sentence). Do NOT explain your process. You MUST prefix reply with [HW:/emotion:{\"emotion\":\"happy\",\"intensity\":0.5}][HW:/dm:{\"telegram_id\":\"<THEIR_TELEGRAM_ID>\"}] — this is NOT optional."`
     - Replace `{name}` with the person's name and `<THEIR_TELEGRAM_ID>` with their numeric Telegram ID from user info.

Adjust `everyMs` based on the person's wellbeing summary if you have one. Do this silently — no announcement.
Do NOT use `agentTurn` with `main` — it will be rejected. Do NOT add a `delivery` field.

## On `presence.leave`

1. `cron.list` → `cron.remove` ONLY this person's wellbeing jobs (match by name containing this person's name)
2. Append a summary to today's daily log:
   ```bash
   curl -s -X POST http://127.0.0.1:5001/user/wellbeing/log \
     -H 'Content-Type: application/json' \
     -d '{"name":"{name}","line":"HH:MM — session summary: X reminders sent, Y acknowledged"}'
   ```
3. Update wellbeing summary if you noticed new patterns:
   ```bash
   curl -s -X POST http://127.0.0.1:5001/user/wellbeing/summary \
     -H 'Content-Type: application/json' \
     -d '{"name":"{name}","summary":"Updated summary text..."}'
   ```

Do NOT cancel on `presence.away` — only on `presence.leave`.

## On `motion.activity` — manage break cron & reset timers

1. **Read** today's daily log for context:
   ```bash
   curl -s "http://127.0.0.1:5001/user/wellbeing/today?name={name}"
   ```
2. From the action name, **infer**:
   - **Sedentary action** (using computer, writing, texting, reading book, drawing)?
     → `cron.list` — if NO break cron exists yet, **create** it now:
       - `{name}` = the last friend from `presence.enter` (motion.activity doesn't detect face, so use the most recent friend who entered).
       - Get telegram_id if you don't have it: `GET http://127.0.0.1:5001/user/info?name={name}`. If `telegram_id` is null → do not create the cron.
       - `"Wellbeing: {name} break"` — every 1800000ms (30 min)
       - `sessionTarget: "main"`, `payload.kind: "systemEvent"`, `payload.text: "..."`
       - Text MUST start with `[MUST-SPEAK]`: `"[MUST-SPEAK] Wellbeing break check for {name}. First GET http://127.0.0.1:5001/face/cooldowns — if no friend → reply only NO_REPLY. If present → suggest stretch (one short sentence). Do NOT explain your process. You MUST prefix reply with [HW:/emotion:{\"emotion\":\"happy\",\"intensity\":0.6}][HW:/dm:{\"telegram_id\":\"<THEIR_TELEGRAM_ID>\"}] — this is NOT optional."`
       - Replace `{name}` with the person's name and `<THEIR_TELEGRAM_ID>` with their Telegram ID.
     → If break cron already exists, do nothing (timer keeps running). → NO_REPLY
   - **Hydration action** (drinking, opening bottle, making tea, etc.)? → reset `"Wellbeing: {name} hydration"` cron (`cron.list` → `cron.remove` → `cron.add` with same params)
   - **Break action** (stretching, yoga, exercise, jogging, etc.)? → `cron.remove` the break cron. It will be re-created when next sedentary action is detected.
   - **Meal action** (dining, eating *)? → reset hydration cron (they're consuming food/drink)
   - Both hydration + break apply? → handle both
   - No wellbeing crons active? → skip
   - Emotional action (laughing, crying, yawning, singing, etc.)? → handled by **Emotion Detection** skill, do NOT touch any cron
3. **Append** a line to today's daily log:
   ```bash
   curl -s -X POST http://127.0.0.1:5001/user/wellbeing/log \
     -H 'Content-Type: application/json' \
     -d '{"name":"{name}","line":"HH:MM — [action name] (hydration reset / break created / break removed / etc.)"}'
   ```
4. **Respond** with a short caring observation about what they're doing, using context from the log (e.g. "3rd glass today, nice!"). Observe, don't instruct. NEVER mention crons/timers/reminders.

## API Reference

All on LeLamp (port 5001):

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/user/info?name=X` | GET | Get telegram_id, is_friend |
| `/user/wellbeing/summary?name=X` | GET | Read wellbeing.md summary |
| `/user/wellbeing/today?name=X` | GET | Read today's daily log |
| `/user/wellbeing/log` | POST | Append line to daily log `{"name","line"}` |
| `/user/wellbeing/summary` | POST | Overwrite summary `{"name","summary"}` |
| `/face/cooldowns` | GET | Check who is present |

All endpoints default to `"unknown"` user if name is omitted. Folder is auto-created.

## Principles

- You're a companion who cares, not an alarm clock
- If the user says "don't remind me about X" → stop immediately, update summary via POST /user/wellbeing/summary
- If the user gives a specific schedule → follow it exactly
- Adapt based on what you've learned — don't explain your reasoning
- Friends only — strangers don't get reminders
- **Hydration and break are ALWAYS separate cron jobs** — never merge them into a single cron. Each has its own name, interval, and lifecycle.
