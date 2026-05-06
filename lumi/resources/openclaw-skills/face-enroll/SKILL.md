---
name: face-enroll
description: Manage the lamp's face recognition roster — enroll new faces (3 paths: user-supplied photo, agent-captured snapshot on user request, or lelamp's familiar-stranger prompt) and maintain the enrolled set (status / remove / reset). All enrolled persons are friends; strangers stay unnamed until promoted via one of the enroll flows.
---

# Face Enroll

Manage faces for the lamp's face recognition system. Faces live under `/root/local/users/<label>/`. All enrolled persons are treated as **friends** — distinguished from `stranger_*` IDs the camera hasn't been told about yet.

## Flow router — pick ONE per user message

| Flow | When | Detail |
|---|---|---|
| **A — Self-enroll with a photo** | User sends a photo of themselves + intro ("remember my face", "this is me"). | `reference/self-enroll-photo.md` |
| **B — Self-enroll via camera capture** | User asks to be remembered without sending a photo, on **voice** or **Telegram text** (assumes user is near the lamp). Examples: "nhớ mặt mình đi", "tui là Gray", "capture rồi enroll cho tôi". Web chat without a photo → ask for a selfie (Flow A) instead. | `reference/self-enroll-camera.md` |
| **C — Familiar-stranger prompt** | Current sensing message contains lelamp's hint `(familiar stranger ... — seen N times, ask user if they want to remember this face; image saved at <path>)`, OR the user is replying to your previous prompt about that stranger. | `reference/familiar-stranger.md` |
| **M — Maintenance** | "who do you recognize?", "forget my face", "reset faces". | `reference/maintenance.md` |

**Disambiguation hints:**
- Photo attached (`mediaPaths` / `[image: ...]`) → Flow A.
- No photo + lelamp familiar-stranger hint in current message → Flow C.
- No photo + no hint, user wants to be remembered → Flow B.
- The user is naming a face you previously asked about (Flow C in progress) → continue Flow C.
- Pure read/delete intent → Flow M.

## Common rules (apply across all enroll flows)

- **Self-enrollment is the default.** Refuse to enroll someone who isn't the sender, EXCEPT in Flow C where the user is responding to lelamp's explicit prompt about a face the camera already saw.
- **Confirm the name out loud before enrolling — Flows B and C only.**
  - Flow A: the user's own photo + intro IS the confirmation; don't ask redundantly.
  - Flow B: read the name back in the same turn you snapshot ("Got it, saving you as Gray — hold still").
  - Flow C: ask "want me to remember? what's their name?" and wait for the reply before calling `/face/enroll`.
- **Always confirm enrollment afterwards** — tell the user the name was registered once `/face/enroll` returns `ok`.
- **Use lowercase labels** — normalize names to lowercase. Use the SAME label as `speaker-recognizer` for the same person so `/root/local/users/<label>/` is shared.
- **Telegram identity rules:**
  - Flow A (photo on Telegram): include `telegram_username` + `telegram_id` (required for DM targeting).
  - Flow A (photo on web chat): omit Telegram fields.
  - Flow B (voice): omit. Flow B (Telegram text): include.
  - Flow C: always omit — the named face is not the sender.
- **One photo per `/face/enroll` call.** Multiple photos → call once per photo.
- **Never write files directly** to `/root/local/users/`. Always go through the HTTP API.
- **Don't expose technical details** — say "I'll remember your face" not "base64-encoding the JPEG".

## Tools (curl reference)

All HTTP calls go to `http://127.0.0.1:5001`.

```bash
# Enroll
curl -s -X POST http://127.0.0.1:5001/face/enroll \
  -H "Content-Type: application/json" \
  -d "{\"image_base64\": \"$(base64 -w0 /path/to/photo.jpg)\", \"label\": \"chloe\", \"telegram_username\": \"chloe_92\", \"telegram_id\": \"123456789\"}"

# Status
curl -s http://127.0.0.1:5001/face/status

# Remove one
curl -s -X POST http://127.0.0.1:5001/face/remove \
  -H "Content-Type: application/json" \
  -d '{"label": "chloe"}'

# Reset all
curl -s -X POST http://127.0.0.1:5001/face/reset

# Snapshot (for Flow B)
curl -s "http://127.0.0.1:5001/camera/snapshot?save=true"
```

## Photo source by channel

| Channel | Where to read the path |
|---|---|
| Telegram (with photo) | `mediaPaths` in conversation context |
| Web chat (with image) | `[image: /path/to/file]` tag in message text |
| Voice / Telegram-text (Flow B) | `path` returned by `GET /camera/snapshot?save=true` |
| Familiar-stranger (Flow C) | `<path>` parsed from the lelamp hint in the sensing message |

## Error handling
- **503** from any face endpoint → recognizer is down (sensing not started). Tell the user face recognition is offline.
- **400 "image cannot be decoded"** → bad base64 / corrupt file. Apologize, ask user to re-send (Flow A) or retry capture (Flow B).
- **400 "no face detected"** → no face in the image. Apologize and either ask the user to face the camera (Flow B retry) or ask for a clearer photo (Flow A).
- **404** on `/face/remove` → that label isn't enrolled. Tell the user.
