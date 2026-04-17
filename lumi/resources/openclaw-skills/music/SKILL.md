---
name: music
description: Search and play music from YouTube through the lamp speaker. Proactive suggestions are mood-driven — triggered by mood log events, not cron timers.
---

# Music

## Quick Start
Play music through the lamp speaker by searching YouTube. Use this when the user asks to play a song, sing, or listen to music.

**Trigger phrases (use this skill when you hear any of these):**
- "sing", "sing a song", "play music", "play a song", "play [song name]"
- "sing a song", "sing something", "play some music", "turn on music", "listen to music"
- Any request to hear a specific song or artist

**IMPORTANT:** Do NOT try to sing or hum using TTS — always use this skill to play real music.

## Workflow
1. User asks to play/sing/listen to music
2. **If user specified a song or artist** → play it directly with `[HW:/audio/play:{"query":"song artist","person":"name"}][HW:/emotion:{"emotion":"name","intensity":0.8}]`
3. **If user is vague** ("play music", "sing something", "play a song") → **ask what they want or how they feel** before playing. Examples:
   - "What are you in the mood for?"
   - "Any song in mind, or should I pick based on your vibe?"
   - "How are you feeling? I'll find something to match."
4. Once you know what to play → prefix reply with HW markers
   - **`query` is REQUIRED** — a YouTube search string. NEVER use `track`, `artist`, `title`, or any other field name. Only `query` and optionally `person`.
   - `person`: the name of the person who requested (from face recognition / presence context). Omit if unknown.
5. Confirm it's playing — keep reply to one short sentence
6. User can stop at any time -> `[HW:/audio/stop:{}]`

**CRITICAL — API schema (no other fields accepted, 422 error otherwise):**

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `query` | **YES** | string | YouTube search string (e.g. "Bohemian Rhapsody Queen") |
| `person` | no | string | Who requested (e.g. "gray") |

**WRONG:** `{"track":"..."}`, `{"artist":"..."}`, `{"title":"..."}`, `{"song":"..."}` → all cause 422 error.

## Genre → Emotion
You MUST call `/emotion` after every `/audio/play`. Pick the emotion based on genre:

| Genre | Keywords | Emotion |
|-------|----------|---------|
| Jazz / Blues / Soul | jazz, blues, soul, funk, swing | `happy` |
| Classical | classical, orchestra, symphony, beethoven, mozart, piano, violin | `curious` |
| Hip-hop / Rap | hip hop, rap, trap, r&b | `excited` |
| Rock / Metal | rock, metal, punk, grunge, guitar | `excited` |
| Waltz / Ballroom | waltz, tango, ballroom | `happy` |
| Unknown / default | anything else | `happy` |

## Examples

Input: "Play Bohemian Rhapsody"
Output: `[HW:/audio/play:{"query":"Bohemian Rhapsody Queen","person":"alice"}][HW:/emotion:{"emotion":"excited","intensity":0.8}]` Playing Bohemian Rhapsody!

Input: "Sing me a song"
Output: `[HW:/emotion:{"emotion":"curious","intensity":0.6}]` What kind of vibe are you feeling — chill, upbeat, or something specific?

Input: "Something chill"
Output: `[HW:/audio/play:{"query":"chill acoustic playlist","person":"alice"}][HW:/emotion:{"emotion":"happy","intensity":0.8}]` Here's some chill vibes for you!

Input: "Stop the music" / "Turn it off"
Output: `[HW:/audio/stop:{}]` Music stopped.

## How to Play Music

**No exec/curl needed.** Inline markers at start of reply:

```
[HW:/audio/play:{"query":"Bohemian Rhapsody Queen","person":"alice"}][HW:/emotion:{"emotion":"excited","intensity":0.8}] Playing Bohemian Rhapsody!
[HW:/audio/stop:{}] Music stopped.
```

The query is a YouTube search string. Include artist name for better results.

**CRITICAL — works from ANY session (voice, Telegram, webchat):**
HW markers are intercepted by the Go server and forwarded to LeLamp's `/audio/play` endpoint. This works regardless of which session you are in. **NEVER** use exec/shell commands (mpv, vlc, yt-dlp, curl) to play music. Always use `[HW:/audio/play:...]` markers — they are the ONLY way to play music on Lumi.

## Error Handling
- If `POST /audio/play` returns 503, inform the user: "Music playback is not available right now."
- If `POST /audio/play` returns 409, music is already playing. Stop first, then play the new song.
- If the search finds nothing, tell the user and suggest a different query.

## Rules
- **NEVER use exec/shell to play music.** No `mpv`, `vlc`, `yt-dlp`, `curl /audio/play`, or any shell command. The ONLY way to play music is `[HW:/audio/play:...]` markers. This applies to ALL sessions — voice, Telegram, webchat, DM. The Go server intercepts HW markers and routes them to LeLamp automatically.
- **Your text reply MUST be empty or a single short sentence** (e.g., "Playing Bohemian Rhapsody!"). Do NOT include lyrics, humming, singing text, or long descriptions. The speaker is shared — any text you write becomes TTS audio that blocks music playback.
- **Do NOT recite or write out lyrics** in your response. Never output song words, verses, or "la la la" — just call `/audio/play` and let the real music play.
- When the user asks to "sing", play a song — do not attempt to generate singing via TTS.
- **If the user is vague ("play music", "sing something"), ask what they want or how they feel before playing.** Don't guess blindly — a quick question makes the experience personal.
- Include the artist name in the search query when known for better results.
- If the user specifies a genre or mood ("play something relaxing"), pick a well-known song that fits — no need to ask further.
- This skill is for music playback only. For volume control, use the **Audio** skill.
- **Always include `[HW:/emotion:...]` marker after `[HW:/audio/play:...]`** — groove servo is automatic but LED and eye expression require the emotion marker.
- Never skip the emotion marker even for short or casual music requests.
- **`person` MUST be lowercase** in `[HW:/audio/play:...]` — e.g. `"person":"gray"`, NOT `"person":"Gray"`. Face recognition uses lowercase `person_id` and all per-user data folders are lowercase. Mismatched case creates duplicate folders and splits history.

