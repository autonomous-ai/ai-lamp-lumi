# Vision Tracking — Object Follow with Servo

Lumi can track and follow any object the user names. Two-stage approach: YOLOWorld API detects the object by name, TrackerVit follows it in real-time.

## Architecture

```
User: "Lumi, follow the cup"
         |
    POST /servo/track {"target": "cup"}
         |
    1. YOLOWorld API: frame + "cup" → bbox [x,y,w,h]  (~1-2s, RunPod GPU)
         |
    2. TrackerVit init on bbox
         |
    3. Tracking loop @ 7 FPS (move-then-freeze cadence)
         |  grab frame (servo stationary) → TrackerVit update → nudge → wait for servo to settle
         |
    4. Object moves → servo follows (yaw + 3 pitch joints)
         |
    5. Confidence < 0.3 for 5 frames → auto-stop + dispatch idle to recover pose
```

### Why move-then-freeze (not high-FPS chasing)

Earlier iterations ran the loop at 20 FPS, commanding servo nudges every 50ms. Two problems:

1. **Camera ego-motion blur.** The camera is mounted on the moving lamp head. Commanding the servo faster than it can physically execute means frames are captured mid-motion — blurred or offset from what the tracker "sees". The tracker then computes bbox from a frame that no longer represents the current servo pose, and the nudge overshoots.
2. **Command stacking.** Small nudges (~0.5°) every 50ms stacked up faster than the motor could reach targets, producing visible hunting and twitching.

The current design reads a frame, decides one nudge, sends it, then explicitly waits for the servo to physically complete the move (~80ms) before reading the next frame. Each frame is sharp and coordinates match the current pose. Fewer commands, bigger deliberate steps, no hunting.

### Start-up waits for animation idle

If the caller fires `/servo/aim` just before `/servo/track` (e.g. the agent handling "look at the desk and follow the cup"), tracking `.start()` blocks until the in-progress recording has completed and a short settle pad has elapsed (capped at 4s). Without the wait, YOLO captured a frame mid-motion — YOLO still returned a detection, but the tracker couldn't lock because the next (settled) frame looked materially different. The wait makes the init frame and the first tracker.update frame both reflect the same stable pose.

### Why there is no periodic YOLO re-detect

Earlier versions called YOLOWorld every 5 seconds during active tracking to correct drift. This was removed because the YOLO round-trip is 1-2 seconds, during which:

- The servo continues moving — the returned bbox is in coordinates that no longer match the current frame.
- The object itself may have moved.
- The scene can change arbitrarily.

Using that bbox to re-init the tracker caused more harm than good. Drift is now handled by the TrackerVit confidence score: if it drops below threshold for 5 frames, tracking stops cleanly and the caller can re-issue the follow command.

### Detection: YOLOWorld API

Open-vocabulary object detection — detects any object by text label, not limited to fixed classes.

- **Endpoint:** `{DL_BACKEND_URL}/detect/yoloworld`
- **Auth:** `x-api-key` header from `DL_API_KEY` config
- **Request:** `{"image_b64": "...", "classes": ["cup"]}`
- **Response:** `[{"class_name": "cup", "xywh": [cx, cy, w, h], "confidence": 0.98}]`
- **Speed:** ~1-2s (RunPod GPU)

Used automatically when `POST /servo/track` is called without `bbox`. Can also provide bbox manually to skip detection.

### Tracking: TrackerVit

Real-time object following after initial detection.

## Tracker: TrackerVit

**Model:** `lelamp/service/tracking/vittrack.onnx` (714KB, checked into repo)

| Feature | Value |
|---------|-------|
| Speed | ~10-20ms/frame on Pi 5 |
| Confidence score | 0.0-1.0 per frame |
| Scale handling | Auto-adjusts bbox size |
| Loss detection | Returns `ok=False` + low score when object disappears |

**Fallback chain:** TrackerVit → CSRT (needs opencv-contrib) → KCF → MIL

## Servo Control

Tracking uses 4 of 5 servos:
- **base_yaw** (ID 1) — left/right pan
- **base_pitch** (ID 2) — up/down tilt (100% of pitch — single joint)
- **elbow_pitch** (ID 3) — unused during tracking (held at start pose)
- **wrist_pitch** (ID 5) — unused during tracking (held at start pose)

Pitch is driven by base_pitch only, symmetric with how yaw uses base_yaw. Earlier versions split pitch across all 3 joints, but elbow/wrist tilt also *translates* the camera as it rotates, producing arc motion that the pixel-to-degree model didn't predict (worse on close objects). Single-joint pitch gives clean rotation around the camera's own axis. Trade-off: base_pitch range -90°..+30° (120°) is narrower than yaw's ±135°, so pitch hits servo limit sooner — motion stops cleanly in that case.

