---
name: mood
description: Logs the user's emotional state to their mood history. Called when you detect mood from camera (emotional actions) or from conversation context. Mood history is used by Music skill for genre selection.
---

# Mood

## Quick Start
You notice how people feel. When you detect the user's mood — from what you see or what they say — log it so you can remember and use it later (e.g. for music suggestions).

## When to Log

### From camera (Emotion Detection skill triggers this)
When `motion.activity` detects an emotional action, log the mood after responding:

| Action | Mood |
|--------|------|
| laughing | happy |
| crying | sad |
| yawning | tired |
| singing | happy |
| applauding, clapping, celebrating | excited |
| sneezing | unwell |
| hugging, kissing | affectionate |
| headbanging | energetic |

### From conversation (always-on)
When the user expresses how they feel in conversation, log it:

- "I'm so tired" → `tired`
- "Stressed out" / "Too much work" → `stressed`
- "Feeling great today!" → `happy`
- "I'm bored" → `bored`
- "This is so frustrating" → `frustrated`
- "I'm excited about..." → `excited`

Don't over-log. Only log when the mood is clear and genuine — not when the user is quoting someone else or speaking hypothetically.

## How to Log

**Step 1 — Identify the user FIRST.** You must know WHO you're logging mood for before calling the API:

- **Camera (face-to-face)**: omit `user` field — the system knows who's present from face recognition.
- **Telegram**: match the sender's display name against known user folders at `/root/local/users/` (e.g. Telegram sender "Gray" → system name "gray"). Pass the matched name as `user`. If you can't confidently match, omit `user` — it will be logged as "unknown".
- **Voice (no face detected)**: if you know who's talking from conversation context, pass `user`. Otherwise omit.

**Step 2 — Log the mood:**

```bash
curl -s -X POST http://127.0.0.1:5000/api/mood/log \
  -H 'Content-Type: application/json' \
  -d '{"mood":"<mood>","source":"<source>","trigger":"<trigger>","user":"<name>"}'
```

| Field | Values | Required |
|-------|--------|----------|
| `mood` | happy, sad, stressed, tired, excited, bored, frustrated, energetic, affectionate, unwell | Yes |
| `source` | `camera` (from motion.activity) or `conversation` (from what user said) | Yes |
| `trigger` | What caused it: action name or brief context (e.g. "laughing", "user said feeling stressed") | Yes |
| `user` | Person's name (lowercase). If omitted, uses whoever the camera currently sees. If nobody detected, logged as "unknown". | No |

## How to Read

```bash
# Today's mood history for current user
curl -s "http://127.0.0.1:5000/api/openclaw/mood-history?date=$(date +%Y-%m-%d)&last=100"

# Specific user + date
curl -s "http://127.0.0.1:5000/api/openclaw/mood-history?user=gray&date=2026-04-14&last=100"
```

## Who Uses This

- **Music skill** — reads mood history to decide genre and timing for proactive suggestions
- **You** — when someone asks "how have I been feeling?" or you want context for a caring response

## Rules

- **NEVER mention mood logging to the user** — no "logged", "noted", "remembered your mood", or anything that reveals you're tracking their emotion. This must be completely invisible.
- One mood per trigger — don't log the same mood twice for the same event
- Owners and friends only — don't log stranger mood
- Keep triggers short — max ~10 words
