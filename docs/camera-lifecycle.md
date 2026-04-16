# Camera Lifecycle — Reactive On/Off

Camera should be **reactive**: on when needed, off when idle. Saves CPU/RAM, respects privacy.

## Current State

- `POST /camera/disable` / `POST /camera/enable` — manual toggle from web monitor
- Camera feeds sensing: face recognition (ONNX InsightFace), pose/motion (ONNX), light level (pixel mean), presence (pixel diff)
- Voice pipeline (mic) runs independently of camera
- Sound perception runs independently of camera

## Design: Camera On/Off as the Only Switch

No new abstractions. Camera on = full sensing. Camera off = vision sensing stops, audio sensing continues.

### When camera is OFF

- `_tick()` skips all vision perceptions (face, pose, motion, light)
- Sound perception still runs (mic-based)
- Wake word detection still runs (voice_service)
- TTS still works
- Servo/LED still work
- Web monitor Camera tab shows "Disabled" with Enable button

### When camera is ON

- All perceptions run as normal
- Face/pose ONNX inference every other tick (existing optimization)

## Auto-Off Triggers

### 1. Scene: night

When `/scene` activates `night` → turn camera off.
- User going to sleep, no need for vision
- Sound perception stays for wake word / sound spike

### 2. Emotion: sleepy

When `/emotion` receives `sleepy` → turn camera off.
- Same as night, agent explicitly put lamp to sleep

### 3. Presence idle timeout

When presence state transitions to `away` (no motion for away_timeout seconds) → turn camera off.
- Nobody in the room, no point running vision
- Sound spike or wake word will turn it back on

### 4. Voice command: "don't look" / "stop watching"

User says "Lumi, đừng nhìn" / "don't watch me" / "privacy mode" → agent calls `[HW:/camera/disable:{}]`.
- Explicit user request for privacy
- Only voice command or web toggle can re-enable

### 5. Scene: focus, reading, movie

When `/scene` activates `focus`, `reading`, or `movie` → turn camera off.
- User already present and engaged, no need to keep detecting
- Presence is already known from the scene activation
- Saves CPU during long sessions
- Camera re-enables when scene changes or user leaves (detected by sound/wake word)

## Auto-On Triggers

### 1. Wake word detected

Voice service detects wake word ("Looney", etc.) → turn camera on.
- User is actively engaging, may need visual context
- Always works because mic runs independently

### 2. Sound spike (loud noise)

Sound perception detects RMS above threshold while camera is off → turn camera on.
- Someone may have entered the room
- Camera on → face detect → presence.enter if person found
- If no face detected after N seconds, camera off again (avoid false positive drain)

### 3. Scene change to active scene

When `/scene` changes from night/sleep to energize or relax → turn camera on.
- User or agent activated a daytime scene

### 4. Emotion change from sleepy to anything else

When `/emotion` receives non-sleepy emotion → turn camera on.
- Agent is actively interacting, may need vision

### 5. Morning cron / scheduled

Cron job at configured wake time (e.g. 6:00 AM) → turn camera on.
- Ready for morning routine before user says anything

### 6. Voice command: "look" / "nhìn xem"

User says "Lumi, nhìn xem" / "look at me" / "camera on" → agent calls `[HW:/camera/enable:{}]`.
- Explicit user request

### 7. Telegram/web chat with visual context needed

Agent needs snapshot (camera skill) → auto-enable camera, take snapshot, optionally leave on or disable after.

## Manual Override

Web monitor Camera tab toggle always works. Manual disable stays until:
- User manually re-enables
- OR a voice command explicitly re-enables

Manual override does NOT get auto-overridden by scene/emotion/presence triggers. Only explicit user action (voice command, web toggle) clears manual override.

## Implementation Plan

### LeLamp (Python)

1. **`server.py`**: Already has `/camera/disable`, `/camera/enable`, `_camera_disabled` flag.

2. **Add `_camera_manual_override` flag**: When user toggles via web or voice command "đừng nhìn", set `True`. Auto triggers (scene, emotion, presence) check this flag and skip if `True`. Voice command "nhìn xem" or web enable clears it.

3. **Scene endpoint** (`/scene`): After setting scene, check scene name:
   - `night`, `focus`, `reading`, `movie` → call `camera_capture.stop()` if not manual override
   - `energize`, `relax` → call `camera_capture.start()` if not manual override

4. **Emotion endpoint** (`/emotion`): 
   - `sleepy` → stop camera if not manual override
   - Any other emotion when camera off and not manual override → start camera

5. **Presence service**: When state → `away` → stop camera if not manual override.

6. **Sound perception**: When camera off and RMS spike detected → start camera, set auto-off timer (30s no face → stop again).

7. **`_tick()` in sensing_service**: Already handles `frame = None` when camera stopped — vision perceptions get `None` frame and skip. No code change needed here.

### Lumi (Go)

8. **Voice service / wake word**: When wake word detected, POST `/camera/enable` to LeLamp before processing.

9. **Healthwatch**: No change needed — camera state is independent of health monitoring.

### OpenClaw Skills

10. **Camera skill** (`servo-control/SKILL.md` or new `camera/SKILL.md`): Add examples:
    - "đừng nhìn" → `[HW:/camera/disable:{}]`
    - "nhìn xem" → `[HW:/camera/enable:{}]`

### Web Monitor

11. Already done — Camera tab has Enable/Disable toggle.

## Edge Cases

- **Guard mode + camera off**: Guard mode requires camera. If guard mode activates while camera is off → force camera on, ignore manual override. Guard mode is security-critical.
- **Face enroll while camera off**: `/face/enroll` uses uploaded image, not live camera. No conflict.
- **Snapshot request while camera off**: Return 503 with message "Camera disabled". Agent handles gracefully.
- **Multiple rapid triggers**: Debounce camera start/stop — don't restart if already starting. `camera_capture.start()` already handles "already started" case.
- **Sound spike false positive loop**: After sound spike auto-on, if no face detected within 30s → auto-off again. Prevents camera staying on from random noise.
