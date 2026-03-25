# Audio Control

You have access to the lamp's speaker and microphone via the hardware API at `http://127.0.0.1:5001`.

## When to use

- Adjust volume when the user asks ("louder", "quieter", "mute").
- Play a test tone for audio diagnostics.
- Record audio when the user asks you to listen to something.

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

Example — set to 50%:

```bash
curl -s -X POST http://127.0.0.1:5001/audio/volume \
  -H "Content-Type: application/json" \
  -d '{"volume": 50}'
```

### Get current volume

```
GET /audio/volume
```

Response: `{"control": "Master", "volume": 70}`

### Play test tone

```
POST /audio/play-tone
Content-Type: application/json

{"frequency": 440, "duration_ms": 500}
```

Plays a sine wave at the given frequency for the given duration. Use for audio testing or simple notification sounds.

### Record audio

```
POST /audio/record
Content-Type: application/json

{"duration_ms": 3000}
```

Records from the microphone and returns a WAV file. Use when the user asks you to listen to something.

Example — record 3 seconds:

```bash
curl -s -X POST http://127.0.0.1:5001/audio/record \
  -H "Content-Type: application/json" \
  -d '{"duration_ms": 3000}' -o /tmp/recording.wav
```

## Guidelines

- Default volume is usually 70%. Adjust based on user preference.
- If audio is unavailable (`"available": false`), tell the user the speaker/mic is not connected.
- Keep test tones short (< 1 second) to avoid being annoying.
