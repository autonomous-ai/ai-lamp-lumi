# DL Backend — Remote Action Recognition

GPU-accelerated action recognition server deployed on RunPod. LeLamp Pi streams camera frames via WebSocket, RunPod runs VideoMAE ONNX inference, returns detected human actions.

## Architecture

```
Pi (LeLamp)                    RunPod GPU
┌─────────────┐    WebSocket    ┌──────────────────┐
│ Camera 640×480│──────────────→│ nginx :8888       │
│ sensing tick │  frame_b64    │   ↓               │
│ every 2s     │               │ uvicorn :8001     │
│              │←──────────────│ VideoMAE ONNX     │
│ motion.event │  detected_    │ 16-frame buffer   │
└─────────────┘  classes       │ 400 Kinetics      │
      │                        └──────────────────┘
      │ HTTP POST
      ↓
Lumi Go :5000
      │ WebSocket
      ↓
OpenClaw Agent
```

## Data Flow

1. **Pi**: `SensingService._tick()` reads camera frame every 2s
2. **Pi**: `MotionPerception` → `RemoteMotionChecker.update()` encodes frame to base64 JPEG
3. **WebSocket**: `{"type": "frame", "frame_b64": "..."}` sent to RunPod with `X-API-Key` header
4. **RunPod**: VideoMAE ONNX model buffers 16 frames, runs inference every 1s
5. **RunPod**: Preprocesses (BGR→RGB, 224×224 center crop, ImageNet normalization), runs softmax over whitelisted actions
6. **WebSocket**: Returns `{"detected_classes": [["walking", 0.87], ["reading book", 0.42]]}` 
7. **Pi**: Buffers actions + snapshots for 10s (`MOTION_FLUSH_S`), then sends aggregated event
8. **Pi → Lumi**: `POST /api/sensing/event` with `type: "motion.activity"` or `type: "motion"`
9. **Lumi → OpenClaw**: Agent receives event, responds based on detected activity

## Key Files

### dlbackend/

| File | Purpose |
|---|---|
| `src/server.py` | FastAPI app, WebSocket endpoint `/api/dl/action-analysis/ws`, health check |
| `src/core/actionanalysis/videomae.py` | VideoMAE ONNX model — 16-frame buffer, 224×224 input, 400 Kinetics classes |
| `src/core/actionanalysis/x3d.py` | X3D ONNX model (alternative) — 256×256 input |
| `src/core/models.py` | Pydantic schemas: FrameRequest, ConfigRequest, ActionResponse |
| `src/core/default_classes.py` | ~400 object classes for YOLO-World/Grounding DINO |
| `src/core/detectors/yolo_world.py` | YOLO-World zero-shot object detection |
| `src/core/detectors/grounding_dino.py` | Grounding DINO zero-shot detection |
| `nginx.conf` | Reverse proxy :8888 → :8001, WebSocket upgrade, 120s timeout |
| `Dockerfile` | CUDA 12.4 PyTorch + nginx + uvicorn |
| `start.sh` | RunPod startup: nginx + uvicorn |

### lelamp/ (Pi side)

| File | Purpose |
|---|---|
| `service/sensing/perceptions/motion.py` | `RemoteMotionChecker` — WebSocket client, frame encoding, action buffering |
| `config.py` | `DL_BACKEND_URL`, `DL_API_KEY`, thresholds |
| `service/sensing/sensing_service.py` | Orchestrates all perceptions in `_tick()` |

## Configuration

### Pi (.env)

```env
DL_BACKEND_URL=wss://<POD_ID>-8888.proxy.runpod.net/lelamp/api/dl/action-analysis/ws
DL_API_KEY=<shared secret>
LELAMP_MOTION_ENABLED=true
```

### RunPod (.env)

```env
DL_API_KEY=<shared secret>
ACTION_RECOGNITION_MODEL=  # optional custom model path
```

### Thresholds (config.py)

| Parameter | Default | Purpose |
|---|---|---|
| `MOTION_X3D_CONFIDENCE_THRESHOLD` | 0.3 | Min action confidence score |
| `MOTION_FLUSH_S` | 10.0 | Buffer flush interval (seconds) |
| `MOTION_EVENT_COOLDOWN_S` | 360.0 | Event cooldown to avoid spam (6 min) |

## WebSocket Protocol

### Client → Server

```json
// Initial config (sent once on connect)
{"type": "config", "whitelist": ["reading", "walking", "using computer"], "threshold": 0.3}

// Frame submission (every tick)
{"type": "frame", "frame_b64": "<base64 JPEG>"}
```

### Server → Client

```json
{"detected_classes": [["using computer", 0.72], ["texting", 0.35]]}
```

## Deployment

### RunPod

```bash
# Upload dlbackend/ to pod
# SSH into pod, then:
cd /workspace/ai-lamp-openclaw/dlbackend
bash start.sh
```

### Docker

```bash
cd dlbackend
docker build -t dlbackend .
docker run --gpus all -p 8888:8888 dlbackend
```

### Health Check

```
GET https://<POD_ID>-8888.proxy.runpod.net/api/dl/health
→ {"status": "ok", "action_model": true}
```

## Event Types Produced

| Event | When | Sent to Agent |
|---|---|---|
| `motion.activity` | Person present + friend detected + actions buffered | Yes, with action list |
| `motion` | Actions detected but no known person | Yes, "someone may have entered" |

## Error Handling

- **WebSocket disconnect**: `RemoteMotionChecker` catches `ConnectionClosedError`, reconnects on next tick
- **RunPod unavailable**: `DL_BACKEND_URL` empty → `MotionPerception` not created, silently skipped
- **Model not loaded**: Server returns WebSocket close with "Model not ready"
- **Bad frame**: Server logs warning, skips frame, continues
