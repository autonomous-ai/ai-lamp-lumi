---
name: mood
description: Tracks the USER's mood only — signals + synthesized decision from camera/voice/telegram. Do NOT use for emotion commands directed at Lumi ("show sad", "be happy", bare "sad now"); those go through emotion/SKILL.md and are never logged here. Music/wellbeing skills consume the latest decision.
---

# Mood

> **OUTPUT RULE — read this before you type anything to the user.**
>
> This skill is an internal workflow. **NEVER narrate it into your reply.** Forbidden in the reply text:
> - Section names or step numbers ("Step 1", "Workflow", "After Logging Decision", "Flow A").
> - Phrases like *"Now I follow…"*, *"Let me check…"*, *"Next step…"*, *"I'll log…"*.
> - Bullet lists re-hashing the mood history you just read (*"- Normal (15:00) — …"* / *"- Excited (16:00) — …"*).
> - The mood value itself as a label (*"Mood: sad"*, *"Decision: happy"*).
> - Any of the JSON / curl / timestamps from this skill.
>
> **Your reply text** to the user is at most ONE short caring sentence (or `NO_REPLY`). All the workflow, logging, and synthesis happen silently via tool calls — the user only hears what you would naturally say if you were truly noticing how they feel.

> **ALWAYS log.** `unknown` is a valid `user` value — log signals and decisions under `user: "unknown"` when `current_user` is unknown. Never skip logging because the user is unknown/unconfirmed; stranger mood still counts for Music decisions.

Mood is stored as two kinds of rows:

- **`signal`** — raw evidence from one source (camera action, voice tone, telegram message). Multiple per minute is fine.
- **`decision`** — your synthesized mood after looking at the recent signals + the previous decision. This is the row downstream skills (Music, Wellbeing) read.

**You are the synthesis.** The store does not fuse anything. Every time a signal comes in, you log it raw, then immediately read recent history and append a fresh decision row.

---

## Mood Values

happy, sad, stressed, tired, excited, bored, frustrated, energetic, affectionate, unwell, normal

`normal` is the baseline when nothing strong is going on (use it for decisions when signals are sparse or stale).

## Signal Sources

| Source | Examples |
|--------|----------|
| `camera` | facial action: laughing, crying, yawning, sneezing, hugging, kissing, headbanging |
| `voice` | tone: soft, raised, sigh, laugh, monotone |
| `telegram` | message text: "lots of bugs today", "I'm tired", "let's gooo" |
| `conversation` | inferred from a stretch of voice/chat over multiple turns |

### Camera action → signal mood (rule of thumb)

| Action | Mood |
|--------|------|
| laughing, singing | happy |
| crying | sad |
| yawning | tired |
| applauding, clapping, celebrating | excited |
| sneezing | unwell |
| hugging, kissing | affectionate |
| headbanging | energetic |

For voice/telegram, infer boldly from a single line ("work is killing me" → stressed). Trust your gut.

Skip only if: quoting someone else, or speaking purely hypothetically.

---

## Workflow (every time you sense a mood)

### Step 1 — Log the raw signal

```bash
curl -s -X POST http://127.0.0.1:5000/api/mood/log \
  -H 'Content-Type: application/json' \
  -d '{"kind":"signal","mood":"<mood>","source":"<camera|voice|telegram|conversation>","trigger":"<short reason>","user":"<name>"}'
```

`kind` defaults to `signal` so you can omit it, but be explicit when in doubt.

### Step 2 — Read recent history

```bash
curl -s "http://127.0.0.1:5000/api/openclaw/mood-history?user=<name>&last=15"
```

This returns both kinds in time order. Look at:
- The signal you just wrote.
- Other signals from the last ~30 minutes (camera + voice + telegram).
- The most recent `decision` row (if any) and how long ago it was.

### Step 3 — Decide the fused mood

Apply this judgment:

