"""Abstract base class for person detectors."""

from abc import ABC, abstractmethod

import cv2

from core.models import PersonDetection


class PersonDetector(ABC):
    """Base interface for person detectors.

    Subclasses implement ``start``, ``stop``, ``is_ready``, and ``detect``.
    ``detect_largest_crop`` is provided by the base class.
    """

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

        Returns ``None`` when no person is found or the crop is empty.
        """
        detections = self.detect(frame)
        if not detections:
            return None

        largest = max(detections, key=lambda d: d.area)
        x1, y1, x2, y2 = largest.bbox_xyxy

        h, w = frame.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        if x2 <= x1 or y2 <= y1:
            return None

        crop = frame[y1:y2, x1:x2]
        return crop if crop.size > 0 else None
