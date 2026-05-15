"""RTMPose 2D pose estimator."""

from pathlib import Path

import numpy as np
import numpy.typing as npt

from core.enums.pose import GraphEnum
from core.perception.pose.constants import RESOURCES_DIR

from .base import PoseEstimator2D


class RTMPose2D(PoseEstimator2D):
    """RTMPose ONNX 2D pose estimator using SimCC coordinate decoding."""

    GRAPH_TYPE: GraphEnum = GraphEnum.COCO

    DEFAULT_MODEL_PATH: Path | None = RESOURCES_DIR / "rtmpose-m.onnx"
    DEFAULT_INPUT_SIZE: tuple[int, int] = (192, 256)

    INPUT_MEAN: npt.NDArray[np.float32] = np.array([123.675, 116.28, 103.53], dtype=np.float32)
    INPUT_STD: npt.NDArray[np.float32] = np.array([58.395, 57.12, 57.375], dtype=np.float32)