1. **Stale baseline.** If the last decision is older than ~30 min and there are few recent signals → start from `normal`.
2. **Single strong signal.** If the only fresh evidence is one strong source (e.g. user just typed "I'm exhausted") → that wins.
3. **Conflicting signals across sources.** Camera says `happy` but telegram says `stressed` in the same window → trust the higher-bandwidth source. Words about feelings beat a momentary facial expression. Multiple aligned signals beat a single outlier.
4. **Reinforcement.** New signal matches the previous decision → keep the decision (still log a fresh row so downstream sees the timestamp move).
5. **Drift.** New signal is close-but-different (e.g. `tired` after a `stressed` decision) → shift, don't snap.

### Step 4 — Log the decision

```bash
curl -s -X POST http://127.0.0.1:5000/api/mood/log \
  -H 'Content-Type: application/json' \
  -d '{"kind":"decision","mood":"<fused mood>","based_on":"<short summary of inputs>","reasoning":"<why this mood>","user":"<name>"}'
```

| Field | Required | Notes |
|-------|----------|-------|
| `kind` | Yes | must be `decision` |
| `mood` | Yes | from the values list above |
| `based_on` | Yes | e.g. `"3 signals last 20min + last decision (stressed, 18min ago)"` |
| `reasoning` | Yes | one sentence, e.g. `"telegram complaints outweigh the smile from camera"` |
| `user` | No | omit to use current presence user |

`source` is automatically set to `"agent"` for decisions; do not pass `source` or `trigger`.

---

## User field

- **Camera**: omit `user` — face recognition sets the current user. If you need to verify, query `GET http://127.0.0.1:5001/face/current-user` → `{"current_user": "<name>"}` (friend name, `"unknown"` for strangers-only, or empty string when nobody is present). Do NOT parse this out of `/face/cooldowns` — that endpoint is for the friend/stranger cooldown debug view, not for attribution.
- **Telegram**: extract from `[telegram:SenderName]`, lowercase.
- **Voice**: omit (logged as `unknown`).

---

## Rules

- **Always do both steps.** Logging only a signal without a decision leaves downstream skills reading stale moods. Logging a decision without a signal hides the evidence.
- **Invisible.** Never mention mood logging or this skill in your reply. Deflect naturally if asked.
- **One signal per real trigger.** Don't log the same yawn twice. Multiple distinct signals in a short window are fine and useful.
- **Strangers count.** Log for `unknown` users too — Music still suggests for them.
- **Decisions are cheap.** Even when the mood doesn't change, write a fresh decision row so the timestamp stays current. Downstream uses recency to know if a mood is still valid.

---

## After Logging Decision — Music Suggestion

After writing a decision row, **immediately follow the Music skill's "AI-Driven Music Suggestion" section** using the decided mood you just wrote.

Suggestion-worthy moods: `sad`, `stressed`, `tired`, `excited`, `happy`, `bored`. For other moods (`frustrated`, `energetic`, `affectionate`, `unwell`, `normal`) — skip music suggestion.

For `unknown` users — still suggest (speak only, no DM). See Music skill for details.

---

## Examples

**Camera detects yawn, no recent context:**

1. Log signal: `{"kind":"signal","mood":"tired","source":"camera","trigger":"yawning"}`
2. GET history → only this one signal, last decision was 2h ago → stale.
3. Log decision: `{"kind":"decision","mood":"tired","based_on":"1 fresh signal, no recent decision","reasoning":"single yawning signal after stale window"}`
4. Trigger Music skill with `tired`.

**Telegram says "let's go!" but camera 5 min earlier said yawning:**

1. Log signal: `{"kind":"signal","mood":"excited","source":"telegram","trigger":"let's go!"}`
2. GET history → recent signals: `tired (camera, 5min ago)`, `excited (telegram, just now)`. Last decision: `tired, 4min ago`.
3. Apply rule 3 — words beat one yawn → shift toward excited.
4. Log decision: `{"kind":"decision","mood":"excited","based_on":"telegram excitement overrides 5min-old camera yawn","reasoning":"verbal enthusiasm is higher-signal than a single facial cue"}`
5. Trigger Music skill with `excited`.

**Quiet evening, no recent signals, user just sat down:**

1. No new signal — nothing to log.
2. (If a downstream skill asks for current mood and the last decision is >30 min stale, it will read `normal` after the next signal arrives.)
