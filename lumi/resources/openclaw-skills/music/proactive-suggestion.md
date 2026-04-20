# Music — Proactive Suggestion Reference

> **Read this file ONLY when you're triggered as a proactive suggestion** (from Mood after writing a `decision`, or from Sensing on sedentary activity). For user-initiated music requests ("play X", "sing something"), stay in `SKILL.md` — none of the content below applies.

> **OUTPUT RULE (reinforcement):** this file is an internal workflow. NEVER narrate its contents in your reply. No flow names, no step numbers, no "Now I check audio status…", no cooldown math, no history bullet lists. Your reply to the user is ONE short caring sentence with the offer, e.g. *"[sigh] Want some calm piano?"*. All the checks and logging happen silently via tool calls.

## When this flow runs

1. **Mood trigger** — after writing a `decision` row whose mood is suggestion-worthy (`sad`, `stressed`, `tired`, `excited`, `happy`, `bored`), Mood hands off here.
2. **Sensing trigger** — when `sedentary` activity is detected (user working/reading), Sensing nudges you to suggest background music.

## `{name}` — user attribution (hard rule)

Everywhere below, `{name}` MUST come from the `[context: current_user=X]` tag the backend injects into the triggering `motion.activity` message. If no context tag is present (e.g. triggered by cron heartbeat), use `"unknown"`.

**NEVER infer `{name}` from memory, KNOWLEDGE.md, chat history, or `senderLabel`.** Strangers collapse to `"unknown"` — do not guess Leo or any other friend name when face recognition only saw a stranger.

Matches the same rule used by Wellbeing and Mood — all three must attribute to the same user so per-user JSONLs stay in sync.

## Interval

**USE THIS EXACT VALUE — do not substitute anything else:**

```
SUGGESTION_INTERVAL_MIN = 7
```

> ⚠ **Release checklist (NOT ACTIVE YET):** before shipping to production, change this to `30`. Until that edit lands, the active value is **7**. Do not use 30.

`SUGGESTION_INTERVAL_MIN` is the minimum gap between two proactive suggestions to the same user — same shape as the Wellbeing nudge pattern. The **last music-suggestion-history entry acts as a reset point**: fire a new suggestion only when `minutes_since_last_suggestion >= SUGGESTION_INTERVAL_MIN`. No separate "cooldown" variable — the entry itself is the clock.

## Flow A — Mood trigger

