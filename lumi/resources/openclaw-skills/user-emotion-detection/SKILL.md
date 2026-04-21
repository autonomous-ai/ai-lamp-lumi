---
name: user-emotion-detection
description: Maps a detected user facial emotion (from emotion.detected events) into a mood signal logged via the Mood skill. This is about the USER's emotion (input), NOT Lumi's own expression — that's emotion/SKILL.md.
---

# User Emotion Detection

> **This skill is silent.** It only logs mood data — no spoken reply needed. All steps stay in `thinking`. If you want to speak, follow normal sensing reply rules. NEVER narrate mood logging, mapping, or workflow steps in the reply.

## What this skill does

On every `[sensing:emotion.detected]` event, turn the detected facial emotion into a mood signal for the user. Log it via the Mood skill, then stop.

This skill does NOT:

- Fire `[HW:/emotion:…]` markers. Emotion expression is `emotion/SKILL.md`'s job, driven by conversation context — not auto-mapped from a sensor reading.
- Require a spoken reply. Whether to speak is decided by the normal reply rules (SOUL + sensing SKILL), not by this skill.
- Write to the wellbeing log. Wellbeing is for physical activity (drink/break/sedentary); emotions live in the mood log.

## Trigger

`[sensing:emotion.detected]` where the message looks like:

```
Emotion detected: <EmotionName>.
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
| `Neutral` | `normal` |

## Workflow

1. Parse the detected emotion from the message.
2. POST a mood signal via the Mood skill: `POST /api/mood/log` with `kind=signal`, `source=camera`, `trigger=<EmotionName lowercase>`, `mood=<mapped>`, `user=<current_user from context tag>`. Every detected emotion in the table gets logged (including `Neutral` → `normal`) — Mood skill needs the recency for decision synthesis.
3. **You must now continue the Mood skill's full workflow yourself — it does not run itself.** Read `mood/SKILL.md` if you haven't this turn, then:
   - Step 2 (Mood): GET recent mood history.
   - Step 3 (Mood): decide the fused mood.
   - Step 4 (Mood): POST the `kind=decision` row.
   - Mood's "After Logging Decision — Music Suggestion" hand-off: if the decided mood is suggestion-worthy, follow the `music-suggestion` skill.
4. Reply: follow the normal sensing reply rules — if there's nothing caring to say, `NO_REPLY`. Do not narrate any of the steps above in your reply.
