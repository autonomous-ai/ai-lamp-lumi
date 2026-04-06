---
name: voice
description: Speak additional text through the lamp's speaker via TTS when you need to say something EXTRA beyond your normal chat reply. Normal replies are auto-spoken — only use this for parallel or supplementary speech.
---

# Voice — Speak Through Speaker

## Quick Start
Your chat replies are automatically spoken aloud through TTS. Use this skill only when you need to speak additional or separate text outside your normal reply (e.g., parallel speech during tool calls, or text different from your chat reply).

## Workflow
1. Determine if you need explicit speech beyond your normal reply:
   - Normal conversational reply -> do NOT call this skill, TTS is automatic
   - Need to speak while also performing tool calls -> use `POST /voice/speak`
   - Need to speak different text than your chat reply -> use `POST /voice/speak`
   - Reacting to a sensing event before reply is finalized -> use `POST /voice/speak`
2. Optionally check if TTS is busy: `GET /voice/status`
3. If `tts_speaking` is true, wait or skip
4. Call `POST /voice/speak` with plain text

## Examples

Input: Normal conversational reply
Output: Do NOT call this skill. Just reply normally — your text is automatically spoken.

Input: You need to greet the user while also activating a scene
Output: Call `POST /voice/speak` with `{"text": "Good morning!"}` in parallel with the Scene API call.

Input: You want to say something different from your chat reply
Output: Call `POST /voice/speak` with the spoken text. Then provide your chat reply separately.

Input: User says "say something" / "tell me a joke"
Output: Do NOT call this skill. Just reply normally with the joke — automatic TTS handles it.

## Tools

Use `Bash` with `curl` to call the HTTP API at `http://127.0.0.1:5001`.

### Speak text
```bash
curl -s -X POST http://127.0.0.1:5001/voice/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello! I am Lumi."}'
```
Text max 2000 characters. Returns immediately; audio plays in background.

### Check voice status
```bash
curl -s http://127.0.0.1:5001/voice/status
```
Response:
```json
{
  "voice_available": true,
  "voice_listening": false,
  "tts_available": true,
  "tts_speaking": false
}
```

## Error Handling
- If `tts_speaking` is true, the speaker is busy. Wait briefly or skip the explicit speech.
- If `voice_available` or `tts_available` is false, inform the user: "Voice output is currently unavailable."
- If the API is unreachable, fall back to chat-only reply. Speech is non-critical.

## Rules
- **Normal replies = automatic TTS.** Do NOT call `/voice/speak` for every response.
- Use `/voice/speak` explicitly only when:
  - You need to say something while ALSO performing tool calls (speech in parallel)
  - You want to speak a different text than your chat reply
  - You are reacting to a sensing event and want to speak before your reply is finalized
- **Keep spoken text plain and short** — 1-3 sentences. No markdown, no emoji, no formatting. Plain natural speech only.
- **Match the user's language** — if they speak Vietnamese, speak Vietnamese.
- Text max 2000 characters.
- For volume control, use the **Audio** skill, not this skill.

## Output Template
```
[Voice] Spoke: "{text}" ({character_count} chars)
```
Examples:
- `[Voice] Spoke: "Hello! I am Lumi." (23 chars)`
- `[Voice] Skipped — TTS already speaking`
- `[Voice] Auto-TTS — no explicit call needed`
