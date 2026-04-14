---
name: face-enroll
description: Enroll faces for recognition. Triggered when user sends a photo with a person's name, introduces someone, or says "remember this face". Supports two roles — owner (lamp's master) and friend (known person).
---

# Face Enroll

## Quick Start
Manage faces for the lamp's face recognition system. Users send a photo via chat to enroll a face. The lamp will then recognize them by name in future encounters.

Two roles:
- **Owner** — the lamp's master. Gets the warmest greeting on presence detection.
- **Friend** — a known person. Gets a friendly greeting, distinguished from strangers.

## Trigger — WHEN to activate this skill

Activate this skill when the user sends a **photo** together with ANY of these patterns:

### Owner enrollment (role = "owner")
- "add owner" / "add owner [name]" / "add owner photo"
- "remember **my** face" / "add **my** photo" / "this is **me**" / "enroll **me**"
- "save owner face" / "save my face"
- Any message where the user is enrolling **themselves** (first person: I, my, me)
- Any message containing "add owner" — this ALWAYS means face enrollment when a photo is attached

### Friend enrollment (role = "friend")
- "add friend" / "add friend [name]"
- "this is [name]" / "this is my friend [name]" / "meet [name]"
- "remember [name]" / "remember this face, [name]"
- "add [name]" / "enroll [name]" / "say hi to [name]"
- Any message where the user is introducing **someone else** (third person, with a name)

### How to decide the role
- **First person** ("my face", "this is me", "remember me as Leo") → **owner**
- **Third person** ("this is Chloe", "remember her", "add bạn này tên Chloe") → **friend**
- If unclear, **ask** the user: "Is this you or a friend?"

## Workflow

### Enroll a face
1. User sends a photo + name/introduction.
2. Determine the **role** (owner or friend) from the message context.
3. Extract the **name** from the message. If no name is given, ask the user.
4. Base64-encode the photo from `mediaPaths`.
5. Call `POST /face/enroll` with the base64 image, label, and role.
6. **If role is owner** — update `USER.md` with `Face ID: <label>` so the owner profile links to the face recognition folder. Also fill in the owner's name if not already set.
7. Confirm to user with the enrolled count.

### Check who is recognized
1. User asks "who do you recognize?" or "how many faces?"
2. Call `GET /face/status`.
3. Reply with names and count.

### Remove a specific person
1. User says "forget Alice" or "remove Alice's face".
2. Call `POST /face/remove` with the label.
3. Confirm removal.

### Change a person's role
1. User says "set Leo as owner" or "change Chloe to friend" or "make all friends".
2. Call `POST /face/set-role` with the label and new role.
3. **If new role is owner** — update `USER.md` with `Face ID: <label>` and the owner's name.
4. Confirm the role change.

### Reset all faces
1. User says "forget all faces" or "reset faces".
2. Call `POST /face/reset`.
3. Confirm all faces cleared.

## Tools

**Bash** with `curl` for HTTP calls to `http://127.0.0.1:5001`.

### Enroll a face (owner)

```bash
curl -s -X POST http://127.0.0.1:5001/face/enroll \
  -H "Content-Type: application/json" \
  -d "{\"image_base64\": \"$(base64 -w0 /path/to/photo.jpg)\", \"label\": \"leo\", \"role\": \"owner\"}"
```

### Enroll a face (friend)

```bash
curl -s -X POST http://127.0.0.1:5001/face/enroll \
  -H "Content-Type: application/json" \
  -d "{\"image_base64\": \"$(base64 -w0 /path/to/photo.jpg)\", \"label\": \"chloe\", \"role\": \"friend\"}"
```

Response: `{"status": "ok", "label": "chloe", "role": "friend", "photo_path": "...", "enrolled_count": 2}`

### Check face status

```bash
curl -s http://127.0.0.1:5001/face/status
```

Response: `{"owner_count": 2, "owner_names": ["chloe", "leo"]}`

### Remove a specific person

```bash
curl -s -X POST http://127.0.0.1:5001/face/remove \
  -H "Content-Type: application/json" \
  -d '{"label": "alice"}'
```

### Change role

```bash
curl -s -X POST http://127.0.0.1:5001/face/set-role \
  -H "Content-Type: application/json" \
  -d '{"label": "leo", "role": "owner"}'
```

Response: `{"status": "ok", "label": "leo", "role": "owner"}`

### Reset all faces

```bash
curl -s -X POST http://127.0.0.1:5001/face/reset
```

## How to base64-encode the photo

When the user sends a photo, it arrives in `mediaPaths`. Read the file and base64-encode it:

```bash
curl -s -X POST http://127.0.0.1:5001/face/enroll \
  -H "Content-Type: application/json" \
  -d "{\"image_base64\": \"$(base64 -w0 /path/to/photo.jpg)\", \"label\": \"alice\", \"role\": \"friend\"}"
```

## Error Handling
- If face recognizer is unavailable (sensing not started), endpoints return 503.
- If the image cannot be decoded, enroll returns 400.
- If no face is detected in the image, enroll returns 400.
- If the label is not found for removal, returns 404.

## Rules
- **Photo + name = face enrollment** — whenever a user sends a photo with a person's name, ALWAYS enroll the face. This is the primary trigger. Do not interpret "add owner" or similar phrases as anything other than face enrollment.
- **Always confirm enrollment** — tell the user the name was registered and how many faces total.
- **Ask for a name if missing** — don't enroll without a label.
- **Use lowercase labels** — normalize names to lowercase for consistency.
- **One photo per enroll call** — if user sends multiple photos, enroll each separately.
- **Never write files directly** — always use the HTTP API endpoints. Do NOT write to `/root/local/users/` or `metadata.json` directly. Use `/face/set-role` to change roles, `/face/enroll` to add photos.
- **Always include role** — determine owner vs friend from context and pass the correct role.
- **Don't expose technical details** — say "I'll remember your face" (owner) or "I'll remember [name]!" (friend), not "base64 encoding the JPEG".
