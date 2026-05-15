from core.enums.person import PersonDetectorEnum
from core.perception.person.predictors.base import PersonDetector


def create_person_detector(
    model_name: PersonDetectorEnum,
    model_path: str | None = None,
    threshold: float | None = None,
    bbox_expand_scale: float | None = None,
) -> PersonDetector:
    """Instantiate the correct recognizer model."""
    if model_name == PersonDetectorEnum.YOLO:
        from core.perception.person.predictors.yolo import YOLOPersonDetector as predictor_cls
    else:
        msg = f"Unknown person detector model: {model_name}"
        raise ValueError(msg)

    return predictor_cls(model_path, threshold=threshold, bbox_expand_scale=bbox_expand_scale)
