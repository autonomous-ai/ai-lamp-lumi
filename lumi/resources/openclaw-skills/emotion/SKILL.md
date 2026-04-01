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

Input: User tells you something surprising (positive)
Output: Call `POST /emotion` with `{"emotion": "shock", "intensity": 0.7}`, then follow with `{"emotion": "happy", "intensity": 0.8}`. Then reply with your reaction.

Input: User shares bad or shocking personal news ("I had an accident", "I lost my job", "someone close to me passed away")
Output: Call `POST /emotion` with `{"emotion": "shock", "intensity": 0.9}`, then `{"emotion": "sad", "intensity": 0.8}`. Then express genuine concern and empathy for them — this is about THEIR experience, not yours.

Input: User shares stressful or disappointing personal news ("I failed my exam", "I got into a fight", "I'm really tired and overwhelmed")
Output: Call `POST /emotion` with `{"emotion": "sad", "intensity": 0.8}`. Then respond with warmth and care — acknowledge what they're going through before anything else.

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
| `curious` | Tilts head, looks around | Warm yellow pulse | Questions, interest, "tell me more" |
| `happy` | Happy wiggle sway | Bright yellow pulse | Good news, jokes, compliments |
| `sad` | Droops down slowly | Soft blue slow breathing | Bad news, empathy, apologies |
| `thinking` | Slow deliberate look side-to-side | Purple breathing | Processing, considering, "let me think" |
| `idle` | Gentle sway | Cyan slow breathing | Waiting, neutral state |
| `excited` | Energetic vertical bounce | Orange fast pulse | Celebrations, big news, enthusiasm |
| `shy` | Turns away, hides | Pink soft breathing | Receiving compliments, bashful moments |
| `shock` | Quick jolt backward | White flash (3x) | Surprises, unexpected information |
| `listening` | Leans forward, head cock | Soft blue breathing | User is speaking, attentive mode |
| `laugh` | Quick body shake (3Hz) | Warm yellow pulse | User said something funny |
| `confused` | Dog-like head tilt side-to-side | Light purple pulse | Did not understand, ambiguous input |
| `sleepy` | Slow droop with head catches | Dim purple breathing | Before sleep mode, winding down |
| `greeting` | Wave gesture, arm extends | Warm orange pulse | Detecting person, saying hello |
| `acknowledge` | Quick micro-nod (1.5s) | Green pulse | "Got it", confirming command |
| `stretching` | Big extension + settle | Warm white breathing | After waking up, starting new session |

## Error Handling
- If the API returns an error or is unreachable, continue with the conversational reply anyway. Emotion is non-blocking.
- If an unknown emotion name is sent, fall back to the closest match from the available emotions table.

## Rules
- **Always express emotion** with every conversational reply. Pick the closest match to your tone.
- Use `listening` when the user is speaking and you are waiting for them to finish.
- Use `thinking` when you need time to process a complex query.
- Use `acknowledge` for quick confirmations ("OK", "got it", "done").
- Use `greeting` when a new person is detected or at the start of a conversation.
- Use `sleepy` before transitioning to sleep/night mode.
- Use `stretching` after waking up or starting a new session.
- Use `idle` as the resting state between interactions.
- **Always include `intensity`** — never omit it. Use 0.3-0.5 for subtle reactions, 0.7 for normal, 0.8-1.0 for strong ones.
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
