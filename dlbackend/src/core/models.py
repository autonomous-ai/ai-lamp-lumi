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


class ActionFrameRequest(BaseModel):
    type: Literal["frame"] = "frame"
    task: Literal["action"] = "action"
    frame_b64: str


class ActionConfigRequest(BaseModel):
    type: Literal["config"] = "config"
    task: Literal["action"] = "action"
    whitelist: list[str] | None = None
    threshold: float = 0.3


class ActionHeartBeatRequest(BaseModel):
    type: Literal["heartbeat"] = "heartbeat"
    task: Literal["action"] = "action"


ActionRequest = Annotated[
    Annotated[ActionFrameRequest, Tag("frame")]
    | Annotated[ActionConfigRequest, Tag("config")]
    | Annotated[ActionHeartBeatRequest, Tag("heartbeat")],
    Discriminator("type"),
]


class ActionDetection(BaseModel):
    class_name: str
    conf: float


class ActionResponse(BaseModel):
    """Single human action analysis result."""

    detected_classes: list[ActionDetection]


# --- Emotion analysis ---


class EmotionFrameRequest(BaseModel):
    type: Literal["frame"] = "frame"
    task: Literal["emotion"] = "emotion"
    frame_b64: str


class EmotionConfigRequest(BaseModel):
    type: Literal["config"] = "config"
    task: Literal["emotion"] = "emotion"
    threshold: float = 0.5


class EmotionHeartBeatRequest(BaseModel):
    type: Literal["heartbeat"] = "heartbeat"
    task: Literal["emotion"] = "emotion"


EmotionRequest = Annotated[
    Annotated[EmotionFrameRequest, Tag("frame")]
    | Annotated[EmotionConfigRequest, Tag("config")]
    | Annotated[EmotionHeartBeatRequest, Tag("heartbeat")],
    Discriminator("type"),
]


class EmotionDetection(BaseModel):
    """Single face emotion detection result."""

    emotion: str
    confidence: float
    face_confidence: float
    bbox: list[int]
    valence: float | None = None
    arousal: float | None = None


class EmotionResponse(BaseModel):
    """Emotion analysis response."""

    detections: list[EmotionDetection]


class EmotionRecognizeRequest(BaseModel):
    """HTTP request for single-image emotion recognition."""

    image_b64: str
    threshold: float = 0.5


class EmotionRecognizeResponse(BaseModel):
    """HTTP response for single-image emotion recognition."""

    detections: list[EmotionDetection]
