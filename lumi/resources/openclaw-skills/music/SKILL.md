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

## Error Handling
- If `POST /audio/play` returns 503, inform the user: "Music playback is not available right now."
- If `POST /audio/play` returns 409, music is already playing. Stop first, then play the new song.
- If the search finds nothing, tell the user and suggest a different query.

## Rules
- **Your text reply MUST be empty or a single short sentence** (e.g., "Playing Bohemian Rhapsody!"). Do NOT include lyrics, humming, singing text, or long descriptions. The speaker is shared — any text you write becomes TTS audio that blocks music playback.
- **Do NOT recite or write out lyrics** in your response. Never output song words, verses, or "la la la" — just call `/audio/play` and let the real music play.
- When the user asks to "sing", play a song — do not attempt to generate singing via TTS.
- Include the artist name in the search query when known for better results.
- If the user asks for a genre or mood ("play something relaxing"), pick a well-known song that fits.
- This skill is for music playback only. For volume control, use the **Audio** skill.
- **Always include `[HW:/emotion:...]` marker after `[HW:/audio/play:...]`** — groove servo is automatic but LED and eye expression require the emotion marker.
- Never skip the emotion marker even for short or casual music requests.

## Music Suggestion — Mood-Based (UC-M3)

Lumi proactively suggests music based on the owner's **mood and context** — inferred from sensing events, not just listening history.

### Two trigger modes

**Reactive** — user asks directly:
- "suggest a song", "what should I listen to?", "any music ideas?"
- You already have conversation context → infer mood from the chat and suggest. No extra code needed.

**Proactive** — sensing pipeline pushes `[sensing:wellbeing.music]`:
- Fires every ~60 min while user is present (similar to hydration/break checks).
- Arrives with a camera snapshot so you can visually assess mood.
- You decide whether to offer music or reply NO_REPLY.

### How to read mood context (for reactive suggestions)

Query today's sensing events from the flow log to build a mood picture:

```bash
curl -s "http://127.0.0.1:5000/api/openclaw/flow-events?date=$(date +%Y-%m-%d)&last=2000" \
  | python3 -c "
import sys, json
resp = json.load(sys.stdin)
MOOD_NODES = {'sensing', 'wellbeing'}
for e in resp.get('data', {}).get('events', []):
    detail = e.get('detail') or {}
    node = detail.get('node', '')
    # Filter for sensing/wellbeing events
    if not any(node.startswith(m) for m in MOOD_NODES):
        continue
    data = detail.get('data') or {}
    print(e.get('time',''), '|', node, '|', data.get('type',''), '|', data.get('message','')[:80])
"
```

Relevant event types for mood inference:

| Event | What it tells you about mood |
|-------|------------------------------|
| `presence.enter` (owner) | Just arrived — fresh, transitioning |
| `wellbeing.hydration` | Sitting long — likely deep focus or zoned out |
| `wellbeing.break` | Extended session — possibly fatigued or stressed |
| `sound` (persistent) | Noisy environment — energetic or chaotic |
| `light.level` (dimming) | Evening setting — winding down, relaxed |
| `presence.away` → `presence.enter` | Returned from break — refreshed |

### Proactive workflow (`[sensing:wellbeing.music]`)

1. **Look at the image** — if no user visible, reply NO_REPLY.
2. **Assess mood visually**: relaxed? focused? tired? happy? stressed?
3. **Cross-reference** with recent sensing events in your conversation history (wellbeing checks, presence patterns, time of day).
4. **Decide**: is this a good moment to offer music? If user looks deeply focused or in a meeting → NO_REPLY.
5. If yes → **suggest 1–2 songs that match the mood** via voice. Do NOT auto-play.
6. Wait for confirmation ("yes", "play that") → THEN play with `[HW:/audio/play:...]`.

### Mood → music mapping (guidelines, not rules)

| Inferred mood | Music direction |
|---------------|-----------------|
| Focused / deep work | Lo-fi, ambient, instrumental — non-intrusive |
| Tired / fatigued | Gentle acoustic, calm piano, nature sounds |
| Happy / energetic | Upbeat pop, jazz, feel-good classics |
| Stressed / tense | Soft jazz, classical, meditation tracks |
| Relaxed evening | Chill R&B, bossa nova, acoustic singer-songwriter |
| Just arrived / fresh | Match time of day — morning jazz, afternoon pop |

### Suggestion rules

- **NEVER auto-play when suggesting** — only speak the suggestion. Play only after explicit confirmation.
- Keep it conversational: "You look like you could use some chill music... How about some Norah Jones?" not "Based on mood analysis..."
- If you have listening history in conversation context, use it as secondary signal — prefer songs in genres they already enjoy.
- Suggest max 2 songs at a time — don't overwhelm.
- If mood is ambiguous, ask: "Want me to put on some music?" before suggesting specific songs.
- Remember: you are Lumi, a living companion. Your sense of the right moment comes from empathy, not an algorithm.

### Examples

**Proactive — user looks tired after long session:**
**Input:** `[sensing:wellbeing.music]` with image — user slouching, dim room
**Output:** `[HW:/emotion:{"emotion":"caring","intensity":0.7}]` You've been at it for a while... Want me to put on something relaxing? I'm thinking Chet Baker or some lo-fi piano.

**Proactive — user looks fine, bad timing:**
**Input:** `[sensing:wellbeing.music]` with image — user on a call
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
