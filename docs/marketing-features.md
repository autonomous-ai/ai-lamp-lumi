# AI Lamp — Marketing-Proposed Features

> Proposed by the marketing team. These features are **not yet in the product vision** and require team review before implementation.

Status: **Under Review** — not scheduled, not implemented.

---

## UC-M1: Facial Expression & Wellness Detection [Proposed]

**Actor**: System (automatic, camera)
**Description**: Camera continuously analyzes the user's facial expression to detect emotional state, stress level, and fatigue — and Lumi responds proactively to support the user's wellbeing.

**Examples**:
- User looks tense/stressed → Lumi dims light, shifts to warm color, softly offers a break
- User looks drowsy/fatigued → Lumi increases brightness, plays an energizing chime, suggests a short walk
- User looks focused and calm → Lumi holds current environment, suppresses all interruptions

**Difference from existing**:
- Current "Stress" detection (Pillar 4 table) uses **mic (voice tone)** — this UC uses **camera (facial expression)**
- Complements voice tone detection; camera catches stress even when the user is silent

**Architecture fit**:
- Add emotion classifier model on top of existing InsightFace face detection in `lelamp/service/sensing/perceptions/facerecognizer.py`
- Fire new sensing event `expression.detected` → Lumi → OpenClaw reacts via SOUL.md
- Requires lightweight ONNX emotion model (~150MB, ~50ms/frame inference on Pi 4)

**Open questions**:
- [ ] Which emotion model? (MobileNet-based FER, EfficientNet-lite, or cloud vision API)
- [ ] Accuracy threshold before triggering — avoid false positives (user just squinting at screen)
- [ ] Privacy: facial expression data must stay fully on-device, never uploaded
- [ ] How does this interact with voice-tone stress detection? Fusion logic needed?

**Acceptance Criteria**:
- Detects minimum 3 states: neutral, stressed/tense, fatigued/drowsy
- Cooldown: minimum 60s between consecutive expression-triggered events
- Inference runs on Pi 4 without degrading sensing loop below 2s cycle
- User can disable expression detection independently of other camera features

---

## UC-M2: Proactive Wellness Reminders [Proposed]

**Actor**: System (automatic, time + camera)
**Description**: Lumi autonomously tracks how long the user has been sitting and proactively reminds them to stand up, drink water, or take a break — without the user having to ask.

**Examples**:
- User has been at desk for 45 minutes → Lumi gently says "You've been sitting for a while — maybe stretch?"
- User has been at desk for 2 hours with no water nearby → "Don't forget to hydrate"
- User is working past midnight → Blue light reduction + gentle wind-down suggestion

**Difference from existing**:
- UC-06 has "Remind me to take a break in 25 minutes" — **user-initiated Pomodoro**
- This UC is **fully proactive** — Lumi tracks sitting duration itself and initiates without being asked

**Architecture fit**:
- Track `presence.enter` timestamp; calculate continuous sitting duration in sensing loop
- Fire `wellness.sitting_too_long` event after configurable threshold (default: 45 min)
- Uses existing presence detection (FaceRecognizer) — no new model required
- OpenClaw handles message tone/timing based on user history and personality

> **Implementation note (2026-04)**: This UC is already covered by a more flexible AI-driven approach. Instead of a fixed-timer `wellness.sitting_too_long` event from the sensing loop, the Wellbeing SKILL uses OpenClaw cron jobs triggered by `motion.activity` sedentary detection (using computer, writing, reading, etc.). The break cron is only created when sedentary activity is confirmed — not on mere presence. The agent has full conversation context, per-person history, and personality awareness, making reminders more natural and adaptive than a static sensing-loop timer. See `lumi/resources/openclaw-skills/wellbeing/SKILL.md`.

**Open questions**:
- [ ] What are the default reminder intervals? (45 min? 60 min? User-configurable?)
- [ ] How does Lumi distinguish "sitting at desk working" vs. "briefly back in frame"?
- [ ] Should water/hydration reminders be time-based or require a separate sensor (humidity near a cup)?
- [ ] Does "Do Not Disturb" mode suppress wellness reminders too, or are they always-on?

**Acceptance Criteria**:
- Sitting time tracked from first `presence.enter` event; reset on `presence.leave` (> 5 min absence)
- Reminder fires at configurable intervals (default: 45 min, 90 min, 150 min)
- Reminder tone adapts to context (gentler at night, more energetic in morning)
- User can configure intervals or disable entirely via voice or web UI

---

## UC-M3: Proactive Music Suggestion by Mood [Proposed]

**Actor**: System (automatic, conversation context + sensing)
**Description**: Lumi proactively suggests or plays music based on detected mood, time of day, and ongoing conversation context — without the user requesting it.

**Examples**:
- User sounds stressed (voice tone) → Lumi softly plays ambient/lo-fi without being asked
- Deep focus detected (sustained silence, no movement) → Lumi offers focus music ("Want some background music?")
- Morning routine detected → Lumi plays an energizing playlist
- User says they feel sad during conversation → Lumi offers comfort music

**Difference from existing**:
- Music playback (SKILL.md + music_service.py) is **fully implemented and working**
- Current behavior: **reactive only** — user must ask "play some music"
- This UC adds the **proactive trigger layer** — Lumi decides to offer/play without being asked

