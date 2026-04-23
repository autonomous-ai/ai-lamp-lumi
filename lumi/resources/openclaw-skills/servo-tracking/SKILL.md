---
name: servo-tracking
description: Use when the user asks Lumi to follow, track, watch, or look at a specific object (e.g. "follow my cup", "look at the bottle", "track that person", "watch my hand").
---

# Vision Tracking

## Quick Start
Tracks and follows any object by name. YOLOWorld detects the object in the camera frame, TrackerVit follows it in real-time with servo movement.

## Workflow
1. User names an object to track.
2. Prefix reply with `[HW:/servo/track:{"target":"<object>"}]` — Lumi detects and follows.
3. To stop, prefix with `[HW:/servo/track/stop:{}] (POST)`.

## Examples

**Input:** "Follow the cup"
**Output:** `[HW:/servo/track:{"target":"cup"}]` OK, following the cup!

**Input:** "Look at the bottle"
**Output:** `[HW:/servo/track:{"target":"bottle"}]` Watching the bottle.

**Input:** "Track that person"
**Output:** `[HW:/servo/track:{"target":"person"}]` Following them now.

**Input:** "Watch my phone"
**Output:** `[HW:/servo/track:{"target":"phone"}]` Got it, tracking your phone.

**Input:** "Follow the teddy bear"
**Output:** `[HW:/servo/track:{"target":"teddy bear"}]` Tracking the teddy bear!

**Input:** "Stop following" / "Stop tracking"
**Output:** `[HW:/servo/track/stop:{}] (POST)` Stopped tracking.

**Input:** "What can you track?"
**Output:** I can track most common objects — cups, bottles, phones, laptops, books, people, bags, and more. Just tell me what to follow!

## How to Control Tracking

**No exec/curl needed.** Inline markers at start of reply:

```
[HW:/servo/track:{"target":"cup"}] Following the cup.
[HW:/servo/track:{"target":"person"}] Tracking you now.
[HW:/servo/track/stop:{}] (POST) Stopped tracking.
```

### Target names

Use common English object names. Works best with:
person, cup, bottle, glass, phone, laptop, keyboard, mouse, book, pen, notebook, bag, chair, monitor, remote control, plate, bowl, plant, vase, clock, lamp, speaker, headphones, watch, glasses, hat, shoe, toy, ball, teddy bear.

Any name works (open-vocabulary detection) but common objects have higher accuracy.

### How it works internally
1. Camera captures current frame
2. YOLOWorld API detects the named object (~1-2s)
3. TrackerVit locks on and follows at 12 FPS
4. Servo (yaw + 3 pitch joints) nudges to keep object centered
5. Auto-stops when object is lost, out of range, or after 5 minutes

## Error Handling
- If the object is not found: "I can't see a {target} right now. Try pointing me toward it, or try a different name."
- If tracking stops unexpectedly: "I lost the {target}. Want me to try again?"
- If servo is not available: "Servo is not available right now."

## Rules
- Only one object can be tracked at a time. Starting a new track stops the previous one.
- Tracking auto-stops when the object leaves the frame, gets occluded, or after 5 minutes.
- When tracking stops, servo resumes idle animation automatically.
- Do NOT use this for emotional reactions — use the Emotion skill instead.
- Use simple, common object names for best results.
