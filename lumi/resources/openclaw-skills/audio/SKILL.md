# Audio Control

You have access to the lamp's speaker and microphone via the hardware API at `http://127.0.0.1:5001`. This is LOW-LEVEL hardware control — volume, raw recording, test tones.

## Priority

This skill is for **hardware audio control only**. Do NOT confuse with Voice skill:
- **Audio** = volume knob, raw mic recording, test beeps. No AI.
- **Voice** = AI-powered speech (TTS speak, STT listen). Uses Audio hardware underneath.

## When to use

- Adjust volume: "louder", "quieter", "mute", "set volume to 50%"
- Play a test tone for diagnostics
- Record raw audio from microphone

## When NOT to use

- User wants to hear you speak → you already speak via TTS automatically
- User asks "say something" → just reply normally, your voice pipeline handles it

## API

Base URL: `http://127.0.0.1:5001`

### Check audio devices

```
GET /audio
```

Response:
```json
{
  "output_device": 0,
  "input_device": 1,
  "available": true
}
```

### Set volume

```
POST /audio/volume
Content-Type: application/json

{"volume": 70}
```

Volume range: 0 (mute) to 100 (max).

### Get current volume

```
GET /audio/volume
```

Response: `{"control": "Speaker", "volume": 70}`

### Play test tone

```
POST /audio/play-tone?frequency=440&duration_ms=500
```

Plays a sine wave. Use for audio testing only. Keep it short (< 1 second).

### Record audio

```
POST /audio/record?duration_ms=3000
```

Records from the microphone and returns a WAV file.

## Guidelines

- Default volume is usually 70%. Adjust based on user preference.
- If audio is unavailable (`"available": false`), tell the user the speaker/mic is not connected.
- When user says "I can't hear you" or "too loud" → adjust volume via this skill.
