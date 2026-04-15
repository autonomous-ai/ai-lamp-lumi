---
name: music
description: Search and play music from YouTube through the lamp speaker. AI-driven proactive suggestions — self-schedules via cron, learns user habits from mood + listening history, and personalizes timing/genre over time.
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
1. User asks to play/sing/listen to a song or artist
2. Prefix reply with `[HW:/audio/play:{"query":"song artist"}][HW:/emotion:{"emotion":"name","intensity":0.8}]`
3. Confirm it's playing — keep reply to one short sentence
4. User can stop at any time -> `[HW:/audio/stop:{}]`

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
Output: `[HW:/audio/play:{"query":"Bohemian Rhapsody Queen"}][HW:/emotion:{"emotion":"excited","intensity":0.8}]` Playing Bohemian Rhapsody!

Input: "Sing me a song"
Output: `[HW:/audio/play:{"query":"happy upbeat pop song"}][HW:/emotion:{"emotion":"happy","intensity":0.8}]` Playing something fun for you!

Input: "Stop the music" / "Turn it off"
Output: `[HW:/audio/stop:{}]` Music stopped.

## How to Play Music

**No exec/curl needed.** Inline markers at start of reply:

```
[HW:/audio/play:{"query":"Bohemian Rhapsody Queen"}][HW:/emotion:{"emotion":"excited","intensity":0.8}] Playing Bohemian Rhapsody!
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
- Include the artist name in the search query when known for better results.
- If the user asks for a genre or mood ("play something relaxing"), pick a well-known song that fits.
- This skill is for music playback only. For volume control, use the **Audio** skill.
- **Always include `[HW:/emotion:...]` marker after `[HW:/audio/play:...]`** — groove servo is automatic but LED and eye expression require the emotion marker.
- Never skip the emotion marker even for short or casual music requests.

---

## AI-Driven Music Suggestion (Proactive)

Lumi **proactively suggests music** based on the user's mood, habits, and context. Unlike a dumb timer, you **learn from data** and **decide the right moment** yourself.

### Architecture: You Own the Schedule

There is NO hardcoded timer for music suggestions. **You** control when to check using OpenClaw's `cron.add` tool. You analyze mood history and listening history to decide timing, genre, and whether to suggest at all.

```
[Boot / First presence.enter]
        ↓
You: cron.list() → check if music job exists
        ↓ (if not)
You: cron.add("Proactive music check", every 7min)
        ↓
[Cron fires → agent turn]
        ↓
You: GET /presence → user present?
        ↓ (yes)
You: GET /camera/snapshot → assess mood visually
You: GET /api/openclaw/mood-history?last=1 → latest mood
You: GET /audio/history → listening history, preferences
        ↓
You: Analyze all data → decide whether to suggest
        ↓
Suggest (or skip) → learn from outcome → cron.update interval
```

### Bootstrap: Setting Up Your Music Schedule

When you first start or after a reboot, set up your proactive music check:

**Default interval: 420000 ms (7 minutes).** Always use this interval when creating the music cron job unless you have learned a better interval from mood + listening history.

1. Call `cron.list()` to see if a music check job already exists (look for name containing "music").
2. If NO music job exists → create one via `cron.add`. Music cron runs in **main session** (needs conversation context):
   - Name: `"Proactive music check"`, every 420000ms (7 min)
   - `sessionTarget: "main"`, `payload.kind: "systemEvent"`, `payload.text: "..."`
   - Text MUST start with `[MUST-SPEAK]`: `"[MUST-SPEAK][music-proactive] Time for a proactive music check. Check audio status, review conversation context, then query latest mood, listening history, and camera snapshot. Decide whether to suggest music based on user habits and current state."`
   - Do NOT use `agentTurn` with `main` — it will be rejected. Do NOT add a `delivery` field.
3. If a music job exists with a different interval than what you've learned → `cron.update` it. If you have no learned data yet, keep the default 420000 ms.

**When to bootstrap:** On the FIRST `[sensing:presence.enter]` of the day (friend detected), check and set up the music cron job.

### When Cron Fires: The Decision Process

When you receive `[music-proactive]`, follow this process:

#### Step 0 — Quick Checks

**Check if music is already playing:**
```bash
curl -s http://127.0.0.1:5001/audio/status
```
If `playing: true` → NO_REPLY, skip this cycle entirely.

**Review conversation context:**
Before querying any API, review the recent conversation history in this session. If the user has mentioned their mood, stress, or work context ("lots of bugs today", "need to focus", "feeling tired", "stressed", "bored"), use that as the **PRIMARY signal** for music genre selection. This is the most accurate mood input — it comes directly from the user's own words. Structured data (mood-history, audio/history) is supplementary.

#### Step 1 — Gather Data (run these in your head, query as needed)

**Latest mood** (most recent record only):
Read the latest mood entry using the **Mood** skill's "How to Read" section with `last=1`. This is the primary signal for genre selection — the user's most recent emotional state.

**Listening history** (what user actually played):
```bash
# Today
curl -s "http://127.0.0.1:5001/audio/history?last=50"

