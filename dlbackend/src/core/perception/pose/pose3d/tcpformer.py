"""TCPFormer 3D pose lifter (ONNX).

Lifts 2D H36M keypoints to 3D using a temporal convolutional model.
Maintains a rolling buffer of 243 frames. Returns the latest 3D
prediction once the buffer is full.

Input keypoints must be in H36M 17-joint format -- use
:func:`core.perception.pose.graph.coco_to_h36m` to convert from COCO first.
"""

import logging
from pathlib import Path

from core.enums.pose import GraphEnum

from .base import PoseEstimator3DLifting

logger = logging.getLogger(__name__)

RESOURCES_DIR = Path(__file__).parent / "resources"


class TCPFormer3D(PoseEstimator3DLifting):
    """TCPFormer ONNX 3D pose lifter.

    Buffers DEFAULT_N_FRAMES frames of normalized 2D H36M keypoints,
    then runs temporal inference to produce 3D joint positions.
    """

    GRAPH_TYPE: GraphEnum = GraphEnum.H36M

    DEFAULT_MODEL: Path = RESOURCES_DIR / "tcpformer_h36m_243.onnx"

    DEFAULT_N_FRAMES: int = 243
    DEFAULT_FRAME_SIZE: tuple[int, int] = (1920, 1080)
