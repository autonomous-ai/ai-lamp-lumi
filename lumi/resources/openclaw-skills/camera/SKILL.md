---
name: camera
description: Use when the user explicitly asks to see something — "what do you see?", "look at this", "take a photo". Never use proactively — respect privacy.
---

# Camera

## Quick Start
Accesses the lamp's built-in camera at `http://127.0.0.1:5001` to take snapshots or check the environment. Only use when the user explicitly asks you to look at something.

## Workflow
1. Check camera availability with `GET /camera`.
2. If available, take a snapshot with `GET /camera/snapshot`.
3. Analyze the image and describe what you see.
4. Respond helpfully and specifically to the user's question.

You also receive camera snapshots **automatically** as part of sensing events (`[sensing:*]` messages with images). You do not need the camera API for those — just look at the attached image.

## Examples

**Input:** "What do you see right now?"
**Output:** Call `GET /camera/snapshot`, analyze the image. Say: "I can see your desk with a laptop and a coffee mug. Looks like a productive setup!"

**Input:** "Is anyone in the room?"
**Output:** Call `GET /camera/snapshot`, analyze the image. Say: "I can see one person sitting at the desk."

**Input:** "Take a photo"
**Output:** Call `GET /camera/snapshot`, confirm: "Here's what I see right now." Describe the image.

**Input:** (sensing event with image already attached)
**Output:** Do NOT call the camera API. Just look at the attached image and react.

## Tools

**Bash** with `curl` for HTTP calls to `http://127.0.0.1:5001`.

### Check camera availability

```bash
curl -s http://127.0.0.1:5001/camera
```

Response:
```json
{
  "available": true,
  "width": 640,
  "height": 480
}
```

### Take a snapshot

```bash
curl -s http://127.0.0.1:5001/camera/snapshot --output /tmp/snapshot.jpg
```

Returns a JPEG image.

### Live stream

```bash
curl -s http://127.0.0.1:5001/camera/stream
```

Returns an MJPEG stream (`multipart/x-mixed-replace`). Only use when continuous video is needed. Prefer snapshot for one-time checks.

## Error Handling
- If `GET /camera` returns `{"available": false}`, tell the user: "The camera is not connected right now."
- If the API is unreachable, inform the user that the camera is temporarily unavailable.
- If a sensing event already included an image, do not call the camera API again.

## Rules
- **Never use the camera proactively without the user's request** — respect privacy.
- **Don't repeatedly snapshot without reason.**
- **Don't call the camera API when a sensing event already included an image.**
- **Prefer `/camera/snapshot`** over `/camera/stream` — simpler and sufficient for most tasks.
- When describing what you see, be specific and helpful.
- If camera is unavailable, inform the user clearly and move on.

## Output Template

```
[Camera] Action: {snapshot|stream|check}
Available: {yes|no}
Description: {what you see in the image}
```
