"""VideoMAE action recognizer model."""

from pathlib import Path

import numpy as np
import numpy.typing as npt

from core.perception.action.constants import RESOURCES_DIR
from core.perception.action.predictors.base import HumanActionRecognizer


class VideoMAEModel(HumanActionRecognizer):
    """VideoMAE ONNX model for action recognition."""

    DEFAULT_MODEL_PATH: Path | None = RESOURCES_DIR / "videomae_int8.onnx"
    DEFAULT_CLASSES_PATH: Path = RESOURCES_DIR / "kinect_classes.txt"
    DEFAULT_WHITELIST_PATH: Path | None = RESOURCES_DIR / "white_list.txt"

    DEFAULT_MAX_FRAMES: int = 16
    DEFAULT_FRAME_SIZE: tuple[int, int] = (224, 224)

    MEAN: npt.NDArray[np.float32] = np.array([123.675, 116.28, 103.53], dtype=np.float32)
    STD: npt.NDArray[np.float32] = np.array([58.395, 57.12, 57.375], dtype=np.float32)
