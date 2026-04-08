---
name: guard
description: Toggle guard mode for security monitoring. Activates when the owner leaves. Use when the owner says "guard mode", "watch the house", "I'm going out", or similar.
---

# Guard Mode

## Quick Start
Guard mode turns Lumi into a silent watchdog. When enabled, Lumi stays physically quiet so intruders don't know they're being watched.

## Workflow
1. Owner requests guard mode (explicit or implied departure).
2. Call `/emotion` (acknowledge, 0.7) and confirm verbally.
3. Enable guard mode via the API.
4. When owner returns (`[sensing:presence.enter]` with owner detected), disable guard mode and report.

## Enable Guard Mode

```bash
curl -s -X POST http://127.0.0.1:5000/api/guard/enable -H 'Content-Type: application/json' -d '{"instruction":"custom instruction here"}'
```

The `instruction` field is **optional**. Use it when the owner adds extra instructions on what to do during guard mode (e.g. "play scary sound when stranger detected", "flash red lights", "play alarm music"). Extract the relevant part from the owner's message and pass it as the instruction. If the owner just says "guard mode" with no extra requests, omit the field or send an empty body.

Response: `{"status": 1, "data": {"guard_mode": true, "instruction": "..."}}`

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

## Trigger Phrases

| User says | Action |
|-----------|--------|
| "guard mode" / "watch mode" / "security mode" | Enable guard mode |
| "I'm going out" / "I'm leaving" / "bye, watch the house" | Enable guard mode |
| "stop guarding" / "I'm back" / "guard off" | Disable guard mode |
| "are you guarding?" / "guard status" | Check and report status |

## Rules

- **Enable:** `/emotion` (acknowledge, 0.7) + enable API (with `instruction` if provided) + confirm: "Guard mode on. I'll keep watch and alert you if anyone shows up."
- **Disable:** `/emotion` (greeting, 0.8) + disable API + report: "Guard mode off. All clear while you were away." (or mention events if any occurred)
- **Auto-disable on owner return:** When you receive `[sensing:presence.enter]` with owner detected while guard mode is on, automatically disable guard mode. Greet the owner warmly and summarize any alerts that occurred.
- **Guard mode does NOT affect direct messages.** If the owner sends a message while guard mode is on, respond normally.

## Error Handling
- If the API is unreachable, inform the owner that guard mode could not be toggled.
- If guard mode is already in the requested state, just confirm the current state.
