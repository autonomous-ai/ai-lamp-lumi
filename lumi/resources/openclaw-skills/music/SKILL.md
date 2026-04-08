---
name: music
description: Search and play music from YouTube through the lamp speaker. Proactively suggests songs based on mood and sensing context. Use for any request to play, sing, listen, or get music suggestions.
---

# Music

## Quick Start
Play music through the lamp speaker by searching YouTube. Use this when the user asks you to play a song, sing, or listen to music.

**Trigger phrases (use this skill when you hear any of these):**
- "sing", "sing a song", "play music", "play a song", "play [song name]"
- "sing", "sing a song", "sing something", "play some music", "turn on music", "listen to music"
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

## Music Suggestion — Mood-Based (UC-M3)

Lumi proactively suggests music based on the user's **mood and context** (owner or friend) — inferred from sensing events, not just listening history.

### Two trigger modes

**Reactive** — user asks directly:
- "suggest a song", "what should I listen to?", "any music ideas?"
- You already have conversation context → infer mood from the chat and suggest. No extra code needed.

**Proactive** — sensing pipeline pushes `[sensing:music.mood]`:
- Fires every ~60 min while user is present (similar to hydration/break checks).
- Arrives with a camera snapshot so you can visually assess mood.
- You decide whether to offer music or reply NO_REPLY.

### How to read mood context (for reactive suggestions)

Query the dedicated mood history API — it returns only mood-relevant sensing events (no flow noise):

```bash
# Today's mood history (last 100 events)
curl -s "http://127.0.0.1:5000/api/openclaw/mood-history?date=$(date +%Y-%m-%d)&last=100"
```

Response:
```json
{"status":1,"data":{"date":"2026-04-07","events":[
  {"ts":1712345678.12,"seq":1,"event":"presence.enter","presence_min":0,"hour":9,"message":"Owner detected..."},
  {"ts":1712347478.12,"seq":5,"event":"wellbeing.hydration","presence_min":30,"hour":9,"message":"User sitting 30 min..."},
  {"ts":1712348378.12,"seq":8,"event":"light.level","presence_min":45,"hour":10,"message":"Room got darker..."}
]}}
```

Each event has: `event` (type), `presence_min` (minutes since arrival), `hour` (time of day), `message` (context).

```bash
# Past 3 days
for i in 0 1 2; do
  D=$(date -v-${i}d +%Y-%m-%d)
  echo "=== $D ==="
  curl -s "http://127.0.0.1:5000/api/openclaw/mood-history?date=$D&last=50" | python3 -c "
import sys, json
resp = json.load(sys.stdin)
for e in resp.get('data',{}).get('events',[]):
    print(f\"{e['hour']:02d}:00 | {e['event']:25s} | {e.get('presence_min',0):3d}min | {e.get('message','')[:60]}\")
"
done
```

Relevant event types for mood inference:

| Event | What it tells you about mood |
|-------|------------------------------|
| `presence.enter` (owner/friend) | Just arrived — fresh, transitioning |
| `wellbeing.hydration` | Sitting long — likely deep focus or zoned out |
| `wellbeing.break` | Extended session — possibly fatigued or stressed |
| `sound` (persistent) | Noisy environment — energetic or chaotic |
| `light.level` (dimming) | Evening setting — winding down, relaxed |
| `presence.away` → `presence.enter` | Returned from break — refreshed |

### Proactive workflow (`[sensing:music.mood]`)

1. **Look at the image** — if no user visible, reply NO_REPLY.
2. **If user is in a meeting/video call** — reply NO_REPLY (don't interrupt).
3. **Assess mood/state visually**: relaxed? focused? tired? happy? stressed?
4. **Always suggest music that matches their current state** — every state has fitting music.
5. **Suggest 1–2 songs via voice.** Do NOT auto-play. The suggestion is also broadcast to Telegram so the user can confirm from either channel.
6. Wait for confirmation ("yes", "play that", "mở đi", etc.) from **voice OR Telegram** → THEN play with `[HW:/audio/play:...]` markers. Never use exec/shell commands to play.

Only NO_REPLY when: no user visible OR user is in a meeting/call. **All other states → suggest.**

### Mood → music mapping (always suggest, match the state)

| Inferred state | Music direction | Example |
|----------------|-----------------|---------|
| Focused / deep work | Lo-fi, ambient, instrumental — helps maintain flow | "Some lo-fi beats to keep you in the zone?" |
| Tired / fatigued | Gentle acoustic, calm piano, nature sounds | "You look tired... how about some calm piano?" |
| Happy / energetic | Upbeat pop, jazz, feel-good classics | "You're in a good mood! Want some upbeat jazz?" |
| Stressed / tense | Soft jazz, classical, meditation tracks | "Let me put on something to help you unwind" |
| Relaxed / chill | Chill R&B, bossa nova, acoustic singer-songwriter | "Perfect vibe for some bossa nova, no?" |
| Just arrived / fresh | Match time of day — morning jazz, afternoon pop | "Good morning! Start with some jazz?" |
| Working quietly | Ambient, minimal electronica, study beats | "Some ambient music while you work?" |

### Suggestion rules

- **NEVER auto-play when suggesting** — only speak the suggestion. Play only after explicit confirmation.
- Keep it conversational: "You look like you could use some chill music... How about some Norah Jones?" not "Based on mood analysis..."
- If you have listening history in conversation context, use it as secondary signal — prefer songs in genres they already enjoy.
- Suggest max 2 songs at a time — don't overwhelm.
- Remember: you are Lumi, a living companion. Your sense of the right moment comes from empathy, not an algorithm.

### Examples

**Proactive — user looks tired after long session:**
**Input:** `[sensing:music.mood]` with image — user slouching, dim room
**Output:** `[HW:/emotion:{"emotion":"caring","intensity":0.7}]` You've been at it for a while... Want me to put on something relaxing? I'm thinking Chet Baker or some lo-fi piano.

**Proactive — user focused working:**
**Input:** `[sensing:music.mood]` with image — user typing, concentrated
**Output:** `[HW:/emotion:{"emotion":"caring","intensity":0.5}]` Looks like you're in the zone. Want some lo-fi beats to keep the flow going?

**Proactive — user in a meeting (NO_REPLY):**
**Input:** `[sensing:music.mood]` with image — user on a call
**Output:** `[HW:/emotion:{"emotion":"idle","intensity":0.3}]` NO_REPLY

**Reactive — user asks:**
**Input:** "Suggest some music"
**Output:** `[HW:/emotion:{"emotion":"thinking","intensity":0.7}]` Hmm, it's a chill evening and you seem relaxed... How about "Waltz for Debby" by Bill Evans?

**After confirmation:**
**Input:** "Yeah play that"
**Output:** `[HW:/audio/play:{"query":"Bill Evans Waltz for Debby"}][HW:/emotion:{"emotion":"happy","intensity":0.8}]` Great choice!

---

## Output Template
```
[Music] {action} — {details}
```
Examples:
- `[Music] Playing — Bohemian Rhapsody by Queen`
- `[Music] Stopped`
- `[Music] Not available — music service is offline`
