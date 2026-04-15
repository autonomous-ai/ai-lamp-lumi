"""FastAPI server for X3D human action recognition.

Usage:
    python server.py                    # default 0.0.0.0:8000
    python server.py --port 9000        # custom port
    python server.py --host 127.0.0.1   # localhost only
"""

import argparse
import base64
import logging
import os
import secrets
from contextlib import asynccontextmanager

import cv2
import numpy as np
import uvicorn
from dotenv import load_dotenv
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

from core.actionanalysis.x3d import X3DActionRecognizer
from core.models import ActionRequest, FrameRequest, WhiteListRequest

_ = load_dotenv()

DL_API_KEY = os.getenv("DL_API_KEY", "")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(api_key_header)):
    """Validate the X-API-Key header against DL_API_KEY."""
    if not DL_API_KEY:
        return
    if not api_key or not secrets.compare_digest(api_key, DL_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

action_recognizer: X3DActionRecognizer | None = None
action_request_adapter = TypeAdapter(ActionRequest)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load models at startup."""
    global action_recognizer

    logger.info("Loading X3D action recognizer...")
    try:
        action_recognizer = X3DActionRecognizer()
        logger.info("X3D action recognizer ready")
    except Exception as e:
        logger.warning(f"Failed to load X3D action recognizer: {e}")

    yield

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
    - {"type": "whitelist", "whitelist": ["action1", ...]} — update whitelist
    - {"type": "whitelist", "whitelist": null} — reset to default whitelist

    API key is validated from the X-API-Key header on connect.
    """
    if DL_API_KEY:
        api_key = websocket.headers.get("x-api-key", "")
        if not api_key or not secrets.compare_digest(api_key, DL_API_KEY):
            await websocket.close(code=1008, reason="Invalid or missing API key")
            return

    await websocket.accept()

    if action_recognizer is None or not action_recognizer.is_ready():
        await websocket.close(code=1011, reason="Action recognizer not loaded")
        return

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                req = action_request_adapter.validate_json(raw)
            except ValidationError as e:
                await websocket.send_json({"error": e.errors()})
                continue

            match req:
                case FrameRequest():
                    frame = decode_image(req.frame_b64)
                    result = action_recognizer.update(frame)
                    if result is not None:
                        await websocket.send_json(result.model_dump())

                case WhiteListRequest():
                    action_recognizer.set_whitelist(req.whitelist)
                    await websocket.send_json({"status": "whitelist_updated"})

                case _:
                    pass

    except WebSocketDisconnect:
        logger.info("Action analysis WebSocket disconnected")


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "action_recognizer": action_recognizer is not None and action_recognizer.is_ready(),
    }


app.include_router(router)
app.include_router(ws_router)


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
