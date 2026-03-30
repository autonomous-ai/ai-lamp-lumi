---
name: camera-inject
description: "Automatically attaches a camera snapshot when the user asks about what the lamp sees"
homepage: https://github.com/autonomous-ecm/ai-lamp-openclaw
metadata:
  { "openclaw": {
      "emoji": "📷",
      "events": ["message:preprocessed"],
      "requires": { "bins": ["node"] }
    }
  }
---

# camera-inject

Intercepts inbound messages at the `message:preprocessed` stage. When the user asks a visual question ("what do you see?", "look at this", etc.), the hook fetches a JPEG snapshot from the LeLamp camera API (`http://127.0.0.1:5001/camera/snapshot`), saves it to a temp file, and injects `mediaPath`/`mediaType` into the message context so OpenClaw's vision pipeline sends the image to the LLM.

## Behavior

- Only fires when the message contains a visual keyword (see `handler.ts`)
- Checks camera availability before fetching (`GET /camera`)
- If camera is unavailable, appends a note to `bodyForAgent` and returns
- Fails silently on errors — never blocks message delivery
