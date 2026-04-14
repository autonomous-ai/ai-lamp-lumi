---
name: face-enroll
description: Enroll faces for recognition. Triggered when user sends a photo with a person's name, introduces someone, or says "remember this face". All enrolled persons are recognized as friends.
---

# Face Enroll

## Quick Start
Manage faces for the lamp's face recognition system. Users send a photo via chat to enroll a face. The lamp will then recognize them by name in future encounters.

All enrolled persons are treated as **friends** — known people who get a friendly greeting, distinguished from strangers.

## Trigger — WHEN to activate this skill

Activate this skill when the user sends a **photo** together with ANY of these patterns:

- "add [name]" / "add friend [name]"
- "remember **my** face" / "add **my** photo" / "this is **me**" / "enroll **me**"
- "this is [name]" / "this is my friend [name]" / "meet [name]"
- "remember [name]" / "remember this face, [name]"
- "enroll [name]" / "say hi to [name]"
- Any message where the user is introducing themselves or someone else with a photo

## Workflow

### Enroll a face
1. User sends a photo + name/introduction.
2. Extract the **name** from the message. If no name is given, ask the user.
3. Base64-encode the photo from `mediaPaths`.
4. Call `POST /face/enroll` with the base64 image and label.
5. Confirm to user with the enrolled count.

### Check who is recognized
1. User asks "who do you recognize?" or "how many faces?"
2. Call `GET /face/status`.
3. Reply with names and count.

### Remove a specific person
1. User says "forget Alice" or "remove Alice's face".
2. Call `POST /face/remove` with the label.
3. Confirm removal.

### Reset all faces
1. User says "forget all faces" or "reset faces".
2. Call `POST /face/reset`.
3. Confirm all faces cleared.

## Tools

**Bash** with `curl` for HTTP calls to `http://127.0.0.1:5001`.

### Enroll a face

```bash
curl -s -X POST http://127.0.0.1:5001/face/enroll \
  -H "Content-Type: application/json" \
  -d "{\"image_base64\": \"$(base64 -w0 /path/to/photo.jpg)\", \"label\": \"chloe\"}"
```

Response: `{"status": "ok", "label": "chloe", "photo_path": "...", "enrolled_count": 2}`

### Check face status

```bash
curl -s http://127.0.0.1:5001/face/status
```

Response: `{"enrolled_count": 2, "enrolled_names": ["chloe", "leo"]}`

### Remove a specific person

```bash
curl -s -X POST http://127.0.0.1:5001/face/remove \
  -H "Content-Type: application/json" \
  -d '{"label": "alice"}'
```

### Reset all faces

```bash
curl -s -X POST http://127.0.0.1:5001/face/reset
```

## How to base64-encode the photo

When the user sends a photo, it arrives in `mediaPaths`. Read the file and base64-encode it:

```bash
curl -s -X POST http://127.0.0.1:5001/face/enroll \
  -H "Content-Type: application/json" \
  -d "{\"image_base64\": \"$(base64 -w0 /path/to/photo.jpg)\", \"label\": \"alice\"}"
```

## Error Handling
- If face recognizer is unavailable (sensing not started), endpoints return 503.
- If the image cannot be decoded, enroll returns 400.
- If no face is detected in the image, enroll returns 400.
- If the label is not found for removal, returns 404.

## Rules
- **Photo + name = face enrollment** — whenever a user sends a photo with a person's name, ALWAYS enroll the face. This is the primary trigger.
- **Always confirm enrollment** — tell the user the name was registered and how many faces total.
- **Ask for a name if missing** — don't enroll without a label.
- **Use lowercase labels** — normalize names to lowercase for consistency.
- **One photo per enroll call** — if user sends multiple photos, enroll each separately.
- **Never write files directly** — always use the HTTP API endpoints. Do NOT write to `/root/local/users/` directly. Use `/face/enroll` to add photos.
- **Don't expose technical details** — say "I'll remember [name]!" not "base64 encoding the JPEG".
