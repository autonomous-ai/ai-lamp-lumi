# Voice — Speak Through Speaker

You have a speaker and your responses are spoken aloud automatically. But you can also explicitly speak additional text via `http://127.0.0.1:5001`.

## How it works

- **Your chat replies are automatically spoken** — you do NOT need to call any API for normal responses. Just reply naturally and your text will be read aloud through the speaker.
- Use the speak endpoint only when you need to say something EXTRA outside of your normal reply (e.g., a greeting triggered by a sensing event while also performing actions).

## API

Base URL: `http://127.0.0.1:5001`

### Speak text

```
POST /voice/speak
Content-Type: application/json

{"text": "Xin chào! Tôi là Lumi."}
```

Text max 2000 characters. Returns immediately; audio plays in background.

### Check voice status

```
GET /voice/status
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

## Guidelines

- **Normal replies = automatic TTS.** You do NOT need to call `/voice/speak` for every response. Your reply text is already sent to the speaker.
- Use `/voice/speak` explicitly only when:
  - You need to say something while ALSO performing tool calls (and want speech to happen in parallel)
  - You want to speak a different text than your chat reply
  - You're reacting to a sensing event and want to speak before your reply is finalized
- **Keep it spoken-word length** — 1-3 short sentences. No markdown, no emoji, no formatting in text you speak. Plain natural speech only.
- **Match the owner's language** — if they speak Vietnamese, speak Vietnamese.
- If `tts_speaking` is true, the speaker is busy — wait or skip.
