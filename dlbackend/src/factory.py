"""Shared predictor singletons and perception builders.

Predictors are created once and shared across perceptions.
Perceptions are built using shared predictors.
"""

import logging
from pathlib import Path

from config import settings
from core.models.action import ActionPerceptionSessionConfig
from core.models.emotion import EmotionPerceptionSessionConfig
from core.perception.action.perception import ActionPerception
from core.perception.action.predictors.base import HumanActionRecognizer
from core.perception.action.utils import create_recognizer
from core.perception.emotion.perception import EmotionPerception
from core.perception.emotion.predictors.base import EmotionRecognizer
from core.perception.emotion.utils import create_emotion_recognizer
from core.perception.face.predictors.base import FaceDetector
from core.perception.face.utils import create_face_detector
from core.perception.person.predictors import PersonDetector
from core.perception.person.utils import create_person_detector
from core.models.pose import PosePerceptionSessionConfig
from core.perception.pose.perception import PosePerception
from core.perception.pose.utils import create_ergo_assessor, create_estimator_2d, create_lifter_3d

logger: logging.Logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared predictor singletons
# ---------------------------------------------------------------------------

_person_detector: PersonDetector | None = None
_face_detector: FaceDetector | None = None
_action_recognizer: HumanActionRecognizer | None = None
_emotion_recognizer: EmotionRecognizer | None = None


def get_or_build_person_detector() -> PersonDetector | None:
    global _person_detector
    if _person_detector is not None:
        return _person_detector
    if not settings.person_detector.enabled:
        return None

    _person_detector = create_person_detector(
        model_name=settings.person_detector.model,
        model_path=settings.person_detector.model_name,
        threshold=settings.person_detector.confidence_threshold,
        bbox_expand_scale=settings.person_detector.bbox_expand_scale,
    )
    _person_detector.start()
    logger.info(
        "Person detector ready (%s: %s)",
        settings.person_detector.model,
        settings.person_detector.model_name,
    )
    return _person_detector


def get_or_build_face_detector() -> FaceDetector:
    global _face_detector
    if _face_detector is not None:
        return _face_detector

    from core.enums.face import FaceDetectorEnum

    _face_detector = create_face_detector(model_name=FaceDetectorEnum.YUNET)
    _face_detector.start()
    logger.info("Face detector ready")
    return _face_detector


def get_or_build_action_recognizer() -> HumanActionRecognizer:
    global _action_recognizer
    if _action_recognizer is not None:
        return _action_recognizer

    action_ckpt: Path | None = Path(settings.action.ckpt_path) if settings.action.ckpt_path else None
    action_frame_size: tuple[int, int] | None = None
    if settings.action.w is not None and settings.action.h is not None:
        action_frame_size = (settings.action.h, settings.action.w)

    _action_recognizer = create_recognizer(
        model_name=settings.action.model,
        model_path=action_ckpt,
        max_frames=settings.action.max_frames,
        frame_size=action_frame_size,
    )
    _action_recognizer.start()
    logger.info("Action recognizer ready (%s)", settings.action.model)
    return _action_recognizer


def get_or_build_emotion_recognizer() -> EmotionRecognizer:
    global _emotion_recognizer
    if _emotion_recognizer is not None:
        return _emotion_recognizer

    emotion_ckpt: Path | None = Path(settings.emotion.ckpt_path) if settings.emotion.ckpt_path else None
    _emotion_recognizer = create_emotion_recognizer(
        model_name=settings.emotion.model,
        model_path=emotion_ckpt,
    )
    _emotion_recognizer.start()
    logger.info("Emotion recognizer ready (%s)", settings.emotion.model)
    return _emotion_recognizer


# ---------------------------------------------------------------------------
# Perception builders (use shared predictors)
# ---------------------------------------------------------------------------


def build_action_perception() -> ActionPerception:
    """Create the ActionPerception using shared predictors."""
    action_recognizer: HumanActionRecognizer = get_or_build_action_recognizer()
    person_detector: PersonDetector | None = get_or_build_person_detector()

    default_config: ActionPerceptionSessionConfig = ActionPerceptionSessionConfig()
    if settings.action.frame_interval is not None:
        default_config.frame_interval = settings.action.frame_interval
    if settings.action.confidence_threshold is not None:
        default_config.threshold = settings.action.confidence_threshold

    return ActionPerception(
        action_recognizer=action_recognizer,
        person_detector=person_detector,
        default_config=default_config,
    )


def build_emotion_perception() -> EmotionPerception:
    """Create the EmotionPerception using shared predictors."""
    emotion_recognizer: EmotionRecognizer = get_or_build_emotion_recognizer()
    face_detector: FaceDetector = get_or_build_face_detector()

    default_config: EmotionPerceptionSessionConfig | None = None
    if settings.emotion.confidence_threshold is not None or settings.emotion.frame_interval is not None:
        default_config = EmotionPerceptionSessionConfig(
            confidence_threshold=settings.emotion.confidence_threshold or 0.5,
            frame_interval=settings.emotion.frame_interval or 1.0,
        )

    return EmotionPerception(
        emotion_recognizer=emotion_recognizer,
        face_detector=face_detector,
        default_config=default_config,
    )


def build_pose_perception() -> PosePerception:
    """Create the PosePerception using shared predictors."""
    pose_ckpt: Path | None = Path(settings.pose.ckpt_path) if settings.pose.ckpt_path else None
    estimator_2d = create_estimator_2d(settings.pose.model, pose_ckpt)

    lifter_3d = None
    if settings.pose.lifter_3d is not None:
        lifter_3d_ckpt: Path | None = (
            Path(settings.pose.lifter_3d_ckpt_path) if settings.pose.lifter_3d_ckpt_path else None
        )
        lifter_3d_input_size: tuple[int, int] | None = None
        if settings.pose.lifter_3d_frame_w is not None and settings.pose.lifter_3d_frame_h is not None:
            lifter_3d_input_size = (settings.pose.lifter_3d_frame_w, settings.pose.lifter_3d_frame_h)
        lifter_3d = create_lifter_3d(settings.pose.lifter_3d, lifter_3d_ckpt, lifter_3d_input_size)

    ergo_assessor = None
    if settings.pose.ergo_assessor is not None:
        ergo_assessor = create_ergo_assessor(
            settings.pose.ergo_assessor,
            confidence_threshold=settings.pose.ergo_confidence_threshold,
        )

    default_config: PosePerceptionSessionConfig = PosePerceptionSessionConfig()
    if settings.pose.confidence_threshold_2d is not None:
        default_config.confidence_threshold_2d = settings.pose.confidence_threshold_2d
    if settings.pose.min_valid_keypoints is not None:
        default_config.min_valid_keypoints = settings.pose.min_valid_keypoints

    return PosePerception(
        estimator_2d=estimator_2d,
        lifter_3d=lifter_3d,
        ergo_assessor=ergo_assessor,
        default_config=default_config,
    )