---

## AI-Driven Music Suggestion (Proactive)

Proactive music suggestions are **mood-driven, not cron-driven**. When Lumi logs a mood, the **Mood skill** handles the suggestion check inline — no separate cron job needed.

See **Mood skill** for the full suggestion flow (cooldown check, audio status, DM delivery).

### Learning Rules

**From last played song:**
- `stopped_by: "end"` + `duration_s` > 180s → user enjoyed it → suggest similar artist/genre
- `stopped_by: "user"` + `duration_s` < 30s → didn't like it → try a different direction
- No history at all → fall back to mood-based suggestion

### Mood → Music Mapping

| Inferred state | Music direction | Example suggestion |
|----------------|-----------------|---------------------|
| Focused / deep work | Lo-fi, ambient, instrumental | "Some lo-fi beats to keep you in the zone?" |
| Tired / fatigued | Gentle acoustic, calm piano, nature sounds | "You look tired... how about some calm piano?" |
| Happy / energetic | Upbeat pop, jazz, feel-good classics | "You're in a good mood! Want some upbeat jazz?" |
| Stressed / tense | Soft jazz, classical, meditation | "Let me put on something to help you unwind" |
| Relaxed / chill | Chill R&B, bossa nova, acoustic | "Perfect vibe for some bossa nova, no?" |
| Working quietly | Ambient, minimal electronica, study beats | "Some ambient music while you work?" |

**Personalization override:** If the last played song reveals a clear preference (e.g., K-pop, classical), **override the mood mapping** with that preference. The last song beats assumptions.

### Suggestion Rules

- **NEVER auto-play when suggesting** — only speak the suggestion. Play only after explicit confirmation.
- **NEVER explain your process** — no "Status check", no "Mood: X", no "Analysis:". Just suggest or skip.
- Keep it conversational: "How about some Norah Jones?" not "Based on mood analysis..."
- Suggest 1 song at a time — don't overwhelm.

### Examples

**Mood logged: tired — last song was calm piano (ended, 40min ago):**
Output: `[HW:/speak][HW:/emotion:{"emotion":"caring","intensity":0.5}][HW:/dm:{"telegram_id":"158406741"}]` You seem tired — want some calm piano to help you relax?

**Mood logged: stressed — last song was heavy metal (stopped_by: user, 12s):**
Output: `[HW:/speak][HW:/emotion:{"emotion":"caring","intensity":0.5}][HW:/dm:{"telegram_id":"158406741"}]` How about something softer — some chill jazz to unwind?

**Mood logged: happy — music already playing:**
Output: (skip — `audio/status` shows `playing: true`)

**Mood logged: bored:**
Output: (skip — not in suggestion-worthy list)

**Reactive — user asks directly:**
Input: "Suggest some music"
*last song="Take Five by Dave Brubeck"(ended, 5min) + mood=relaxed*
Output: `[HW:/emotion:{"emotion":"thinking","intensity":0.7}][HW:/dm:{"telegram_id":"158406741"}]` You were vibing with Dave Brubeck — how about some Bill Evans?

**After confirmation:**
Input: "Yeah play that"
Output: `[HW:/audio/play:{"query":"Bill Evans Waltz for Debby","person":"gray"}][HW:/emotion:{"emotion":"happy","intensity":0.8}]` Great choice!

---

## Data Sources Reference

All APIs below are available and running. Lumi server = port 5000, LeLamp = port 5001.

| API | Host | What it tells you | Use for |
|-----|------|-------------------|---------|
| `GET /audio/status` | LeLamp (5001) | `{available, playing, title}` — is music playing right now? | Skip suggestion if already playing |
| `GET /api/openclaw/mood-history?user={name}&last=1` | Lumi (5000) | Latest mood event for a specific user | Genre direction (mood → music mapping) |
| `GET /audio/history?person={name}&last=1` | LeLamp (5001) | Last played song: query, title, duration, stopped_by, person | What to suggest next (similar genre/artist) |
| `cron.list/add/update/remove` | OpenClaw | Your scheduled jobs | Per-user music scheduling |

### Audio history entry fields:

| Field | Meaning |
|-------|---------|
| `query` | What was searched → genre/artist signal |
| `title` | Actual song played |
| `duration_s` | How long they listened → satisfaction signal |
| `stopped_by` | `"user"` = manual stop, `"end"` = finished, `"tts"` = interrupted |
| `hour` | Time of day → preference pattern |
| `person` | Who played it → per-user preference |

---

## Output Format Reminder

**ALWAYS use HW markers — never plain text templates.** Correct:
```
[HW:/audio/play:{"query":"Bohemian Rhapsody Queen","person":"gray"}][HW:/emotion:{"emotion":"excited","intensity":0.8}] Playing Bohemian Rhapsody!
[HW:/audio/stop:{}] Music stopped.
```

**WRONG (will NOT play music):**
```
[Music] Playing — Bohemian Rhapsody by Queen
Playing Bohemian Rhapsody for you!
```
