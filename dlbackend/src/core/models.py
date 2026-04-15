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


class WhiteListRequest(ActionRecognitionRequest):
    type: Literal["whitelist"] = "whitelist"
    whitelist: list[str] | None = None


ActionRequest = Annotated[
    Annotated[FrameRequest, Tag("frame")] | Annotated[WhiteListRequest, Tag("whitelist")],
    Discriminator("type"),
]


class ActionResponse(BaseModel):
    """Single human action analysis result."""

    detected_classes: list[tuple[str, float]]
