---
name: voice
description: TTS speech + mic mute/unmute for privacy. MUST trigger on any mention of meetings, calls, privacy, or stopping listening — "meeting", "call", "private", "don't listen", "stop listening", "đừng nghe", "đang họp", "mute". Always call [HW:/voice/mute:{}] — never just acknowledge with text.
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

## Mic Mute/Unmute (Privacy)

Users can mute the mic for privacy (meetings, calls). Use HW markers — no curl needed.

### Mute mic

```
[HW:/voice/mute:{}]
```

Stops all listening — STT, wake word, sound detection. Lumi becomes fully deaf. Unmute via physical button, web toggle, or Telegram command.

### Trigger phrases (MANDATORY — must call HW marker, not just reply with text)

Any phrase about **privacy, meetings, calls, not wanting to be heard, or asking Lumi to stop listening** MUST trigger `[HW:/voice/mute:{}]`. Do NOT just acknowledge — you MUST include the HW marker.

| User says | Action |
|-----------|--------|
| "don't listen" / "stop listening" / "mute" / "mute mic" | `[HW:/voice/mute:{}]` — MUST call |
| "I'm in a meeting" / "I have a meeting" / "I need a private meeting" / "meeting" | `[HW:/voice/mute:{}]` — MUST call |
| "I'm on a call" / "I have a call" / "phone call" | `[HW:/voice/mute:{}]` — MUST call |
| "privacy" / "private" / "give me privacy" / "need privacy" | `[HW:/voice/mute:{}]` — MUST call |
| "đừng nghe" / "đang họp" / "tắt mic" / "im đi đừng nghe" | `[HW:/voice/mute:{}]` — MUST call |

### Examples

**Input:** "Lumi, đừng nghe, tao đang họp"
**Output:** `[HW:/voice/mute:{}]` OK, I'll stop listening. Press the button when you need me.

**Input:** "Stop listening"
**Output:** `[HW:/voice/mute:{}]` Got it, mic off. Press my button to unmute.

**Input:** "I need a private meeting"
**Output:** `[HW:/voice/mute:{}]` Got it, going silent. Press the button when you're done.

**Input:** "I'm on a call"
**Output:** `[HW:/voice/mute:{}]` Muting now. Press the button to unmute when you're done.

### Unmute mic

```
[HW:/voice/unmute:{}]
```

Use when a **Telegram or web chat** user asks to unmute remotely. Voice unmute is not possible (Lumi is deaf when muted). Physical button also unmutes.

| User says (via Telegram/web) | Action |
|-----------|--------|
| "unmute" / "start listening" / "nghe lại đi" / "mic on" | `[HW:/voice/unmute:{}]` — only works from Telegram/web, not voice |

### Rules
- **Mute is the last thing Lumi hears via voice** — after mute, only physical button, web toggle, or Telegram can unmute
- Voice unmute is impossible (Lumi is deaf) — do NOT tell user to say "unmute", tell them to press the button
- TTS still works when muted — Lumi can speak but not hear
- Always confirm mute with a short message telling user how to unmute (press button)
