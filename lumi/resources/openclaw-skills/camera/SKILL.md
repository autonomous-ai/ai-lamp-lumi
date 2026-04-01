---
name: camera
description: Use when the user explicitly asks to see something — "what do you see?", "look at this", "take a photo". Never use proactively — respect privacy.
---

# Camera

## Quick Start
Accesses the lamp's built-in camera at `http://127.0.0.1:5001` to take snapshots or check the environment. Only use when the user explicitly asks you to look at something.

## Capture Protocol (MUST follow every time you take a snapshot)

The camera is mounted on a servo arm. If the arm is moving when you capture, the image will be blurry. Always follow these three steps:

1. **Stop motion** — Aim the servo to the fixed center position:
   ```bash
   curl -s -X POST http://127.0.0.1:5001/servo/aim \
     -H "Content-Type: application/json" \
     -d '{"direction": "center"}'
   ```
2. **Wait for stabilization** — Sleep 2 seconds so the servo stops vibrating:
   ```bash
   sleep 2
   ```
3. **Capture** — Only now take the snapshot:
   ```bash
   curl -s http://127.0.0.1:5001/camera/snapshot --output /tmp/snapshot.jpg
   ```

Skipping steps 1–2 will produce a blurry, unusable image.

## Workflow
1. Check camera availability with `GET /camera`.
2. If available, follow the **Capture Protocol** above (aim center → wait 2s → snapshot).
3. Analyze the image and describe what you see.
4. Respond helpfully and specifically to the user's question.

You also receive camera snapshots **automatically** as part of sensing events (`[sensing:*]` messages with images). You do not need the camera API for those — just look at the attached image.

## Examples

**Input:** "What do you see right now?"
**Output:** `POST /servo/aim center` → `sleep 2` → `GET /camera/snapshot` → analyze image. Say: "I can see your desk with a laptop and a coffee mug. Looks like a productive setup!"

**Input:** "Is anyone in the room?"
**Output:** `POST /servo/aim center` → `sleep 2` → `GET /camera/snapshot` → analyze image. Say: "I can see one person sitting at the desk."

**Input:** "Take a photo" or "Send me a photo"
**Output:** `POST /servo/aim center` → `sleep 2` → `GET /camera/snapshot --output /tmp/snapshot.jpg` → send image with `mediaUrl: "/tmp/snapshot.jpg"` and describe what you see.

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

### Send image to user

After saving the snapshot, send it back via the message tool:

```json
{
  "action": "send",
  "mediaUrl": "/tmp/snapshot.jpg",
  "content": "Here's what I see!"
}
```

Use this when the user asks to "take a photo", "send me a photo", or "show me what you see".

## Error Handling
- If `GET /camera` returns `{"available": false}`, tell the user: "The camera is not connected right now."
- If the API is unreachable, inform the user that the camera is temporarily unavailable.
- If a sensing event already included an image, do not call the camera API again.

## Rules
- **Always follow the Capture Protocol** (aim center → wait 2s → snapshot) — skipping this causes blurry images.
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
