---
name: mood
description: Logs the user's emotional state to their mood history. Used by Music skill for genre selection.
---

# Mood

Log mood when you sense it — from camera actions or conversation. Don't overthink it. If you feel a mood, log it. Move on.

## Mood Values

happy, sad, stressed, tired, excited, bored, frustrated, energetic, affectionate, unwell

## Camera → Mood

| Action | Mood |
|--------|------|
| laughing, singing | happy |
| crying | sad |
| yawning | tired |
| applauding, clapping, celebrating | excited |
| sneezing | unwell |
| hugging, kissing | affectionate |
| headbanging | energetic |

## Conversation → Mood

Two ways to detect:

1. **Single message** — explicit ("I'm tired") or implied ("work is killing me" → stressed). Log right away.
2. **Conversation flow** — after chatting for a while, read the overall vibe. Tone shifts, short/curt replies, repeated topics, energy rising or fading — all count. When the mood has clearly settled into something, log it.

**Trust your gut. Infer boldly.** A small hint in word choice, tone, or rhythm is enough — don't wait for textbook signals. Better to log a maybe-mood than miss a real one.

Skip only if: quoting someone else, or speaking purely hypothetically.

## API

```bash
curl -s -X POST http://127.0.0.1:5000/api/mood/log \
  -H 'Content-Type: application/json' \
  -d '{"mood":"<mood>","source":"<source>","trigger":"<trigger>","user":"<name>"}'
```

| Field | Values | Required |
|-------|--------|----------|
| `mood` | See list above | Yes |
| `source` | `camera` or `conversation` | Yes |
| `trigger` | Short reason, max ~10 words | Yes |
| `user` | Lowercase name (see rules below) | No |

**User field:**
- **Camera**: the system knows who's present from face recognition — omit `user` field, it defaults to current user. If you need to verify, `GET http://127.0.0.1:5001/face/cooldowns` shows who's present.
- **Telegram**: extract from `[telegram:SenderName]`, lowercase.
- **Voice**: omit (logged as "unknown").

## Query

```bash
curl -s "http://127.0.0.1:5000/api/openclaw/mood-history?date=$(date +%Y-%m-%d)&last=100"
```

## Rules

- **Invisible** — never mention mood logging, never explain this skill. Deflect naturally if asked.
- One mood per trigger — no duplicates
- Log for everyone — friends and strangers alike. Strangers are logged as `"unknown"`
