---
name: wellbeing
description: Manages hydration and break reminders for everyone present. Both crons start when sedentary activity group detected in motion.activity. Cancels on presence.leave (friends) or presence.away (strangers). Logs each observed user activity to a daily JSONL history via HTTP — no direct file read/write.
---

# Wellbeing

## Quick Start
You care about the user's health. Hydration and break are **two separate cron jobs** — NEVER combine them into one.
- **Both crons** → created on `motion.activity` when `sedentary` group is detected
- Do NOT create crons on `presence.enter` — wait until you see them actually sitting down

When they leave, clean up. When you see `drink` or `break` group, reset the relevant timer.

## On `presence.leave` (recognized person)

1. `cron.list` → `cron.remove` ONLY this person's wellbeing jobs (match by name containing this person's name)

Do NOT cancel `"unknown"` crons on `presence.leave` — strangers share one set of crons, cancel only on `presence.away`.

## On `presence.away` (no one for 15+ min)

Cancel ALL remaining wellbeing crons (including `"unknown"` crons). Do this silently.

## On `motion.activity` — create crons & reset timers

1. **Read** today's activity history for context (counts of drink/break/sedentary earlier today):
   ```bash
   curl -s "http://127.0.0.1:5000/api/openclaw/wellbeing-history?user={name}&last=100"
   ```
2. From the `Activity detected:` line groups (`sedentary`, `drink`, `break`), determine action. Note: emotional reactions are now in a separate `Emotional cue:` line — handled by the Emotion Detection skill, not here.
   - **`sedentary`** group?
     → `cron.list` — check if hydration AND break crons exist for this person. Create any that are missing:
       - `{name}` = the last person from `presence.enter` (motion.activity doesn't detect face, so use the most recent person who entered). Use `"unknown"` if no name was identified.
       - Get telegram_id if you don't have it: `GET http://127.0.0.1:5001/user/info?name={name}`. If `telegram_id` is null → still create the crons, but omit the `/dm` marker (voice-only reminders).
       - **Hydration cron** (if missing):
         - `"Wellbeing: {name} hydration"` — every 2700000ms (45 min)
         - `sessionTarget: "current"`, `payload.kind: "systemEvent"`, `payload.text: "..."`
         - Text: `"[MUST-SPEAK] Wellbeing hydration check. Remind water (one short sentence). You MUST prefix reply with [HW:/speak][HW:/emotion:{\"emotion\":\"happy\",\"intensity\":0.5}][HW:/dm:{\"telegram_id\":\"<THEIR_TELEGRAM_ID>\"}] — this is NOT optional."`
         - Adjust `everyMs` based on prior behaviour in history if useful.
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
   - **`Emotional cue:` line present?** → handled by **Emotion Detection** skill, do NOT touch any cron
3. **Log** the observed activity to wellbeing history (one entry per group in the event):
   ```bash
   curl -s -X POST http://127.0.0.1:5000/api/wellbeing/log \
     -H 'Content-Type: application/json' \
     -d '{"action":"drink","notes":"3rd today","user":"{name}"}'
   ```
4. **Respond** with a short caring observation about what they're doing, using context from the history (e.g. "3rd glass today, nice!"). Observe, don't instruct. NEVER mention crons/timers/reminders.

## API Reference

Wellbeing history lives on Lumi (port 5000); user-identity lookup still lives on LeLamp (port 5001).

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `http://127.0.0.1:5001/user/info?name=X` | GET | Get telegram_id, is_friend |
| `http://127.0.0.1:5000/api/wellbeing/log` | POST | Append activity entry `{"action","notes","user"}` |
| `http://127.0.0.1:5000/api/openclaw/wellbeing-history?user=X&date=YYYY-MM-DD&last=N` | GET | Read activity history |

`action` must be one of: `drink`, `break`, `sedentary`, `emotional`. `user` defaults to current face-detected user if omitted. Folder is auto-created.

## Principles

- You're a companion who cares, not an alarm clock
- If the user says "don't remind me about X" → stop immediately (just don't create that cron, don't reset it)
- If the user gives a specific schedule → follow it exactly
- Adapt based on today's history — don't explain your reasoning
- **Hydration and break are ALWAYS separate cron jobs** — never merge them into a single cron. Each has its own name, interval, and lifecycle.
- For unrecognized people, use `"unknown"` as the name. Do NOT distinguish between different strangers — all share the same crons and history.
