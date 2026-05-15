"""TCPFormer 3D pose lifter."""

from pathlib import Path

from core.enums.pose import GraphEnum
from core.perception.pose.constants import RESOURCES_DIR

from .base import PoseEstimator3DLifting


class TCPFormer3D(PoseEstimator3DLifting):
    """TCPFormer ONNX 3D pose lifter (H36M, 243 frames)."""

    GRAPH_TYPE: GraphEnum = GraphEnum.H36M

    DEFAULT_MODEL_PATH: Path | None = RESOURCES_DIR / "tcpformer_h36m_243.onnx"
    DEFAULT_N_FRAMES: int = 243
    DEFAULT_INPUT_SIZE: tuple[int, int] = (1920, 1080)