**Implementation status** (partial):
- ✅ **History-based suggestion** — Music SKILL.md updated with "Music Suggestion (Proactive)" section. Queries `hw_audio` events from flow log API (`GET /api/openclaw/flow-events`) to build listening history. Suggests 1–2 songs via TTS without auto-playing; plays only after user confirmation.
- ⬜ **Sensing-triggered suggestion** — Proactive triggers from stress/focus/morning context not yet wired (requires sensing event → suggestion pipeline)

**Architecture fit**:
- Lowest effort of the 4 proposed features — no new hardware model needed
- Music SKILL.md updated with suggestion workflow, bash recipes to query flow logs, and suggestion rules
- Sensing events already available: `sound.voice_tone` (stress), `sound.silence` (focus), `time.schedule` (morning/night)
- OpenClaw maps: stress → ambient/lo-fi, focus → instrumental, morning → upbeat

**Open questions**:
- [x] User music preferences: how does Lumi learn over time what the user likes? → **Solved: queries `hw_audio` flow log history**
- [x] Should Lumi ask first ("Want some music?") or just play? → **Always suggest first, play only after confirmation**
- [ ] How to avoid being annoying — music interrupting a phone call or video meeting?
- [ ] Integrate with UC-16 (Screen Awareness) to detect Spotify/YouTube already running → don't suggest

**Acceptance Criteria**:
- Proactive music trigger fires on: stress detection, sustained focus (>15 min silence), morning schedule
- Always asks before playing (first time) — "plays directly" only after user confirms preference
- Respects video call mode (UC-12) — no music during active calls
- User can say "stop suggesting music" and Lumi remembers via OpenClaw long-term memory

---

## UC-M4: Screen-Time Awareness & Gesture Support [Proposed]

**Actor**: System (automatic, camera)
**Description**: Camera tracks how long the user has been staring at a screen without looking away, and proactively offers eye-care reminders or support. Additionally, hand gestures can trigger supportive actions.

**Sub-feature A — Screen-Time / Eye-Care Tracking**:
- Camera detects user's gaze direction (facing screen continuously)
- After configurable duration (e.g., 20 min) without looking away → Lumi suggests the 20-20-20 rule ("Look at something 20 feet away for 20 seconds")
- Tracks "look-away" events to reset the timer

**Sub-feature B — Contextual Gesture Support**:
- User glances at Lumi while looking stressed/overwhelmed → Lumi offers assistance
- User rubs eyes (fatigue gesture) → Lumi dims light and suggests a break
- Note: this is distinct from UC-10 (gesture control for lamp) — this is **welfare-oriented**, not control-oriented

**Difference from existing**:
- UC-10 covers lamp-control gestures (wave = toggle, thumbs up = scene) — fully defined but not implemented
- This UC covers **wellness gestures** (eye-rub, looking at Lumi) → Lumi offers support
- UC-16 covers screen awareness via desktop agent — this UC uses **camera only**, no desktop agent required

**Architecture fit**:
- Sub-feature A: Track face-present + gaze direction duration. Gaze estimation is a medium-complexity addition to FaceRecognizer
- Sub-feature B: High complexity — requires gesture/pose model (MediaPipe Hand Lite or similar), ~300-500MB RAM impact
- Pi 4 feasibility: Sub-feature A is viable; Sub-feature B requires benchmark before committing

**Open questions**:
- [ ] Sub-feature A: Is gaze direction detection accurate enough without dedicated eye-tracking hardware?
- [ ] Sub-feature B: MediaPipe on Pi 4 — benchmark needed. May require Pi 5 or USB accelerator (Coral)
- [ ] How does this interact with UC-10 (gesture for lamp control)? Same model, different intent classification?
- [ ] Should Sub-feature A and B be split into separate UCs given the complexity difference?

**Acceptance Criteria (Sub-feature A)**:
- Screen-stare timer fires after 20 min of continuous face-present without significant head movement
- Reminder uses 20-20-20 rule messaging
- Timer resets when user looks away (head turn > 30 degrees) for > 5 seconds
- User can configure threshold or disable

**Acceptance Criteria (Sub-feature B)**:
- Pending Pi 4 benchmark — define after feasibility confirmed
- If feasible: minimum 2 wellness gestures recognized with > 80% accuracy

---

## Summary & Recommended Priority

| UC | Feature | Effort | Pi 4 Risk | Recommended Priority |
|---|---|---|---|---|
| UC-M3 | Proactive Music Suggestion | Low (SKILL.md + SOUL.md only) | None | **P1 — partial (history-based suggestion done)** |
| UC-M2 | Proactive Wellness Reminders | Low (sensing loop logic) | None | **P1 — do first** |
| UC-M1 | Facial Expression Detection | Medium (new ONNX model) | Low | P2 |
| UC-M4a | Screen-Time / Eye-Care | Medium (gaze estimation) | Medium | P2 |
| UC-M4b | Wellness Gestures | High (MediaPipe, needs benchmark) | High | P3 — benchmark first |

---

*Proposed by marketing team 2026-04-06. Requires product owner sign-off before scheduling.*
