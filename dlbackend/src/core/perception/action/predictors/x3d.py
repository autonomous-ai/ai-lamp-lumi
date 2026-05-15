"""X3D action recognizer model."""

from pathlib import Path

import numpy as np
import numpy.typing as npt

from core.perception.action.constants import RESOURCES_DIR
from core.perception.action.predictors.base import HumanActionRecognizer


class X3DModel(HumanActionRecognizer):
    """X3D ONNX model for action recognition."""

    DEFAULT_MODEL_PATH: Path | None = RESOURCES_DIR / "x3d_m_16x5x1_int8.onnx"
    DEFAULT_CLASSES_PATH: Path = RESOURCES_DIR / "kinect_classes.txt"
    DEFAULT_WHITELIST_PATH: Path | None = RESOURCES_DIR / "white_list.txt"

    DEFAULT_MAX_FRAMES: int = 16
    DEFAULT_FRAME_SIZE: tuple[int, int] = (256, 256)

    MEAN: npt.NDArray[np.float32] = np.array([114.75, 114.75, 114.75], dtype=np.float32)
    STD: npt.NDArray[np.float32] = np.array([57.38, 57.38, 57.38], dtype=np.float32)
