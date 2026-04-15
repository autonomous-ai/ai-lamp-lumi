"""Abstract base class for object detectors."""

from abc import ABC, abstractmethod

import numpy as np

from models import DetectionResult


class BaseDetector(ABC):
    """Base interface for all detection backends."""

    @abstractmethod
    def detect(self, image: np.ndarray, classes: list[str]) -> list[DetectionResult]:
        """Run detection on a BGR numpy image and return results.

        Args:
            image: BGR numpy array (H, W, 3).
            classes: List of class names to detect.

        Returns:
            List of DetectionResult with xywh in pixel coordinates.
        """
        ...

    @abstractmethod
    def is_ready(self) -> bool:
        """Return True if the model is loaded and ready for inference."""
        ...
