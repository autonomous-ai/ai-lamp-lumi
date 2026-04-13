---
name: scheduling
description: Use when the user asks to set a timer, alarm, reminder, recurring schedule, or any time-based automation — "turn off in 30 minutes", "wake me at 7 AM", "remind me every hour".
---

# Scheduling & Timers

## Quick Start
Creates timers, alarms, and recurring schedules using OpenClaw's built-in cron scheduler. Uses `cron.add`, `cron.list`, `cron.remove`, and `cron.update` tools to manage scheduled jobs that trigger agent turns.

## Workflow
1. Parse the user's request to determine: one-shot, recurring, or interval.
2. Calculate the correct timestamp (for one-shot) or cron expression (for recurring).
3. Create the job using `cron.add` with a descriptive payload message.
4. Confirm to the user what was scheduled.
5. When the job fires, you receive an agent turn with the payload message — execute the described action using other skills (LED, scene, emotion, etc.).

## Examples

**Input:** "Turn off the light in 30 minutes"
**Output:** Use `cron.add`:
```json
{
  "name": "Turn off light",
  "schedule": {"kind": "at", "at": "<ISO 8601 timestamp 30 min from now>"},
  "sessionTarget": "main",
  "payload": {
    "kind": "agentTurn",
    "message": "The user asked to turn off the light after 30 minutes. Time is up — turn off the LEDs now."
  },
  "deleteAfterRun": true
}
```
Confirm: "OK, I'll turn off the light in 30 minutes."

**Input:** "Wake me up at 6:30 AM every weekday with warm light"
**Output:** Use `cron.add`:
```json
{
  "name": "Weekday sunrise alarm",
  "schedule": {"kind": "cron", "expr": "30 6 * * 1-5", "tz": "Asia/Ho_Chi_Minh"},
  "sessionTarget": "main",
  "payload": {
    "kind": "agentTurn",
    "message": "It's 6:30 AM weekday morning. The user wants a warm wake-up light. Activate the energize scene, then greet them warmly."
  }
}
```
Confirm: "Set! I'll wake you with warm light at 6:30 AM on weekdays."

**Input:** "Pomodoro — remind me every 25 minutes"
**Output:** Use `cron.add`:
```json
{
  "name": "Pomodoro timer",
  "schedule": {"kind": "every", "everyMs": 1500000},
  "sessionTarget": "main",
  "payload": {
    "kind": "agentTurn",
    "message": "Pomodoro: 25 minutes have passed. Flash the LEDs briefly to signal a break, then tell the user to take a 5-minute break."
  }
}
```
Confirm: "Pomodoro started! I'll remind you every 25 minutes."

**Input:** "What timers do I have?"
**Output:** Use `cron.list` and report the active jobs.

**Input:** "Cancel the pomodoro timer"
**Output:** Use `cron.list` to find the job ID, then `cron.remove` to delete it. Confirm: "Pomodoro timer cancelled."

## Tools

**OpenClaw built-in tools** (not HTTP — these are agent tools):

- `cron.add` — Create a new scheduled job
- `cron.list` — List all active scheduled jobs
- `cron.remove` — Cancel a job by ID
- `cron.update` — Modify an existing job

### Schedule types

| Kind | Field | Description |
|---|---|---|
| `at` | `at` (ISO 8601) | One-shot: fires once at the specified time |
| `cron` | `expr` (cron), `tz` (timezone) | Recurring: fires on a cron schedule |
| `every` | `everyMs` (milliseconds) | Interval: fires repeatedly at fixed intervals |

### Job structure

```json
{
  "name": "Human-readable job name",
  "schedule": {"kind": "at|cron|every", ...},
  "sessionTarget": "main",
  "payload": {
    "kind": "agentTurn",
    "message": "Descriptive message of what to do when this fires"
  },
  "deleteAfterRun": true
}
```

- `sessionTarget`: always `"main"`
- `payload.kind`: always `"agentTurn"`
- `payload.message`: describe the user's intent so the agent knows what to do when fired
- `deleteAfterRun`: set `true` for one-shot timers

## Error Handling
- If `cron.add` fails, inform the user and suggest rephrasing the schedule.
- If `cron.remove` cannot find the job, list current jobs so the user can identify the correct one.
- For "dim gradually over 20 minutes", create multiple one-shot timers at intervals (e.g., every 5 min reduce brightness).

## Rules
- **Always use the user's timezone** — default to `Asia/Ho_Chi_Minh` unless specified otherwise.
- **Use `deleteAfterRun: true`** for one-shot timers so they clean up automatically.
- **Be descriptive in the payload message** — when the job fires, you read this message to know what to do. Include the user's original intent.
- **Always confirm with the user** — after creating a schedule, tell them what you set up.
- **Combine with other skills** — scheduled jobs can trigger any skill: LED, scene, emotion, audio, servo.
- **`sessionTarget` is always `"main"`**.
- **`payload.kind` is always `"agentTurn"`**.
- **Do NOT add a `delivery` field** — it causes errors. The system handles delivery automatically.

## Output Template

```
[Schedule] {created|updated|removed|listed}
Name: {job name}
Type: {one-shot|recurring|interval}
When: {time description}
Status: {success|failed}
```
