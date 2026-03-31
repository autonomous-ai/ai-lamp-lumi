from abc import ABC, abstractmethod
from typing import Callable, Optional

import numpy as np


class Perception(ABC):
    """Base class for a single camera-frame perception check."""

    def __init__(self, send_event: Callable):
        self._send_event = send_event

    @abstractmethod
    def check(self, frame: np.ndarray) -> None:
        """Run detection on a single frame."""
