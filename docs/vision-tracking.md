# Vision Tracking — Object Follow with Servo

Lumi can track and follow any object the user describes in natural language. The system uses a hybrid approach: LLM vision for initial detection, TrackerVit (ViT-based ONNX) for real-time follow.

## Architecture

```
User: "Lumi, follow my cup"
         |
    OpenClaw Agent (understands intent)
         |
    1. Capture snapshot → LLM: "Find the cup, return bbox [x,y,w,h]"
         |
    2. POST /servo/track {bbox, target}
         |
    3. TrackerService (background loop @ 12 FPS)
         |  grab frame → TrackerVit update → confidence check → pixel offset → servo nudge
         |
    4. Object moves → servo follows (yaw + 3 pitch joints)
         |
    5. Confidence < 0.3 for 5 frames → auto-stop + resume idle
```

### Why hybrid?

| Approach | Speed | Flexibility | Problem |
|----------|-------|-------------|---------|
| LLM vision only | ~1-2s/frame | Any object via language | Too slow for tracking |
| YOLO/ML only | ~30ms/frame | Fixed classes | Can't track "the blue cup on the left" |
| **Hybrid** | **~15ms/frame** | **Any object** | — |

LLM handles the "what" (natural language to bounding box). TrackerVit handles the "where" (real-time position tracking with confidence scoring).

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
- **base_pitch** (ID 2) — up/down tilt (1/3 of pitch)
- **elbow_pitch** (ID 3) — up/down tilt (1/3 of pitch)
- **wrist_pitch** (ID 5) — up/down tilt (1/3 of pitch)

Pitch is split equally across 3 joints for full range of vertical motion.

**During tracking:**
- `_hold_mode = True` — suppresses idle animations
- `send_action()` — direct servo write, non-blocking (servo P-gain handles smoothing)
- Internal position tracking — reads bus once at start, tracks deltas internally

**On stop:** resumes idle animation via `dispatch(SERVO_CMD_PLAY, idle_recording)`.

### Pixel-to-Degree Conversion

```
Frame center: (320, 240) for 640x480
Object center: (cx, cy) from tracker bbox

dx = cx - 320   (positive = right)
dy = cy - 240   (positive = below)

yaw_deg   = dx * 0.02   (same sign: right → right)
pitch_deg = dy * 0.02   (same sign: down → down)
```

### Tuning Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `DEG_PER_PX_YAW` | 0.02 | Degrees per pixel horizontal |
| `DEG_PER_PX_PITCH` | 0.02 | Degrees per pixel vertical |
| `DEAD_ZONE_PX` | 15 | Ignore offsets smaller than this (anti-jitter) |
| `MAX_NUDGE_DEG` | 1.5 | Max degrees per step |
| `TRACK_FPS` | 12 | Tracking loop frequency |
| `CONFIDENCE_THRESHOLD` | 0.3 | Below this = "lost" |
| `MAX_LOW_CONFIDENCE_FRAMES` | 5 | Consecutive low-confidence frames before auto-stop |
| `BBOX_JUMP_PX` | 100 | Skip nudge if bbox center jumps more than this |

### Servo Position Limits

| Joint | Min | Max |
|-------|-----|-----|
| base_yaw | -135 | 135 |
| base_pitch | -90 | 30 |
| elbow_pitch | -90 | 90 |
| wrist_pitch | -90 | 90 |

## Loss Detection

TrackerVit provides confidence scoring, unlike MIL/KCF which silently drift.

| Condition | Action |
|-----------|--------|
| `confidence < 0.3` for 5 frames | Auto-stop, resume idle |
| Bbox center jumps > 100px in 1 frame | Skip nudge (tracker glitch) |
| `tracker.update()` returns `ok=False` | Count as low-confidence frame |

## API Endpoints

All under `/servo/track`.

### POST /servo/track — Start tracking

```json
// Request
{
  "bbox": [190, 50, 170, 300],
  "target": "cup"
}

// Response
{
  "status": "ok",
  "tracking": true,
  "target": "cup",
  "bbox": [190, 50, 170, 300],
  "confidence": 1.0
}
```

### DELETE /servo/track — Stop tracking

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

### PUT /servo/track — Re-initialize bbox

Re-detect without stopping tracking session.

```json
{"bbox": [250, 160, 75, 95], "target": "cup"}
```

## End-to-End Flow

### Happy path

```
1. User: "Lumi, follow the cup"
2. OpenClaw agent:
   a. Call /camera/snapshot → get frame
   b. Send frame to LLM: "Find the cup, return bounding box [x, y, w, h]"
   c. LLM returns: [190, 50, 170, 300]
   d. Call POST /servo/track {"bbox": [190,50,170,300], "target": "cup"}
3. TrackerVit follows the cup in real-time (confidence ~0.5-0.7)
4. User: "OK stop" → agent calls DELETE /servo/track
5. Servo resumes idle animation
```

### Auto-stop on lost

```
1. Object leaves frame or is occluded
2. TrackerVit confidence drops below 0.3
3. After 5 consecutive low-confidence frames → auto-stop
4. Servo resumes idle animation
5. Agent can notify user or auto re-detect
```

### Periodic re-detect (PUT)

```
1. Tracking active but bbox drifting (scale change, partial occlusion)
2. Agent takes snapshot → LLM → new bbox → PUT /servo/track
3. TrackerVit re-initializes on fresh bbox, session continues
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
- No additional packages needed

## Interaction with Other Systems

| System | During tracking | After tracking |
|--------|----------------|----------------|
| Servo idle animation | Suppressed (`_hold_mode`) | Resumed |
| `/servo/play` | Blocked by `_hold_mode` | Resumed |
| Sensing (face, motion) | Continues — shares camera | Continues |
| Camera stream overlay | Green bbox drawn | Normal stream |
| TTS | Continues normally | Continues normally |

## Next Steps

- **LLM detect integration** — OpenClaw skill to get bbox from natural language description
- **Periodic re-detect** — auto PUT every N seconds to correct drift
- **PID control** — smoother servo response instead of proportional-only
- **Multi-object** — track multiple objects, switch between them