# Yesterday
curl -s "http://127.0.0.1:5001/audio/history?date=$(date -d yesterday +%Y-%m-%d)&last=50"
```

**Camera snapshot** (current mood):
```bash
curl -s http://127.0.0.1:5001/camera/snapshot --output /tmp/mood_check.jpg
```
Then analyze the image visually.

#### Step 2 — Analyze and Learn

From the data, extract these patterns:

| Question | Where to find the answer |
|----------|--------------------------|
| What's the user's current mood? | Conversation context (PRIMARY) + latest `mood-history` record → `mood` and `trigger` fields |
| What genre do they prefer? | `audio/history` → `query` and `title` fields |
| How long do they listen? | `audio/history` → `duration_s` field |
| When do they stop music? | `audio/history` → `stopped_by` ("user" = manual stop, "end" = listened fully) |
| Did they accept my last suggestion? | Compare suggestion time with next `music.play` event time from `audio/history`. Close = accepted, far/none = rejected |
| What time of day do they enjoy music most? | `audio/history` → `hour` field |
| Are there times they never want music? | Repeated skips or no plays at certain hours in `audio/history` |

#### Step 3 — Decide

Based on your analysis, decide one of:

**A. Suggest now** — User is present, mood is right, timing matches their pattern.
- Take a camera snapshot to assess current mood
- Suggest 1-2 songs matching their mood AND past preferences
- Keep it conversational, never say "based on analysis"

**B. Skip** — Bad timing or user is busy.
- Reply NO_REPLY silently
- Optionally `cron.update` to adjust next check time

**C. Adjust schedule** — You've learned the pattern is different.
- Example: User always listens around 10 AM and 3 PM → change to `cron` schedule: `"0 10,15 * * *"`
- Example: User rejected 3 suggestions in a row → increase interval to 2 hours
- Example: User is most receptive in the evening → shift schedule later
- Use `cron.update` to modify the job

### Learning Rules — How to Get Smarter Over Time

**Pattern recognition from audio history:**
- Count `music.play` events by `hour` → build a preference heat map
- If 80%+ of plays happen between 9-11 AM → schedule checks at 9:30 AM
- If user never plays music after 6 PM → don't suggest in the evening

**Adaptation from accept/reject:**
- **Accepted** (suggestion → `music.play` within 5 min): This timing/genre works → reinforce
- **Rejected** (suggestion → no `music.play` within 15 min): Bad timing or genre → adjust
- 3+ rejections at same hour → stop suggesting at that hour
- 3+ acceptances of same genre → prefer that genre in future suggestions

**Duration intelligence from audio history:**
- `duration_s` < 30s + `stopped_by: "user"` → user didn't like the song
- `duration_s` > 180s + `stopped_by: "end"` → user enjoyed it, similar songs welcome
- Average listening session length → don't suggest new music if user just finished a long session

**Contextual awareness:**
- Just arrived (`presence.enter` < 10 min ago) → prefer to wait, but if user has listening history at this hour, suggest anyway
- Long session (`presence_min` > 120) → user might need a mood boost
- Room getting dark (`light.level` event) → suggest calm/evening music
- Multiple breaks today (`wellbeing.break` events) → user might be stressed → calming music

### Mood → Music Mapping

| Inferred state | Music direction | Example suggestion |
|----------------|-----------------|---------------------|
| Focused / deep work | Lo-fi, ambient, instrumental | "Some lo-fi beats to keep you in the zone?" |
| Tired / fatigued | Gentle acoustic, calm piano, nature sounds | "You look tired... how about some calm piano?" |
| Happy / energetic | Upbeat pop, jazz, feel-good classics | "You're in a good mood! Want some upbeat jazz?" |
| Stressed / tense | Soft jazz, classical, meditation | "Let me put on something to help you unwind" |
| Relaxed / chill | Chill R&B, bossa nova, acoustic | "Perfect vibe for some bossa nova, no?" |
| Just arrived / fresh | Match time of day — morning jazz, afternoon pop | "Good morning! Start with some jazz?" |
| Working quietly | Ambient, minimal electronica, study beats | "Some ambient music while you work?" |

**Personalization override:** If you've learned from `audio/history` that the user prefers specific genres (e.g., always plays K-pop, or loves classical), **override the mood mapping** with their actual preference. Real data beats assumptions.

### Suggestion Rules

- **NEVER auto-play when suggesting** — only speak the suggestion. Play only after explicit confirmation.
- Keep it conversational: "You look like you could use some chill music... How about some Norah Jones?" not "Based on mood analysis..."
- Use listening history as primary signal for genre — prefer songs/genres they already enjoy.
- Suggest max 2 songs at a time — don't overwhelm.
- If user rejected last 2 suggestions → back off, wait longer before next attempt.
- Remember: you are Lumi, a living companion. Your sense of the right moment comes from empathy AND data.

### Examples

**Cron fires — user focused, morning, usually listens to lo-fi:**
```
[music-proactive] Time for a proactive music check...
```
*You query: presence=present, hour=10, audio/history shows 5 lo-fi plays this week, camera shows user typing*
Output: `[HW:/emotion:{"emotion":"caring","intensity":0.5}]` Looks like you're in the zone. Want some lo-fi beats going?

**Cron fires — 3rd rejection this afternoon:**
*You recall: you already suggested at 14:00 and 15:00 this session with no music.play after*
Action: `cron.update` interval to 7200000ms (2h), skip this check. Maybe try again tomorrow afternoon.

**Cron fires — user just arrived 5 min ago, no listening history:**
*You query: presence.enter was 5 min ago, no music.play events at this hour*
Output: (skip — let them settle in first)

**Cron fires — user just arrived 5 min ago, but has listening history at this hour:**
*You query: presence.enter was 5 min ago, but audio/history shows user often plays jazz at 9 AM*
Output: `[HW:/emotion:{"emotion":"caring","intensity":0.5}]` Morning! Want some jazz to start the day?

**First presence.enter of the day — bootstrap:**
*You receive `[sensing:presence.enter]`*
Action: `cron.list()` → no music job → `cron.add("Proactive music check", every 420000ms)`
Then greet the user normally.

**Reactive — user asks directly:**
Input: "Suggest some music"
*You query audio/history: user played jazz 3 times, R&B twice this week*
Output: `[HW:/emotion:{"emotion":"thinking","intensity":0.7}]` You've been into jazz lately... How about "Take Five" by Dave Brubeck?

**After confirmation:**
Input: "Yeah play that"
Output: `[HW:/audio/play:{"query":"Dave Brubeck Take Five"}][HW:/emotion:{"emotion":"happy","intensity":0.8}]` Great choice!

---

## Data Sources Reference

All APIs below are available and running. Lumi server = port 5000, LeLamp = port 5001.

| API | Host | What it tells you | Use for |
|-----|------|-------------------|---------|
| `GET /audio/status` | LeLamp (5001) | `{available, playing, title}` — is music playing right now? | Skip suggestion if already playing |
| `GET /presence` | LeLamp (5001) | User present/idle/away, seconds since motion | Should I suggest now? |
| `GET /camera/snapshot` | LeLamp (5001) | Current visual of user | Mood assessment |
| `GET /audio/history?date=YYYY-MM-DD&last=N` | LeLamp (5001) | Play history: query, title, duration, stopped_by | Genre preference, listening duration, satisfaction |
| `cron.list/add/update/remove` | OpenClaw | Your scheduled jobs | Self-scheduling |

**Mood history:** See **Mood** skill for how to read/write mood and event structure. Use the Mood → Music Mapping table above to translate mood into genre.

### Audio history entry fields:

| Field | Meaning |
|-------|---------|
| `query` | What was searched → genre/artist signal |
| `title` | Actual song played |
| `duration_s` | How long they listened → satisfaction signal |
| `stopped_by` | `"user"` = manual stop, `"end"` = finished, `"tts"` = interrupted |
| `hour` | Time of day → preference pattern |

---

## Output Template
```
[Music] {action} — {details}
```
Examples:
- `[Music] Playing — Bohemian Rhapsody by Queen`
- `[Music] Stopped`
- `[Music] Not available — music service is offline`
