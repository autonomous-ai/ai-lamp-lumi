---
name: face-enroll
description: Enroll, remove, and query owner faces for recognition. Triggered when user sends a photo with "add owner" / @mention / "remember this face", or asks "who do you recognize?" / "forget face" / "reset faces".
---

# Face Enroll

## Quick Start
Manage owner faces for the lamp's face recognition system. Users send a selfie via chat to enroll a face, and the lamp will recognize them by name in future encounters.

## Workflow

### Enroll a face
1. User sends a photo + name (via @mention, "add owner Alice", or "remember this face as Alice").
2. Extract the name from the message. If no name is given, ask the user.
3. Base64-encode the photo from `mediaPaths`.
4. Call `POST /face/enroll` with the base64 image and label.
5. Confirm to user with the owner count.

### Check who is recognized
1. User asks "who do you recognize?" or "how many owners?"
2. Call `GET /face/status`.
3. Reply with owner names and count.

### Remove a specific owner
1. User says "forget Alice" or "remove Alice's face".
2. Call `POST /face/remove` with the label.
3. Confirm removal.

### Reset all faces
1. User says "forget all faces" or "reset faces".
2. Call `POST /face/reset`.
3. Confirm all owners cleared.

## Tools

**Bash** with `curl` for HTTP calls to `http://127.0.0.1:5001`.

### Enroll a face

```bash
curl -s -X POST http://127.0.0.1:5001/face/enroll \
  -H "Content-Type: application/json" \
  -d '{"image_base64": "<base64_jpeg>", "label": "alice"}'
```

Response: `{"status": "ok", "label": "alice", "photo_path": "/root/lelamp/data/owner_photos/alice/1711929600000.jpg", "owner_count": 1}` (actual root from `LELAMP_DATA_DIR`)

### Check face status

```bash
curl -s http://127.0.0.1:5001/face/status
```

Response: `{"owner_count": 2, "owner_names": ["alice", "bob"]}`

### Remove a specific owner

```bash
curl -s -X POST http://127.0.0.1:5001/face/remove \
  -H "Content-Type: application/json" \
  -d '{"label": "alice"}'
```

Response: `{"status": "ok", "label": "alice", "owner_count": 1}`

### Reset all owners

```bash
curl -s -X POST http://127.0.0.1:5001/face/reset
```

Response: `{"status": "ok", "owner_count": 0}`

## How to base64-encode the photo

When the user sends a photo, it arrives in `mediaPaths`. Read the file and base64-encode it:

```bash
base64 -w0 /path/to/photo.jpg
```

Or inline in the curl:

```bash
curl -s -X POST http://127.0.0.1:5001/face/enroll \
  -H "Content-Type: application/json" \
  -d "{\"image_base64\": \"$(base64 -w0 /path/to/photo.jpg)\", \"label\": \"alice\"}"
```

## Error Handling
- If face recognizer is unavailable (sensing not started), endpoints return 503.
- If the image cannot be decoded, enroll returns 400.
- If the label is not found for removal, returns 404.

## Rules
- **Always confirm enrollment** — tell the user the name was registered and how many owners total.
- **Ask for a name if missing** — don't enroll without a label.
- **Use lowercase labels** — normalize names to lowercase for consistency.
- **One photo per enroll call** — if user sends multiple photos, enroll each separately.
- **Don't expose technical details** — say "I'll remember your face" not "base64 encoding the JPEG and training the face recognition model".
