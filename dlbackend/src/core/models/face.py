"""Internal face detection models — dataclasses for core logic."""

from dataclasses import dataclass, field
from typing import cast

import cv2.typing as cv2t
import numpy as np
import numpy.typing as npt


@dataclass
class RawFaceDetection:
    """Raw face detector output for a single frame — batched numpy arrays.

    Each array's first dimension is N (number of detected faces).
    Empty arrays (N=0) when no faces detected.
    """

    bbox_xyxy: npt.NDArray[np.float32]
    """Shape: (N, 4) — [x1, y1, x2, y2] per face."""

    confidence: npt.NDArray[np.float32]
    """Shape: (N,) — detection confidence per face."""

    area: npt.NDArray[np.float32] = field(init=False)
    """Shape: (N,) — computed from bbox."""

    def __post_init__(self) -> None:
        if self.bbox_xyxy.size == 0:
            self.area = np.zeros(0, dtype=np.float32)
            return

        if self.bbox_xyxy.shape[-1] != 4:
            msg: str = f"bbox_xyxy last dimension must be exactly 4, got {self.bbox_xyxy.shape[-1]}"
            raise ValueError(msg)

        dx: npt.NDArray[np.float32] = cast(
            npt.NDArray[np.float32], np.maximum(self.bbox_xyxy[..., 2] - self.bbox_xyxy[..., 0], 0)
        )
        dy: npt.NDArray[np.float32] = cast(
            npt.NDArray[np.float32], np.maximum(self.bbox_xyxy[..., 3] - self.bbox_xyxy[..., 1], 0)
        )
        self.area = dx * dy


@dataclass
class FaceCrop:
    """Single face crop with metadata — convenience for downstream consumers."""

    crop: cv2t.MatLike
    bbox_xyxy: list[int]  # [x1, y1, x2, y2]
    confidence: float
