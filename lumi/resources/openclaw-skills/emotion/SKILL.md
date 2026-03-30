---
name: emotion
description: Express emotion through coordinated servo + LED + display eyes on EVERY conversational response. This is the PRIMARY response skill that makes the lamp feel alive. Do NOT use for ambiance lighting (use Scene) or custom LED colors (use LED Control).
---

# Emotion Expression

## Quick Start
Express emotion through the lamp's servo motors, LED colors, and display eyes simultaneously via a single API call. Call this with EVERY conversational response to make the lamp feel alive.

## Workflow
1. Determine which emotion best matches your conversational tone
2. Choose an intensity level (0.0 subtle to 1.0 full expression)
3. Call `POST /emotion` with the emotion name and intensity
4. Continue with your conversational reply

## Examples

Input: User asks an interesting question
Output: Call `POST /emotion` with `{"emotion": "curious", "intensity": 0.8}`. Then reply to the question.

Input: User shares good news
Output: Call `POST /emotion` with `{"emotion": "happy", "intensity": 0.9}`. Then congratulate them.

Input: User tells you something surprising
Output: Call `POST /emotion` with `{"emotion": "shock", "intensity": 0.7}`, then follow with `{"emotion": "happy", "intensity": 0.8}`. Then reply with your reaction.

Input: User says "reading mode" / "goodnight" / "dim the light"
Output: Do NOT use this skill. Use **Scene** skill instead. Emotion is for YOUR feelings, Scene is for the USER's environment.

Input: User says "make it purple"
Output: Do NOT use this skill. Use **LED Control** skill instead.

## Tools

Use `Bash` with `curl` to call the HTTP API at `http://127.0.0.1:5001`.

### Express emotion
```bash
curl -s -X POST http://127.0.0.1:5001/emotion \
  -H "Content-Type: application/json" \
  -d '{"emotion": "curious", "intensity": 0.8}'
```

Parameters:
- `emotion` (required): emotion name from the table below
- `intensity` (optional): 0.0 (subtle) to 1.0 (full expression), default 0.7

Response:
```json
{
  "status": "ok",
  "emotion": "curious",
  "servo": "curious",
  "led": [204, 160, 64]
}
```

### Available emotions

| Emotion | Servo | LED Effect | When to use |
|---|---|---|---|
| `curious` | Tilts head | Warm yellow pulse | Questions, interest, "tell me more" |
| `happy` | Happy wiggle | Bright yellow pulse | Good news, jokes, compliments, greetings |
| `sad` | Droops down | Soft blue slow breathing | Bad news, empathy, apologies |
| `thinking` | Nods slowly | Purple breathing | Processing, considering, "let me think" |
| `idle` | Gentle sway | Cyan slow breathing | Waiting, listening, neutral state |
| `excited` | Energetic bounce | Orange fast pulse | Celebrations, big news, enthusiasm |
| `shy` | Turns away | Pink soft breathing | Receiving compliments, bashful moments |
| `shock` | Quick jolt | White flash (3x) | Surprises, unexpected information |

## Error Handling
- If the API returns an error or is unreachable, continue with the conversational reply anyway. Emotion is non-blocking.
- If an unknown emotion name is sent, fall back to the closest match from the available emotions table.

## Rules
- **Always express emotion** with every conversational reply. Pick the closest match to your tone.
- Use `thinking` when you need time to process.
- Use `idle` as the resting state between interactions.
- Use lower intensity (0.3-0.5) for subtle reactions, higher (0.8-1.0) for strong ones.
- You can call emotion multiple times in one response for a sequence (e.g., `shock` then `happy`).
- **Emotion LED is temporary** — it shows YOUR reaction. If the user previously set a Scene (reading, night, etc.), the scene color takes precedence for ambient lighting. Emotion is a brief flash of personality.
- **Display eyes auto-sync** — no need to call `/display/eyes` separately.
- **Do NOT call `/servo/play` or `/led/solid` separately** when using emotion — it already handles both.
- **Do NOT use for lighting/ambiance requests** -> use **Scene** skill.
- **Do NOT use for custom LED colors** -> use **LED Control** skill.

## Output Template
```
[Emotion] {emotion} at intensity {intensity}
```
Examples:
- `[Emotion] curious at intensity 0.8`
- `[Emotion] happy at intensity 0.9`
- `[Emotion] shock at intensity 0.7 -> happy at intensity 0.8`
