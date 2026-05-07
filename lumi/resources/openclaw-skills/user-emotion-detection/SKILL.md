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

## What this skill produces

A single `kind=signal` row in the mood log:

```bash
curl -s -X POST http://127.0.0.1:5000/api/mood/log \
  -H 'Content-Type: application/json' \
  -d '{"kind":"signal","source":"camera","trigger":"<EmotionName lowercase>","mood":"<mapped>","user":"<current_user>"}'
```

Every detected emotion in the mapping table gets logged (including `Neutral` → `normal`) — Mood needs the recency for decision synthesis. Use `"unknown"` when the context tag is missing. If no `POST /api/mood/log` tool call fires this turn, the skill failed.

## Combined with mood + music-suggestion

The backend injects this turn with `[REQUIRED — run both skills this turn]`. That means a single combined plan, not three sequential workflows:

- **Reads (batch in one bash with `&` + `wait`)** — `GET /api/openclaw/mood-history?last=15` (mood decision input), plus the music-suggestion read set listed in `music-suggestion/SKILL.md`.
- **Decide locally** — map detected emotion → signal mood, apply mood decision rules from `mood/SKILL.md`, evaluate music skip/genre rules from `music-suggestion/SKILL.md`.
- **Writes (batch in one bash with `&` + `wait`)** — POST mood signal (this skill), POST mood decision (mood), POST music-suggestion log if suggesting (music-suggestion).

Tool calls without data dependencies must fire concurrently. Do not split mood signal, mood decision, and music-suggestion across multiple tool turns.

Reply: follow the normal sensing reply rules — if there's nothing caring to say, `NO_REPLY`. Never narrate the mapping or logging in the reply.