**During tracking:**
- `_hold_mode = True` + `_tracking_active = True` — `_tracking_active` is strict: the animation loop drops any in-progress recording (e.g. a shock reaction from a loud noise) so nothing fights the tracker or resumes jerking when tracking ends. `/emotion` calls during tracking still update the LED but their servo animation is suppressed.
- `send_action()` — direct servo write, non-blocking (servo P-gain handles smoothing)
- Bus position re-read each cycle — internal pose state is re-synced from the hardware bus at the start of every loop iteration, so if anything external (scene change, stale animation, manual command) did move the servo, the tracker picks up the real pose instead of compounding stale deltas.

**On stop:** dispatches the idle recording to recover the lamp to a safe pose. An earlier iteration held the last tracked position (to avoid the snap-back looking jerky), but that meant the lamp could be left torqued against an awkward pose near a servo limit — the motor felt physically stuck. Resuming idle is the safer default; the idle recording's interpolation smooths the transition.

### Pixel-to-Degree Conversion

```
Frame center: (320, 240) for 640x480
Object center: tracker bbox (no smoothing — the ~143ms move-then-freeze
                             cadence suppresses tracker jitter naturally)

dx = cx - 320   (positive = right)
dy = cy - 240   (positive = below)

yaw_deg   = dx * 0.022    (clamped to ±6.0°, zero if |dx| < 18)
pitch_deg = -dy * 0.022   (negated; see "Pitch sign" below)
```

### Tuning Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `DEG_PER_PX_YAW` | 0.022 | Degrees per pixel horizontal |
| `DEG_PER_PX_PITCH` | 0.022 | Degrees per pixel vertical |
| `DEAD_ZONE_PX` | 18 | Ignore offsets smaller than this (anti-jitter) |
| `MAX_NUDGE_DEG` | 6.0 | Max degrees per step |
| `TRACK_FPS` | 7 | Tracking loop frequency (~143ms/cycle) |
| `SERVO_SETTLE_S` | 0.08 | Sleep after nudge before reading next frame |
| `CONFIDENCE_THRESHOLD` | 0.3 | Below this = "lost" |
| `MAX_LOW_CONFIDENCE_FRAMES` | 5 | Consecutive low-confidence frames before auto-stop |
| `PITCH_WEIGHT_BASE/ELBOW/WRIST` | 1.0 / 0.0 / 0.0 | Pitch on base only (single joint, symmetric with yaw) |
| `CLOSE_OBJECT_RATIO` | 0.35 | bbox area / frame area above this → reduce gain |
| `CLOSE_OBJECT_GAIN` | 0.5 | Gain multiplier when object is close |
| `DETECT_MIN_AREA_RATIO` | 0.003 | Reject YOLO bbox smaller than this (too few pixels to track) |
| `DETECT_MAX_AREA_RATIO` | 0.30 | Reject YOLO bbox larger than this (loose, likely merged) |
| `DETECT_MIN_CONFIDENCE` | 0.30 | Reject YOLO detections below this confidence |
| `TRACK_BASE_PITCH_MIN/MAX` | -75 / +15 | Tracker-allowed pitch range (narrower than hardware -90/+30) — auto-stops before hitting a physical stop |
| `animation_wait_budget_s` | 7 | Max wait in `start()` for a preceding /servo/aim animation to finish |
| Bbox bloat stop ratio | 2× initial | Auto-stop when tracker bbox grows to this multiple of init area |

### Pitch sign

`base_pitch` grows positive as the lamp tilts *up* (see `AIM_UP` has `base_pitch=+10`, `AIM_DOWN` has `-50`). To bring an object from the top of the frame (dy < 0) toward the centre, the lamp must tilt up — base_pitch must *increase* — so the pixel-to-degree conversion negates dy. Without this negation the tracker drove the lamp away from the target on the vertical axis and eventually pinned base_pitch against its hardware maximum.

### Servo Position Limits

| Joint | Min | Max |
|-------|-----|-----|
| base_yaw | -135 | 135 |
| base_pitch | -90 | 30 |
| elbow_pitch | -90 | 90 |
| wrist_pitch | -90 | 90 |

## Auto-Stop Conditions

TrackerVit provides confidence scoring, unlike MIL/KCF which silently drift. Tracking auto-stops and dispatches the idle recording to recover in these cases:

