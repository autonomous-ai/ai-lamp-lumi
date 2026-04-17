# DL Backend — Action + Audio Recognition

GPU-accelerated backend service for:
- real-time human action recognition via WebSocket (VideoMAE),
- speaker enrollment/recognition via HTTP APIs (AudioRecognizer).

LeLamp Pi streams camera frames to DL backend for action analysis, and clients can register/recognize speakers through authenticated `/api/dl/audio-recognizer/*` endpoints.

## Architecture

```
Pi (LeLamp) / Clients               DL Backend (RunPod or local)
┌──────────────────────┐            ┌──────────────────────────────┐
│ Camera 640x480       │ WebSocket  │ /api/dl/action-analysis/ws   │
│ frame_b64 every tick │──────────→ │ VideoMAE ONNX inference      │
│                      │ ←───────── │ detected_classes             │
└──────────────────────┘            └──────────────────────────────┘

┌──────────────────────┐    HTTP    ┌──────────────────────────────┐
│ App / tools          │──────────→ │ /api/dl/audio-recognizer/*   │
│ wav URL/chunks/PCM16 │            │ register/recognize/list/remove│
└──────────────────────┘            └──────────────────────────────┘
```

## Action Analysis Data Flow (WebSocket)

1. **Pi**: `SensingService._tick()` reads camera frame every 2s
2. **Pi**: `MotionPerception` → `RemoteMotionChecker.update()` encodes frame to base64 JPEG
3. **WebSocket**: `{"type": "frame", "frame_b64": "..."}` sent to RunPod with `X-API-Key` header
4. **RunPod**: VideoMAE ONNX model buffers 16 frames, runs inference every 1s
5. **RunPod**: Preprocesses (BGR→RGB, 224×224 center crop, ImageNet normalization), runs softmax over whitelisted actions
6. **WebSocket**: Returns `{"detected_classes": [["walking", 0.87], ["reading book", 0.42]]}` 
7. **Pi**: Buffers actions + snapshots for `MOTION_FLUSH_S`, then sends aggregated event
8. **Pi → Lumi**: `POST /api/sensing/event` with `type: "motion.activity"` or `type: "motion"`
9. **Lumi → OpenClaw**: Agent receives event, responds based on detected activity

## Audio Recognition Data Flow (HTTP)

1. Client calls `/api/dl/audio-recognizer/register` with one of:
   - `wav_path`/`wav_paths` (HTTP/HTTPS URLs),
   - `chunks` (`number[][]`),
   - `pcm16_b64` + `chunk_sample_rate`,
   - `multipart/form-data` wav upload.
2. Protocol layer normalizes input into audio chunks.
3. `AudioRecognizer` extracts embeddings and persists speaker vectors in JSON speaker DB.
4. Client calls `/api/dl/audio-recognizer/recognize` with supported input formats.
5. Service returns best speaker match with confidence score.

## Key Files

### dlbackend/

| File | Purpose |
|---|---|
| `src/server.py` | FastAPI app, API key guard, health check, action WS router mounting, audio API router mounting |
| `src/core/actionanalysis/videomae.py` | VideoMAE ONNX model — 16-frame buffer, 224×224 input, 400 Kinetics classes |
| `src/core/actionanalysis/x3d.py` | X3D ONNX model (alternative) — 256×256 input |
| `src/core/models.py` | Pydantic schemas: FrameRequest, ConfigRequest, ActionResponse |
| `src/protocols/htpp/audio_recognizer.py` | Audio HTTP endpoints: register / recognize / list / remove; input normalization (URL/chunks/PCM16/multipart) |
| `src/core/audio_recognition/audio_recognizer.py` | Speaker embedding service (ONNX + fbank), register/recognize/remove logic |
| `src/core/audio_recognition/speaker_db.py` | JSON-backed speaker storage (active/deleted status + metadata) |
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
# optional: audio model/db path can use service defaults if omitted
```

### Thresholds (config.py)

| Parameter | Default | Purpose |
|---|---|---|
| `MOTION_X3D_CONFIDENCE_THRESHOLD` | 0.3 | Min action confidence score |
| `MOTION_FLUSH_S` | 10.0 | Buffer flush interval (seconds) |
| `MOTION_EVENT_COOLDOWN_S` | 360.0 | Event cooldown to avoid spam (6 min) |

## Authentication

- HTTP routes under `/api/dl/*` use header `X-API-Key` when `DL_API_KEY` is set.
- WebSocket `/api/dl/action-analysis/ws` validates `X-API-Key` from WS headers on connect.
- If `DL_API_KEY` is empty, auth is effectively disabled (dev mode).

## Action WebSocket Protocol

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

## Audio HTTP APIs

Base path: `/api/dl/audio-recognizer`

### 1) Register speaker

- `POST /register`
- Required: `name`
- Accepted inputs (one of):
  - JSON `wav_path` (http/https URL only),
  - JSON `wav_paths` (URL list),
  - JSON `chunks` + `chunk_sample_rate`,
  - JSON `pcm16_b64` + `chunk_sample_rate`,
  - multipart wav upload.
- Behavior: overwrite/create speaker embedding in local speaker DB.

### 2) Recognize speaker

- `POST /recognize`
- Accepted inputs:
  - JSON `wav_path` (http/https URL only),
  - JSON `chunks` + `chunk_sample_rate`,
  - JSON `pcm16_b64` + `chunk_sample_rate`,
  - multipart wav upload.
- Response:
  - `{"name": "<best_match_or_empty>", "confidence": 0.0..1.0}`

### 3) List speakers

- `GET /speakers`
- Response includes:
  - `total`
  - `speakers`: list of `{name, embedding_dim}`

### 4) Remove speaker

- `DELETE /speakers/{speaker_name}`
- Response:
  - `{"name": "...", "removed": true|false}`

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
- **Audio multipart without file**: `422` with validation message
- **Audio URL not http/https**: validation error (local filesystem paths are rejected)
- **Audio model/dependency unavailable**: audio endpoints return `503` from protocol layer
