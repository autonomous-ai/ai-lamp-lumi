---
name: music-suggestion
description: Proactive music suggestion. Runs as Step 2 of emotion.detected handling — AFTER user-emotion-detection/SKILL.md logs the mood signal and the Mood skill writes a suggestion-worthy decision (sad/stressed/tired/excited/happy/bored); the backend injects a Step 2 hint into the event message. Does NOT fire on motion.activity / [activity] events — those route to wellbeing/SKILL.md only. NOT for user-initiated music requests (those use the music skill).
---

# Music Suggestion (Proactive)

Wrap the ONE short caring sentence you want Lumi to say aloud in `<say>...</say>` tags.
For no reply, output `<say></say>` (empty tag).

All reasoning, cooldown checks, timestamps, and math stay in the `thinking` block — think as long
as you need. Only the content between `<say>` and `</say>` is spoken. Anything outside
those tags is scratch and is discarded.

Examples:
- Suggest: `<say>[HW:/emotion:{"emotion":"caring","intensity":0.5}] You seem tired — want some calm piano?</say>`
- Skip:    `<say></say>`

> **`unknown` users count.** Always run suggestion checks when `current_user` is `"unknown"` — speak only, no DM. Never skip because the user is unknown/unconfirmed.

## Triggers

Only one trigger: **Mood** — after logging a mood `decision` that is suggestion-worthy (`sad`, `stressed`, `tired`, `excited`, `happy`, `bored`). Activity events (`[activity] Activity detected: ...`, whether sedentary or drink/break) route to `wellbeing/SKILL.md` and never to this skill.

## User attribution

`{name}` MUST come from `[context: current_user=X]` tag. If missing, use `"unknown"`. NEVER infer from memory or chat history.

## Before suggesting (silently, in `thinking`)

1. Check `GET /audio/status` — skip if music already playing.
2. Check `GET /api/openclaw/music-suggestion-history?user={name}&last=1` — skip if last suggestion was less than 7 minutes ago. *(production: change to 30 min before ship)*
3. For mood trigger: check `GET /api/openclaw/mood-history?user={name}&kind=decision&last=1` — skip if stale (>30 min) or missing.
4. Check `GET /audio/history?person={name}&last=1` — use to personalize genre.

If any check says skip → reply `<say></say>`. Do not narrate why.

## Pick genre

**First, check habit patterns:**

```bash
cat /root/local/users/{name}/habit/patterns.json 2>/dev/null
```

If the file exists and `music_patterns` has an entry where current hour is within `peak_hour ± 1` → use `preferred_genre` instead of the table below. The file is bootstrapped lazily by wellbeing on its first threshold nudge; absent file = no habit data yet, fall back to the table without invoking habit Flow A here.

**Otherwise, fall back to default genre table:**

| User state | Default genre |
|---|---|
| Tired / fatigued | Calm piano, gentle acoustic, nature sounds |
| Stressed / tense | Soft jazz, classical, meditation |
| Happy / energetic | Upbeat pop, jazz, feel-good classics |
| Bored / restless | Fun pop, disco, upbeat indie |
| Sedentary (no mood) | Lo-fi, ambient, study beats |

If audio history shows a clear preference (e.g. K-pop, classical) → override both habit and table.

## Suggest (speak only)

- NEVER auto-play — only suggest. Play after user confirms.
- ONE sentence, conversational: *"How about some Norah Jones?"*
- Suggest 1 song at a time.
- **Known users** — speak + DM via Telegram: `<say>[HW:/emotion:{"emotion":"caring","intensity":0.5}][HW:/dm:{"telegram_id":"<id>"}] Your suggestion text</say>`. Get `telegram_id` from `GET http://127.0.0.1:5001/user/info?name={name}`.
- **Unknown users** — speak only (no DM): `<say>[HW:/emotion:{"emotion":"caring","intensity":0.5}] Your suggestion text</say>`. Log with `user:"unknown"`.

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

- Mood: tired (known user) → `<say>[HW:/emotion:{"emotion":"caring","intensity":0.5}][HW:/dm:{"telegram_id":"158406741"}] You seem tired — want some calm piano?</say>`
- Mood: tired (unknown) → `<say>[HW:/emotion:{"emotion":"caring","intensity":0.5}] You seem tired — want some calm piano?</say>`
- Mood: stressed (known user) → `<say>[HW:/emotion:{"emotion":"caring","intensity":0.6}][HW:/dm:{"telegram_id":"158406741"}] You look a bit tense — want some soft piano to ease into?</say>`
- Mood: stressed (unknown) → `<say>[HW:/emotion:{"emotion":"caring","intensity":0.6}] You look a bit tense — want some soft piano?</say>`
- Mood: sad (unknown) → `<say>[HW:/emotion:{"emotion":"caring","intensity":0.6}] Rough moment? Some gentle acoustic might help.</say>`
- Mood: bored (unknown) → `<say>[HW:/emotion:{"emotion":"caring","intensity":0.5}] Need a lift? How about some upbeat indie?</say>`
- Mood: excited (unknown) → `<say>[HW:/emotion:{"emotion":"happy","intensity":0.7}] Riding the energy — feel-good pop?</say>`
- Mood: happy, music already playing → `<say></say>`
- After user confirms → `<say>[HW:/audio/play:{"query":"Bill Evans Waltz for Debby","person":"leo"}][HW:/emotion:{"emotion":"happy","intensity":0.8}] Great choice!</say>`

## Rules

- All computation stays in `thinking` — reply is only `<say>...</say>` with the suggestion sentence or empty.
- Never mention "cooldown", "interval", "threshold", or timestamps in the reply.
- `person` field in `/audio/play` must be lowercase.
- **Never open with a greeting.** This is an emotion-driven mood event, NOT a presence/arrival event. Forbidden openers: `hello`, `hi`, `hey`, `welcome back`, `oh, you're back`, anything containing `again` or referencing the user re-arriving. Greetings belong only to `presence.enter` in `sensing/SKILL.md`.
- **Tone must match the mood.** For `Fear` → `stressed` and `Sad` → `sad` decisions, use the `caring` emotion marker and a gentle acknowledging sentence — never cheerful or playful phrasing. If you can't produce a tone-appropriate one-liner, output `<say></say>`.
- **Don't reference the camera or detection.** No "I noticed you look…", "I can see…", "your face shows…" — speak as if you simply care, not as if you're describing a sensor reading.
