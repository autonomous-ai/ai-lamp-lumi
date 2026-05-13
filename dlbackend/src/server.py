"""DL Backend — FastAPI server.

Thin shell: app creation, lifespan (model loading), router registration.

Usage:
    python server.py                    # default 0.0.0.0:8001
    python server.py --port 9000        # custom port
    python server.py --host 127.0.0.1   # localhost only
"""

import argparse
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.security import APIKeyHeader

from config import settings
from core.action.enums import HumanActionRecognizerEnum
from core.action.uniformerv2 import UniformerV2Model
from core.action.videomae import VideoMAEModel
from core.action.x3d import X3DModel
from core.emotion.emotion import EmotionModel
from core.persondetector import YOLOPersonDetector
from enums import PersonDetectorEnum
from protocols.htpp import audio_recognizer as audio_recognizer_protocol
from protocols.htpp import speech_emotion_recognizer as ser_protocol
from protocols.htpp.action import router as action_ws_router
from protocols.htpp.audio_recognizer import router as audio_recognizer_router
from protocols.htpp.emotion import http_router as emotion_http_router
from protocols.htpp.emotion import ws_router as emotion_ws_router
from protocols.htpp.health import router as health_router
from protocols.htpp.speech_emotion_recognizer import router as ser_router
from protocols.utils.state import (
    get_action_model,
    get_emotion_model,
    set_action_model,
    set_emotion_model,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# --- Auth ---

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(api_key_header)):
    """Validate the X-API-Key header against DL_API_KEY."""
    if not settings.dl_api_key:
        return
    if not api_key or not secrets.compare_digest(api_key, settings.dl_api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# --- Lifespan ---


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load models at startup, release on shutdown."""
    logger.info("Loading action model...")
    try:
        if settings.action_recognition_ckpt_path is not None:
            action_ckpt_path = Path(settings.action_recognition_ckpt_path)
        else:
            action_ckpt_path = None

        person_detector = None
        if settings.person_detector.enabled:
            if settings.person_detector.model == PersonDetectorEnum.YOLO:
                person_detector = YOLOPersonDetector()
            else:
                raise ValueError(f"Unknown person detector: {settings.person_detector.model}")
            person_detector.start()
            logger.info(
                "Person detector ready (%s: %s)",
                settings.person_detector.model,
                settings.person_detector.model_name,
            )

        if settings.action_recognition_model == HumanActionRecognizerEnum.VIDEOMAE:
            set_action_model(VideoMAEModel(action_ckpt_path, person_detector=person_detector))
        elif settings.action_recognition_model == HumanActionRecognizerEnum.UNIFORMERV2:
            set_action_model(UniformerV2Model(action_ckpt_path, person_detector=person_detector))
        elif settings.action_recognition_model == HumanActionRecognizerEnum.X3D:
            set_action_model(X3DModel(action_ckpt_path, person_detector=person_detector))

        action_model = get_action_model()
        if action_model is not None:
            action_model.start()
            logger.info("[%s] action model ready", settings.action_recognition_model)
    except Exception as e:
        logger.warning(
            "Failed to load %s action model due to %s", settings.action_recognition_model, e
        )

    logger.info("Loading emotion model...")
    try:
        if settings.emotion_recognition_ckpt_path is not None:
            emotion_ckpt_path = Path(settings.emotion_recognition_ckpt_path)
        else:
            emotion_ckpt_path = None

        emotion_model = EmotionModel(emotion_model_path=emotion_ckpt_path)
        emotion_model.start()
        set_emotion_model(emotion_model)
        logger.info("Emotion model ready")
    except Exception as e:
        logger.warning("Failed to load emotion model: %s", e)

    logger.info("Loading audio recognizer...")
    try:
        audio_recognizer_protocol._get_audio_recognizer()
        logger.info("Audio recognizer ready")
    except Exception as e:
        logger.warning("Failed to load audio recognizer: %s", e)

    logger.info("Loading speech emotion recognizer...")
    try:
        ser_protocol._get_recognizer()
        logger.info("Speech emotion recognizer ready")
    except Exception as e:
        logger.warning("Failed to load speech emotion recognizer: %s", e)

    yield

    logger.info("Shutting down DL backend...")
    action_model = get_action_model()
    if action_model is not None:
        action_model.stop()
    emotion_model = get_emotion_model()
    if emotion_model is not None:
        emotion_model.stop()
    logger.info("DL backend shutdown complete")


# --- App + Routers ---

app = FastAPI(title="DL Backend", lifespan=lifespan)


app.include_router(action_ws_router, prefix="/api/dl")
app.include_router(emotion_ws_router, prefix="/api/dl")
app.include_router(emotion_http_router, prefix="/api/dl", dependencies=[Depends(verify_api_key)])
app.include_router(health_router, prefix="/api/dl", dependencies=[Depends(verify_api_key)])
app.include_router(
    audio_recognizer_router, prefix="/api/dl", dependencies=[Depends(verify_api_key)]
)
app.include_router(ser_router, prefix="/api/dl", dependencies=[Depends(verify_api_key)])


# --- CLI ---


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DL Backend Server")
    _ = parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    _ = parser.add_argument("--port", type=int, default=8001, help="Bind port (default: 8001)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    logger.info(f"Starting DL backend on {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)
