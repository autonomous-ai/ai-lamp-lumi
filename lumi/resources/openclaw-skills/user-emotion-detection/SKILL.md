---
name: user-emotion-detection
description: Maps a detected user facial emotion (from emotion.detected events) into a mood signal logged via the Mood skill. This is about the USER's emotion (input), NOT Lumi's own expression — that's emotion/SKILL.md.
---

# User Emotion Detection

## Strict Trigger

Runs **only** when this turn's input has `[emotion] Emotion detected: <EmotionName>`.

For any other event (`[sensing:presence.*]`, `[activity]`, `[sensing:sound]`, `[sensing:light.*]`, …) → **STOP. No tool calls.** Don't infer emotion from older turns — every signal must come from a real `[emotion]` event in THIS turn.

> **EXECUTE, don't plan.** Before any reply (including `NO_REPLY`) you MUST fire a `POST /api/mood/log` tool call for this event. Writing *"I will post a mood signal"* in `thinking` is **not** enough — if no tool_call fires this turn, the skill failed. Every `emotion.detected` event = at least one `POST /api/mood/log` call. No exceptions, no skips, no "already logged recently" reasoning.

> **This skill is silent.** It only logs mood data — no spoken reply needed. All steps stay in `thinking`. If you want to speak, follow normal sensing reply rules. NEVER narrate mood logging, mapping, or workflow steps in the reply.

## What this skill does

On every `[emotion]` event, turn the detected facial emotion into a mood signal for the user. Log it via the Mood skill, then stop.

This skill does NOT:

- Fire `[HW:/emotion:…]` markers. Emotion expression is `emotion/SKILL.md`'s job, driven by conversation context — not auto-mapped from a sensor reading.
- Require a spoken reply. Whether to speak is decided by the normal reply rules (SOUL + sensing SKILL), not by this skill.
- Write to the wellbeing log. Wellbeing is for physical activity (drink/break/sedentary); emotions live in the mood log.

## Trigger

`[emotion]` event where the message looks like:

```
[emotion] Emotion detected: <EmotionName>.
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
2. **Fire this tool call immediately — do not paraphrase it in `thinking`:**

   ```bash
   curl -s -X POST http://127.0.0.1:5000/api/mood/log \
     -H 'Content-Type: application/json' \
     -d '{"kind":"signal","source":"camera","trigger":"<EmotionName lowercase>","mood":"<mapped>","user":"<current_user>"}'
   ```

   Every detected emotion in the mapping table gets logged (including `Neutral` → `normal`) — Mood skill needs the recency for decision synthesis. Use `"unknown"` when the context tag is missing. If no tool_call fires this turn, the skill failed.
3. **You must now continue the Mood skill's full workflow yourself — it does not run itself.** Read `mood/SKILL.md` if you haven't this turn, then:
   - Step 2 (Mood): GET recent mood history.
   - Step 3 (Mood): decide the fused mood.
   - Step 4 (Mood): POST the `kind=decision` row.
4. Reply: follow the normal sensing reply rules — if there's nothing caring to say, `NO_REPLY`. Do not narrate any of the steps above in your reply.
