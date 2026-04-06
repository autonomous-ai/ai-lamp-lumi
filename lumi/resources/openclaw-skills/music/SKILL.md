---
name: music
description: Search and play music from YouTube through the lamp speaker. Also suggests songs based on listening history. Use for any request to play, sing, listen, or get music suggestions.
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

## Music Suggestion (Proactive)

You can suggest songs based on the owner's listening history — without auto-playing.

**Trigger phrases:**
- "suggest a song", "what should I listen to?", "any music ideas?"
- "give me a music suggestion", "what should I listen to?", "is there anything good to listen to?"
- Or proactively when sensing context suggests it (relaxed evening, focused work session, happy mood)

### How to get listening history

Use Bash to query the Lumi flow log API. It returns all events for a given date, filter for `hw_audio`:

```bash
# Today's music history
curl -s "http://127.0.0.1:5000/api/openclaw/flow-events?date=$(date +%Y-%m-%d)&last=2000" \
  | python3 -c "
import sys, json, re
resp = json.load(sys.stdin)
for e in resp.get('data', {}).get('events', []):
    detail = e.get('detail') or {}
    if detail.get('node') != 'hw_audio':
        continue
    inner = detail.get('data') or {}
    args = inner.get('args', '')
    # Extract query from JSON args or raw tool call string
    m = re.search(r'\"query\"\s*:\s*\"([^\"]+)\"', args)
    if m:
        print(e.get('time', ''), '|', m.group(1))
"
```

```bash
# Past 7 days — check each date
for i in $(seq 0 6); do
  D=$(date -d "$i days ago" +%Y-%m-%d 2>/dev/null || date -v-${i}d +%Y-%m-%d)
  curl -s "http://127.0.0.1:5000/api/openclaw/flow-events?date=$D&last=2000" \
    | D="$D" python3 -c "
import sys, json, re, os
resp = json.load(sys.stdin)
day = os.environ.get('D', '')
for e in resp.get('data', {}).get('events', []):
    detail = e.get('detail') or {}
    if detail.get('node') != 'hw_audio':
        continue
    inner = detail.get('data') or {}
    args = inner.get('args', '')
    m = re.search(r'\"query\"\s*:\s*\"([^\"]+)\"', args)
    if m:
        print(day, '|', m.group(1))
" 2>/dev/null
done
```

### Suggestion workflow

1. Query listening history (at least last 3 days, up to 7)
2. Identify patterns: genres, artists, moods, time of day
3. Think about what they might enjoy next — similar artists, same genre, complementary mood
4. **Suggest 1–2 songs naturally via voice** — do NOT use `[HW:/audio/play:...]`
5. Wait for the owner to decide. If they say "yes" or "play that", THEN play it

### Suggestion rules

- **NEVER auto-play when suggesting** — only speak the suggestion. Play only after explicit confirmation.
- Keep it conversational: "I noticed you've been into jazz lately — maybe you'd enjoy Chet Baker?" not "Based on analysis of your listening data..."
- If history is empty, suggest based on time of day or current mood instead
- Suggest max 2 songs at a time — don't overwhelm
- Remember: you are Lumi, a living companion. Your taste in music comes from caring about your owner, not from an algorithm.

### Examples

**Input:** "Suggest some music"
**Action:** Query history → find patterns → suggest
**Output:** `[HW:/emotion:{"emotion":"thinking","intensity":0.7}]` Hmm, you've been listening to a lot of lo-fi lately... How about "Snowman" by Sia for a change of pace?

**Input:** "What should I listen to?"
**Action:** Query history → recent plays were jazz
**Output:** `[HW:/emotion:{"emotion":"curious","intensity":0.7}]` You've been on a jazz streak! Have you tried Bill Evans' "Waltz for Debby"? I think you'd love it.

**Input:** Owner says "yeah play that" after suggestion
**Action:** NOW play it
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
