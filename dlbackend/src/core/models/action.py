from typing import Annotated, Literal

from pydantic import BaseModel, Discriminator, Tag


class ActionFrameRequest(BaseModel):
    type: Literal["frame"] = "frame"
    task: Literal["action"] = "action"
    frame_b64: str


class ActionConfigRequest(BaseModel):
    type: Literal["config"] = "config"
    task: Literal["action"] = "action"
    whitelist: list[str] | None = None
    threshold: float = 0.3
    person_detection_enabled: bool | None = None  # toggle person detector on/off for this session
    person_min_area_ratio: float | None = (
        None  # override person detector min area ratio for this session
    )


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
