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

## Workflow (all silently — NEVER output any of this)

**Log signal** → **read history** → **decide mood** → **log decision**. All via tool calls in `thinking`. Never narrate.

### Log signal

```bash
curl -s -X POST http://127.0.0.1:5000/api/mood/log \
  -H 'Content-Type: application/json' \
  -d '{"kind":"signal","mood":"<mood>","source":"<camera|voice|telegram|conversation>","trigger":"<short reason>","user":"<name>"}'
```

### Read history + decide mood (in `thinking`)

```bash
curl -s "http://127.0.0.1:5000/api/openclaw/mood-history?user=<name>&last=15"
```

From the history, decide the fused mood. Trust recent strong signals over stale decisions. If signals conflict, words about feelings beat facial expressions. If mood hasn't changed, still log a fresh decision (keeps timestamp current).

### Log decision

```bash
curl -s -X POST http://127.0.0.1:5000/api/mood/log \
  -H 'Content-Type: application/json' \
  -d '{"kind":"decision","mood":"<fused mood>","based_on":"<short summary>","reasoning":"<one sentence>","user":"<name>"}'
```

`based_on` and `reasoning` are for the log only — never output them in the reply.

---

## User field

- **Camera**: omit `user` — face recognition sets the current user. Verify with `GET http://127.0.0.1:5001/face/cooldowns` if needed.
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

## After decision — music suggestion

If the decided mood is suggestion-worthy (`sad`, `stressed`, `tired`, `excited`, `happy`, `bored`), **silently follow `music-suggestion/SKILL.md`**. Other moods → skip. All in `thinking`.