| Condition | Action |
|-----------|--------|
| `confidence < 0.3` for 5 frames | Stop — lost target |
| Bbox area > 3x initial size | Stop — tracker drift/bloat |
| Bbox covers > 50% of frame | Stop — tracker drift |
| Servo at yaw/pitch limit + object still >30% off center | Stop — object unreachable |
| Tracking duration > 5 minutes | Stop — timeout to save motor/CPU |
| `tracker.update()` returns `ok=False` | Count as low-confidence frame |

## API Endpoints

All under `/servo/track`.

### GET /servo/track/targets — List suggested targets

```json
{"targets": ["person", "cup", "bottle", "glass", "phone", "laptop", ...]}
```

YOLOWorld is open-vocabulary — any text works, this list is just suggestions.

### POST /servo/track — Start tracking

`target` accepts either a single string or a list of candidate labels. When a list is passed, YOLOWorld evaluates all labels and the single highest-confidence detection is used. Useful when the caller (e.g. an LLM skill) is unsure which exact label will match.

```json
// Auto-detect, single label
{"target": "cup"}

// Auto-detect, list of candidate labels (preferred from LLM skills)
{"target": ["cup", "mug", "coffee cup"]}

// Manual bbox (skip detection — target is for display only)
{"bbox": [190, 50, 170, 300], "target": "cup"}

// Response
{
  "status": "ok",
  "tracking": true,
  "target": "cup | mug | coffee cup",
  "bbox": [190, 50, 170, 300],
  "confidence": 1.0
}
```

### POST /servo/track/stop — Stop tracking

```json
{"status": "ok", "tracking": false}
```

### GET /servo/track — Check status

```json
{
  "status": "ok",
  "tracking": true,
  "target": "cup",
  "bbox": [195, 55, 175, 295],
  "confidence": 0.612
}
```

### POST /servo/track/update — Re-initialize bbox

Manual re-init of the tracker with a new bbox without stopping the session.

```json
{"bbox": [250, 160, 75, 95], "target": "cup"}
```

Note: there is no automatic periodic YOLO re-detect — the caller decides when to re-init. See "Why there is no periodic YOLO re-detect" above.

## End-to-End Flow

### Happy path

```
1. User: "Lumi, follow the cup"
2. Agent calls POST /servo/track {"target": "cup"}
3. LeLamp internally:
   a. Snapshots a frame and holds on to it
   b. Sends that frame to YOLOWorld API → gets bbox (~1-2s)
   c. TrackerVit init uses the *same* frame + bbox (coordinates match)
   d. Starts the move-then-freeze tracking loop
4. Servo follows the cup in real-time (confidence ~0.5-0.7)
5. User: "OK stop" → agent calls POST /servo/track/stop
6. Servo dispatches idle to recover to a safe pose
```

### Auto-stop on lost

```
1. Object leaves frame or is occluded
2. TrackerVit confidence drops below 0.3
3. After 5 consecutive low-confidence frames → auto-stop
4. Servo dispatches idle to recover to a safe pose
5. Agent can notify user or auto re-detect
```

## Camera Stream Overlay

When tracking is active, the MJPEG stream (`/camera/stream`) draws:
- Green bounding box around tracked object
- Target label above the box

## Web UI

Camera section shows:
- **Vision Tracking card** — target input, bbox input, Start/Stop/Status buttons
- **Stream badge** — "LIVE" or "TRACKING: {target}"
- **Confidence** — shown in tracking info panel
- **Polling** — status refreshes every 3 seconds

## Dependencies

- `opencv-python>=4.8.0` (already in `pyproject.toml`)
- `vittrack.onnx` — checked into repo at `lelamp/service/tracking/vittrack.onnx`
- `requests` (already in project)
- **YOLOWorld API** — RunPod DL backend at `DL_BACKEND_URL/detect/yoloworld`

## Interaction with Other Systems

| System | During tracking | After tracking |
|--------|----------------|----------------|
| Servo idle animation | Suppressed (`_hold_mode`) | Resumed |
| `/servo/play` | Blocked by `_hold_mode` | Resumed |
| Sensing (face, motion) | Continues — shares camera | Continues |
| Camera stream overlay | Green bbox drawn | Normal stream |
| TTS | Continues normally | Continues normally |

## Next Steps

- **OpenClaw skill** — `track/SKILL.md` so agent can call tracking via voice
- ~~**Periodic re-detect**~~ — tried, rolled back. 1-2s YOLO round-trip desyncs from servo motion (see "Why there is no periodic YOLO re-detect" above)
- **PID control** — smoother servo response instead of proportional-only
- **Multi-object** — track multiple objects, switch between them
