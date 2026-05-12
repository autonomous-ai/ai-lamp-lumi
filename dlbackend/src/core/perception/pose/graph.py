"""Skeleton graph definitions and format conversions."""

import numpy as np
import numpy.typing as npt

# COCO 17-joint skeleton connectivity (RTMPose output order).
COCO_SKELETON: list[tuple[int, int]] = [
    (15, 13), (13, 11), (16, 14), (14, 12),
    (11, 12), (5, 11), (6, 12), (5, 6),
    (5, 7), (6, 8), (7, 9), (8, 10),
    (1, 2), (0, 1), (0, 2), (1, 3), (2, 4), (3, 5), (4, 6),
]

# COCO 17-joint -> H36M 17-joint index mapping.
# Joints that map directly from COCO to H36M:
_COCO_TO_H36M_DIRECT = {
    1: 11,   # Left Hip       <- COCO Left Hip
    2: 13,   # Left Knee      <- COCO Left Knee
    3: 15,   # Left Ankle     <- COCO Left Ankle
    4: 12,   # Right Hip      <- COCO Right Hip
    5: 14,   # Right Knee     <- COCO Right Knee
    6: 16,   # Right Ankle    <- COCO Right Ankle
    9: 0,    # Neck/Nose      <- COCO Nose
    11: 6,   # Right Shoulder <- COCO Right Shoulder
    12: 8,   # Right Elbow    <- COCO Right Elbow
    13: 10,  # Right Hand     <- COCO Right Wrist
    14: 5,   # Left Shoulder  <- COCO Left Shoulder
    15: 7,   # Left Elbow     <- COCO Left Elbow
    16: 9,   # Left Hand      <- COCO Left Wrist
}


def coco_to_h36m(
    keypoints: npt.NDArray[np.float32],
    scores: npt.NDArray[np.float32],
) -> tuple[npt.NDArray[np.float32], npt.NDArray[np.float32]]:
    """Convert COCO 17-joint keypoints to H36M 17-joint format.

    Args:
        keypoints: (N, 17, 2) array of COCO keypoints (x, y).
        scores:    (N, 17) array of COCO confidence scores.

    Returns:
        h36m_kps:    (N, 17, 2) array in H36M joint order.
        h36m_scores: (N, 17) array of scores in H36M joint order.
    """
    N = keypoints.shape[0]
    h36m_kps = np.zeros((N, 17, 2), dtype=np.float32)
    h36m_scores = np.zeros((N, 17), dtype=np.float32)

    # Direct mappings
    for h36m_idx, coco_idx in _COCO_TO_H36M_DIRECT.items():
        h36m_kps[:, h36m_idx] = keypoints[:, coco_idx]
        h36m_scores[:, h36m_idx] = scores[:, coco_idx]

    # Interpolated joints
    # 0: Bottom torso (pelvis) = midpoint(COCO Left Hip 11, COCO Right Hip 12)
    h36m_kps[:, 0] = (keypoints[:, 11] + keypoints[:, 12]) / 2
    h36m_scores[:, 0] = np.minimum(scores[:, 11], scores[:, 12])

    # 8: Upper torso (thorax) = midpoint(COCO Left Shoulder 5, COCO Right Shoulder 6)
    h36m_kps[:, 8] = (keypoints[:, 5] + keypoints[:, 6]) / 2
    h36m_scores[:, 8] = np.minimum(scores[:, 5], scores[:, 6])

    # 7: Center torso (spine) = midpoint(pelvis, thorax)
    h36m_kps[:, 7] = (h36m_kps[:, 0] + h36m_kps[:, 8]) / 2
    h36m_scores[:, 7] = np.minimum(h36m_scores[:, 0], h36m_scores[:, 8])

    # 10: Center head = midpoint(COCO Left Ear 3, COCO Right Ear 4)
    h36m_kps[:, 10] = (keypoints[:, 3] + keypoints[:, 4]) / 2
    h36m_scores[:, 10] = np.minimum(scores[:, 3], scores[:, 4])

    return h36m_kps, h36m_scores
