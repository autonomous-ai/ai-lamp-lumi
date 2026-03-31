from abc import ABC, abstractmethod
from typing import Callable

import numpy as np
import numpy.typing as npt


class Perception(ABC):
    """Base class for a single camera-frame perception check."""

    def __init__(self, send_event: Callable):
        self._send_event = send_event

    @abstractmethod
    def check(self, frame: npt.NDArray[np.uint8]) -> None:
        """Run detection on a single frame."""
