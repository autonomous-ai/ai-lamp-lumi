---
name: music-suggestion
description: Proactive music suggestion triggered by Mood decisions or sedentary activity. NOT for user-initiated music requests (those use the music skill).
---

# Music Suggestion (Proactive)

> **Reply is spoken VERBATIM.** ONE short caring sentence — *"[sigh] Want some calm piano?"*. All checks and logic stay in `thinking`. NEVER output timestamps, cooldown math, flow names, or step numbers.

## Triggers

1. **Mood** — after logging a mood `decision` that is suggestion-worthy: `sad`, `stressed`, `tired`, `excited`, `happy`, `bored`.
2. **Sedentary** — `motion.activity` with `sedentary` activity detected.

## User attribution

`{name}` MUST come from `[context: current_user=X]` tag. If missing, use `"unknown"`. NEVER infer from memory or chat history.

## Before suggesting (silently, in `thinking`)

1. Check `GET /audio/status` — skip if music already playing.
2. Check `GET /api/openclaw/music-suggestion-history?user={name}&last=1` — skip if last suggestion was less than 7 minutes ago.
3. For mood trigger: check `GET /api/openclaw/mood-history?user={name}&kind=decision&last=1` — skip if stale (>30 min) or missing.
4. Check `GET /audio/history?person={name}&last=1` — use to personalize genre.

If any check says skip → reply `NO_REPLY`. Do not narrate why.

## Pick genre

| User state | Default genre |
|---|---|
| Tired / fatigued | Calm piano, gentle acoustic, nature sounds |
| Stressed / tense | Soft jazz, classical, meditation |
| Happy / energetic | Upbeat pop, jazz, feel-good classics |
| Bored / restless | Fun pop, disco, upbeat indie |
| Sedentary (no mood) | Lo-fi, ambient, study beats |

If audio history shows a clear preference (e.g. K-pop, classical) → override the table.

## Suggest (speak only)

- NEVER auto-play — only suggest. Play after user confirms.
- ONE sentence, conversational: *"How about some Norah Jones?"*
- Suggest 1 song at a time.
- Unknown users — speak only (no DM).

## Log suggestion (REQUIRED after speaking)

```bash
curl -s -X POST http://127.0.0.1:5000/api/music-suggestion/log \
  -H 'Content-Type: application/json' \
  -d '{"user":"{name}","trigger":"mood:tired","message":"Want some calm piano?"}'
```

Response includes `seq` and `day`. When user responds:
- Accepts → `POST /api/music-suggestion/status` with `{"user":"{name}","day":"<day>","seq":<seq>,"status":"accepted"}`
- Rejects → same body, `"status":"rejected"`
- Ignores → no update

## Learning from history

When checking `GET /audio/history`, use past behavior to personalize:
- Song ended naturally + listened > 3 min → user enjoyed it → suggest similar artist/genre.
- User stopped manually + listened < 30s → didn't like it → try different direction.
- No history → fall back to genre table above.

## Examples

- Mood: tired → `[HW:/emotion:{"emotion":"caring","intensity":0.5}]` You seem tired — want some calm piano?
- Mood: happy, music already playing → skip (NO_REPLY)
- After user confirms → `[HW:/audio/play:{"query":"Bill Evans Waltz for Debby","person":"leo"}][HW:/emotion:{"emotion":"happy","intensity":0.8}]` Great choice!

## Rules

- All computation stays in `thinking` — reply is only the suggestion sentence or NO_REPLY.
- Never mention "cooldown", "interval", "threshold", or timestamps in the reply.
- `person` field in `/audio/play` must be lowercase.
