---
name: sensing
description: React to passive sensing events from the lamp — presence, sound, light. Events arrive as [sensing:<type>] messages and each gets an emotion marker + optional short line. Does NOT handle motion.activity (→ wellbeing) or emotion.detected (→ user-emotion-detection).
---

# Sensing

`[sensing:<type>]` messages arrive automatically from the lamp's detectors (camera, mic, light). React naturally — emotion marker + optional short line. Reply is spoken verbatim via TTS; keep it to ONE short sentence or `NO_REPLY`. Reasoning, thresholds, log dumps stay in `thinking`.

## ⛔ Out of scope — route elsewhere

| Event | Handled by |
|---|---|
| `[activity]` (Activity detected: ...) | `wellbeing/SKILL.md` only — whether the label is `drink`, `break`, or a sedentary raw label (`using computer`, `writing`, etc.). Activity events never route to music-suggestion. |
| `[emotion]` (Emotion detected: ...) | Step 1 → `user-emotion-detection/SKILL.md` (log mood signal + decision). Step 2 → `music-suggestion/SKILL.md` (run AFTER mood decision is logged). Backend injects both steps in the event message. |
| Any sensing event while guard mode is on | `guard/SKILL.md` — dramatic reactions, Telegram broadcast |

If one of those arrives, stop and switch — don't improvise here.

> **Emotion events are NOT presence events.** When `[emotion]` fires, the user is already in front of the lamp — do NOT greet, do NOT say `welcome back` / `hello again` / anything with `again`. The presence row in the matrix below applies only to `presence.enter` events.

## `[HW:...]` markers are plain text

Type them at the very start of your reply. They are NOT tool calls. The system reads and strips them before TTS.

```
[HW:/emotion:{"emotion":"greeting","intensity":0.9}][HW:/servo/aim:{"direction":"user"}][HW:/servo/track:{"target":["person"]}] Welcome back!
```

## Event → response matrix

| Event | Image? | HW markers | Voice |
|---|---|---|---|
| `presence.enter` (friend) | Yes | `[HW:/emotion:{"emotion":"greeting","intensity":0.9}][HW:/servo/aim:{"direction":"user"}][HW:/servo/track:{"target":["person"]}]` | YES — warm personal greeting by name |
| `presence.enter` (stranger) | Yes | `[HW:/emotion:{"emotion":"curious","intensity":0.8}][HW:/servo/play:{"recording":"scanning"}]` | YES — cautious acknowledgment |
| `presence.leave` | No | `[HW:/emotion:{"emotion":"idle","intensity":0.4}][HW:/servo/track/stop:{}]` | NO (`NO_REPLY`) — always silent |
| `presence.away` | No | `[HW:/emotion:{"emotion":"sleepy","intensity":0.8}][HW:/servo/track/stop:{}]` | YES — brief "going to sleep" line |
| `sound` 1st occurrence | No | `[HW:/emotion:{"emotion":"shock","intensity":0.8}]` | NO (`NO_REPLY`) |
| `sound` 2nd | No | `[HW:/emotion:{"emotion":"curious","intensity":0.7}]` | NO (`NO_REPLY`) |
| `sound` 3rd+ (persistent) | No | `[HW:/emotion:{"emotion":"curious","intensity":0.9}][HW:/servo/play:{"recording":"shock"}]` | YES — speak once |
| `light.level` | No | `[HW:/emotion:{"emotion":"idle","intensity":0.4}]` | Optional brief remark — AND adjust brightness via `led-control/SKILL.md` |

Every event emits at least one `[HW:/emotion:...]` marker, even on `NO_REPLY`. No silent reactions.

## Rules

- **HW markers first**, then text or `NO_REPLY`. Text = ONE short sentence max, spoken verbatim.
- **Tool-call scope** — only `motion.activity` (→ wellbeing) and `emotion.detected` (→ user-emotion-detection + music-suggestion Step 2) may fire POSTs. On `presence.*`, `sound`, `light.level`, NEVER POST to mood/wellbeing logs — even if prior turn content suggests it. Hallucinated side-effects on selfreplay turns violate this; see `docs/debug/openclaw-selfreplay.md`.
- **Never dump reasoning into the reply.** No log deltas, no "Looking at context…", no "No nudge needed". Scratch stays in `thinking`.
- **Use the image when attached** — real visual context beats generic phrasing.
- **Night-aware** — lower intensity emotions and shorter speech after ~22:00.
- **Don't narrate the tech** — "I see someone at the door" not "face detection matched".
- **Trust cooldowns** — system throttles already (60s sound, 10s presence, 30s light).
- **Never call any API to receive events** — they arrive automatically.
- **Presence auto-control is automatic** — don't manually toggle LED for presence events. Override only if the user asks (see Presence auto-control below).

## Proactive care

`presence.enter` gives you their image + time of day. Occasionally use it to say something thoughtful beyond the greeting:

| Time | You see | You might add |
|---|---|---|
| 08:30 | Friend arrives | "Morning! Had breakfast?" |
| 14:00 | Friend back from lunch | Nothing extra |
| 22:45 | Friend still at desk | "Almost 11 PM — call it a night?" |

Rules: never nag, don't repeat a reminder <20 min old, respect preferences they've set, one short sentence max, and when in doubt stay quiet.

## Presence auto-control (automatic)

- Someone arrives → light on (restores last scene)
- No motion 5 min → dim to 20%
- No motion 15 min → off

Override when the user says "stay on" / "don't turn off":

```bash
curl -s -X POST http://127.0.0.1:5001/presence/disable    # pause auto-control
curl -s -X POST http://127.0.0.1:5001/presence/enable     # resume
curl -s http://127.0.0.1:5001/presence                    # check state
```

## Error handling

- Presence API unreachable → still react to events; presence control is optional.
- Image can't be read → react on the text description alone.
- `[HW:...]` markers appear literally in TTS → binary doesn't support them; fall back to curl hardware commands for this session.

## Output template

```
[HW:/emotion:{"emotion":"<name>","intensity":<n>}][HW:/servo/...] <one short sentence | NO_REPLY>
```
