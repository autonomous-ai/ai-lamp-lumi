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

The backend injects this turn with an `[emotion_context: {...JSON...}]` block that pre-computes everything the three skills need (this skill is the router, mood logs the decision, music-suggestion fires only when this router picks the `music` route). **Do NOT fire any read tool calls** — the data is already in the message.

Pre-fetched fields (use directly):
- `mapped_mood` — already maps this turn's `<EmotionName>` per the table above. This is the value to log as the signal mood. **You no longer need to look it up yourself.**
- `recent_signals`, `prior_decision`, `is_decision_stale` — feed `mood/SKILL.md`'s decision rules and this skill's routing table.
- `audio_playing`, `last_suggestion_age_min`, `audio_recent`, `music_pattern_for_hour`, `suggestion_worthy` — feed this skill's routing table (see **Response routing** below) and `music-suggestion/SKILL.md`'s genre pick.

Single combined plan, not three sequential workflows:

- **Decide locally** — apply mood decision rules from `mood/SKILL.md`; pick a route from the routing table below; if the route is `music`, evaluate genre from `music-suggestion/SKILL.md`.
- **Writes (batch in one bash with `&` + `wait`)** — POST mood signal (this skill), POST mood decision (mood), and on `music` or `checkin` route, POST the music-suggestion log (the shared cooldown channel).

### Fallback (only if `[emotion_context: ...]` is missing)

If the message has no context block (pre-fetch failed), fall back to the read batch from `mood/SKILL.md` and `music-suggestion/SKILL.md` (concurrent GETs in one bash via `& ... wait`).

Reply: routing decides the spoken reply (see next section). Never narrate the mapping, logging, or routing decision.

## Response routing (this skill is the router)

After logging the mood signal, pick **exactly one** response route. Read straight from `[emotion_context: ...]` — no extra tool calls. Apply top-to-bottom, first match wins:

| # | Condition | Route | What happens |
|---|---|---|---|
| 1 | `audio_playing == true` | **action** | LED-only ambient ack, no spoken reply. Emit `[HW:/emotion:{"emotion":"caring","intensity":0.4}]` + `NO_REPLY`. Music is already covering — don't talk over it. |
| 2 | `last_suggestion_age_min ∈ [0, 7)` (any recent proactive outreach — music OR checkin) | **action** | Same as #1: LED ack, `NO_REPLY`. Cooldown protects the user from nag. |
| 3 | `suggestion_worthy == true` AND (`is_decision_stale == false` OR fresh decision synthesized this turn) | **music** | See `music-suggestion/SKILL.md` for genre + phrasing + log marker. |
| 4 | anything else (mood=normal/frustrated, stale decision with no fresh synthesis, etc.) | **checkin** | See `reference/checkin.md` for phrasing + log marker. One soft open-ended line. |

Rules:

- **One route per turn.** Don't double-fire (e.g. music + checkin both). Pick the first matching row.
- **No silent route on emotion events.** Every non-gated emotion produces either a music suggestion or a checkin; rows #1–#2 (audio playing / cooldown) are the only paths to `NO_REPLY`.
- **Output ownership:** `music` → produced by `music-suggestion/SKILL.md`. `checkin` → produced by `reference/checkin.md` (this skill). `action` → emitted inline by this router (the `[HW:/emotion:...]` marker in rows #1–#2).
- **Cooldown is shared** between music and checkin: both log via `music-suggestion/log` so `last_suggestion_age_min` reflects either channel. Row #2 catches both.
- Never narrate the routing decision in the spoken reply.
- `Neutral` is filtered upstream at lelamp and never reaches this skill in practice; no special case needed here.
