# AI Lamp — Marketing-Proposed Features

> Features proposed by the marketing team. Status updated 2026-04-21 based on current codebase.

---

## UC-M1: Facial Expression & Wellness Detection [DONE]

**Status: Implemented** (2026-04)

**Actor**: System (automatic, camera)
**Description**: Camera analyzes the user's facial expression to detect emotional state — Lumi responds proactively to support the user's wellbeing.

**Examples**:
- User looks tense/stressed → Lumi dims light, shifts to warm color, softly offers a break
- User looks drowsy/fatigued → Lumi increases brightness, plays an energizing chime, suggests a short walk
- User looks focused and calm → Lumi holds current environment, suppresses all interruptions

**Implementation**:
- Emotion classifier runs via **dlbackend WebSocket** (remote inference server), not on-device ONNX. LeLamp sends camera frames, receives emotion predictions.
- `lelamp/service/sensing/perceptions/emotion.py` — `RemoteEmotionChecker` connects to dlbackend, fires `emotion.detected` sensing event with detected emotion (Angry, Disgust, Fear, Happy, Sad, Surprise, Neutral).
- Lumi `user-emotion-detection/SKILL.md` maps detected facial emotion → mood signal via `POST /api/mood/log`.
- Lumi `mood/SKILL.md` fuses signals (camera emotion, conversation context, voice tone) into mood decisions.
- Mood decisions trigger downstream actions: `music-suggestion` (proactive music), `wellbeing` (break/hydration nudges), `emotion` (lamp expression).
- Configurable confidence threshold via `EMOTION_CONFIDENCE_THRESHOLD` in LeLamp config.

**Resolved questions**:
- [x] Which emotion model? → Remote dlbackend (not on-device ONNX). Offloads inference, no Pi 4 RAM/CPU impact.
- [x] Accuracy threshold → Configurable `EMOTION_CONFIDENCE_THRESHOLD` (default in LeLamp config).
- [x] Privacy → Frames sent to self-hosted dlbackend only, not third-party cloud.
- [x] Voice-tone interaction → Both feed into Mood skill fusion logic; camera emotion = signal, mood decision = fused output.

---

## UC-M2: Proactive Wellness Reminders [DONE]

**Status: Implemented** (2026-04)

**Actor**: System (automatic, sensing-driven)
**Description**: Lumi autonomously tracks sedentary activity and proactively reminds users to stand up, drink water, or take a break — without the user having to ask.

**Examples**:
- User has been at desk for 45 minutes → Lumi gently says "You've been sitting for a while — maybe stretch?"
- User has been at desk for 2 hours with no water nearby → "Don't forget to hydrate"

**Implementation**:
- **Event-driven, not timer-based.** The `wellbeing/SKILL.md` triggers on every `motion.activity` event (from action recognition).
- Action recognition via dlbackend classifies user activity: `using computer`, `writing`, `reading book`, `texting`, `drawing`, `playing controller` (sedentary) vs `drink`, `break` (reset activities).
- Each activity is logged to per-user JSONL timeline via `POST /api/openclaw/wellbeing/log`.
- On each event, skill reads recent history, computes time since last hydration/break reset, and nudges if thresholds exceeded.
- Per-user tracking: `current_user` from sensing context tag, strangers share `"unknown"` timeline.
- `lumi/resources/openclaw-skills/wellbeing/SKILL.md` — full workflow with threshold logic, dedup rules, and cooldowns.

**Resolved questions**:
- [x] Reminder intervals → AI-driven thresholds computed from activity log (not fixed timers).
- [x] "Sitting at desk" vs "briefly back" → Action recognition distinguishes sedentary labels from transient presence.
- [x] Hydration reminders → Time-based from last `drink` activity detection in wellbeing log.
- [x] DND mode → Agent personality handles context sensitivity (gentler at night, adapts to mood).

---

## UC-M3: Proactive Music Suggestion by Mood [DONE]

**Status: Implemented** (2026-04)

**Actor**: System (automatic, mood + sensing-driven)
**Description**: Lumi proactively suggests music based on detected mood, sedentary activity, and listening history — without the user requesting it.

