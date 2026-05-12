"""RTMPose 2D pose estimator (ONNX, SimCC decoding).

Runs a single top-down pose estimation pass on a full frame.
Returns COCO 17-joint keypoints with confidence scores.

Input: BGR frame of any size — resized internally to 192x256.
Output: Pose2D with COCO keypoints in original pixel coordinates.
"""

import logging
from pathlib import Path

import numpy as np
import numpy.typing as npt

from core.enums.pose import GraphEnum

from .base import PoseEstimator2D

logger = logging.getLogger(__name__)

RESOURCES_DIR = Path(__file__).parent / "resources"


class RTMPose2D(PoseEstimator2D):
    """RTMPose ONNX 2D pose estimator using SimCC coordinate decoding."""

    GRAPH_TYPE: GraphEnum = GraphEnum.COCO
    DEFAULT_MODEL: Path = RESOURCES_DIR / "rtmpose-m.onnx"

    DEFAULT_FRAME_SIZE: tuple[int, int] = (192, 256)

    INPUT_MEAN: npt.NDArray[np.float32] = np.array([123.675, 116.28, 103.53], dtype=np.float32)
    INPUT_STD: npt.NDArray[np.float32] = np.array([58.395, 57.12, 57.375], dtype=np.float32)
