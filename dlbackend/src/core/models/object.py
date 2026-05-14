from pydantic import BaseModel


class DetectionRequest(BaseModel):
    """Request payload for object detection endpoints."""

    image_b64: str
    classes: list[str] | None = None


class DetectionResult(BaseModel):
    """Single detection result with bounding box in pixel coordinates."""

    class_name: str
    xywh: list[float]
    confidence: float
