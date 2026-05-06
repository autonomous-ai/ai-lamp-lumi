"""YOLO12-based person detector for action recognition preprocessing.

Detects person bounding boxes in a frame and exposes ``detect_largest_crop``
to extract the crop of the largest person for downstream action recognition.
"""

import logging
from dataclasses import dataclass

import cv2
from ultralytics.models.yolo import YOLO

from config import settings

logger = logging.getLogger(__name__)

# COCO class index for "person"
_PERSON_CLASS_ID = 0


@dataclass
class PersonDetection:
    """Internal bounding box for a detected person."""

    bbox_xyxy: tuple[int, int, int, int]
    confidence: float
    area: int


class YOLOPersonDetector:
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
        model_name: str = settings.person_detector.model_name,
        threshold: float = settings.person_detector.confidence_threshold,
        bbox_expand_scale: float = settings.person_detector.bbox_expand_scale,
    ):
        """
        Args:
            model_name: Ultralytics model identifier, e.g. ``"yolo12x.pt"``.
            threshold:  Minimum detection confidence to keep.
            bbox_expand_scale: Scale factor to expand detected bbox around center.
        """
        self._model_name: str = model_name
        self._threshold: float = threshold
        self._bbox_expand_scale: float = bbox_expand_scale

        self._model = None
        self._running: bool = False

    def start(self) -> None:
        """Load the YOLO model weights (blocking)."""

        logger.info("[%s] Loading YOLO model '%s'", self.__class__.__name__, self._model_name)
        self._model = YOLO(self._model_name)
        self._running = True

    def stop(self) -> None:
        self._model = None
        self._running = False

    def is_ready(self) -> bool:
        return self._running and self._model is not None

    def _scale_and_clamp_bbox(self, bbox: list[int], h: int, w: int, scale: float = 1.0):
        x1, y1, x2, y2 = bbox
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2

        x1 = int(max(min(cx + (x1 - cx) * scale, w - 1), 0))
        x2 = int(max(min(cx + (x2 - cx) * scale, w - 1), 0))
        y1 = int(max(min(cy + (y1 - cy) * scale, h - 1), 0))
        y2 = int(max(min(cy + (y2 - cy) * scale, h - 1), 0))
        return [x1, y1, x2, y2]

    def detect(self, frame: cv2.typing.MatLike) -> list[PersonDetection]:
        """Run person detection on *frame* and return all person detections."""
        if self._model is None:
            msg = f"{self.__class__.__name__} must be started before detection"
            raise RuntimeError(msg)

        try:
            H, W = frame.shape[:2]
            results = self._model(
                frame,
                classes=[_PERSON_CLASS_ID],
                conf=self._threshold,
                verbose=False,
            )
            detections: list[PersonDetection] = []
            for r in results:
                if r.boxes is None or len(r.boxes) == 0:
                    continue
                for box in r.boxes:
                    x1, y1, x2, y2 = self._scale_and_clamp_bbox(
                        [int(v) for v in box.xyxy[0].tolist()],
                        H,
                        W,
                        self._bbox_expand_scale,
                    )
                    conf = float(box.conf[0])
                    area = max(0, x2 - x1) * max(0, y2 - y1)
                    detections.append(
                        PersonDetection(
                            bbox_xyxy=(x1, y1, x2, y2),
                            confidence=conf,
                            area=area,
                        )
                    )
            return detections
        except Exception:
            logger.exception("[%s] Inference error", self.__class__.__name__)
            return []

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