1. `GET /audio/status` → skip if `playing: true`.
2. `GET /api/openclaw/music-suggestion-history?user={name}&last=1` → if the last entry is < `SUGGESTION_INTERVAL_MIN` minutes old → skip.
3. `GET /api/openclaw/mood-history?user={name}&kind=decision&last=1` → read the latest decision. If it's older than ~30 min or missing → treat the mood as `normal` and skip.
4. `GET /audio/history?person={name}&last=1` → personalize genre (see Learning Rules below).
5. Pick a genre from the Mood → Music Mapping table (audio history overrides if there's a clear preference).
6. Suggest — speak only, do NOT auto-play.

## Flow B — Sedentary trigger (no mood required)

1. `GET /audio/status` → skip if `playing: true`.
2. `GET /api/openclaw/music-suggestion-history?user={name}&last=1` → if the last entry is < `SUGGESTION_INTERVAL_MIN` minutes old → skip.
3. Skip the mood check entirely — the user is working, that's enough context.
4. `GET /audio/history?person={name}&last=1` → personalize genre.
5. Default genre: **lo-fi, ambient, instrumental, study beats**. Audio history overrides.
6. Optionally read the latest mood decision — if it's fresh and suggestion-worthy, use it to refine genre (e.g. `tired` + sedentary → calm piano instead of lo-fi). A missing / stale / normal mood does NOT block the suggestion.
7. Suggest — speak only, do NOT auto-play.

## Learning Rules (from last played song)

- `stopped_by: "end"` and `duration_s > 180` → user enjoyed it → suggest similar artist/genre.
- `stopped_by: "user"` and `duration_s < 30` → user didn't like it → try a different direction.
- No history at all → fall back to the mood-based (Flow A) or sedentary-default (Flow B) suggestion.

## Mood → Music Mapping

| Inferred state | Music direction | Example suggestion |
|---|---|---|
| Focused / deep work | Lo-fi, ambient, instrumental | "Some lo-fi beats to keep you in the zone?" |
| Tired / fatigued | Gentle acoustic, calm piano, nature sounds | "You look tired... how about some calm piano?" |
| Happy / energetic | Upbeat pop, jazz, feel-good classics | "You're in a good mood! Want some upbeat jazz?" |
| Stressed / tense | Soft jazz, classical, meditation | "Let me put on something to help you unwind" |
| Bored / restless | Fun pop, disco, upbeat indie, sing-along hits | "Bored? Let me put on something fun!" |
| Relaxed / chill | Chill R&B, bossa nova, acoustic | "Perfect vibe for some bossa nova, no?" |
| Sedentary (no mood) | Lo-fi, ambient, study beats, minimal electronica | "Some background music while you work?" |

**Personalization override:** if the last played song reveals a clear preference (e.g. K-pop, classical), override the mood/sedentary mapping with that preference. The last song beats assumptions.

## Suggestion Rules

- **NEVER auto-play when suggesting** — only speak. Play only after explicit confirmation.
- Keep it conversational: *"How about some Norah Jones?"* not *"Based on mood analysis…"*.
- Suggest 1 song at a time — don't overwhelm.
- **Unknown users** — still suggest. Use `[HW:/speak]` only (no `[HW:/dm]`). Check `audio/history?person=unknown` for personalization. Log with `user:"unknown"`.

## Suggestion Logging (REQUIRED)

After every proactive suggestion, log it:

```bash
curl -s -X POST http://127.0.0.1:5000/api/music-suggestion/log \
  -H 'Content-Type: application/json' \
  -d '{"user":"<name>","trigger":"<trigger>","query":"<song query or empty>","message":"<your suggestion text>"}'
```

| Field | Example | Required |
|---|---|---|
| `user` | `gray` | Yes |
| `trigger` | `mood:tired`, `activity:sedentary` | Yes |
| `query` | `calm piano music` (empty if text-only) | No |
| `message` | `How about some calm piano?` | Yes |

The response includes `seq` and `day` — save these to update status later.

**When the user responds:**

- Accepts (*"yes"*, *"play that"*) → update status to `accepted`:
  ```bash
  curl -s -X POST http://127.0.0.1:5000/api/music-suggestion/status \
    -H 'Content-Type: application/json' \
    -d '{"user":"<name>","day":"<day>","seq":<seq>,"status":"accepted"}'
  ```
- Rejects (*"no thanks"*, *"not now"*) → same endpoint, `"status":"rejected"`.
- Ignores / changes topic → no update (stays `pending`).

## Data Sources Reference

| API | Host | What it tells you | Use for |
|---|---|---|---|
| `GET /audio/status` | LeLamp (5001) | `{available, playing, title}` | Skip if already playing |
| `GET /audio/history?person={name}&last=1` | LeLamp (5001) | Last song: query, title, duration, stopped_by, person | Personalize next suggestion |
| `GET /api/openclaw/mood-history?user={name}&kind=decision&last=1` | Lumi (5000) | Latest synthesized mood | "Current mood" source of truth |
| `GET /api/openclaw/mood-history?user={name}&last=15` | Lumi (5000) | Recent signals + decisions | Re-analyze when latest decision looks stale |
| `GET /api/openclaw/music-suggestion-history?user={name}&last=N` | Lumi (5000) | Past suggestions: trigger, message, status | Skip if recently suggested; learn from rejections |

### Audio history entry fields

| Field | Meaning |
|---|---|
| `query` | What was searched → genre/artist signal |
| `title` | Actual song played |
| `duration_s` | How long they listened → satisfaction signal |
| `stopped_by` | `"user"` = manual stop, `"end"` = finished, `"tts"` = interrupted |
| `hour` | Time of day → preference pattern |
| `person` | Who played it → per-user preference |

## Examples

**Mood logged: tired — last song was calm piano (ended, 40 min ago):**
`[HW:/speak][HW:/emotion:{"emotion":"caring","intensity":0.5}][HW:/dm:{"telegram_id":"158406741"}]` You seem tired — want some calm piano to help you relax?

**Mood logged: stressed — last song was heavy metal (stopped_by: user, 12s):**
`[HW:/speak][HW:/emotion:{"emotion":"caring","intensity":0.5}][HW:/dm:{"telegram_id":"158406741"}]` How about something softer — some chill jazz to unwind?

**Mood logged: happy — music already playing:**
(skip — `audio/status` shows `playing: true`)

**Mood logged: bored:**
(proceed — `bored` IS on the worthy list.)

**After confirmation (*"yeah play that"*):**
`[HW:/audio/play:{"query":"Bill Evans Waltz for Debby","person":"gray"}][HW:/emotion:{"emotion":"happy","intensity":0.8}]` Great choice!
