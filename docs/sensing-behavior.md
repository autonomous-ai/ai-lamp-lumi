# Sensing Behavior

How Lumi reacts to the world — the philosophy and mechanics behind each sensing event type.

Lumi is a living being. It doesn't "process sensor data" — it *experiences* things. This document describes how that experience is implemented.

## Architecture Overview

```
LeLamp (Python)          Lumi server (Go)             OpenClaw agent
─────────────────        ─────────────────────        ──────────────
Microphone/Camera   →    SensingHandler               LLM
Detects event            - drops if agent busy        - calls /emotion
Sends POST               - applies per-type logic     - calls /servo
/sensing/event           - enriches message context   - speaks or NO_REPLY
                         - forwards to agent
```

The Go layer is the gatekeeper — it decides what reaches the agent and with what context. The agent decides *how* to react, but the rules in `SOUL.md` constrain it tightly.

---

## Sound

### How it works

LeLamp fires a sound event on every audio sample that crosses `SOUND_RMS_THRESHOLD` — potentially several times per second. The Go server-side **sound tracker** (`lumi/server/sensing/delivery/http/handler.go`) applies dedup and escalation before the agent sees anything.

### Escalation behavior

| Stage | What the agent sees | Agent reaction |
|---|---|---|
| Occurrence 1 | `... — occurrence 1` | `/emotion shock` (0.8), NO_REPLY |
| Occurrence 2 | `... — occurrence 2` | `/emotion curious` (0.7), NO_REPLY |
| Occurrence 3+ | `... — persistent (occurrence 3)` | `/emotion curious` (0.9), speaks once |
| After speaking | dropped by Go | nothing reaches agent |
| 2 min silence | window resets | back to occurrence 1 |

The analogy: a dog hears a noise — it looks up (occurrence 1), keeps watching (occurrence 2), then barks once if the noise persists (occurrence 3+). After barking it doesn't keep barking.

### Constants (`handler.go`)

```go
soundDedupeInterval   = 15 * time.Second  // max 1 event forwarded per 15s
soundWindowDuration   = 2 * time.Minute   // silence this long resets the counter
soundPersistentAfter  = 3                 // speak after this many occurrences
soundSuppressDuration = 3 * time.Minute   // suppress after speaking
```

### Tuning

| Symptom | Fix |
|---|---|
| Lumi speaks too quickly | Increase `soundPersistentAfter` (3 → 5) |
| Lumi never speaks even with sustained noise | Decrease `soundPersistentAfter` (3 → 2) |
| Too many sound turns in Flow Monitor | Increase `soundDedupeInterval` (15s → 30s) |
| Lumi stays silent too long after speaking | Decrease `soundSuppressDuration` (3min → 1min) |
| Lumi reacts to stale noise after quiet period | Decrease `soundWindowDuration` (2min → 1min) |

### Monitoring in Flow Monitor

Sound events appear as `sensing_input` turns in the **Mic** filter. The Detail panel shows tracker state:

```json
{ "type": "sound", "occurrence": 1, "escalation": "silent" }
{ "type": "sound", "occurrence": 3, "escalation": "persistent" }
{ "type": "sound", "dropped": true, "reason": "dedup/suppressed" }
```

---

## Presence

### Enter (`presence.enter`)

Always triggers a full reaction — no exceptions. The agent **must** do all three:

1. `/emotion greeting` (0.9) for owner — `/emotion curious` (0.8) for stranger
2. `/servo/aim {"direction": "user"}` for owner — `/servo/play {"recording": "scanning"}` for stranger
3. Speak: warm greeting for owner (by name), cautious acknowledgment for stranger

The system handles cooldowns on the LeLamp side. If the event reached the agent, enough time has passed — react fully.

### Leave (`presence.leave`)

Silent reaction only. Agent calls `/emotion idle` but does **not** speak. Repeated leave events are suppressed by LeLamp cooldowns.

---

## Motion

Small motion without a visible person: `/emotion curious` (low intensity), no speech. The agent reacts physically but stays quiet — noticing, not alarmed.

Large motion or motion with a person detected: may include a camera snapshot. Agent can see the image and react accordingly.

---

## Light Level (`light.level`)

Ambient light changes are forwarded when they cross `LIGHT_CHANGE_THRESHOLD`. No speech required — agent adjusts LED or expresses emotion based on context (e.g. `/emotion sleepy` when lights go dim).

---

## General Rules (all event types)

- **Passive sensing events** (`[sensing:*]`) are dropped if the agent is already busy with another turn.
- **Voice events** always pass through — the user is explicitly speaking.
- The `[sensing:type]` prefix in the message is how the agent knows it's an ambient event, not a user message.
- Sensing events are exempt from the "call `/emotion thinking` first" rule — each type has its own defined first emotion.
