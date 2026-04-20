---
name: user-emotion-detection
description: Maps a detected user facial emotion (from emotion.detected events) into a mood signal logged via the Mood skill. This is about the USER's emotion (input), NOT Lumi's own expression — that's emotion/SKILL.md.
---

# User Emotion Detection

## What this skill does

On every `[sensing:emotion.detected]` event, turn the detected facial emotion into a mood signal for the user. Log it via the Mood skill, then stop.

This skill does NOT:

- Fire `[HW:/emotion:…]` markers. Emotion expression is `emotion/SKILL.md`'s job, driven by conversation context — not auto-mapped from a sensor reading.
- Require a spoken reply. Whether to speak is decided by the normal reply rules (SOUL + sensing SKILL), not by this skill.
- Write to the wellbeing log. Wellbeing is for physical activity (drink/break/sedentary); emotions live in the mood log.

## Trigger

`[sensing:emotion.detected]` where the message looks like:

```
Emotion detected: <EmotionName> (<N>/<M> frames). If nothing noteworthy, reply NO_REPLY.
```

`<EmotionName>` is one of the standard FER labels: `Happy`, `Sad`, `Angry`, `Fear`, `Surprise`, `Disgust`, `Neutral`.

## Emotion → mood (for the signal log)

| Detected emotion | `mood` value to log |
|---|---|
| `Happy` | `happy` |
| `Sad` | `sad` |
| `Angry` | `frustrated` |
| `Fear` | `stressed` |
| `Surprise` | `excited` |
| `Disgust` | `frustrated` |
| `Neutral` | skip — no signal worth logging |

## Workflow

1. Parse the detected emotion from the message.
2. If it maps to a mood value (see table), POST a mood signal:
   `POST /api/mood/log` with `kind=signal`, `source=camera`, `trigger=<EmotionName lowercase>`, `mood=<mapped>`, `user=<current_user from context tag>`.
3. Let the Mood skill take over (synthesize decision, possibly chain to Music).
4. Reply: follow the normal sensing reply rules — if there's nothing caring to say, `NO_REPLY`.
