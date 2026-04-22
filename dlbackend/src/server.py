"""FastAPI server for VideoMAE human action recognition.

Usage:
    python server.py                    # default 0.0.0.0:8000
    python server.py --port 9000        # custom port
    python server.py --host 127.0.0.1   # localhost only
"""

import argparse
import base64
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
import numpy as np
import uvicorn
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Security,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.security import APIKeyHeader
from pydantic import TypeAdapter, ValidationError

from config import settings
from core.action.base import HumanActionRecognizerModel
from core.action.enums import HumanActionRecognizerEnum
from core.action.uniformerv2 import UniformerV2Model
from core.action.videomae import VideoMAEModel
from core.action.x3d import X3DModel
from core.emotion.emotion import EmotionModel
from core.models import (
    ActionConfigRequest,
    ActionFrameRequest,
    ActionHeartBeatRequest,
    ActionRequest,
    EmotionConfigRequest,
    EmotionFrameRequest,
    EmotionHeartBeatRequest,
    EmotionRecognizeRequest,
    EmotionRecognizeResponse,
    EmotionRequest,
)
from protocols.htpp import audio_recognizer as audio_recognizer_protocol
from protocols.htpp.audio_recognizer import router as audio_recognizer_router

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(api_key_header)):
    """Validate the X-API-Key header against DL_API_KEY."""
    if not settings.dl_api_key:
        return
    if not api_key or not secrets.compare_digest(api_key, settings.dl_api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

action_model: HumanActionRecognizerModel | None = None
emotion_model: EmotionModel | None = None
action_request_adapter = TypeAdapter(ActionRequest)
emotion_request_adapter = TypeAdapter(EmotionRequest)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load models at startup."""
    global action_model

    logger.info("Loading VideoMAE action model...")
    try:
        if settings.action_recognition_ckpt_path is not None:
            action_ckpt_path = Path(settings.action_recognition_ckpt_path)
        else:
            action_ckpt_path = None

        if settings.action_recognition_model == HumanActionRecognizerEnum.VIDEOMAE:
            action_model = VideoMAEModel(action_ckpt_path)
        elif settings.action_recognition_model == HumanActionRecognizerEnum.UNIFORMERV2:
            action_model = UniformerV2Model(action_ckpt_path)
        elif settings.action_recognition_model == HumanActionRecognizerEnum.X3D:
            action_model = X3DModel(action_ckpt_path)

        if action_model is not None:
            action_model.start()
            logger.info("[%s] action model ready", settings.action_recognition_model)
    except Exception as e:
        logger.warning(
            "Failed to load %s action model due to %s", settings.action_recognition_model, e
        )

    global emotion_model
    logger.info("Loading emotion model...")
    try:
        if settings.emotion_recognition_ckpt_path is not None:
            emotion_ckpt_path = Path(settings.emotion_recognition_ckpt_path)
        else:
            emotion_ckpt_path = None

        emotion_model = EmotionModel(fer_path=emotion_ckpt_path)
        emotion_model.start()
        logger.info("Emotion model ready")
    except Exception as e:
        logger.warning("Failed to load emotion model: %s", e)

    logger.info("Loading audio recognizer...")
    try:
        audio_recognizer_protocol._get_audio_recognizer()
        logger.info("Audio recognizer ready")
    except Exception as e:
        logger.warning("Failed to load audio recognizer: %s", e)

    yield

    if action_model is not None:
        action_model.stop()
    if emotion_model is not None:
        emotion_model.stop()
    logger.info("Shutting down DL backend")


app = FastAPI(title="DL Backend", lifespan=lifespan)
router = APIRouter(prefix="/api/dl", dependencies=[Depends(verify_api_key)])
ws_router = APIRouter(prefix="/api/dl")


def decode_image(image_b64: str) -> np.ndarray:
    """Decode a base64-encoded JPEG/PNG image to a BGR numpy array."""
    try:
        img_bytes = base64.b64decode(image_b64)
        img_array = np.frombuffer(img_bytes, dtype=np.uint8)
        image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("cv2.imdecode returned None")
        return image
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to decode image: {e}")


@ws_router.websocket("/action-analysis/ws")
async def action_analysis_ws(websocket: WebSocket):
    """WebSocket endpoint for streaming action recognition.

    Accepts JSON messages with a "type" field:
    - {"type": "frame", "frame_b64": "<base64>"} — feed a frame
    - {"type": "config", "whitelist": ["action1", ...]} — update whitelist
    - {"type": "config", "whitelist": null} — reset to default whitelist

    API key is validated from the X-API-Key header on connect.
    """
    if settings.dl_api_key:
        api_key = websocket.headers.get("x-api-key", "")
        if not api_key or not secrets.compare_digest(api_key, settings.dl_api_key):
            await websocket.close(code=1008, reason="Invalid or missing API key")
            return

    await websocket.accept()

    if action_model is None or not action_model.is_ready():
        await websocket.close(code=1011, reason="Action model not loaded")
        return

    try:
        action_recognizer = action_model.create_session()
        while True:
            raw = await websocket.receive_text()
            try:
                req = action_request_adapter.validate_json(raw)
            except ValidationError as e:
                await websocket.send_json({"error": e.errors()})
                continue

            match req:
                case ActionFrameRequest():
                    frame = decode_image(req.frame_b64)
                    result = action_recognizer.update(frame)
                    if result is not None:
                        await websocket.send_json(result.model_dump())

                case ActionConfigRequest():
                    action_recognizer.set_config(req.whitelist, req.threshold)
                    await websocket.send_json({"status": "config_updated"})

                case ActionHeartBeatRequest():
                    await websocket.send_json({"status": "ok"})

                case _:
                    pass

    except WebSocketDisconnect:
        logger.info("Action analysis WebSocket disconnected")


@ws_router.websocket("/emotion-analysis/ws")
async def emotion_analysis_ws(websocket: WebSocket):
    """WebSocket endpoint for streaming emotion recognition.

    Accepts JSON messages with a "type" field:
    - {"type": "frame", "task": "emotion", "frame_b64": "<base64>"} — feed a frame
    - {"type": "config", "task": "emotion", "threshold": 0.5} — update threshold

    API key is validated from the X-API-Key header on connect.
    """
    if settings.dl_api_key:
        api_key = websocket.headers.get("x-api-key", "")
        if not api_key or not secrets.compare_digest(api_key, settings.dl_api_key):
            await websocket.close(code=1008, reason="Invalid or missing API key")
            return

    await websocket.accept()

    if emotion_model is None or not emotion_model.is_ready():
        await websocket.close(code=1011, reason="Emotion model not loaded")
        return

    try:
        session = emotion_model.create_session()
        while True:
            raw = await websocket.receive_text()
            try:
                req = emotion_request_adapter.validate_json(raw)
            except ValidationError as e:
                await websocket.send_json({"error": e.errors()})
                continue

            match req:
                case EmotionFrameRequest():
                    frame = decode_image(req.frame_b64)
                    result = session.update(frame)
                    if result is not None:
                        await websocket.send_json(result.model_dump())

                case EmotionConfigRequest():
                    session.set_config(req.threshold)
                    await websocket.send_json({"status": "config_updated"})

                case EmotionHeartBeatRequest():
                    await websocket.send_json({"status": "ok"})

                case _:
                    pass

    except WebSocketDisconnect:
        logger.info("Emotion analysis WebSocket disconnected")


@router.post("/emotion-recognize", response_model=EmotionRecognizeResponse)
async def emotion_recognize(req: EmotionRecognizeRequest):
    """Single-shot emotion recognition from a base64-encoded image.

    Detects faces, classifies emotion for each, returns detections above threshold.
    """
    if emotion_model is None or not emotion_model.is_ready():
        raise HTTPException(status_code=503, detail="Emotion model not loaded")

    frame = decode_image(req.image_b64)
    detections = emotion_model.detect(frame)
    filtered = [d for d in detections if d.confidence >= req.threshold]
    return EmotionRecognizeResponse(detections=filtered)


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "action_model": action_model is not None and action_model.is_ready(),
        "emotion_model": emotion_model is not None and emotion_model.is_ready(),
    }


app.include_router(router)
app.include_router(ws_router)
app.include_router(
    audio_recognizer_router, prefix="/api/dl", dependencies=[Depends(verify_api_key)]
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="DL Backend Server")
    _ = parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    _ = parser.add_argument("--port", type=int, default=8001, help="Bind port (default: 8001)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    logger.info(f"Starting DL backend on {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)
