---
name: music-suggestion
description: Proactive music suggestion. Runs together with user-emotion-detection + mood on every emotion.detected event — reads, decision, and writes share the same parallel batch in a single turn (the backend injects [REQUIRED — run both skills this turn]). Triggered when the synthesized mood is suggestion-worthy (sad/stressed/tired/excited/happy/bored). Does NOT fire on motion.activity / [activity] events — those route to wellbeing/SKILL.md only. NOT for user-initiated music requests (those use the music skill).
---

# Music Suggestion (Proactive)

> **`unknown` users count.** Always run suggestion checks when `current_user` is `"unknown"` — speak only, no DM. Never skip because the user is unknown/unconfirmed.

## Triggers

Only one trigger: **Mood** — after logging a mood `decision` that is suggestion-worthy (`sad`, `stressed`, `tired`, `excited`, `happy`, `bored`). Activity events (`[activity] Activity detected: ...`, whether sedentary or drink/break) route to `wellbeing/SKILL.md` and never to this skill.

## User attribution

`{name}` MUST come from `[context: current_user=X]` tag. If missing, use `"unknown"`. NEVER infer from memory or chat history.

## What to read (pre-fetched in `[emotion_context: ...]`)

The backend injects everything you need on `emotion.detected`:

- `audio_playing` (bool) — replaces `GET /audio/status`.
- `last_suggestion_age_min` (int, `-1` if none today) — replaces `music-suggestion-history?last=1`.
- `prior_decision` + `is_decision_stale` — replaces `mood-history?kind=decision&last=1`. The freshly synthesized decision from THIS turn still lives in your `thinking`.
- `audio_recent` (`{track,duration_s,stopped}`) — replaces `audio/history?last=1`.
- `music_pattern_for_hour` (`{preferred_genre,strength,peak_hour}` or `null`) — replaces `cat patterns.json` matching by current hour ±1.
- `suggestion_worthy` (bool) — pre-applied bucket gate (true for `sad/stressed/tired/excited/happy/bored`).
- `mapped_mood` — convenient mirror of `user-emotion-detection`'s mapping; useful when no fresh decision exists yet.

**Do NOT fire any read tool calls when this block is present.**

### Fallback (only if `[emotion_context: ...]` is missing)

If the message has no context block (pre-fetch failed), fall back to the concurrent GET batch:

```bash
curl -s http://127.0.0.1:5001/audio/status &
curl -s "http://127.0.0.1:5000/api/openclaw/music-suggestion-history?user={name}&last=1" &
curl -s "http://127.0.0.1:5000/api/openclaw/mood-history?user={name}&kind=decision&last=1" &
curl -s "http://127.0.0.1:5001/audio/history?person={name}&last=1" &
cat /root/local/users/{name}/habit/patterns.json 2>/dev/null &
wait
```

## Skip rules (apply silently in `thinking`)

Read these straight from `[emotion_context: ...]`:

- `audio_playing == true` → skip.
- `last_suggestion_age_min` ∈ [0, 7) → skip cooldown still active. *(production: change to 30 min before ship)*
- `is_decision_stale == true` AND this turn did not synthesize a fresh decision → skip.
- `suggestion_worthy == false` → skip (mapped_mood is in `frustrated/energetic/affectionate/unwell/normal`).

If any rule says skip → reply `NO_REPLY`. Do not narrate why. Use `audio_recent` to personalize genre when not skipping.

## Pick genre

**Use `music_pattern_for_hour` from the context block** (already matched by current hour ± 1; do NOT re-`cat` patterns.json).

If `music_pattern_for_hour` is non-null → use its `preferred_genre`. Otherwise fall back to the default table below. The pattern is bootstrapped lazily by wellbeing on its first threshold nudge; absent = no habit data yet, fall back without invoking habit Flow A here.

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
- **Known users** — speak + DM via Telegram: `[HW:/emotion:{"emotion":"caring","intensity":0.5}][HW:/dm:{"telegram_id":"<id>"}] Your suggestion text`. Get `telegram_id` from `GET http://127.0.0.1:5001/user/info?name={name}`.
- **Unknown users** — speak only (no DM): `[HW:/emotion:{"emotion":"caring","intensity":0.5}] Your suggestion text`. Log with `user:"unknown"`.

## What to write (batch with the mood writes)

The suggestion log POST shares the write batch with mood signal + mood decision. Fire all three concurrently in one bash via `& ... wait`:

```bash
curl -s -X POST http://127.0.0.1:5000/api/music-suggestion/log \
  -H 'Content-Type: application/json' \
  -d '{"user":"{name}","trigger":"mood:tired","message":"Want some calm piano?"}'
```

Skip this POST when you skipped the suggestion (the `NO_REPLY` path).

Response includes `seq` and `day`. When user responds (in a later turn):
- Accepts → `POST /api/music-suggestion/status` with `{"user":"{name}","day":"<day>","seq":<seq>,"status":"accepted"}`
- Rejects → same body, `"status":"rejected"`
- Ignores → no update

## Learning from history

When checking `GET /audio/history`, use past behavior to personalize:
- Song ended naturally + listened > 3 min → user enjoyed it → suggest similar artist/genre.
- User stopped manually + listened < 30s → didn't like it → try different direction.
- No history → fall back to genre table above.

## Examples

- Mood: tired (known user) → `[HW:/emotion:{"emotion":"caring","intensity":0.5}][HW:/dm:{"telegram_id":"158406741"}] You seem tired — want some calm piano?`
- Mood: tired (unknown) → `[HW:/emotion:{"emotion":"caring","intensity":0.5}] You seem tired — want some calm piano?`
- Mood: stressed (known user) → `[HW:/emotion:{"emotion":"caring","intensity":0.6}][HW:/dm:{"telegram_id":"158406741"}] You look a bit tense — want some soft piano to ease into?`
- Mood: stressed (unknown) → `[HW:/emotion:{"emotion":"caring","intensity":0.6}] You look a bit tense — want some soft piano?`
- Mood: sad (unknown) → `[HW:/emotion:{"emotion":"caring","intensity":0.6}] Rough moment? Some gentle acoustic might help.`
- Mood: bored (unknown) → `[HW:/emotion:{"emotion":"caring","intensity":0.5}] Need a lift? How about some upbeat indie?`
- Mood: excited (unknown) → `[HW:/emotion:{"emotion":"happy","intensity":0.7}] Riding the energy — feel-good pop?`
- Mood: happy, music already playing → `NO_REPLY`
- After user confirms → `[HW:/audio/play:{"query":"Bill Evans Waltz for Debby","person":"leo"}][HW:/emotion:{"emotion":"happy","intensity":0.8}] Great choice!`

## Rules

- All computation stays in `thinking` — reply is only the suggestion sentence (with HW markers) or `NO_REPLY`.
- Never mention "cooldown", "interval", "threshold", or timestamps in the reply.
- `person` field in `/audio/play` must be lowercase.
- **Never open with a greeting.** This is an emotion-driven mood event, NOT a presence/arrival event. Forbidden openers: `hello`, `hi`, `hey`, `welcome back`, `oh, you're back`, anything containing `again` or referencing the user re-arriving. Greetings belong only to `presence.enter` in `sensing/SKILL.md`.
- **Tone must match the mood.** For `Fear` → `stressed` and `Sad` → `sad` decisions, use the `caring` emotion marker and a gentle acknowledging sentence — never cheerful or playful phrasing. If you can't produce a tone-appropriate one-liner, output `NO_REPLY`.
- **Don't reference the camera or detection.** No "I noticed you look…", "I can see…", "your face shows…" — speak as if you simply care, not as if you're describing a sensor reading.