**Examples**:
- User detected as stressed (facial emotion + conversation) → Lumi suggests calm piano
- User doing sedentary work for a while → Lumi offers lo-fi/study beats
- User detected as happy/excited → Lumi suggests upbeat music

**Implementation**:
- `lumi/resources/openclaw-skills/music-suggestion/SKILL.md` — dedicated proactive skill (separate from reactive `music/SKILL.md`).
- **Two triggers**:
  1. **Mood-driven**: After `mood/SKILL.md` logs a mood decision (sad, stressed, tired, excited, happy, bored) → music-suggestion fires.
  2. **Sedentary-driven**: `motion.activity` with sedentary labels (using computer, writing, etc.) → direct suggestion trigger.
- Checks before suggesting: audio already playing? recent suggestion cooldown (7 min)? stale mood decision (>30 min)?
- Queries `GET /audio/history?person={name}` for personalized genre preference.
- Genre mapping: stressed → soft jazz/classical, tired → calm piano, happy → upbeat pop, sedentary → lo-fi/ambient.
- Always suggests first via TTS, plays only after user confirmation.
- `[HW:/speak]` marker forces TTS on lamp speaker even for channel-origin sessions.

**Resolved questions**:
- [x] Music preferences → Queries `hw_audio` flow log + `/audio/history` for listening history.
- [x] Ask first vs auto-play → Always suggest first, play only after confirmation.
- [x] Sensing-triggered → Done: mood decisions + sedentary activity both trigger suggestions.
- [ ] Phone call / video meeting detection → Not yet (requires UC-12 or screen awareness).

---

## UC-M4: Screen-Time Awareness & Gesture Support [NOT STARTED]

**Status: Not implemented** — requires new models not yet in the codebase.

**Sub-feature A — Screen-Time / Eye-Care Tracking**:
- Needs gaze estimation model — not implemented in LeLamp sensing pipeline.
- Pi 4 feasibility unknown, benchmark needed.

**Sub-feature B — Contextual Gesture Support**:
- Needs gesture/pose model (MediaPipe Hand Lite or similar) — not implemented.
- High complexity, ~300-500MB RAM impact. May require Pi 5 or USB accelerator.

**Open questions** (unchanged):
- [ ] Gaze direction detection accuracy without dedicated eye-tracking hardware?
- [ ] MediaPipe on Pi 4 — benchmark needed
- [ ] Interaction with UC-10 (gesture for lamp control)?
- [ ] Split Sub-feature A and B into separate UCs?

---

## Bonus: Speaker Recognition [DONE]

**Status: Implemented** (2026-04) — not in original marketing proposal but a significant feature.

**Description**: Lumi recognizes who is speaking by voice. Mic transcripts are prefixed with the speaker's name (`Leo:`) or `Unknown:`. Users can self-enroll their voice by introducing themselves.

**Implementation**:
- `lelamp/speaker_recognizer.py` + `lelamp/service/voice/speaker_recognizer/speaker_recognizer.py` — voice embedding model, profile storage, real-time matching.
- `lumi/resources/openclaw-skills/speaker-recognizer/SKILL.md` — self-enrollment skill (mic intro, Telegram voice note, two-turn enrollment).
- Voice profiles stored per-user alongside face data in `/root/local/users/{name}/`.
- Telegram identity linked during voice enrollment for DM targeting.

---

## Summary

| UC | Feature | Status | Implementation |
|---|---|---|---|
| UC-M1 | Facial Expression Detection | **DONE** | dlbackend emotion WS + `user-emotion-detection` + `mood` skills |
| UC-M2 | Proactive Wellness Reminders | **DONE** | `wellbeing` skill, event-driven from `motion.activity` |
| UC-M3 | Proactive Music Suggestion | **DONE** | `music-suggestion` skill, mood + sedentary triggers |
| UC-M4a | Screen-Time / Eye-Care | **NOT STARTED** | Needs gaze estimation model |
| UC-M4b | Wellness Gestures | **NOT STARTED** | Needs gesture model (MediaPipe) |
| Bonus | Speaker Recognition | **DONE** | LeLamp voice embeddings + Lumi enrollment skill |

---

*Originally proposed by marketing team 2026-04-06. Status updated 2026-04-21.*
