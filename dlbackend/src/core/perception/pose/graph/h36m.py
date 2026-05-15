"""Human3.6M 17-joint skeleton graph."""

from enum import IntEnum

from .base import SkeletonGraph


class H36MJoint(IntEnum):
    PELVIS = 0
    L_HIP = 1
    L_KNEE = 2
    L_FOOT = 3
    R_HIP = 4
    R_KNEE = 5
    R_FOOT = 6
    SPINE = 7
    THORAX = 8
    NECK = 9
    HEAD = 10
    L_SHOULDER = 11
    L_ELBOW = 12
    L_WRIST = 13
    R_SHOULDER = 14
    R_ELBOW = 15
    R_WRIST = 16


class H36MSkeleton(SkeletonGraph):
    """Human3.6M 17-joint skeleton."""

    JOINT_NAMES: dict[int, str] = {j.value: j.name for j in H36MJoint}

    EDGES: list[tuple[int, int]] = [
        (H36MJoint.PELVIS, H36MJoint.L_HIP),
        (H36MJoint.L_HIP, H36MJoint.L_KNEE),
        (H36MJoint.L_KNEE, H36MJoint.L_FOOT),
        (H36MJoint.PELVIS, H36MJoint.R_HIP),
        (H36MJoint.R_HIP, H36MJoint.R_KNEE),
        (H36MJoint.R_KNEE, H36MJoint.R_FOOT),
        (H36MJoint.PELVIS, H36MJoint.SPINE),
        (H36MJoint.SPINE, H36MJoint.THORAX),
        (H36MJoint.THORAX, H36MJoint.NECK),
        (H36MJoint.NECK, H36MJoint.HEAD),
        (H36MJoint.THORAX, H36MJoint.L_SHOULDER),
        (H36MJoint.L_SHOULDER, H36MJoint.L_ELBOW),
        (H36MJoint.L_ELBOW, H36MJoint.L_WRIST),
        (H36MJoint.THORAX, H36MJoint.R_SHOULDER),
        (H36MJoint.R_SHOULDER, H36MJoint.R_ELBOW),
        (H36MJoint.R_ELBOW, H36MJoint.R_WRIST),
    ]

    @property
    def joint_names(self) -> dict[int, str]:
        return self.JOINT_NAMES

    @property
    def edges(self) -> list[tuple[int, int]]:
        return self.EDGES
