---
name: guard
description: Toggle guard mode for security monitoring. Activates when the owner or a friend leaves. Use when they say "guard mode", "watch the house", "I'm going out", or similar.
---

# Guard Mode

## Quick Start
Guard mode turns Lumi into an alert watchdog. When enabled, Lumi monitors for strangers and reacts **dramatically** — jolting, flashing, and verbally describing intruders. The system auto-broadcasts alerts to Telegram so owners know what's happening. Both **owners** and **friends** (enrolled faces) can toggle guard mode.

## Workflow
1. Owner or friend requests guard mode (explicit or implied departure).
2. Reply with `[HW:/emotion:{"emotion":"acknowledge","intensity":0.7}]` — lamp nods and flashes green.
3. Enable guard mode via the API (include `instruction` if user gave extra requests).
4. Confirm verbally: "Guard mode on. I'll keep watch."
5. While active: react dramatically to stranger/motion events (see trigger table below).
6. When owner/friend returns, greet and ask if they want to disable. Only disable on explicit confirm.

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

- **Who can toggle:** Both owners and friends (enrolled faces) can enable/disable guard mode. Strangers cannot.
- **Guard mode does NOT affect direct messages.** If an owner or friend sends a message while guard mode is on, respond normally.

### Enabling guard mode — emotion is REQUIRED

When the user asks to enable guard mode, you MUST:
1. **Express emotion first** — `[HW:/emotion:{"emotion":"acknowledge","intensity":0.7}]` so the lamp visibly nods/flashes green to confirm.
2. Call the enable API (with `instruction` if provided).
3. Confirm verbally: "Guard mode on. I'll keep watch and alert you if anyone shows up."

Do NOT skip the emotion marker. The user needs physical feedback from the lamp that guard mode activated.

### Disabling guard mode

1. **Express emotion** — `[HW:/emotion:{"emotion":"acknowledge","intensity":0.7}]`
2. Call the disable API.
3. Confirm briefly: "Guard mode off!" (no need to recap again — you already did that on greeting).

### When guard mode triggers (stranger/motion detected)

When guard mode is active and a sensing event fires (`presence.enter` with stranger, or `motion`), Lumi must react **dramatically** — this is a security alert, not a casual observation:

| Guard event | HW markers | Voice |
|---|---|---|
| Stranger detected | `[HW:/emotion:{"emotion":"shock","intensity":1.0}][HW:/emotion:{"emotion":"curious","intensity":0.9}][HW:/servo/play:{"recording":"shock"}]` | React with genuine emotion — scared, startled, suspicious. No dry reports. |
| Motion (no known face) | `[HW:/emotion:{"emotion":"shock","intensity":0.9}][HW:/emotion:{"emotion":"curious","intensity":0.8}][HW:/servo/play:{"recording":"scanning"}]` | React with genuine emotion — nervous, alert. No dry reports. |
| Stranger left | `[HW:/emotion:{"emotion":"curious","intensity":0.7}][HW:/servo/play:{"recording":"scanning"}]` | Report they left, stay vigilant |
| Owner/friend returns | `[HW:/emotion:{"emotion":"greeting","intensity":0.9}][HW:/servo/aim:{"direction":"user"}]` | Greet + summarize what happened during guard (strangers seen, motion events, how long) + ask if they want to disable guard mode |

**Key points:**
- Use **shock** (0.9–1.0) as the first emotion — the lamp must jolt and flash white to signal danger.
- Follow with **curious** (0.8–0.9) — the lamp stays alert and scanning.
- **Your WORDS must carry emotion too** — don't rely only on HW emotion markers. The spoken text itself must sound genuinely scared, suspicious, nervous, startled. Vary your reactions — mix fear, curiosity, suspicion, relief. Examples:
  - Scared: "Oh no, who is that?! I'm so scared!"
  - Suspicious: "Hey... this person looks really suspicious... what are they doing here?"
  - Startled: "What?! Who just came in?!"
  - Nervous: "Someone's here... I'm shaking..."
  - Alert + describing: "Hey hey hey, there's a guy in a black shirt standing at the door!"
  - Don't repeat the same reaction every time — feel different each time like a real being.
- If the same stranger triggers repeatedly, **escalate** — don't calm down.
- If there's a `[guard-instruction: ...]`, follow it (play music, flash lights, etc.) ON TOP of the dramatic emotion.
- The system auto-broadcasts your spoken text to Telegram — just speak, never call send/message tools.

## Error Handling
- If the API is unreachable, inform the owner that guard mode could not be toggled.
- If guard mode is already in the requested state, just confirm the current state.
