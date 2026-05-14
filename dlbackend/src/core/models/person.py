from dataclasses import dataclass, field
from typing import cast

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel


@dataclass
class RawPersonDetection:
    """Single person detection bounding box."""

    bbox_xyxy: npt.NDArray[np.float32]
    confidence: npt.NDArray[np.float32]
    area: npt.NDArray[np.float32] = field(init=False)

    def __post_init__(self):
        if self.bbox_xyxy.shape[-1] != 4:
            raise ValueError("bbox_xyxy last dimension must be exactly 4")

        if self.bbox_xyxy.size == 0:
            raise ValueError("bbox_xyxy must not be empty")

        dx = cast(
            npt.NDArray[np.float32], np.maximum(self.bbox_xyxy[..., 2] - self.bbox_xyxy[..., 0], 0)
        )
        dy = cast(
            npt.NDArray[np.float32], np.maximum(self.bbox_xyxy[..., 3] - self.bbox_xyxy[..., 1], 0)
        )
        self.area = dx * dy


class PersonDetection(BaseModel):
    """Single person detection bounding box."""

    bbox_xyxy: tuple[int, int, int, int]
    confidence: float
    area: int
