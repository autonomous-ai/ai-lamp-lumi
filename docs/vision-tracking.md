# Vision Tracking — Object Follow with Servo

Lumi can track and follow any object the user describes in natural language. The system uses a hybrid approach: LLM vision for initial detection, OpenCV tracker for real-time follow.

## Architecture

```
User: "Lumi, follow my hand"
         |
    OpenClaw Agent (understands intent)
         |
    1. Capture snapshot → LLM vision → bounding box [x, y, w, h]
         |
    2. POST /servo/track {bbox, target}
         |
    3. TrackerService (background loop @ 10 FPS)
         |  grab frame → OpenCV CSRT update → pixel offset → servo nudge
         |
    4. Object moves → servo follows
         |
    5. Tracker loses target → auto re-detect or stop
```

### Why hybrid?

| Approach | Speed | Flexibility | Problem |
|----------|-------|-------------|---------|
| LLM vision only | ~1-2s/frame | Any object via language | Too slow for tracking |
| YOLO/ML only | ~30ms/frame | Fixed classes | Can't track "the blue cup on the left" |
| **Hybrid** | **~100ms/frame** | **Any object** | — |

LLM handles the "what" (natural language to bounding box). OpenCV handles the "where" (real-time position tracking).

## Components

### TrackerService (`lelamp/service/tracking/tracker_service.py`)

Core tracking engine. Manages a single tracking session.

**Lifecycle:**
1. `start(bbox, target_label, camera, servo)` — init OpenCV tracker on bbox
2. Background thread runs at `TRACK_FPS` (default 10)
3. Each frame: update tracker → compute offset from frame center → nudge servo
4. `stop()` — end session, resume idle animations

**Servo control during tracking:**
- Sets `_hold_mode = True` to suppress idle/ambient animations
- Nudges `base_yaw` and `base_pitch` directly via `move_to()` (bypasses HTTP for speed)
- Clears hold mode on stop

**Auto-stop:** Tracker loses target for `MAX_LOST_FRAMES` (15 frames = ~1.5s) → stops automatically.

### Pixel-to-Degree Conversion

```
Frame center: (320, 240) for 640x480
Object center: (cx, cy) from tracker bbox
Offset: dx = cx - 320, dy = cy - 240

yaw_degrees  = -dx * DEG_PER_PX_YAW   (0.08 deg/px default)
pitch_degrees = -dy * DEG_PER_PX_PITCH  (0.08 deg/px default)
```

**Tuning constants** (top of `tracker_service.py`):

| Constant | Default | Description |
|----------|---------|-------------|
| `DEG_PER_PX_YAW` | 0.08 | Degrees per pixel horizontal. ~60 deg FOV / 640px |
| `DEG_PER_PX_PITCH` | 0.08 | Degrees per pixel vertical |
| `DEAD_ZONE_PX` | 20 | Ignore offsets smaller than this (anti-jitter) |
| `MAX_NUDGE_DEG` | 10.0 | Max degrees per nudge step (prevents wild swings) |
| `TRACK_FPS` | 10 | Tracking loop frequency |
| `MAX_LOST_FRAMES` | 15 | Frames before auto-stop (~1.5s at 10 FPS) |
| `NUDGE_DURATION` | 0.15 | Servo move duration per step (seconds) |

These values need calibration on the actual Pi + camera setup.

## API Endpoints

All under `/servo/track`.

### POST /servo/track — Start tracking

```json
// Request
{
  "bbox": [200, 150, 80, 100],  // [x, y, w, h] in pixels on 640x480 frame
  "target": "water bottle"       // human-readable label (optional)
}

// Response
{
  "status": "ok",
  "tracking": true,
  "target": "water bottle",
  "bbox": [200, 150, 80, 100]
}
```

### DELETE /servo/track — Stop tracking

```json
// Response
{"status": "ok", "tracking": false}
```

### GET /servo/track — Check status

```json
// Response
{
  "status": "ok",
  "tracking": true,
  "target": "water bottle",
  "bbox": [210, 155, 78, 98]  // updated bbox from last frame
}
```

### PUT /servo/track — Re-initialize bbox

Used when LLM re-detects the object after tracker loses it.

```json
// Request
{
  "bbox": [250, 160, 75, 95],
  "target": "water bottle"
}
```

## End-to-End Flow

### Happy path

```
1. User: "Lumi, follow the water bottle"
2. OpenClaw agent:
   a. Call /camera/snapshot → get frame
   b. Send frame to LLM: "Find the water bottle, return bounding box as [x, y, w, h]"
   c. LLM returns: [200, 150, 80, 100]
   d. Call POST /servo/track {"bbox": [200,150,80,100], "target": "water bottle"}
3. TrackerService follows the bottle in real-time
4. User: "OK stop" → agent calls DELETE /servo/track
```

### Re-detect on lost

```
1. TrackerService loses target (MAX_LOST_FRAMES reached) → tracking stops
2. Agent can:
   a. Notify user: "I lost the bottle"
   b. Or auto re-detect: snapshot → LLM → new bbox → POST /servo/track
```

### Re-detect while tracking (PUT)

```
1. Tracking active but confidence drifting
2. Agent takes snapshot → LLM → new bbox → PUT /servo/track
3. Tracker re-initializes without stopping the session
```

## OpenCV Tracker Selection

**Primary: CSRT** (Channel and Spatial Reliability Tracker)
- Good accuracy, handles partial occlusion
- ~20-30ms/frame on Pi 5
- Requires `opencv-contrib-python`

**Fallback: KCF** (Kernelized Correlation Filters)
- Faster but less accurate
- Available in base `opencv-python`
- Auto-selected if CSRT is not available

## Dependencies

- `opencv-python>=4.8.0` (already in `pyproject.toml`)
- For CSRT: need `opencv-contrib-python` (replace `opencv-python` in pyproject.toml)
- No additional ML models needed

## Interaction with Other Systems

| System | During tracking | After tracking |
|--------|----------------|----------------|
| Servo idle animation | Suppressed (`_hold_mode`) | Resumed |
| Sensing (face, motion) | Continues — shares camera | Continues |
| Emotion animations | Blocked by hold mode | Resumed |
| Camera freeze (snapshot) | Tracker uses `last_frame`, unaffected | N/A |
| TTS | Continues normally | Continues normally |

## Calibration Guide

After deploying to Pi:

1. **Test static target**: Place object at frame center. Start tracking. Object should stay centered — servo should not move.

2. **Test offset**: Place object at frame edge. Servo should nudge toward it. If too slow → increase `DEG_PER_PX_*`. If overshooting → decrease.

3. **Test movement**: Slowly move object. Servo should follow smoothly. If jerky → increase `NUDGE_DURATION`. If laggy → decrease `NUDGE_DURATION` or increase `TRACK_FPS`.

4. **Test yaw direction**: Move object right in frame. Servo should turn right. If inverted → flip sign in `_nudge_servo` (`yaw_deg = dx * DEG_PER_PX_YAW` instead of `-dx`).

5. **Test pitch direction**: Move object down. Servo pitch should tilt down. Same sign check.

## Future Improvements

- **Smooth PID control** instead of proportional-only nudge
- **Predictive tracking** — anticipate movement direction when object leaves frame edge
- **Multi-object** — track multiple objects, switch between them
- **Confidence threshold** — use tracker confidence score to trigger re-detect before full loss
- **Frame-rate adaptive** — reduce TRACK_FPS when CPU is high, increase when load is low
