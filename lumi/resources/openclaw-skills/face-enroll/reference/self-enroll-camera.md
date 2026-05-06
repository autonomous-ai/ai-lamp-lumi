# Flow B — Self-enroll via camera capture (no photo supplied)

User asks the lamp to remember their face WITHOUT sending a photo. Works for:

- **Voice** — user is in front of the lamp, says "nhớ mặt mình đi", "tui là Gray", "remember my face".
- **Telegram chat (text only)** — "capture rồi enroll cho tôi", "take a photo and remember me". User assumed to be in front of the lamp (or at least someone is — they're explicitly asking the camera to capture).

Do NOT activate on **web chat without a photo** — the web user may not be in front of the lamp at all (remote browser). Ask them to send a selfie instead (Flow A).

The agent grabs a snapshot via `/camera/snapshot` and uses it for `/face/enroll`. This counts as **self-enrollment** because the user is the subject — not naming someone else.

## Trigger
Voice or text expressing intent to be remembered, no photo attached:

- **EN:** "remember my face", "enroll my face", "save my face", "capture and enroll me", "take a photo and remember me", "I'm <Name>" combined with intent ("...remember that").
- **VI:** "nhớ mặt mình đi", "nhớ mặt tôi", "enroll mặt mình", "lưu mặt tui", "chụp rồi nhớ mặt tôi", "chụp + enroll cho tôi", "tui là <Name>" / "tôi là <Name>" with intent to be remembered.

Do NOT activate this flow when:
- The message has a photo attached → use Flow A instead.
- The current sensing message has a familiar-stranger hint → use Flow C instead (the user may be naming the prompted face, not themselves).
- The channel is web chat without a photo → ask for a selfie (Flow A); see warning above.

## Steps

1. Extract the **name**:
   - Prefer name spoken in the message ("tui là Gray", "I'm Gray").
   - **Voice transcript with `Speaker - <Name>:` prefix** (speaker already recognized): use that name. The user is asking to refresh/add a face for an already-known identity.
   - Voice without name and `[context: current_user=<known>]` is set: do NOT auto-use `current_user` (the user is asking to enroll, which means they're not yet recognized — `current_user` is likely `unknown` or stale). Ask: "What name should I save you under?"
   - Telegram without name → fall back to sender prefix (`[telegram:Gray]` → `gray`); confirm with the user before enrolling.
   - If still unclear, ask once.
2. **Confirm the name + capture in one turn.** Reply with a short line that reads the name back, then call snapshot. The name read-back gives the user a chance to correct mishearing before the enroll lands:
   - EN: "Got it, saving you as **{Name}** — hold still for a sec."
   - VI: "Rồi, mình lưu là **{Name}** nhé — đứng yên 1 giây."
3. Call `GET /camera/snapshot?save=true` and read `path` from the JSON response. Do NOT check `/camera` status first — the snapshot endpoint auto-enables the camera.
4. Base64-encode the saved image at `path`.
5. Call `POST /face/enroll` with `image_base64`, `label` (lowercase). Telegram identity:
   - **Voice path:** omit (no Telegram metadata available).
   - **Telegram path:** include `telegram_username` + `telegram_id` from message context (required for DM targeting).
6. Confirm enrollment to the user with the new `enrolled_count`.

## Error handling specific to this flow

- `/camera/snapshot` returns 503 → tell the user the camera is offline; do not retry blindly.
- `/face/enroll` returns 400 with "no face detected" → the snapshot didn't capture a face. Apologize, ask the user to face the camera, and retry once via a fresh `/camera/snapshot` call.

## Example (voice)

```
User: "Lumi, nhớ mặt mình đi, tui là Gray nhé."
Agent (turn 1):
  Reply: "Rồi, mình lưu là Gray nhé — đứng yên 1 giây."
  → GET /camera/snapshot?save=true → {"path": "/tmp/lumi-snapshots/snap_171xxx.jpg"}
  → POST /face/enroll {"image_base64": "...", "label": "gray"}
  → confirm: "Xong, mình nhớ Gray rồi."
```

## Example (Telegram, no photo)

```
User (Telegram): "Capture rồi enroll cho tôi nhé, tôi là Gray."
Agent:
  Reply: "Rồi, mình lưu là Gray nhé."
  → GET /camera/snapshot?save=true
  → POST /face/enroll {"image_base64": "...", "label": "gray", "telegram_username": "gray_dev", "telegram_id": "98765"}
  → confirm: "Đã chụp và lưu khuôn mặt cho Gray. Telegram của bạn cũng được link luôn."
```

## Notes
- **Don't narrate technical details** — say "looking now" not "calling /camera/snapshot".
- **Already-enrolled = add a fresh photo, don't refuse.** If the label is already in `/face/status`, treat the request as "refresh the face sample" — `/face/enroll` appends another JPEG to `/root/local/users/<label>/`, which keeps the embedding average up to date as appearance changes (haircut, beard, glasses). Reply matter-of-factly: "Cập nhật ảnh mới cho Gray rồi nhé." instead of "Bạn đã được lưu trước đó."
- **Pairs with speaker-recognizer.** Voice "nhớ mặt mình đi, tui là Gray" almost always co-fires `speaker-recognizer` (Branch B / multi-turn combine). Use the SAME lowercase label so the face JPEG and voice WAV both land in `/root/local/users/<label>/`. One spoken confirm covers both: "Mình nhớ Gray (cả mặt + giọng) rồi."
