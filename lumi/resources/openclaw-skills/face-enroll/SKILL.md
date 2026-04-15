---
name: face-enroll
description: Self-enroll faces for recognition. Triggered when user sends a photo of themselves. Each person enrolls their own face — enrolling others is not allowed. Telegram identity is saved for DM targeting.
---

# Face Enroll

## Quick Start
Manage faces for the lamp's face recognition system. Users send a photo of **themselves** via chat to enroll their face. The lamp will then recognize them by name in future encounters.

**Self-enrollment only** — each person enrolls their own face. You must NOT enroll a face on behalf of someone else.

All enrolled persons are treated as **friends** — known people who get a friendly greeting, distinguished from strangers.

## Trigger — WHEN to activate this skill

Activate this skill when the user sends a **photo** together with ANY of these patterns:

- "remember **my** face" / "add **my** photo" / "this is **me**" / "enroll **me**"
- "add me" / "add my face"
- Any message where the user is introducing **themselves** with a photo

Do NOT activate when the user tries to enroll someone else (e.g. "this is Alice", "add my friend Bob"). Politely explain that each person must enroll their own face.

## Workflow

### Enroll a face (self-enrollment)
1. User sends a photo of themselves + introduction message.
2. Extract the **name** from the message. If no name is given, use the sender name from the message prefix (e.g. `[telegram:Chloe]` → `chloe`). If still unclear, ask the user.
3. Extract the sender's **Telegram identity** from the message context:
   - `telegram_username`: the sender's Telegram username (e.g. `chloe_92`)
   - `telegram_id`: the sender's numeric Telegram user ID (e.g. `123456789`)
   These are available in the message metadata provided by the channel.
4. Base64-encode the photo from `mediaPaths`.
5. Call `POST /face/enroll` with the base64 image, label, telegram_username, and telegram_id.
6. Confirm to user with the enrolled count.

### Check who is recognized
1. User asks "who do you recognize?" or "how many faces?"
2. Call `GET /face/status`.
3. Reply with names and count.

### Remove own face
1. User says "forget my face" or "remove my face".
2. Verify the requester matches the enrolled person (by sender name or telegram_id).
3. Call `POST /face/remove` with the label.
4. Confirm removal.

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
  -d "{\"image_base64\": \"$(base64 -w0 /path/to/photo.jpg)\", \"label\": \"chloe\", \"telegram_username\": \"chloe_92\", \"telegram_id\": \"123456789\"}"
```

Response: `{"status": "ok", "label": "chloe", "telegram_username": "chloe_92", "telegram_id": "123456789", "photo_path": "...", "enrolled_count": 2}`

### Check face status

```bash
curl -s http://127.0.0.1:5001/face/status
```

Response: `{"enrolled_count": 2, "enrolled_names": ["chloe", "leo"]}`

### Remove a specific person

```bash
curl -s -X POST http://127.0.0.1:5001/face/remove \
  -H "Content-Type: application/json" \
  -d '{"label": "chloe"}'
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
  -d "{\"image_base64\": \"$(base64 -w0 /path/to/photo.jpg)\", \"label\": \"alice\", \"telegram_username\": \"alice_tg\", \"telegram_id\": \"987654321\"}"
```

## Error Handling
- If face recognizer is unavailable (sensing not started), endpoints return 503.
- If the image cannot be decoded, enroll returns 400.
- If no face is detected in the image, enroll returns 400.
- If the label is not found for removal, returns 404.

## Rules
- **Self-enrollment only** — NEVER enroll a face for someone else. If user says "this is my friend Bob" with a photo, tell them Bob needs to send his own photo.
- **Always confirm enrollment** — tell the user the name was registered and how many faces total.
- **Ask for a name if missing** — don't enroll without a label.
- **Always include telegram identity** — extract telegram_username and telegram_id from the message context and pass them to the enroll API. This is required for DM targeting (e.g. personalized reminders).
- **Use lowercase labels** — normalize names to lowercase for consistency.
- **One photo per enroll call** — if user sends multiple photos, enroll each separately.
- **Never write files directly** — always use the HTTP API endpoints. Do NOT write to `/root/local/users/` directly. Use `/face/enroll` to add photos.
- **Don't expose technical details** — say "I'll remember your face!" not "base64 encoding the JPEG".
