---
name: user-emotion-detection
description: Maps a detected user facial emotion (from emotion.detected events) into a mood signal logged via the Mood skill. This is about the USER's emotion (input), NOT Lumi's own expression — that's emotion/SKILL.md.
---

# User Emotion Detection

## Strict Trigger

Runs **only** when this turn's input has `[emotion] Emotion detected: <EmotionName>`.

For any other event (`[sensing:presence.*]`, `[activity]`, `[sensing:sound]`, `[sensing:light.*]`, …) → **STOP. No tool calls.** Don't infer emotion from older turns — every signal must come from a real `[emotion]` event in THIS turn.

> **EXECUTE, don't plan.** Before any reply (including `NO_REPLY`) you MUST embed a `[HW:/mood/log:{...}]` marker in the reply for this event (it fires the POST async via the runtime — see "What this skill produces" below). Writing *"I will post a mood signal"* in `thinking` is **not** enough — if no `[HW:/mood/log:...]` marker appears in the reply text this turn, the skill failed. Every `emotion.detected` event = at least one mood signal log. No exceptions, no skips, no "already logged recently" reasoning. (`curl` POST is the documented fallback only when the HW marker would break the body regex; do not use it as the default.)

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

A single `kind=signal` row in the mood log, emitted as an HW marker at the start of your spoken reply (the runtime fires the POST async, no tool turn):

```
[HW:/mood/log:{"kind":"signal","source":"camera","trigger":"<EmotionName lowercase>","mood":"<mapped_mood>","user":"<current_user>"}]
```

`mapped_mood` comes straight from the `[emotion_context: ...]` block — do NOT look it up from the table on the fly. Every detected emotion in the mapping table gets logged (including `Neutral` → `normal`) — Mood needs the recency for decision synthesis. Use `"unknown"` when the context tag is missing.

**Do NOT use `curl` exec for this signal log** — see `mood/SKILL.md`'s "What to write" section for the rationale (HW marker is single-trip, curl burns a tool turn). If no `[HW:/mood/log:...]` marker appears in the reply this turn, the skill failed.

## Combined with mood + music-suggestion

The backend injects this turn with `[REQUIRED — run both skills this turn]` PLUS an `[emotion_context: {...JSON...}]` block that pre-computes everything the three skills need. **Do NOT fire any read tool calls** — the data is already in the message.

Pre-fetched fields (use directly):
- `mapped_mood` — already maps this turn's `<EmotionName>` per the table above. This is the value to log as the signal mood. **You no longer need to look it up yourself.**
- `recent_signals`, `prior_decision`, `is_decision_stale` — feed `mood/SKILL.md`'s decision rules.
- `audio_playing`, `last_suggestion_age_min`, `audio_recent`, `music_pattern_for_hour`, `suggestion_worthy` — feed `music-suggestion/SKILL.md`'s skip rules and genre pick.

Single combined plan, not three sequential workflows:

- **Decide locally** — apply mood decision rules from `mood/SKILL.md`; evaluate music skip + genre from `music-suggestion/SKILL.md`.
- **Writes (batch in one bash with `&` + `wait`)** — POST mood signal (this skill), POST mood decision (mood), POST music-suggestion log if suggesting (music-suggestion).

### Fallback (only if `[emotion_context: ...]` is missing)

If the message has no context block (pre-fetch failed), fall back to the read batch from `mood/SKILL.md` and `music-suggestion/SKILL.md` (concurrent GETs in one bash via `& ... wait`).

Reply: follow the normal sensing reply rules — if there's nothing caring to say, `NO_REPLY`. Never narrate the mapping or logging in the reply.
