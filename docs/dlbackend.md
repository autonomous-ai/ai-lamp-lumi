# DL Backend — Action + Emotion + Audio Recognition

GPU-accelerated backend service for:
- real-time human action recognition via WebSocket (X3D / UniformerV2 / VideoMAE),
- facial emotion recognition via WebSocket or HTTP (POSTER V2 / EmoNet),
- optional person detection for action recognition preprocessing (YOLO12),
- speaker enrollment/recognition via HTTP APIs (AudioRecognizer).

LeLamp Pi streams camera frames to DL backend for action and emotion analysis, and clients can register/recognize speakers through authenticated `/api/dl/audio-recognizer/*` endpoints.

## Architecture

```
Pi (LeLamp) / Clients               DL Backend (RunPod or local, nginx :8888 → uvicorn :8001)
┌──────────────────────┐            ┌──────────────────────────────────────────────┐
│ Camera 640x480       │ WebSocket  │ /api/dl/action-analysis/ws                   │
│ frame_b64 every tick │──────────→ │ Action model (X3D/UniformerV2/VideoMAE) ONNX │
│                      │ ←───────── │ detected_classes                             │
├──────────────────────┤            ├──────────────────────────────────────────────┤
│ Face crop (base64)   │   HTTP     │ /api/dl/emotion-recognize                    │
│ from InsightFace     │──────────→ │ Emotion model (POSTER V2 / EmoNet) ONNX     │
│                      │ ←───────── │ emotion + confidence (+ valence/arousal)     │
├──────────────────────┤            ├──────────────────────────────────────────────┤
│ Face crop (base64)   │ WebSocket  │ /api/dl/emotion-analysis/ws                  │
│ streaming            │──────────→ │ Same emotion model, per-session state        │
│                      │ ←───────── │ detections                                   │
├──────────────────────┤            ├──────────────────────────────────────────────┤
│ App / tools          │   HTTP     │ /api/dl/audio-recognizer/*                   │
│ wav URL/chunks/PCM16 │──────────→ │ register/recognize/list/remove               │
└──────────────────────┘            └──────────────────────────────────────────────┘
```

## Models

### Action Recognition

Selectable via `ACTION_RECOGNITION_MODEL` env var:

| Model | Enum | ONNX file | Input | Default frames |
|---|---|---|---|---|
| **X3D** (default) | `x3d` | `x3d_m_16x5x1_int8.onnx` | 256×256 | 16 |
| **UniformerV2** | `uniformerv2` | User-provided | 224×224 | 8 |
| **VideoMAE** | `videomae` | `videomae_int8.onnx` | 224×224 | 16 |

All classify from **Kinetics-400** action classes, filtered by a configurable whitelist (`white_list.txt`).

### Emotion Recognition

Selectable via `EMOTION_RECOGNITION_MODEL` env var:

| Model | Enum | ONNX file | Input | Output |
|---|---|---|---|---|
| **POSTER V2** (default) | `posterv2` | `posterv2_7cls.onnx` | 224×224, ImageNet norm | 7 emotions (RAF-DB: Surprise, Fear, Disgust, Happy, Sad, Anger, Neutral) |
| **EmoNet** | `emonet` | `emonet_8.onnx` | 256×256 | 8 emotions + valence + arousal |

Face detection for emotion uses **YuNet** (`face_detection_yunet_2023mar.onnx`) to crop faces before classification. This is separate from LeLamp's InsightFace (used for identity recognition on-device).

### Person Detection (Optional)

When enabled, YOLO12 detects the largest person in each frame and crops it before feeding to the action recognition model. Helps when the camera is moving (servo ego-motion).

| Setting | Default |
|---|---|
| Model | `yolo12x.pt` (Ultralytics) |
| Enabled | `false` |
| Confidence threshold | 0.4 |
| Bbox expand scale | 2.0 (expands crop around detected person) |

### Speaker Recognition

Selectable via `AUDIO_RECOGNIZER_ENGINE` env var:

| Model | Enum | ONNX file | Embedding dim |
|---|---|---|---|
| **WeSpeaker ResNet34** (default) | `resnet34` | `voxceleb_resnet34_LM.onnx` | 256 |
| ECAPA-TDNN 1024 | `ecapa-tdnn1024` | `voxceleb_ECAPA1024_LM.onnx` | — |
| CAM++ | `campplus` | `voxceleb_CAM++.onnx` | — |

## API Endpoints

### Action Analysis (WebSocket)

```
WS /api/dl/action-analysis/ws
```

**Client → Server:**
```json
{"type": "config", "whitelist": ["reading", "walking", "using computer"], "threshold": 0.3}
{"type": "frame", "frame_b64": "<base64 JPEG>"}
```

**Server → Client:**
```json
{"detected_classes": [["using computer", 0.72], ["texting", 0.35]]}
```

### Emotion Analysis (WebSocket)

```
WS /api/dl/emotion-analysis/ws
```

**Client → Server:**
```json
{"type": "frame", "task": "emotion", "frame_b64": "<base64 JPEG>"}
{"type": "config", "task": "emotion", "threshold": 0.5}
```

