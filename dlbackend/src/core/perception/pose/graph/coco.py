"""COCO 17-joint skeleton graph."""

from enum import IntEnum

from .base import SkeletonGraph


class COCOJoint(IntEnum):
    NOSE = 0
    L_EYE = 1
    R_EYE = 2
    L_EAR = 3
    R_EAR = 4
    L_SHOULDER = 5
    R_SHOULDER = 6
    L_ELBOW = 7
    R_ELBOW = 8
    L_WRIST = 9
    R_WRIST = 10
    L_HIP = 11
    R_HIP = 12
    L_KNEE = 13
    R_KNEE = 14
    L_ANKLE = 15
    R_ANKLE = 16


class COCOSkeleton(SkeletonGraph):
    """COCO 17-joint skeleton (RTMPose output order)."""

    JOINT_NAMES: dict[int, str] = {j.value: j.name for j in COCOJoint}

    EDGES: list[tuple[int, int]] = [
        (COCOJoint.L_ANKLE, COCOJoint.L_KNEE),
        (COCOJoint.L_KNEE, COCOJoint.L_HIP),
        (COCOJoint.R_ANKLE, COCOJoint.R_KNEE),
        (COCOJoint.R_KNEE, COCOJoint.R_HIP),
        (COCOJoint.L_HIP, COCOJoint.R_HIP),
        (COCOJoint.L_SHOULDER, COCOJoint.L_HIP),
        (COCOJoint.R_SHOULDER, COCOJoint.R_HIP),
        (COCOJoint.L_SHOULDER, COCOJoint.R_SHOULDER),
        (COCOJoint.L_SHOULDER, COCOJoint.L_ELBOW),
        (COCOJoint.R_SHOULDER, COCOJoint.R_ELBOW),
        (COCOJoint.L_ELBOW, COCOJoint.L_WRIST),
        (COCOJoint.R_ELBOW, COCOJoint.R_WRIST),
        (COCOJoint.L_EYE, COCOJoint.R_EYE),
        (COCOJoint.NOSE, COCOJoint.L_EYE),
        (COCOJoint.NOSE, COCOJoint.R_EYE),
        (COCOJoint.L_EYE, COCOJoint.L_EAR),
        (COCOJoint.R_EYE, COCOJoint.R_EAR),
        (COCOJoint.L_EAR, COCOJoint.L_SHOULDER),
        (COCOJoint.R_EAR, COCOJoint.R_SHOULDER),
    ]

    @property
    def joint_names(self) -> dict[int, str]:
        return self.JOINT_NAMES

    @property
    def edges(self) -> list[tuple[int, int]]:
        return self.EDGES
