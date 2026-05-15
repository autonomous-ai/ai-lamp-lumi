"""Factory functions for face detectors."""

from pathlib import Path

from core.enums.face import FaceDetectorEnum
from core.perception.face.predictors.base import FaceDetector


def create_face_detector(
    model_name: FaceDetectorEnum,
    model_path: Path | None = None,
    score_threshold: float | None = None,
    nms_threshold: float | None = None,
) -> FaceDetector:
    """Instantiate the correct face detector model."""
    if model_name == FaceDetectorEnum.YUNET:
        from core.perception.face.predictors.yunet import YuNetFaceDetector as detector_cls
    else:
        msg: str = f"Unknown face detector model: {model_name}"
        raise ValueError(msg)

    return detector_cls(
        model_path=model_path,
        score_threshold=score_threshold,
        nms_threshold=nms_threshold,
    )
