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
3. Confirm what you found and that it's playing
4. User can ask to stop at any time -> call `POST /audio/stop`

## Examples

Input: "Play Bohemian Rhapsody"
Output: Call `POST /audio/play` with `{"query": "Bohemian Rhapsody Queen"}`. Confirm: "Playing Bohemian Rhapsody by Queen."

Input: "Sing me a song" / "Play some music"
Output: Pick something fitting the mood or ask what they'd like to hear.

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
- **Do NOT speak (TTS) before or while playing music.** The speaker is shared — TTS will block music playback. Just call `/audio/play` silently and let the music speak for itself.
- When the user asks to "sing", play a song — do not attempt to generate singing via TTS.
- Include the artist name in the search query when known for better results.
- If the user asks for a genre or mood ("play something relaxing"), pick a well-known song that fits.
- This skill is for music playback only. For volume control, use the **Audio** skill.
- **Always call the Emotion skill** when starting music playback. Use `excited` (intensity 0.8) for upbeat songs, `happy` (0.7) for general music, or match the mood of the song.

## Output Template
```
[Music] {action} — {details}
```
Examples:
- `[Music] Playing — Bohemian Rhapsody by Queen`
- `[Music] Stopped`
- `[Music] Not available — music service is offline`
