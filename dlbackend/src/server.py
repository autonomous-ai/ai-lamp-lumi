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
from core.enums import PersonDetectorEnum
from core.perception.action.action import ActionAnalysis
from core.perception.action.utils import create_recognizer
from core.perception.emotion.emotion import EmotionAnalysis
from core.perception.persondetector import YOLOPersonDetector
from core.perception.pose.pose import PoseAnalysis
from core.perception.pose.utils import create_ergo_assessor, create_estimator_2d, create_lifter_3d
from protocols.htpp import audio_recognizer as audio_recognizer_protocol
from protocols.htpp import speech_emotion_recognizer as ser_protocol
from protocols.htpp.action import router as action_ws_router
from protocols.htpp.audio_recognizer import router as audio_recognizer_router
from protocols.htpp.emotion import http_router as emotion_http_router
from protocols.htpp.emotion import ws_router as emotion_ws_router
from protocols.htpp.health import router as health_router
from protocols.htpp.pose import http_router as pose_http_router
from protocols.htpp.pose import ws_router as pose_ws_router
from protocols.htpp.speech_emotion_recognizer import router as ser_router
from protocols.utils.state import (
    get_action_model,
    get_emotion_model,
    get_pose_model,
    set_action_model,
    set_emotion_model,
    set_pose_model,
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


# --- Model builders ---


def _build_person_detector():
    """Create and start the person detector from config, or return None."""
    if not settings.person_detector.enabled:
        return None

    if settings.person_detector.model == PersonDetectorEnum.YOLO:
        detector = YOLOPersonDetector(
            model_name=settings.person_detector.model_name,
            threshold=settings.person_detector.confidence_threshold,
            bbox_expand_scale=settings.person_detector.bbox_expand_scale,
            min_area_ratio=settings.person_detector.min_area_ratio,
        )
    else:
        raise ValueError(f"Unknown person detector: {settings.person_detector.model}")

    detector.start()
    logger.info(
        "Person detector ready (%s: %s)",
        settings.person_detector.model,
        settings.person_detector.model_name,
    )
    return detector


def _build_action_analysis() -> ActionAnalysis:
    """Create the ActionAnalysis from config settings."""
    action_ckpt = Path(settings.action.ckpt_path) if settings.action.ckpt_path else None
    person_detector = _build_person_detector()

    action_frame_size = None
    if settings.action.w is not None and settings.action.h is not None:
        action_frame_size = (settings.action.h, settings.action.w)

    recognizer = create_recognizer(
        model_name=settings.action.model,
        model_path=action_ckpt,
        max_frames=settings.action.max_frames,
        frame_size=action_frame_size,
    )
    return ActionAnalysis(
        recognizer=recognizer,
        person_detector=person_detector,
        confidence_threshold=settings.action.confidence_threshold,
        frame_interval=settings.action.frame_interval,
    )


def _build_emotion_analysis() -> EmotionAnalysis:
    """Create the EmotionAnalysis from config settings."""
    emotion_ckpt = Path(settings.emotion.ckpt_path) if settings.emotion.ckpt_path else None

    return EmotionAnalysis(
        model_name=settings.emotion.model,
        emotion_model_path=emotion_ckpt,
        confidence_threshold=settings.emotion.confidence_threshold,
        frame_interval=settings.emotion.frame_interval,
    )


def _build_pose_analysis() -> PoseAnalysis:
    """Create the PoseAnalysis from config settings."""
    pose_ckpt = Path(settings.pose.ckpt_path) if settings.pose.ckpt_path else None
    estimator_2d = create_estimator_2d(settings.pose.model, pose_ckpt)

    lifter_3d = None
    if settings.pose.lifter_3d is not None:
        lifter_3d_ckpt = (
            Path(settings.pose.lifter_3d_ckpt_path) if settings.pose.lifter_3d_ckpt_path else None
        )
        lifter_3d_frame_size = None
        if (
            settings.pose.lifter_3d_frame_w is not None
            and settings.pose.lifter_3d_frame_h is not None
        ):
            lifter_3d_frame_size = (
                settings.pose.lifter_3d_frame_w,
                settings.pose.lifter_3d_frame_h,
            )
        lifter_3d = create_lifter_3d(settings.pose.lifter_3d, lifter_3d_ckpt, lifter_3d_frame_size)

    ergo_assessor = None
    if settings.pose.ergo_assessor is not None:
        ergo_assessor = create_ergo_assessor(
            settings.pose.ergo_assessor,
            confidence_threshold=settings.pose.ergo_confidence_threshold,
        )

    return PoseAnalysis(
        estimator_2d=estimator_2d,
        lifter_3d=lifter_3d,
        ergo_assessor=ergo_assessor,
        confidence_threshold_2d=settings.pose.confidence_threshold_2d,
        min_valid_keypoints=settings.pose.min_valid_keypoints,
    )


# --- Lifespan ---


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load models at startup, release on shutdown."""

    # -- Action model --
    if settings.action.enabled:
        logger.info("Loading action model...")
        try:
            action_model = _build_action_analysis()
            action_model.start()
            set_action_model(action_model)
            logger.info("Action model ready")
        except Exception as e:
            logger.warning("Failed to load action model: %s", e)

    # -- Emotion model --
    if settings.emotion.enabled:
        logger.info("Loading emotion model...")
        try:
            emotion_model = _build_emotion_analysis()
            emotion_model.start()
            set_emotion_model(emotion_model)
            logger.info("Emotion model ready")
        except Exception as e:
            logger.warning("Failed to load emotion model: %s", e)

    # -- Audio recognizer --
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

    # -- Pose estimator --
    if settings.pose.enabled:
        logger.info("Loading pose estimator...")
        try:
            pose_model = _build_pose_analysis()
            pose_model.start()
            set_pose_model(pose_model)
            logger.info("Pose estimator ready")
        except Exception as e:
            logger.warning("Failed to load pose estimator: %s", e)

    yield

    logger.info("Shutting down DL backend...")
    action_model = get_action_model()
    if action_model is not None:
        action_model.stop()
    emotion_model = get_emotion_model()
    if emotion_model is not None:
        emotion_model.stop()
    pose_model = get_pose_model()
    if pose_model is not None:
        pose_model.stop()
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
app.include_router(pose_ws_router, prefix="/api/dl")
app.include_router(pose_http_router, prefix="/api/dl", dependencies=[Depends(verify_api_key)])


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
