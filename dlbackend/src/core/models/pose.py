from typing import Annotated, Literal, NamedTuple

from pydantic import BaseModel, Discriminator, Tag

from core.enums.pose import GraphEnum


class Point2D(NamedTuple):
    x: float
    y: float


class Point3D(NamedTuple):
    x: float
    y: float
    z: float


class Pose2D(BaseModel):
    graph_type: GraphEnum
    joints: list[Point2D]
    confs: list[float]


class Pose3D(BaseModel):
    graph_type: GraphEnum
    joints: list[Point3D]
    confs: list[float]


# -- HTTP request/response --


class PoseEstimateRequest(BaseModel):
    """HTTP request for single-image pose estimation."""

    image_b64: str


class PoseEstimateResponse(BaseModel):
    """HTTP response for single-image pose estimation."""

    pose_2d: Pose2D
    pose_3d: Pose3D | None = None


# -- WebSocket messages --


class PoseFrameRequest(BaseModel):
    type: Literal["frame"] = "frame"
    task: Literal["pose"] = "pose"
    frame_b64: str


class PoseConfigRequest(BaseModel):
    type: Literal["config"] = "config"
    task: Literal["pose"] = "pose"
    frame_interval: float | None = None


class PoseHeartBeatRequest(BaseModel):
    type: Literal["heartbeat"] = "heartbeat"
    task: Literal["pose"] = "pose"


PoseRequest = Annotated[
    Annotated[PoseFrameRequest, Tag("frame")]
    | Annotated[PoseConfigRequest, Tag("config")]
    | Annotated[PoseHeartBeatRequest, Tag("heartbeat")],
    Discriminator("type"),
]
