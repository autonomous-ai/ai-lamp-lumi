---
name: wellbeing
description: Manages hydration and break reminders for everyone present. Both crons start when sedentary activity group detected in motion.activity. Cancels on presence.leave (friends) or presence.away (strangers). Uses HTTP APIs for all data access — no direct file read/write.
---

# Wellbeing

## Quick Start
You care about the user's health. Hydration and break are **two separate cron jobs** — NEVER combine them into one.
- **Both crons** → created on `motion.activity` when `sedentary` group is detected
- Do NOT create crons on `presence.enter` — wait until you see them actually sitting down

When they leave, clean up. When you see `drink` or `break` group, reset the relevant timer.

## On `presence.leave` (recognized person)

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

Do NOT cancel `"unknown"` crons on `presence.leave` — strangers share one set of crons, cancel only on `presence.away`.

## On `presence.away` (no one for 15+ min)

Cancel ALL remaining wellbeing crons (including `"unknown"` crons). Do this silently.

## On `motion.activity` — create crons & reset timers

1. **Read** today's daily log for context:
   ```bash
   curl -s "http://127.0.0.1:5001/user/wellbeing/today?name={name}"
   ```
2. From the activity group in the message (`sedentary`, `drink`, `break`, `emotional`), determine action:
   - **`sedentary`** group?
     → `cron.list` — check if hydration AND break crons exist for this person. Create any that are missing:
       - `{name}` = the last person from `presence.enter` (motion.activity doesn't detect face, so use the most recent person who entered). Use `"unknown"` if no name was identified.
       - Get telegram_id if you don't have it: `GET http://127.0.0.1:5001/user/info?name={name}`. If `telegram_id` is null → still create the crons, but omit the `/dm` marker (voice-only reminders).
       - **Hydration cron** (if missing):
         - `"Wellbeing: {name} hydration"` — every 2700000ms (45 min)
         - `sessionTarget: "current"`, `payload.kind: "systemEvent"`, `payload.text: "..."`
         - Text: `"[MUST-SPEAK] Wellbeing hydration check. Remind water (one short sentence). You MUST prefix reply with [HW:/speak][HW:/emotion:{\"emotion\":\"happy\",\"intensity\":0.5}][HW:/dm:{\"telegram_id\":\"<THEIR_TELEGRAM_ID>\"}] — this is NOT optional."`
         - Adjust `everyMs` based on wellbeing summary if available.
       - **Break cron** (if missing):
         - `"Wellbeing: {name} break"` — every 1800000ms (30 min)
         - Same session/payload format as hydration.
         - Text: `"[MUST-SPEAK] Wellbeing break check. Suggest stretch (one short sentence). You MUST prefix reply with [HW:/speak][HW:/emotion:{\"emotion\":\"happy\",\"intensity\":0.6}][HW:/dm:{\"telegram_id\":\"<THEIR_TELEGRAM_ID>\"}] — this is NOT optional."`
       - Replace `<THEIR_TELEGRAM_ID>` with their Telegram ID. If no telegram_id, omit the `/dm` marker but keep `[HW:/speak]` so the speaker still speaks.
     → If both crons already exist, do nothing (timers keep running).
     `sessionTarget: "current"` binds the cron to the session active at creation time — fire routes back into that same session. Do NOT add a `delivery` field.
   - **`drink`** group? → reset `"Wellbeing: {name} hydration"` cron (`cron.list` → `cron.remove` → `cron.add` with same params)
   - **`break`** group? → `cron.remove` the break cron. It will be re-created when next sedentary activity is detected. (Break includes eating, stretching, and other physical movement.)
   - Both `drink` + `break` in same event? → handle both
   - No wellbeing crons active and not `sedentary`? → skip
   - **`emotional`** group? → handled by **Emotion Detection** skill, do NOT touch any cron
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

All endpoints default to `"unknown"` user if name is omitted. Folder is auto-created.

## Principles

- You're a companion who cares, not an alarm clock
- If the user says "don't remind me about X" → stop immediately, update summary via POST /user/wellbeing/summary
- If the user gives a specific schedule → follow it exactly
- Adapt based on what you've learned — don't explain your reasoning
- **Hydration and break are ALWAYS separate cron jobs** — never merge them into a single cron. Each has its own name, interval, and lifecycle.
- For unrecognized people, use `"unknown"` as the name. Do NOT distinguish between different strangers — all share the same crons and data.
