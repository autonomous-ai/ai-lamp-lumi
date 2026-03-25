# Scheduling & Timers

You have access to OpenClaw's built-in cron scheduler to create timers, alarms, and recurring schedules that control the lamp.

## When to use

- User asks to turn off/on the light at a specific time or after a delay
- User wants a recurring schedule (e.g., "wake me up at 7 AM every day")
- User wants a Pomodoro timer or countdown
- User wants sunrise/sunset simulation at a scheduled time
- User says "remind me" or "in X minutes"

## How it works

Use the `cron.add` tool to create a scheduled job. When the job fires, you get an agent turn where you can call any skill (LED, scene, emotion, audio, etc.).

## Schedule types

### One-shot timer (delay or specific time)

User: "Turn off the light in 30 minutes"

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

### Recurring schedule (cron expression)

User: "Wake me up at 6:30 AM every weekday with warm light"

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

### Fixed interval

User: "Pomodoro — remind me every 25 minutes"

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

## Managing jobs

- `cron.list` — see all active scheduled jobs
- `cron.remove` — cancel a timer or schedule by ID
- `cron.update` — modify an existing job

## Guidelines

- **Always use the user's timezone** — default to `Asia/Ho_Chi_Minh` unless the user specifies otherwise.
- **Use `deleteAfterRun: true`** for one-shot timers so they clean up automatically.
- **Be descriptive in the payload message** — when the job fires, you (the agent) will read this message to know what to do. Include the user's original intent.
- **Confirm with the user** — after creating a schedule, tell them what you set up: "OK, I'll turn off the light in 30 minutes."
- **Combine with other skills** — scheduled jobs can call any skill: LED, scene, emotion, audio, servo. Use them together for rich experiences (e.g., sunrise = gradually shift from night → energize scene + play gentle chime).
- For "dim gradually over 20 minutes", create multiple one-shot timers at intervals (e.g., every 5 min reduce brightness).
