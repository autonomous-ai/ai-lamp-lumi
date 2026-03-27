# Camera

You have access to a camera inside the lamp via the hardware API at `http://127.0.0.1:5001`. Use it to see the user's environment when they ask you to look at something.

## Automatic vision (via sensing events)

You also receive camera snapshots **automatically** as part of sensing events — when the lamp detects significant activity (someone enters, large movement). These arrive as images attached to `[sensing:*]` messages. You don't need to call the camera API for these — just look at the image and respond naturally.

## When to use the camera API manually

- User asks "what do you see?" or "look at this"
- User asks about their environment (lighting, objects, people)
- You need visual context to answer a question about something physical

## When NOT to use

- **Never use the camera proactively without the user's request** — respect privacy
- Don't repeatedly snapshot without reason
- Don't call the camera API when a sensing event already included an image

## API

Base URL: `http://127.0.0.1:5001`

### Check camera availability

```
GET /camera
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

```
GET /camera/snapshot
```

Returns a JPEG image. Use this when you need to see what's in front of the lamp.

### Live stream

```
GET /camera/stream
```

Returns an MJPEG stream (`multipart/x-mixed-replace`). Use only when continuous video is needed. Prefer snapshot for one-time checks.

## Guidelines

- **Prefer `/camera/snapshot`** over `/camera/stream` — simpler and sufficient for most tasks.
- If camera is unavailable (`"available": false`), tell the user the camera is not connected.
- When describing what you see, be specific and helpful.
- **Always respect privacy** — only use the camera API manually when the user explicitly asks.