**Server → Client:**
```json
{"detections": [{"emotion": "Happy", "confidence": 0.82, "face_confidence": 0.95, "bbox": [x,y,w,h], "valence": null, "arousal": null}]}
```

### Emotion Recognition (HTTP)

```
POST /api/dl/emotion-recognize
```

**Request:**
```json
{"image_b64": "<base64 face crop>", "threshold": 0.5}
```

**Response:**
```json
{"detections": [{"emotion": "Happy", "confidence": 0.82, "face_confidence": 1.0, "bbox": [0,0,W,H]}]}
```

> **Note:** LeLamp currently uses the HTTP endpoint (not WebSocket) for emotion. Face crops are produced by InsightFace on-device, then sent to dlbackend for emotion classification only.

### Audio Recognition (HTTP)

Base path: `/api/dl/audio-recognizer`

| Method | Path | Description |
|---|---|---|
| POST | `/register` | Enroll speaker (wav_path/chunks/pcm16_b64/multipart) |
| POST | `/recognize` | Identify speaker from audio |
| GET | `/speakers` | List enrolled speakers |
| DELETE | `/speakers/{name}` | Remove speaker |

### Health Check

```
GET /api/dl/health
→ {"status": "ok", "action_model": true, "emotion_model": true}
```

## Data Flows

### Action Analysis

1. **Pi**: `SensingService._tick()` reads camera frame every 2s
2. **Pi**: `MotionPerception` → `RemoteMotionChecker.update()` encodes frame to base64 JPEG
3. **WebSocket**: `{"type": "frame", "frame_b64": "..."}` sent to RunPod with `X-API-Key` header
4. **RunPod**: Action model buffers frames, runs inference every `frame_interval`
5. **RunPod**: If person detector enabled → crop largest person first, then classify
6. **RunPod**: Preprocesses (BGR→RGB, center crop, normalization), runs softmax over whitelisted actions
7. **WebSocket**: Returns `{"detected_classes": [["walking", 0.87], ["reading book", 0.42]]}`
8. **Pi**: Buffers actions + snapshots for `MOTION_FLUSH_S`, then sends aggregated event
9. **Pi → Lumi**: `POST /api/sensing/event` with `type: "motion.activity"` or `type: "motion"`
10. **Lumi → OpenClaw**: Agent receives event, responds based on detected activity

### Emotion Analysis

1. **Pi**: `SensingService._tick()` detects faces via InsightFace (on-device)
2. **Pi**: `EmotionPerception` crops face, encodes to base64 JPEG
3. **HTTP**: `POST /api/dl/emotion-recognize` with face crop + threshold
4. **RunPod**: YuNet re-detects face in crop (optional), POSTER V2 / EmoNet classifies emotion
5. **HTTP**: Returns `{"detections": [{"emotion": "Happy", "confidence": 0.82}]}`
6. **Pi**: Buffers, applies polarity-bucket dedup, fires `emotion.detected` event
7. **Pi → Lumi**: `POST /api/sensing/event` with `type: "emotion.detected"`

## Configuration

### RunPod (.env)

```env
DL_API_KEY=<shared secret>

# Action recognition: x3d | uniformerv2 | videomae
ACTION_RECOGNITION_MODEL=x3d
# ACTION_RECOGNITION_CKPT_PATH=/path/to/model.onnx

# Emotion recognition: posterv2 | emonet
EMOTION_RECOGNITION_MODEL=posterv2
# EMOTION_RECOGNITION_CKPT_PATH=/path/to/posterv2_7cls.onnx

# Per-model overrides (nested via __ delimiter)
# X3D__CONFIDENCE_THRESHOLD=0.3
# X3D__MAX_FRAMES=16
# X3D__W=256
# X3D__H=256
# UNIFORMERV2__CONFIDENCE_THRESHOLD=0.3
# UNIFORMERV2__MAX_FRAMES=8
# EMOTION__CONFIDENCE_THRESHOLD=0.5
# EMOTION__FRAME_INTERVAL=1.0

# Person detector (crops person before action recognition)
# PERSON_DETECTOR__ENABLED=false
# PERSON_DETECTOR__MODEL_NAME=yolo12x.pt
# PERSON_DETECTOR__CONFIDENCE_THRESHOLD=0.4
# PERSON_DETECTOR__BBOX_EXPAND_SCALE=2.0

# Audio recognition: resnet34 | ecapa-tdnn1024 | campplus
AUDIO_RECOGNIZER_ENGINE=resnet34
```

### Pi (.env)

```env
DL_BACKEND_URL=wss://<POD_ID>-8888.proxy.runpod.net/lelamp/api/dl/action-analysis/ws
DL_API_KEY=<shared secret>
LELAMP_MOTION_ENABLED=true
```

### Thresholds (lelamp/config.py)

| Parameter | Default | Purpose |
|---|---|---|
| `MOTION_CONFIDENCE_THRESHOLD` | 0.3 | Min action confidence score |
| `MOTION_FLUSH_S` | 10.0 | Buffer flush interval (seconds) |
| `MOTION_EVENT_COOLDOWN_S` | 360.0 | Event cooldown to avoid spam (6 min) |
| `EMOTION_CONFIDENCE_THRESHOLD` | configurable | Min emotion confidence to fire event |

