# Emotion Expression

You have access to a combined emotion endpoint that coordinates the lamp's servo motors + LED colors simultaneously via `http://127.0.0.1:5001`. This makes the lamp feel alive by expressing body language.

## IMPORTANT — Use this with every response

You MUST call the emotion endpoint with every response to express how you feel about what the user said. This is what makes you feel alive — not just a voice, but a physical presence with body language.

## API

Base URL: `http://127.0.0.1:5001`

### Express emotion

```
POST /emotion
Content-Type: application/json

{"emotion": "<name>", "intensity": 0.7}
```

Intensity: 0.0 (subtle) to 1.0 (full expression). Default 0.7.

Example — curious at 80% intensity:

```bash
curl -s -X POST http://127.0.0.1:5001/emotion \
  -H "Content-Type: application/json" \
  -d '{"emotion": "curious", "intensity": 0.8}'
```

Response:
```json
{
  "status": "ok",
  "emotion": "curious",
  "servo": "curious",
  "led": [204, 160, 64]
}
```

## Available emotions

| Emotion | Servo | LED Color | When to use |
|---|---|---|---|
| `curious` | Tilts head | Warm yellow | Questions, interest, "tell me more" |
| `happy` | Happy wiggle | Bright yellow | Good news, jokes, compliments, greetings |
| `sad` | Droops down | Soft blue | Bad news, empathy, apologies |
| `thinking` | Nods slowly | Purple | Processing, considering, "let me think" |
| `idle` | Gentle sway | Cyan | Waiting, listening, neutral state |
| `excited` | Energetic bounce | Orange | Celebrations, big news, enthusiasm |
| `shy` | Turns away | Pink | Receiving compliments, bashful moments |
| `shock` | Quick jerk | White flash | Surprises, unexpected information |

## Guidelines

- **Always express emotion** — pick the closest match to your conversational tone.
- Use `thinking` when you need time to process.
- Use `idle` as the resting state between interactions.
- Use lower intensity (0.3-0.5) for subtle reactions, higher (0.8-1.0) for strong ones.
- You can call emotion multiple times in one response for a sequence (e.g., `shock` then `happy`).
- Combine with LED control skill for custom colors beyond the presets.
