"""Abstract base class for person detectors."""

import logging
from abc import ABC, abstractmethod

import cv2

from core.models import PersonDetection

logger = logging.getLogger(__name__)


class PersonDetector(ABC):
    """Base interface for person detectors.

    Subclasses implement ``start``, ``stop``, ``is_ready``, and ``detect``.
    ``detect_largest_crop`` is provided by the base class.
    """

    def __init__(self, min_area_ratio: float = 0.0):
        self._min_area_ratio: float = min_area_ratio

    @property
    def min_area_ratio(self) -> float:
        return self._min_area_ratio

    @min_area_ratio.setter
    def min_area_ratio(self, value: float) -> None:
        self._min_area_ratio = value

    @abstractmethod
    def start(self) -> None:
        """Load model weights (blocking)."""

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def is_ready(self) -> bool: ...

    @abstractmethod
    def detect(self, frame: cv2.typing.MatLike) -> list[PersonDetection]:
        """Run person detection on *frame* and return all detections."""

    def detect_largest_crop(
        self,
        frame: cv2.typing.MatLike,
    ) -> cv2.typing.MatLike | None:
        """Return a crop of the largest detected person in *frame*.

        Skips persons whose area is below ``min_area_ratio`` of the frame.
        Returns ``None`` when no qualifying person is found.
        """
        detections = self.detect(frame)
        if not detections:
            return None

        h, w = frame.shape[:2]
        frame_area = h * w

        # Filter out persons too small relative to frame
        if self._min_area_ratio > 0 and frame_area > 0:
            detections = [d for d in detections if d.area / frame_area >= self._min_area_ratio]
            if not detections:
                return None

        largest = max(detections, key=lambda d: d.area)
        x1, y1, x2, y2 = largest.bbox_xyxy

        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        if x2 <= x1 or y2 <= y1:
            return None

        crop = frame[y1:y2, x1:x2]
        return crop if crop.size > 0 else None
