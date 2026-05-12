from enum import StrEnum


class GraphEnum(StrEnum):
    COCO = "coco"
    H36M = "h36m"


class PoseEstimator2DEnum(StrEnum):
    RTMPOSE = "rtmpose"


class PoseLifter3DEnum(StrEnum):
    TCPFORMER = "tcpformer"
