from typing import Annotated, Literal

from pydantic import BaseModel, Discriminator, Tag


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
