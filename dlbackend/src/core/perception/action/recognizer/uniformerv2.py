"""UniformerV2 action recognizer model."""

from pathlib import Path

import numpy as np
import numpy.typing as npt

from .base import HumanActionRecognizerModel, RESOURCES_DIR


class UniformerV2Model(HumanActionRecognizerModel):
    """UniformerV2 ONNX model for action recognition."""

    DEFAULT_MODEL: Path | None = None
    DEFAULT_CLASSES_PATH: Path = RESOURCES_DIR / "kinect_classes.txt"
    DEFAULT_WHITELIST_PATH: Path | None = RESOURCES_DIR / "white_list.txt"
    DEFAULT_MAX_FRAMES: int = 8
    DEFAULT_FRAME_SIZE: tuple[int, int] = (224, 224)
    DEFAULT_FRAME_INTERVAL: float = 1.0
    DEFAULT_CONFIDENCE_THRESHOLD: float = 0.3

    MEAN: npt.NDArray[np.float32] = np.array([114.75, 114.75, 114.75], dtype=np.float32)
    STD: npt.NDArray[np.float32] = np.array([57.375, 57.375, 57.375], dtype=np.float32)

    def __init__(
        self,
        model_path: Path | None = None,
        max_frames: int = DEFAULT_MAX_FRAMES,
        frame_size: tuple[int, int] = DEFAULT_FRAME_SIZE,
    ):
        super().__init__(model_path, max_frames, frame_size)