## Key Files

### dlbackend/

| File | Purpose |
|---|---|
| `src/server.py` | FastAPI app, model loading, WS + HTTP routes, health check |
| `src/config.py` | Pydantic settings: model selection, per-model configs, person detector |
| `src/enums/action_recognizer.py` | `HumanActionRecognizerEnum` (x3d/uniformerv2/videomae) |
| `src/enums/emotion_recognizer.py` | `EmotionRecognizerEnum` (posterv2/emonet) |
| `src/core/action/base.py` | Base action recognizer model + session (ONNX, frame buffer, predict) |
| `src/core/action/x3d.py` | X3D model (256×256, 16 frames) |
| `src/core/action/uniformerv2.py` | UniformerV2 model (224×224, 8 frames) |
| `src/core/action/videomae.py` | VideoMAE model (224×224, 16 frames) |
| `src/core/action/person_detector.py` | YOLO12 person detector (optional preprocessing) |
| `src/core/emotion/emotion.py` | EmotionModel — factory selects PosterV2 or EmoNet based on config |
| `src/core/emotion/posterv2.py` | POSTER V2 classifier (224×224, 7 RAF-DB classes, ImageNet norm) |
| `src/core/emotion/emonet.py` | EmoNet classifier (256×256, 8 classes + valence/arousal) |
| `src/core/faces/yunet.py` | YuNet face detector (for emotion pipeline face cropping) |
| `src/core/audio_recognition/audio_recognizer.py` | Speaker embedding (WeSpeaker ResNet34 / ECAPA / CAM++) |
| `src/core/audio_recognition/speaker_db.py` | JSON-backed speaker storage |
| `src/core/models.py` | Pydantic schemas: ActionResponse, EmotionDetection, EmotionResponse |
| `nginx.conf` | Reverse proxy :8888 → :8001, `/lelamp/` prefix strip, WS upgrade |
| `Dockerfile` | CUDA 12.4 PyTorch + nginx + uvicorn |
| `start.sh` | RunPod startup: nginx + uvicorn |

### lelamp/ (Pi side)

| File | Purpose |
|---|---|
| `service/sensing/perceptions/processors/motion.py` | `RemoteMotionChecker` — WS client, frame encoding, action buffering |
| `service/sensing/perceptions/processors/emotion.py` | `RemoteEmotionChecker` — HTTP client, face crop → emotion classify |
| `config.py` | `DL_BACKEND_URL`, `DL_API_KEY`, thresholds |
| `service/sensing/sensing_service.py` | Orchestrates all perceptions in `_tick()` |

## Nginx Routing

```
:8888 (public)
├── /              → 127.0.0.1:8000
└── /lelamp/       → 127.0.0.1:8001  (strips /lelamp/ prefix, WS upgrade enabled)
```

All LeLamp traffic goes through `/lelamp/` → port 8001 (FastAPI). Routes are prefixed `/api/dl/` on the FastAPI side.

Full URL examples:
```
https://<POD>-8888.proxy.runpod.net/lelamp/api/dl/action-analysis/ws
https://<POD>-8888.proxy.runpod.net/lelamp/api/dl/emotion-recognize
https://<POD>-8888.proxy.runpod.net/lelamp/api/dl/emotion-analysis/ws
https://<POD>-8888.proxy.runpod.net/lelamp/api/dl/audio-recognizer/register
https://<POD>-8888.proxy.runpod.net/lelamp/api/dl/health
```

## Authentication

- HTTP routes under `/api/dl/*` use header `X-API-Key` when `DL_API_KEY` is set.
- WebSocket endpoints validate `X-API-Key` from WS headers on connect.
- If `DL_API_KEY` is empty, auth is effectively disabled (dev mode).

## Deployment

### RunPod

```bash
cd /workspace/ai-lamp-openclaw/dlbackend
bash start.sh
```

### Docker

```bash
cd dlbackend
docker build -t dlbackend .
docker run --gpus all -p 8888:8888 dlbackend
```

## Event Types Produced

| Event | When | Sent to Agent |
|---|---|---|
| `motion.activity` | Person present + actions detected | Yes, with action list |
| `motion` | Large motion, no known person | Yes, "someone may have entered" |
| `emotion.detected` | Face emotion above confidence threshold | Yes, with emotion label + confidence |

## Error Handling

- **WebSocket disconnect**: `RemoteMotionChecker` catches `ConnectionClosedError`, reconnects on next tick
- **RunPod unavailable**: `DL_BACKEND_URL` empty → perception not created, silently skipped
- **Model not loaded**: Server returns WebSocket close with "Model not ready" / HTTP 503
- **Bad frame**: Server logs warning, skips frame, continues
- **Audio multipart without file**: `422` with validation message
- **Audio URL not http/https**: validation error (local filesystem paths are rejected)
- **Audio model/dependency unavailable**: audio endpoints return `503` from protocol layer
