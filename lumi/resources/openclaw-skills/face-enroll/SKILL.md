---
name: face-enroll
description: Self-enroll faces for recognition. Triggered when user sends a photo of themselves, or when lelamp surfaces a "familiar stranger" prompt (a stranger seen ≥2 times). Each person enrolls their own face for self-enrollment; familiar-stranger prompts let the user name a face the camera already captured. Telegram identity is saved for DM targeting.
---

# Face Enroll

## Quick Start
Manage faces for the lamp's face recognition system. Two enrollment paths:

1. **Self-enrollment** — user sends a photo of **themselves** via chat.
2. **Familiar-stranger prompt** — lelamp has seen the same unknown face 2 times and asks the user to name it. The image is already saved by lelamp; the user only supplies a name.

All enrolled persons are treated as **friends** — known people who get a friendly greeting, distinguished from strangers.

## Trigger — WHEN to activate this skill

Activate this skill when ANY of these fire:

**Self-enrollment (user sends a photo):**
- "remember **my** face" / "add **my** photo" / "this is **me**" / "enroll **me**"
- "add me" / "add my face"
- Any message where the user is introducing **themselves** with a photo

**Familiar-stranger prompt (no user photo needed):**
- The current sensing message contains the lelamp hint pattern:
  `(familiar stranger <stranger_id> — seen <N> times, ask user if they want to remember this face; image saved at <path>)`
- The user responds to your prompt with a name (e.g. "yes, that's Alice", "her name is Alice", "Alice").
- The user declines (e.g. "no", "ignore", "skip") — acknowledge and do nothing.

Do NOT activate self-enrollment when the user tries to enroll someone else with a photo (e.g. "this is Alice", "add my friend Bob"). That requires the familiar-stranger path — only proceed if lelamp surfaced the prompt first.

## Workflow

### Enroll a face (self-enrollment)
1. User sends a photo of themselves + introduction message.
2. Extract the **name** from the message. If no name is given, use the sender name from the message prefix (e.g. `[telegram:Chloe]` → `chloe`). If still unclear, ask the user.
3. Extract the sender's **Telegram identity** from the message context:
   - `telegram_username`: the sender's Telegram username (e.g. `chloe_92`)
   - `telegram_id`: the sender's numeric Telegram user ID (e.g. `123456789`)
   These are available in the message metadata provided by the channel.
4. Base64-encode the photo: use `mediaPaths` (Telegram) or the path from `[image: /path/to/file]` tag in the message (web chat).
5. Call `POST /face/enroll` with the base64 image, label, telegram_username, and telegram_id.
6. Confirm to user with the enrolled count.

### Enroll a familiar stranger (lelamp prompt)
Triggered when the current sensing message contains the lelamp hint:
`(familiar stranger <stranger_id> — seen <N> times, ask user if they want to remember this face; image saved at <path>)`

1. Parse `<stranger_id>` and `<path>` from the hint.
2. **Ask the user** in a natural, single message — do NOT enroll yet:
   - EN: "I've seen this person {N} times now — want me to remember them? If yes, what's their name?"
   - VI: "Mình đã thấy người này {N} lần rồi — bạn muốn mình ghi nhớ họ không? Nếu có thì tên họ là gì?"
3. Wait for the user's next reply.
4. If the user gives a **name** (with or without "yes"):
   - Lowercase the name → `label`.
   - Base64-encode the file at `<path>`.
   - Call `POST /face/enroll` with `image_base64`, `label`. Telegram identity is **not** included on this path (the named person is not the sender).
   - Confirm: "Got it, I'll remember {Name} from now on."
5. If the user **declines** ("no" / "skip" / "ignore"): acknowledge once ("Okay, I won't ask about this person again.") and stop. Lelamp will not re-prompt for the same `stranger_id` (the threshold fires only once per id).
6. If the user is **ambiguous** ("maybe later", silence-ish reply): treat as decline.

**One-shot rule:** the lelamp hint surfaces exactly once per stranger when the count first reaches the threshold. Don't re-ask in later turns even if you see the same `stranger_id` again — only act on the hint when it appears in the current sensing message.

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

When the user sends a photo, the file path is available from:
- **Telegram**: `mediaPaths` in conversation context
- **Web chat**: `[image: /path/to/file]` tag in the message text

Read the file and base64-encode it:

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
- **Self-enrollment is the default** — if the user sends a photo and asks to enroll someone else (e.g. "this is my friend Bob" with a photo), refuse: that person must send their own photo. The only exception is the familiar-stranger flow below.
- **Familiar-stranger flow only on lelamp prompt** — naming a face you didn't capture yourself is allowed ONLY when the current sensing message carries the lelamp hint. Never proactively enroll a stranger ID without that hint.
- **Always ask before enrolling** — for both flows, explicitly confirm the name with the user before calling `/face/enroll`. Don't enroll silently even when the user's wording sounds direct.
- **Always confirm enrollment** — tell the user the name was registered after the API returns ok.
- **Ask for a name if missing** — don't enroll without a label.
- **Telegram identity only on self-enrollment** — extract `telegram_username` and `telegram_id` from the message context for self-enrollment (required for DM targeting). Omit them on the familiar-stranger path — the named person is not the sender.
- **Use lowercase labels** — normalize names to lowercase for consistency.
- **One photo per enroll call** — if user sends multiple photos, enroll each separately.
- **Never write files directly** — always use the HTTP API endpoints. Do NOT write to `/root/local/users/` directly. Use `/face/enroll` to add photos.
- **Don't expose technical details** — say "I'll remember your face!" not "base64 encoding the JPEG".
