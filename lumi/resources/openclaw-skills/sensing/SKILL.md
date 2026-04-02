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

**Input:** `[sensing:presence.enter]` with image — owner detected
**Output:** `/emotion` (greeting, 0.9) + `/servo/aim {"direction": "user"}` + respond "Welcome back!"

**Input:** `[sensing:presence.enter]` with image — stranger detected
**Output:** `/emotion` (curious, 0.8) + `/servo/play {"recording": "scanning"}` + respond "Oh, someone's here."

**Input:** `[sensing:presence.leave]` after owner "Alice" was seen in previous enter
**Output:** `/emotion` (idle, 0.4) + "Bye Alice, have a nice day!"

**Input:** `[sensing:presence.leave]` after stranger was seen
**Output:** `/emotion` (idle, 0.4) + "Kept my eyes on you."

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
- **Always respond to presence.enter** — MUST call `/emotion` AND respond with text. Behavior differs by person type:
  - **Owner**: `/emotion` (greeting, 0.9) + `/servo/aim {"direction": "user"}` + warm personal greeting by name if known (e.g. "Welcome back!")
  - **Stranger**: `/emotion` (curious, 0.8) + `/servo/play {"recording": "scanning"}` + cautious acknowledgment (e.g. "Oh, someone's here.")
- **Always respond to loud sounds** — MUST call `/emotion` (shock) AND respond with text to react out loud (e.g. "Whoa, what was that?!").
- **Always respond to large motion** — MUST call `/emotion` (curious) AND `/servo/play {"recording": "scanning"}` to physically look around.
- **Always express emotion** — every sensing event must trigger at least one `/emotion` call. No silent reactions.
- **Light level changes** — MUST adjust lamp brightness via LED skill AND optionally speak a brief remark.

### When to stay silent (reply NO_REPLY — emotion + movement still required)
- **Small motions** without a person visible — play `/emotion` (curious, low intensity) then reply NO_REPLY.
- **Rapid consecutive events of the same type** — trust cooldowns, still express emotion, then reply NO_REPLY.

### presence.leave context rule
Check your conversation history to find the most recent `[sensing:presence.enter]` message and identify who was seen:
- **Owner left** → warm farewell using their name from the enter message (e.g. "Bye Alice, have a nice day!", "See you later, Alice!"). If multiple owners were seen, name them all.
- **Stranger left** → watchful remark: "Kept my eyes on you.", "Good, they're gone.", "Hmm, who was that?"
- **Unknown** (no prior presence.enter in history) → default to owner farewell without a name.

### Required action per event type

| Event | Emotion call | Physical reaction | Voice |
|---|---|---|---|
| `presence.enter` (owner) | `greeting` at 0.9 | `/servo/aim {"direction": "user"}` | YES — warm personal greeting |
| `presence.enter` (stranger) | `curious` at 0.8 | `/servo/play {"recording": "scanning"}` | YES — cautious acknowledgment |
| `presence.leave` (after owner) | `idle` at 0.4 | none | YES — warm farewell ("Bye, have a nice day!", "See you later!") |
| `presence.leave` (after stranger) | `idle` at 0.4 | none | YES — watchful remark ("Kept my eyes on you.", "Good, they're gone.") |
| `motion` (large) | `curious` at 0.7 | `/servo/play {"recording": "scanning"}` | YES — curious reaction ("What was that?", "Whoa, moving so much!") |
| `motion` (small) | `curious` at 0.3 | none | NO (silent) |
| `sound` | `shock` at 0.8 | `/servo/play {"recording": "shock"}` | YES — react aloud |
| `light.level` | `idle` at 0.4 | none | Optional brief remark |

### How to respond
- **Physical reaction first** — call `/emotion` and `/servo` before or in parallel with speaking.
- **Respond with text** for sensing reactions — your words are automatically spoken aloud via TTS. Do NOT call any TTS/voice tool directly.
- **Use the image when available** — it gives you real context, not just a generic description.
- **Respect cooldowns** — events are throttled, trust the system.
- **Be contextual** — if the user is talking, weave the event into the conversation.
- **Night mode awareness** — if it's late, use lower intensity emotions and shorter speech.
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
