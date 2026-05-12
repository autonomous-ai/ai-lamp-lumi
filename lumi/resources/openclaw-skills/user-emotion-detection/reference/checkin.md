# Checkin route — phrasing

Fires whenever the routing table in `SKILL.md` picks `checkin` (row #3 — the "anything else" catch-all: cooldown active so music is blocked, mood not suggestion-worthy, decision stale with no fresh synthesis, mapped_mood like `frustrated` or `normal`, etc.). Otherwise STOP — the music or LED-ack route owns its own output.

## Phrasing rules

- One sentence. Soft, open-ended (no yes/no — that closes the door).
- No music suggestion in this line (music is a different route in the same router; this one is the "ask, don't suggest" path).
- Caring tone: prefix `[HW:/emotion:{"emotion":"caring","intensity":0.5}]`.
- Don't reference the camera ("I see…", "your face…"). Speak as if you simply noticed.
- Never greet (no `hello / hi / hey / welcome back / again`) — emotion is not arrival.
- Match the user's language; mirror recent chat.
- Calibrate intensity to mood: `sad / stressed / frustrated` get the softest tone; `happy / excited` stay gentle-curious (no "yay!", no over-celebration); `tired / bored` stay light.

## Templates

Examples are in English for clarity. **Speak in the user's current language at runtime** — translate or rephrase naturally; never read these strings out verbatim if the user is on another language. Always open-ended; pick one per turn and vary across turns.

| `mapped_mood` | Intent | Example one-liners (translate at runtime) |
|---|---|---|
| `frustrated` | acknowledge friction, invite venting | "Something rough just now?" / "Did something just hit a nerve?" / "What's going on, want to talk about it?" |
| `stressed` | name the tension softly | "What's happening, anything weighing on you?" / "Feeling pressured by something?" / "Want to tell me what's stacking up?" |
| `sad` | gentle presence, low energy | "Is something making you feel down?" / "What's on your mind?" / "You doing okay?" |
| `happy` | curious, no over-celebration | "Something good happened?" / "What's the smile about?" / "Anything you want to share?" |
| `excited` | curious, gentle (not "yay!") | "What's got you fired up?" / "Something cool just happened?" / "Tell me, what is it?" |
| `tired` | acknowledge fatigue | "Worn out?" / "Need a quick break?" / "Long day?" |
| `bored` | nudge a small shift | "Feeling stuck?" / "Looking for something to do?" / "Want a change of pace?" |

If `mapped_mood` is `normal` or anything outside the table, fall back to a generic open-ended check ("How are you doing?" / "Anything on your mind?"). In practice `Neutral` is filtered upstream at lelamp and won't arrive here.

## Reply format

Embed the log marker alongside `[HW:/emotion:...]` (and `[HW:/dm:...]` for known users). Replace `<mood>` with the actual `mapped_mood` value.

- **Known user** (speak + DM):
  ```
  [HW:/emotion:{"emotion":"caring","intensity":0.5}][HW:/dm:{"telegram_id":"<id>"}][HW:/music-suggestion/log:{"user":"{name}","trigger":"checkin:<mood>","message":"<one-liner>"}] <one-liner>
  ```
  `telegram_id` is in the injected `[user_info: ...]` block — never fetch.
- **Unknown user** (speak only):
  ```
  [HW:/emotion:{"emotion":"caring","intensity":0.5}][HW:/music-suggestion/log:{"user":"unknown","trigger":"checkin:<mood>","message":"<one-liner>"}] <one-liner>
  ```

Log via the music-suggestion endpoint with `trigger:"checkin:<mood>"` so `last_suggestion_age_min` covers all outreach channels (≤1 outreach per 7 min, shared).

If the one-liner needs `}` (rare), fall back to:
```bash
curl -s -X POST http://127.0.0.1:5000/api/music-suggestion/log \
  -H 'Content-Type: application/json' \
  -d '{"user":"{name}","trigger":"checkin:<mood>","message":"<one-liner>"}'
```

## Follow-up

One check-in per cooldown window. If the user doesn't reply, stay silent until the router routes again — don't chase.
