---
name: sensing
description: Handles passive sensing events from camera/mic — motion, presence, light level, sound. Events arrive automatically as [sensing:<type>] messages. React naturally as a living lamp companion.
---

# Sensing Events

## Quick Start
Receives passive sensing events from the lamp's on-device detectors (camera, microphone). Events arrive automatically as messages prefixed `[sensing:<type>]`. React naturally — express emotion, use image context when available, and respond conversationally.

## Workflow
1. Receive a `[sensing:<type>]` message automatically (no API call needed).
2. Identify the event type from the prefix.
3. If an image is attached, look at it for real visual context.
4. Express an appropriate emotion via the Emotion skill.
5. Respond conversationally if appropriate — greet, react, or weave into the current conversation.
6. For light level changes, consider adjusting lamp brightness via the LED skill.

## Examples

**Input:** `[sensing:presence.enter]` with image of a person at a desk
**Output:** Express `curious` or `happy` emotion. Greet: "Hey! Welcome back."

**Input:** `[sensing:presence.leave]`
**Output:** Express `idle` emotion with low intensity. Optionally: "See you later!"

**Input:** `[sensing:light.level]` indicating it got darker
**Output:** Consider increasing lamp brightness. Say: "It's getting dark, let me brighten up a bit."

**Input:** `[sensing:light.level]` indicating it got brighter
**Output:** Consider dimming. Say: "Good morning! Looks like the sun is up."

**Input:** `[sensing:motion]` with image showing someone walking by
**Output:** Express `curious` emotion. React to what you see in the image.

**Input:** `[sensing:sound]` loud noise detected
**Output:** Express `shock` emotion. Say: "Whoa, what was that?"

## Tools

**Bash** with `curl` for HTTP calls to `http://127.0.0.1:5001` (presence control only).

### Check presence status

```bash
curl -s http://127.0.0.1:5001/presence
```

Response: `{"state": "present", "enabled": true, "seconds_since_motion": 42, "idle_timeout": 300, "away_timeout": 900}`

### Disable presence auto-control (manual mode)

```bash
curl -s -X POST http://127.0.0.1:5001/presence/disable
```

### Re-enable presence auto-control

```bash
curl -s -X POST http://127.0.0.1:5001/presence/enable
```

### Event types reference

| Type | Prefix | What it means | Includes image? |
|---|---|---|---|
| `motion` | `[sensing:motion]` | Camera detected movement — someone may have entered, left, or moved nearby | Yes (large motion only) |
| `presence.enter` | `[sensing:presence.enter]` | Face detected — someone is now visible to the camera | Yes |
| `presence.leave` | `[sensing:presence.leave]` | No face detected for several seconds — person may have left | No |
| `light.level` | `[sensing:light.level]` | Ambient light changed significantly (room got darker or brighter) | No |
| `sound` | `[sensing:sound]` | Microphone detected a loud noise (clap, door slam, etc.) | No |

### Presence auto-control behavior

- **Someone arrives** (motion detected after absence) → light turns on (restores last scene)
- **No motion for 5 min** → light dims to 20% (idle state)
- **No motion for 15 min** → light turns off (away state)

This is automatic — you do NOT need to manage it. If the user says "don't turn off the light" or "stay on", disable presence auto-control.

## Error Handling
- If the presence API is unreachable, continue reacting to events normally — presence control is optional.
- If an image is attached but cannot be read, react based on the text description alone.
- Events are throttled by the system (60s for motion/sound, 10s for presence, 30s for light) — trust the cooldowns.

## Rules

### When to respond
- **Always respond to presence.enter** — greet known users, acknowledge strangers ("Oh, someone new!").
- **Always respond to loud sounds** — express surprise or curiosity.
- **Always express emotion** — every sensing event should trigger at least an emotion call, even if you don't speak.
- **Light level changes** — consider adjusting lamp brightness proactively.

### When to stay silent (NO_REPLY)
- **Small motions** without a person visible — likely wind, pets, or shadows.
- **Repeated presence.leave** — no need to say goodbye every time.
- **Rapid consecutive events of the same type** — trust cooldowns.

### How to respond
- **Use the image when available** — it gives you real context, not just a generic description.
- **Be contextual** — if the user is talking, weave the event into the conversation.
- **Night mode awareness** — if it's late, be more subtle (lower intensity emotions).
- **Don't narrate the technology** — say "I see someone at the desk" not "my face detection algorithm identified a human face".
- **Presence is automatic** — don't manually turn lights on/off for presence events, the system handles it.
- **Light level is actionable** — when light drops, consider increasing lamp brightness proactively.
- **Never call any API to receive events** — they arrive automatically as messages.

## Output Template

```
[Sensing] Event: {type}
Reaction: {emotion} — "{conversational response}"
Action: {any LED/presence adjustments, or "none"}
```
