from typing import NamedTuple

from pydantic import BaseModel

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
