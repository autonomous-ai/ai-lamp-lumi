# DL Backend — YOLO-World & Grounding DINO

Self-contained FastAPI server for zero-shot object detection using **YOLO-World** and **Grounding DINO**. Designed as a drop-in replacement for the external detection server used by the GO2 middle layer's depth camera pipeline.

## Setup

```bash
cd dlbackend
pip install -r requirements.txt
```

> **Note:** First run will download model weights from the internet:
> - YOLO-World: `yolov8x-worldv2.pt` (~68 MB, from ultralytics)
> - Grounding DINO: `IDEA-Research/grounding-dino-tiny` (~340 MB, from HuggingFace Hub)

## Usage

```bash
python server.py                    # default 0.0.0.0:8000
python server.py --port 9000        # custom port
python server.py --host 127.0.0.1   # localhost only
```

Both models are loaded at startup. If a model fails to load (e.g. missing GPU for Grounding DINO), the other model still works — the failed endpoint returns HTTP 503.

## Endpoints

All endpoints are under the `/api/dl` prefix.

### `POST /api/dl/yoloworld`

Run YOLO-World zero-shot detection.

### `POST /api/dl/grounding-dino`

Run Grounding DINO zero-shot detection.

**Request** (same for both):
```json
{
  "image_b64": "<base64-encoded JPEG or PNG>",
  "classes": ["person", "chair", "table"]
}
```

`classes` is optional. If omitted, ~400 default classes are used (indoor, outdoor, natural, and general objects).

**Response** (same for both):
```json
[
  { "class_name": "person", "xywh": [320.5, 240.0, 80.0, 160.0], "confidence": 0.92 }
]
```

- `xywh`: bounding box as `[center_x, center_y, width, height]` in **pixel coordinates**
- `confidence`: detection confidence score

### `GET /api/dl/health`

```json
{
  "status": "ok",
  "yolo_world": true,
  "grounding_dino": true
}
```

## Configuration

Models are configured via `dlbackend/.env`:

```env
YOLO_WORLD_MODEL=yolov8x-worldv2.pt
GROUNDING_DINO_MODEL=IDEA-Research/grounding-dino-tiny
```

## Deployment on RunPod

1. Create a GPU pod with a PyTorch template
2. Upload `dlbackend/` to `/workspace/go2_middle_layer/dlbackend/`
3. Run the startup script:
   ```bash
   bash /workspace/go2_middle_layer/dlbackend/start.sh
   ```
4. Access endpoints at `https://<POD_ID>-8888.proxy.runpod.net/api/dl/health`

### Docker

```bash
cd dlbackend
docker build -t dlbackend .
docker run --gpus all -p 8888:8888 dlbackend
```

### nginx

The included `nginx.conf` proxies port 8888 to uvicorn on port 8000. This is used for RunPod deployments where you want nginx in front of uvicorn.

## Integration with GO2 Middle Layer

Update `DEFAULT_REMOTE_DETECTOR_URL` in your `.env`:

```env
# Use YOLO-World
DEFAULT_REMOTE_DETECTOR_URL=http://localhost:8000/api/dl/yoloworld

# Or use Grounding DINO
DEFAULT_REMOTE_DETECTOR_URL=http://localhost:8000/api/dl/grounding-dino

# RunPod example
DEFAULT_REMOTE_DETECTOR_URL=https://<POD_ID>-8888.proxy.runpod.net/api/dl/yoloworld
```

No code changes are needed — the response format matches what `RemoteYOLOv8Detector` expects.

## File Structure

```
dlbackend/
├── server.py              # FastAPI app with /api/dl/* endpoints
├── models.py              # Pydantic request/response schemas
├── default_classes.py     # ~400 default object classes
├── detectors/
│   ├── __init__.py
│   ├── base.py            # Abstract base detector interface
│   ├── yolo_world.py      # YOLO-World detector (ultralytics)
│   └── grounding_dino.py  # Grounding DINO detector (HF transformers)
├── .env                   # Model configuration
├── .env.example           # Example configuration
├── requirements.txt       # Dependencies
├── nginx.conf             # nginx reverse proxy config
├── Dockerfile             # Docker image (CUDA + nginx)
├── start.sh               # RunPod startup script
└── README.md              # This file
```
