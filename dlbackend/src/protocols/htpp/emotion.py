"""Emotion analysis WebSocket + HTTP endpoints."""

import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

from core.models.emotion import (
    EmotionConfigRequest,
    EmotionFrameRequest,
    EmotionHeartBeatRequest,
    EmotionRecognizeRequest,
    EmotionRecognizeResponse,
    EmotionRequest,
)
from protocols.utils.common import decode_image, verify_ws_api_key
from protocols.utils.state import get_emotion_model

logger = logging.getLogger(__name__)

# WS router does manual API key validation; HTTP router uses Depends(verify_api_key) at registration.
ws_router = APIRouter()
http_router = APIRouter()
_request_adapter = TypeAdapter(EmotionRequest)


@ws_router.websocket("/emotion-analysis/ws")
async def emotion_analysis_ws(websocket: WebSocket):
    """WebSocket endpoint for streaming emotion recognition.

    Accepts JSON messages with a "type" field:
    - {"type": "frame", "task": "emotion", "frame_b64": "<base64>"} — feed a frame
    - {"type": "config", "task": "emotion", "threshold": 0.5} — update threshold

    API key is validated from the X-API-Key header on connect.
    """
    if not await verify_ws_api_key(websocket):
        return

    await websocket.accept()

    emotion_model = get_emotion_model()
    if emotion_model is None or not emotion_model.is_ready():
        await websocket.close(code=1011, reason="Emotion model not loaded")
        return

    try:
        session = emotion_model.create_session()
        while True:
            raw = await websocket.receive_text()
            try:
                req = _request_adapter.validate_json(raw)
            except ValidationError as e:
                await websocket.send_json({"error": e.errors()})
                continue

            try:
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
                        logger.warning("Unknown emotion WS message type: %s", raw[:200])
            except Exception as e:
                logger.exception("Error processing emotion WS message")
                await websocket.send_json({"error": str(e)})

    except WebSocketDisconnect:
        logger.info("Emotion analysis WebSocket disconnected")


@http_router.post("/emotion-recognize", response_model=EmotionRecognizeResponse)
async def emotion_recognize(req: EmotionRecognizeRequest):
    """Single-shot emotion recognition from a base64-encoded image.

    Detects faces, classifies emotion for each, returns detections above threshold.
    """
    emotion_model = get_emotion_model()
    if emotion_model is None or not emotion_model.is_ready():
        raise HTTPException(status_code=503, detail="Emotion model not loaded")

    frame = decode_image(req.image_b64)
    detections = emotion_model.detect_single_face(frame)
    filtered = [d for d in detections if d.confidence >= req.threshold]
    logger.info(
        "[Emotion] Detected %s",
        ", ".join([f"{f.emotion} ({f.confidence})" for f in filtered]),
    )
    return EmotionRecognizeResponse(detections=filtered)
