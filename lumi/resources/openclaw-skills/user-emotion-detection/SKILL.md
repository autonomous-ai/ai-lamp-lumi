---
name: user-emotion-detection
description: Detects the USER's emotional state from a dedicated motion.emotional event. That event type is not yet emitted — until it is, this skill has no trigger and never runs. Do not invoke it. This is NOT for Lumi's own emotion expression — that's emotion/SKILL.md.
---

# User Emotion Detection

> **⚠ SKILL CURRENTLY INACTIVE.** Emotional X3D actions (laughing, crying, yawning, singing) are no longer forwarded by LeLamp on `motion.activity`. A dedicated `motion.emotional` event type will be added later; until then this skill has no trigger. **Do not invoke it from `motion.activity`.**

## What this skill does (when it's active again)

Turn a `motion.emotional` event (raw X3D action — `laughing` / `crying` / `yawning` / `singing`) into a mood signal. That's it. Log via the Mood skill, then stop.

This skill does NOT:

- Fire `[HW:/emotion:…]` markers. Emotion expression is `emotion/SKILL.md`'s job, driven by conversational context — not auto-mapped from a detected cue.
- Require a spoken reply. Whether to speak is decided by the normal reply rules (SOUL + sensing SKILL), not by this skill.
- Write to the wellbeing activity log. Wellbeing is about physical activity groups (drink / break / sedentary); emotions live in the mood log.

## Action → mood (for the signal log only)

| X3D action | `mood` value to log |
|---|---|
| `laughing`, `singing` | `happy` |
| `crying` | `sad` |
| `yawning` | `tired` |

## Workflow

1. Receive `motion.emotional` with one or more raw actions.
2. For each action, map to a mood value using the table above.
3. Log via Mood skill: `POST /api/mood/log` with `kind=signal`, `source=camera`, `trigger=<raw action>`, `mood=<mapped>`, `user=<current_user from context tag>`.
4. Done. Mood skill will take over from there (synthesize decision, possibly chain to Music).

No emotion markers, no mandatory speaking, no wellbeing log entry.
