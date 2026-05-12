"""VideoMAE action recognizer model."""

from pathlib import Path

import numpy as np
import numpy.typing as npt

from core.perception.action.constants import RESOURCES_DIR, VIDEOMAE_DEFAULTS

from .base import HumanActionRecognizerModel

_D = VIDEOMAE_DEFAULTS


class VideoMAEModel(HumanActionRecognizerModel):
    """VideoMAE ONNX model for action recognition."""

    DEFAULT_MODEL: Path | None = RESOURCES_DIR / "videomae_int8.onnx"
    DEFAULT_CLASSES_PATH: Path = RESOURCES_DIR / "kinect_classes.txt"
    DEFAULT_WHITELIST_PATH: Path | None = RESOURCES_DIR / "white_list.txt"

    MEAN: npt.NDArray[np.float32] = np.array([123.675, 116.28, 103.53], dtype=np.float32)
    STD: npt.NDArray[np.float32] = np.array([58.395, 57.12, 57.375], dtype=np.float32)

    DEFAULT_MAX_FRAMES: int = _D["max_frames"]
    DEFAULT_FRAME_SIZE: tuple[int, int] = _D["frame_size"]

    def __init__(
        self,
        model_path: Path | None = None,
        max_frames: int = DEFAULT_MAX_FRAMES,
        frame_size: tuple[int, int] = DEFAULT_FRAME_SIZE,
    ):
        super().__init__(model_path, max_frames, frame_size)
