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
    3. Tracking loop @ 20 FPS
         |  grab frame → TrackerVit update → confidence check → pixel offset → servo nudge
         |
    4. Object moves → servo follows (yaw + 3 pitch joints)
         |
    5. Confidence < 0.3 for 5 frames → auto-stop + hold servo at current pose
```

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
- **base_pitch** (ID 2) — up/down tilt (55% of pitch — leads the motion)
- **elbow_pitch** (ID 3) — up/down tilt (30% of pitch)
- **wrist_pitch** (ID 5) — up/down tilt (15% of pitch)

Pitch is weighted across 3 joints (55/30/15): base leads, elbow follows, wrist finishes. This gives smoother head motion than splitting equally.

**During tracking:**
- `_hold_mode = True` — suppresses idle animations
- `send_action()` — direct servo write, non-blocking (servo P-gain handles smoothing)
- Internal position tracking — reads bus once at start, tracks deltas internally

**On stop:** holds servo at the last tracked position. The lamp does *not* snap back to idle pose — that was removed because it caused a visible jerk right after tracking ended. Idle animation resumes on the next user interaction.

### Pixel-to-Degree Conversion

```
Frame center: (320, 240) for 640x480
Object center: EMA-smoothed from tracker bbox

dx = cx - 320   (positive = right)
dy = cy - 240   (positive = below)

gain = 1.3 if max(|dx|,|dy|) > 120 else 1.0   (adaptive: catch up when far)

yaw_deg   = dx * 0.022 * gain
pitch_deg = dy * 0.022 * gain
```

### Tuning Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `DEG_PER_PX_YAW` | 0.022 | Degrees per pixel horizontal |
| `DEG_PER_PX_PITCH` | 0.022 | Degrees per pixel vertical |
| `ADAPTIVE_GAIN_PX` | 120 | Offset threshold to boost gain |
| `ADAPTIVE_GAIN_MULT` | 1.3 | Gain multiplier when object is far |
| `EMA_ALPHA` | 0.3 | Smoothing factor on bbox center (higher = more responsive) |
| `DEAD_ZONE_PX` | 12 | Ignore offsets smaller than this (anti-jitter) |
| `WAKE_ZONE_PX` | 40 | Once settled, wake only when offset exceeds this |
| `MAX_NUDGE_DEG` | 4.5 | Max degrees per step |
| `TRACK_FPS` | 20 | Tracking loop frequency |
| `CONFIDENCE_THRESHOLD` | 0.3 | Below this = "lost" |
| `MAX_LOW_CONFIDENCE_FRAMES` | 5 | Consecutive low-confidence frames before auto-stop |
| `BBOX_JUMP_PX` | 120 | On jump, fall back to EMA-smoothed center (no nudge drop) |
| `PITCH_WEIGHT_BASE/ELBOW/WRIST` | 0.55 / 0.30 / 0.15 | Pitch distribution across 3 joints |

### Servo Position Limits

| Joint | Min | Max |
|-------|-----|-----|
| base_yaw | -135 | 135 |
| base_pitch | -90 | 30 |
| elbow_pitch | -90 | 90 |
| wrist_pitch | -90 | 90 |

## Auto-Stop Conditions

TrackerVit provides confidence scoring, unlike MIL/KCF which silently drift. Tracking auto-stops and holds the servo at its last position in these cases:

| Condition | Action |
|-----------|--------|
| `confidence < 0.3` for 5 frames | Stop — lost target |
| Bbox area > 3x initial size | Stop — tracker drift/bloat |
| Bbox covers > 50% of frame | Stop — tracker drift |
| Servo at yaw/pitch limit + object still >30% off center | Stop — object unreachable |
| Tracking duration > 5 minutes | Stop — timeout to save motor/CPU |
| Bbox center jumps > 120px in 1 frame | Fall back to EMA-smoothed center (keep nudging) |
| `tracker.update()` returns `ok=False` | Count as low-confidence frame |

## API Endpoints

All under `/servo/track`.

### GET /servo/track/targets — List suggested targets

```json
{"targets": ["person", "cup", "bottle", "glass", "phone", "laptop", ...]}
```

YOLOWorld is open-vocabulary — any text works, this list is just suggestions.

### POST /servo/track — Start tracking

```json
// Auto-detect (YOLOWorld finds the object)
{"target": "cup"}

// Manual bbox (skip detection)
{"bbox": [190, 50, 170, 300], "target": "cup"}

// Response
{
  "status": "ok",
  "tracking": true,
  "target": "cup",
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

Manual re-detect without stopping tracking session.

```json
{"bbox": [250, 160, 75, 95], "target": "cup"}
```

Note: Automatic re-detect runs every 5 seconds via YOLOWorld — this endpoint is for manual override only.

## End-to-End Flow

### Happy path

```
1. User: "Lumi, follow the cup"
2. Agent calls POST /servo/track {"target": "cup"}
3. LeLamp internally:
   a. Captures current frame
   b. Sends to YOLOWorld API → gets bbox (~1-2s)
   c. Re-grabs fresh frame
   d. TrackerVit init on bbox → starts tracking
4. Servo follows the cup in real-time (confidence ~0.5-0.7)
5. User: "OK stop" → agent calls POST /servo/track/stop
6. Servo holds at current position (no snap-back to idle)
```

### Auto-stop on lost

```
1. Object leaves frame or is occluded
2. TrackerVit confidence drops below 0.3
3. After 5 consecutive low-confidence frames → auto-stop
4. Servo holds at last known position (no snap-back)
5. Agent can notify user or auto re-detect
```

### Auto re-detect (built-in)

```
1. Every 5 seconds, tracking loop calls YOLOWorld in background thread
2. If object found → TrackerVit re-initializes with fresh bbox
3. Corrects drift without interrupting tracking
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
- ~~**Periodic re-detect**~~ — done, auto re-detect every 5s built into tracking loop
- **PID control** — smoother servo response instead of proportional-only
- **Multi-object** — track multiple objects, switch between them
