"""YOLO12-based person detector for action recognition preprocessing.

Detects person bounding boxes in a frame and exposes ``detect_largest_crop``
to extract the crop of the largest person for downstream action recognition.
"""

import logging
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

logger = logging.getLogger(__name__)

# COCO class index for "person"
_PERSON_CLASS_ID = 0


@dataclass
class _PersonDetection:
    """Internal bounding box for a detected person."""

    bbox_xyxy: tuple[int, int, int, int]
    confidence: float
    area: int


class PersonDetector:
    """YOLO12-based person detector.

    Loads an ultralytics YOLO model once and runs inference to locate people
    in BGR frames.  Rate-limiting is handled by the caller
    (``HumanActionRecognizerSession.update``), so this class runs on every
    frame it receives.

    Usage::

        detector = PersonDetector()
        detector.start()
        crop = detector.detect_largest_crop(frame)   # ndarray or None
    """

    def __init__(
        self,
        model_name: str = "yolo12x.pt",
        threshold: float = 0.4,
    ):
        """
        Args:
            model_name: Ultralytics model identifier, e.g. ``"yolo12x.pt"``.
            threshold:  Minimum detection confidence to keep.
        """
        self._model_name = model_name
        self._threshold = threshold

        self._model = None
        self._running: bool = False

    def start(self) -> None:
        """Load the YOLO model weights (blocking)."""
        from ultralytics import YOLO  # type: ignore[import]

        logger.info("[PersonDetector] Loading YOLO model '%s'", self._model_name)
        self._model = YOLO(self._model_name)
        self._running = True
        logger.info("[PersonDetector] Model ready")

    def stop(self) -> None:
        self._running = False

    def is_ready(self) -> bool:
        return self._running and self._model is not None

    def detect(self, frame: npt.NDArray[np.uint8]) -> list[_PersonDetection]:
        """Run person detection on *frame* and return all person detections."""
        try:
            results = self._model(  # type: ignore[misc]
                frame,
                classes=[_PERSON_CLASS_ID],
                conf=self._threshold,
                verbose=False,
            )
            detections: list[_PersonDetection] = []
            for r in results:
                if r.boxes is None or len(r.boxes) == 0:
                    continue
                for box in r.boxes:
                    x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
                    conf = float(box.conf[0])
                    area = max(0, x2 - x1) * max(0, y2 - y1)
                    detections.append(
                        _PersonDetection(
                            bbox_xyxy=(x1, y1, x2, y2),
                            confidence=conf,
                            area=area,
                        )
                    )
            return detections
        except Exception:
            logger.exception("[PersonDetector] Inference error")
            return []

    def detect_largest_crop(
        self,
        frame: npt.NDArray[np.uint8],
    ) -> npt.NDArray[np.uint8] | None:
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
