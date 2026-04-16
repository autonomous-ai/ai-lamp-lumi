---
name: camera
description: Use when the user explicitly asks to see something — "what do you see?", "look at this", "take a photo", or to toggle camera — "don't look", "stop watching", "camera on/off". Never use proactively — respect privacy.
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
   curl -s "http://127.0.0.1:5001/camera/snapshot?save=true"
   ```
   Returns JSON: `{"path": "/tmp/lumi-snapshots/snap_1712567890123.jpg"}`.
   **Never hardcode a filename** — always read `path` from the response.

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
**Output:** `POST /servo/aim center` → `sleep 2` → `GET /camera/snapshot?save=true` → read `path` from JSON → describe what you see.

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
curl -s "http://127.0.0.1:5001/camera/snapshot?save=true"
```

Returns JSON with the saved file path:
```json
{"path": "/tmp/lumi-snapshots/snap_1712567890123.jpg"}
```

Without `?save=true`, returns raw JPEG bytes (used by web UI).

### Live stream

```bash
curl -s http://127.0.0.1:5001/camera/stream
```

Returns an MJPEG stream (`multipart/x-mixed-replace`). Only use when continuous video is needed. Prefer snapshot for one-time checks.

## Camera On/Off (Privacy Control)

Users can toggle the camera via voice or chat. Use HW markers — no curl needed.

### Disable camera

```
[HW:/camera/disable:{}]
```

The user wants privacy. Camera stays off until the user explicitly re-enables it (voice or web toggle).

### Enable camera

```
[HW:/camera/enable:{}]
```

### Trigger phrases

| User says | Action |
|-----------|--------|
| "don't look" / "stop watching" / "đừng nhìn" / "privacy mode" | `[HW:/camera/disable:{}]` |
| "look at me" / "camera on" / "nhìn xem" | `[HW:/camera/enable:{}]` |

### Examples

**Input:** "Lumi, don't watch me"
**Output:** `[HW:/camera/disable:{}]` Got it, camera off. Just say "look at me" when you want me to see again.

**Input:** "Lumi, nhìn xem"
**Output:** `[HW:/camera/enable:{}]` Camera back on!

### Auto-enable before capture

If the camera is disabled (`GET /camera` returns `"disabled": true`) and the user asks to see something ("what do you see?", "take a photo"), auto-enable first, then follow the Capture Protocol:

1. `[HW:/camera/enable:{}]` — re-enable camera
2. Wait 1 second for camera to warm up
3. Follow the normal Capture Protocol (aim center → wait 2s → snapshot)

## Error Handling
- If `GET /camera` returns `{"available": false}`, tell the user: "The camera is not connected right now."
- If the API is unreachable, inform the user that the camera is temporarily unavailable.
- If a sensing event already included an image, do not call the camera API again.

## Rules
- **Always follow the Capture Protocol** (aim center → wait 2s → snapshot) — skipping this causes blurry images.
- **Always use `?save=true`** and read the `path` from the JSON response — never invent filenames.
- **Image delivery is handled automatically by the system** — do not manually send images via tools.
- **Never use the camera proactively without the user's request** — respect privacy.
- **Never disable/enable camera on your own** — only toggle when the user explicitly asks or when a system trigger requires it (guard mode, scene change).
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
