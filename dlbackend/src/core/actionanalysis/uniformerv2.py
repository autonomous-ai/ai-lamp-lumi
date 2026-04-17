"""VideoMAE video action recognition-based human action recognizer.

Buffers frames at a configurable interval and runs them through a
VideoMAE ONNX model to classify actions from 400 Kinetics action classes.

The ONNX model is loaded once via VideoMAEModel, and each WebSocket connection
creates a lightweight VideoMAEActionRecognizer that shares the model but
maintains its own frame buffer, whitelist, and timing state.
"""

import logging
from pathlib import Path
from typing import Self
from typing_extensions import override

import numpy as np
import numpy.typing as npt

from config import settings
from core.actionanalysis.base import HumanActionRecognizerModel, HumanActionRecognizerSession
from core.actionanalysis.constants import RESOURCES_DIR

logger = logging.getLogger(__name__)


class UniformerV2Model(HumanActionRecognizerModel):
    """Shared VideoMAE ONNX model. Loaded once, used by all recognizer sessions."""

    DEFAULT_MODEL: Path | None = None
    DEFAULT_CLASSES_PATH: Path = RESOURCES_DIR / "kinect_classes.txt"
    DEFAULT_WHITELIST_PATH: Path | None = RESOURCES_DIR / "white_list.txt"

    MEAN: npt.NDArray[np.float32] = np.array([114.75, 114.75, 114.75], dtype=np.float32)
    STD: npt.NDArray[np.float32] = np.array([57.375, 57.375, 57.375], dtype=np.float32)

    def __init__(
        self,
        model_path: Path | None = None,
        max_frames: int = settings.uniformerv2.max_frames,
        frame_size: tuple[int, int] = settings.uniformerv2.frame_size,
    ):
        super().__init__(model_path, max_frames, frame_size)

    @override
    def create_session(
        self,
        threshold: float = settings.uniformerv2.confidence_threshold,
        frame_interval: float = settings.uniformerv2.frame_interval,
    ) -> HumanActionRecognizerSession[Self]:
        return HumanActionRecognizerSession(
            model=self,
            threshold=threshold,
            frame_interval=frame_interval,
        )
