"""X3D video action recognition-based human action recognizer.

Buffers frames at a configurable interval and runs them through an
X3D ONNX model to classify actions from 400 Kinetics action classes.

The ONNX model is loaded once via X3DModel, and each WebSocket connection
creates a lightweight X3DActionRecognizer that shares the model but
maintains its own frame buffer, whitelist, and timing state.
"""

import logging
from pathlib import Path
from typing import Self, override

import numpy as np
import numpy.typing as npt

from config import settings
from core.actionanalysis.base import HumanActionRecognizerModel, HumanActionRecognizerSession
from core.actionanalysis.constants import RESOURCES_DIR

logger = logging.getLogger(__name__)


class X3DModel(HumanActionRecognizerModel):
    """Shared X3D ONNX model. Loaded once, used by all recognizer sessions."""

    DEFAULT_MODEL: Path | None = RESOURCES_DIR / "x3d_m_16x5x1_int8.onnx"
    DEFAULT_CLASSES_PATH: Path = RESOURCES_DIR / "kinect_classes.txt"
    DEFAULT_WHITELIST_PATH: Path | None = RESOURCES_DIR / "white_list.txt"

    MEAN: npt.NDArray[np.float32] = np.array([114.75, 114.75, 114.75], dtype=np.float32)
    STD: npt.NDArray[np.float32] = np.array([57.38, 57.38, 57.38], dtype=np.float32)

    def __init__(
        self,
        model_path: Path | None = None,
        max_frames: int = settings.x3d.max_frames,
        frame_size: tuple[int, int] = settings.x3d.frame_size,
    ):
        super().__init__(model_path, max_frames, frame_size)

    @override
    def create_session(
        self,
        threshold: float = settings.x3d.confidence_threshold,
        frame_interval: float = settings.x3d.frame_interval,
    ) -> HumanActionRecognizerSession[Self]:
        return HumanActionRecognizerSession(
            model=self,
            threshold=threshold,
            frame_interval=frame_interval,
        )
