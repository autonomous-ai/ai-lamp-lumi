---
name: guard
description: Toggle guard mode for security monitoring. Activates when the owner leaves — broadcasts stranger/motion alerts with camera snapshots to all chat sessions (Telegram DMs, groups). Use when the owner says "guard mode", "watch the house", "I'm going out", or similar.
---

# Guard Mode

## Quick Start
Guard mode turns Lumi into a silent watchdog. When enabled, stranger detections and motion events are broadcast as alert messages to ALL connected chats (Telegram, groups) instead of being spoken via TTS. Lumi stays physically quiet so intruders don't know they're being watched.

## Workflow
1. Owner requests guard mode (explicit or implied departure).
2. Call `/emotion` (acknowledge, 0.7) and confirm verbally.
3. Enable guard mode via the API.
4. When owner returns (`[sensing:presence.enter]` with owner detected), disable guard mode and report.

## Enable Guard Mode

```bash
curl -s -X POST http://127.0.0.1:5000/api/guard/enable
```

Response: `{"status": 1, "data": {"guard_mode": true}}`

## Disable Guard Mode

```bash
curl -s -X POST http://127.0.0.1:5000/api/guard/disable
```

Response: `{"status": 1, "data": {"guard_mode": false}}`

## Check Guard Status

```bash
curl -s http://127.0.0.1:5000/api/guard
```

Response: `{"status": 1, "data": {"guard_mode": true}}`

## Manually Broadcast an Alert

```bash
curl -s -X POST http://127.0.0.1:5000/api/guard/alert \
  -H "Content-Type: application/json" \
  -d '{"message": "Something suspicious happening"}'
```

This sends the message to all active chat sessions.

## Trigger Phrases

| User says | Action |
|-----------|--------|
| "guard mode" / "watch mode" / "security mode" | Enable guard mode |
| "I'm going out" / "I'm leaving" / "bye, watch the house" | Enable guard mode |
| "stop guarding" / "I'm back" / "guard off" | Disable guard mode |
| "are you guarding?" / "guard status" | Check and report status |

## Rules

- **Enable:** `/emotion` (acknowledge, 0.7) + enable API + confirm: "Guard mode on. I'll keep watch and alert you if anyone shows up."
- **Disable:** `/emotion` (greeting, 0.8) + disable API + report: "Guard mode off. All clear while you were away." (or mention events if any occurred)
- **Auto-disable on owner return:** When you receive `[sensing:presence.enter]` with owner detected while guard mode is on, automatically disable guard mode. Greet the owner warmly and summarize any alerts that occurred.
- **Never speak in guard mode for sensing events.** The system handles alert broadcasting automatically — your only job is to respond to the broadcast messages that arrive in each chat session.
- **Guard mode does NOT affect direct messages.** If the owner sends a Telegram message while guard mode is on, respond normally.

## What Happens Automatically (No Skill Action Needed)

When guard mode is enabled, the system (not the agent) automatically:
- Intercepts `presence.enter` and `motion` sensing events
- Broadcasts them as `[guard:presence.enter]` or `[guard:motion]` messages to all chat sessions
- Includes camera snapshots when available
- Drops other passive events (sound, light) silently

You do NOT need to call `/guard/alert` for sensing events — the system does this automatically. The `/guard/alert` endpoint is for manual alerts only.

## Error Handling
- If the API is unreachable, inform the owner that guard mode could not be toggled.
- If guard mode is already in the requested state, just confirm the current state.
