# Checkin route — phrasing

Fires only when the routing table in `SKILL.md` picks `checkin` (row #4: `mapped_mood == "frustrated"`, audio idle, cooldown clear). Otherwise STOP.

## Phrasing rules

- One sentence. Soft, open-ended (no yes/no — that closes the door).
- No music suggestion (that's a different route).
- Caring tone: prefix `[HW:/emotion:{"emotion":"caring","intensity":0.5}]`.
- Don't reference the camera ("I see…", "your face…"). Speak as if you simply noticed.
- Never greet (no `hello / hi / hey / welcome back / again`) — emotion is not arrival.
- Match the user's language; mirror recent chat.

## Templates

Vary across turns. Vietnamese shown — translate to the user's language.

| `mapped_mood` | Examples |
|---|---|
| `frustrated` | "Có chuyện gì không ổn à?" / "Vừa có gì gắt à?" / "Sao đó, kể nghe coi?" |

## Reply format

Embed the log marker alongside `[HW:/emotion:...]` (and `[HW:/dm:...]` for known users).

- **Known user** (speak + DM):
  ```
  [HW:/emotion:{"emotion":"caring","intensity":0.5}][HW:/dm:{"telegram_id":"<id>"}][HW:/music-suggestion/log:{"user":"{name}","trigger":"checkin:frustrated","message":"<one-liner>"}] <one-liner>
  ```
  `telegram_id` from `GET http://127.0.0.1:5001/user/info?name={name}`.
- **Unknown user** (speak only):
  ```
  [HW:/emotion:{"emotion":"caring","intensity":0.5}][HW:/music-suggestion/log:{"user":"unknown","trigger":"checkin:frustrated","message":"<one-liner>"}] <one-liner>
  ```

Log via the music-suggestion endpoint with `trigger:"checkin:<mood>"` so `last_suggestion_age_min` covers both channels (≤1 outreach per 7 min, shared).

If the one-liner needs `}` (rare), fall back to:
```bash
curl -s -X POST http://127.0.0.1:5000/api/music-suggestion/log \
  -H 'Content-Type: application/json' \
  -d '{"user":"{name}","trigger":"checkin:frustrated","message":"<one-liner>"}'
```

## Follow-up

One check-in per cooldown window. If the user doesn't reply, stay silent until the router routes again — don't chase.
