"""RULA-specific geometry helpers."""

import numpy as np
import numpy.typing as npt

from core.perception.pose.graph.h36m import H36MJoint
from core.utils.compute import angle_between_3d, rotate_to

# Joint name lookup for skipped-joints reporting
JOINT_NAMES: dict[int, str] = {j.value: j.name.lower() for j in H36MJoint}


def signed_flexion_angle(
    v: npt.NDArray[np.float32],
    trunk_up: npt.NDArray[np.float32],
) -> float:
    """Signed flexion angle (degrees) of *v* relative to *trunk_up*.

    Positive = forward flexion, negative = extension.
    Computed fully in 3D using the cross product to determine sign.
    """
    angle: float = angle_between_3d(v, trunk_up)
    cross: npt.NDArray[np.float32] = np.cross(trunk_up, v)
    if cross[0] > 0:
        return angle
    else:
        return -angle


def align_to_vertical(
    keypoints: npt.NDArray[np.float32],
) -> npt.NDArray[np.float32]:
    """Rotate 3D keypoints so that spine-to-thorax aligns with +Z (up)."""
    spine: npt.NDArray[np.float32] = keypoints[H36MJoint.SPINE]
    thorax: npt.NDArray[np.float32] = keypoints[H36MJoint.THORAX]
    trunk_vec: npt.NDArray[np.float32] = thorax - spine

    return rotate_to(
        keypoints,
        src_vec=trunk_vec,
        dst_vec=np.array([0.0, 0.0, 1.0], dtype=np.float32),
        center=spine,
    )
