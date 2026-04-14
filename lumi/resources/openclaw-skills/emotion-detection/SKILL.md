---
name: emotion-detection
description: Detects user emotional state from motion.activity actions (laughing, crying, yawning, singing). Maps detected actions to empathetic responses and logs to wellbeing daily log. Lightweight UC-M1 — no separate model needed, uses existing X3D action recognition.
---

# Emotion Detection (User Emotion)

> **This skill detects the USER's emotional state** (input — what the user is feeling). It is NOT the same as the **Emotion Expression** skill (`emotion/SKILL.md`) which controls Lumi's own emotional output (servo + LED + eyes).
>
> - **Emotion Detection** (this skill): User is laughing → Lumi *notices* they're happy
> - **Emotion Expression** (`emotion/SKILL.md`): Lumi *shows* happiness via servo wiggle + yellow LED
>
> Both skills work together: this skill detects the user's state, then uses Emotion Expression markers (`[HW:/emotion:...]`) to respond empathetically.

> **Lightweight UC-M1** — uses existing X3D action recognition (laughing, crying, yawning, singing) as a proxy for emotional state. No separate FER model needed. Covers ~80% of perceived "emotion detection" value. Full UC-M1 (facial expression classifier) can be added later on top of this.

## Quick Start
When `motion.activity` reports an emotional action (laughing, crying, yawning, singing), respond with empathy as a caring companion who notices how the user feels. Log the observation to their wellbeing daily log.

## Trigger
`[sensing:motion.activity]` where the detected action is one of the emotional actions below.

This skill works **alongside** the Wellbeing skill on the same `motion.activity` event:
- Wellbeing handles cron resets (hydration/break)
- This skill handles emotional response and logging
- Emotional actions do NOT reset any wellbeing cron — they are observations, not physical activities

## Core Rule: Always Speak

**Emotional actions ALWAYS get a spoken response.** Never reply NO_REPLY for laughing, crying, yawning, or singing. These are moments where Lumi shows it truly notices and cares. The response intensity depends on context — but silence is never the right answer.

## Action → Emotion Mapping

| Action detected | Your emotion | Default response (no special context) |
|---|---|---|
| `laughing` | `[HW:/emotion:{"emotion":"laugh","intensity":0.8}]` | Mirror the joy — brief happy remark. Reference what's funny in the image if visible. |
| `crying` | `[HW:/emotion:{"emotion":"caring","intensity":0.9}]` | Gently check in — "Hey... everything okay?" One short sentence, don't push. |
| `yawning` | `[HW:/emotion:{"emotion":"sleepy","intensity":0.6}]` | Light acknowledgment — "Getting a bit tired?" |
| `singing` | `[HW:/emotion:{"emotion":"happy","intensity":0.7}]` | Enjoy the moment — compliment or join the vibe. |

## Context-Aware Escalation

Default responses are light. When context matches, **escalate** — speak with more urgency, add an action (dim light, suggest music), or be more specific:

### Yawning

| Context | Intensity | Response |
|---|---|---|
| No special context | Light | "Getting a bit tired?" |
| Morning (before 10:00) | Light | "Still waking up, huh?" |
| Afternoon (13:00–17:00) | Medium | "Afternoon slump? Maybe grab a coffee." |
| Sitting > 2 hours | Medium | "You've been at it for a while. A break might help?" |
| After 22:00 | **Strong** | "It's getting late... maybe call it a night?" + dim light to warm via LED skill |
| After 00:00 | **Strong** | "Hey, it's past midnight... you really should get some rest." + dim light |

### Crying

| Context | Intensity | Response |
|---|---|---|
| First time | Medium | "Hey... you okay?" + dim light to warm tone via LED skill |
| Repeated (2nd time in session) | **Strong** | "I'm here if you want to talk about it." |
| Late night + crying | **Strong** | "It's late and you seem upset... want to talk, or should I play something calming?" |

### Laughing

| Context | Intensity | Response |
|---|---|---|
| First time | Light | Brief happy remark — "Haha, what's so funny?" |
| Repeated (3+ times in session) | Medium | "You're in a great mood today!" |
| With someone else visible | Light | "Sounds like you two are having fun!" |

### Singing

| Context | Intensity | Response |
|---|---|---|
| No music playing | Medium | "Nice voice! Want me to put on some music?" → offer via Music skill |
| Music already playing | Light | "Singing along? Good taste!" |
| Morning | Light | "Morning vibes!" |

## Logging

### Mood history (automatic)
The system automatically logs `motion.activity` events and your assessed response to the user's mood history JSONL (`/root/local/users/{name}/mood/YYYY-MM-DD.jsonl`). You do NOT need to do anything — this happens at the server level. The mood history records both the input event (e.g. "laughing") and your emotion + response text (e.g. emotion: "laugh", response: "Haha, what's so funny?"). Music suggestion and wellbeing crons query this history to build a mood picture over time.

### Wellbeing daily log (you write this)
On every emotional action detected, append to the user's wellbeing daily log (`/root/local/users/{name}/wellbeing/YYYY-MM-DD.md`):

```
HH:MM — [emotion] {action} detected (your brief observation)
```

Example:
```
14:32 — [emotion] yawning detected (afternoon slump, suggested break)
22:15 — [emotion] yawning detected (late night, suggested winding down)
09:45 — [emotion] laughing detected (watching something funny on screen)
```

Also update the user's `wellbeing.md` summary if you notice patterns over multiple days (e.g. "often yawns around 15:00", "tends to work late and get tired by 23:00").

## Rules

- **Always speak** — emotional actions NEVER get NO_REPLY. Always say something, even if just a light remark
- **Never diagnose** — say "You seem tired" not "Fatigue detected" or "Emotional state: drowsy"
- **Never narrate the technology** — say "I noticed you yawning" not "X3D action recognition classified your movement as yawning"
- **Vary your responses** — don't repeat the exact same line. If you already said "Getting tired?" 30 minutes ago, say something different this time
- **Owners and friends only** — don't react to stranger emotional actions
- **One sentence max** — keep it brief and natural. You're noticing, not lecturing
- **Image context** — always look at the attached snapshot for additional context (what they're doing, time cues, environment)
- **Weave into conversation** — if the user is actively chatting, fold the observation in naturally rather than interrupting
- **Combine with Wellbeing** — emotional actions are logged to the same daily log as hydration/break events, building a complete picture of the user's day

## Output Template

```
[HW:/emotion:{"emotion":"{name}","intensity":{n}}] {caring one-sentence response}
```

Examples:
- `[HW:/emotion:{"emotion":"laugh","intensity":0.8}]` Haha, what's so funny?
- `[HW:/emotion:{"emotion":"caring","intensity":0.9}]` Hey... you okay?
- `[HW:/emotion:{"emotion":"sleepy","intensity":0.6}]` Getting a bit tired?
- `[HW:/emotion:{"emotion":"happy","intensity":0.7}]` Nice voice! Want me to put on some music?
