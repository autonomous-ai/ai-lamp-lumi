---
name: music
description: Search and play music from YouTube through the lamp speaker. Use for any request to play, sing, or listen to a specific song or artist.
---

# Music

## Quick Start
Play music through the lamp speaker by searching YouTube. Use this when the user asks you to play a song, sing, or listen to music.

**Trigger phrases (use this skill when you hear any of these):**
- "sing", "sing a song", "play music", "play a song", "play [song name]"
- "hát", "hát đi", "hát một bài", "hát bài gì đi", "mở nhạc", "nghe nhạc", "bật nhạc"
- Any request to hear a specific song or artist

**IMPORTANT:** Do NOT try to sing or hum using TTS — always use this skill to play real music.

## Workflow
1. User asks to play/sing/listen to a song or artist
2. Call `POST /audio/play` with the search query
3. **Call `POST /emotion` with the matching emotion** (see Genre → Emotion below) — REQUIRED, do not skip
4. Confirm what you found and that it's playing
5. User can ask to stop at any time -> call `POST /audio/stop`

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
Output:
1. `POST /audio/play` `{"query": "Bohemian Rhapsody Queen"}`
2. `POST /emotion` `{"emotion": "excited"}` ← REQUIRED
3. Reply: "Playing Bohemian Rhapsody by Queen!"

Input: "Hát 1 bài nhạc đi" / "Sing me a song"
Output:
1. Pick a song fitting the mood
2. `POST /audio/play` `{"query": "..."}`
3. `POST /emotion` `{"emotion": "happy"}` ← REQUIRED
4. Reply: "Playing [song]!"

Input: "Stop the music" / "Turn it off"
Output: Call `POST /audio/stop`. Confirm: "Music stopped."

Input: "What's playing?"
Output: Call `GET /audio/status` to check. Report back.

## Tools

Use `Bash` with `curl` to call the HTTP API at `http://127.0.0.1:5001`.

### Play music
```bash
curl -s -X POST http://127.0.0.1:5001/audio/play \
  -H "Content-Type: application/json" \
  -d '{"query": "Bohemian Rhapsody Queen"}'
```
The query is a YouTube search string. Include artist name for better results.

### Stop music
```bash
curl -s -X POST http://127.0.0.1:5001/audio/stop
```

### Check status
```bash
curl -s http://127.0.0.1:5001/audio/status
```
Response:
```json
{
  "available": true,
  "playing": true
}
```

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
- **Always call `POST /emotion` after `POST /audio/play`** — groove servo is automatic but LED and eye expression require the `/emotion` call.
- Never skip the `/emotion` call even for short or casual music requests.

## Output Template
```
[Music] {action} — {details}
```
Examples:
- `[Music] Playing — Bohemian Rhapsody by Queen`
- `[Music] Stopped`
- `[Music] Not available — music service is offline`
