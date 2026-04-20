"""Pydantic request/response schemas for the DL backend."""

from typing import Annotated, Literal

from pydantic import BaseModel, Discriminator, Tag


class DetectionRequest(BaseModel):
    """Request payload for object detection endpoints."""

    image_b64: str
    classes: list[str] | None = None


class DetectionResult(BaseModel):
    """Single detection result with bounding box in pixel coordinates."""

    class_name: str
    xywh: list[float]
    confidence: float


class ActionRecognitionRequest(BaseModel):
    """Request payload for human action analysis endpoints."""

    type: Literal["frame", "whitelist"]


class FrameRequest(ActionRecognitionRequest):
    type: Literal["frame"] = "frame"
    frame_b64: str


class ConfigRequest(ActionRecognitionRequest):
    type: Literal["config"] = "config"
    whitelist: list[str] | None = None
    threshold: float = 0.3


ActionRequest = Annotated[
    Annotated[FrameRequest, Tag("frame")] | Annotated[ConfigRequest, Tag("config")],
    Discriminator("type"),
]


class ActionResponse(BaseModel):
    """Single human action analysis result."""

    detected_classes: list[tuple[str, float]]


# --- Emotion analysis ---


class EmotionFrameRequest(BaseModel):
    type: Literal["frame"] = "frame"
    task: Literal["emotion"] = "emotion"
    frame_b64: str


class EmotionConfigRequest(BaseModel):
    type: Literal["config"] = "config"
    task: Literal["emotion"] = "emotion"
    threshold: float = 0.5


EmotionRequest = Annotated[
    Annotated[EmotionFrameRequest, Tag("frame")]
    | Annotated[EmotionConfigRequest, Tag("config")],
    Discriminator("type"),
]


class EmotionDetection(BaseModel):
    """Single face emotion detection result."""

    emotion: str
    confidence: float
    face_confidence: float
    bbox: list[int]


class EmotionResponse(BaseModel):
    """Emotion analysis response."""

    detections: list[EmotionDetection]
