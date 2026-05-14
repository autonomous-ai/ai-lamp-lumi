"""YOLO-based person detector for action recognition preprocessing.

Detects person bounding boxes in a frame and exposes ``detect_largest_crop``
to extract the crop of the largest person for downstream action recognition.
"""

import logging

import cv2
from typing_extensions import override
from ultralytics.models.yolo import YOLO

from core.models.person import PersonDetection
from core.perception.persondetector.base import PersonDetector

logger = logging.getLogger(__name__)

# COCO class index for "person"
_PERSON_CLASS_ID = 0


class YOLOPersonDetector(PersonDetector):
    """YOLO-based person detector.

    Loads an ultralytics YOLO model once and runs inference to locate people
    in BGR frames.  Rate-limiting is handled by the caller, so this class
    runs on every frame it receives.

    Usage::

        detector = YOLOPersonDetector(model_name="yolo12x.pt")
        detector.start()
        crop = detector.detect_largest_crop(frame)   # ndarray or None
    """

    DEFAULT_MODEL_NAME: str = "yolo12x.pt"
    DEFAULT_CONFIDENCE_THRESHOLD: float = 0.4
    DEFAULT_BBOX_EXPAND_SCALE: float = 2.0
    DEFAULT_MIN_AREA_RATIO: float = 0.25

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        bbox_expand_scale: float = DEFAULT_BBOX_EXPAND_SCALE,
        min_area_ratio: float = DEFAULT_MIN_AREA_RATIO,
    ):
        super().__init__(min_area_ratio=min_area_ratio)
        self._model_name: str = model_name
        self._threshold: float = threshold
        self._bbox_expand_scale: float = bbox_expand_scale

        self._model: YOLO | None = None
        self._running: bool = False

    @override
    def start(self) -> None:
        """Load the YOLO model weights (blocking)."""
        logger.info("[%s] Loading YOLO model '%s'", self.__class__.__name__, self._model_name)
        self._model = YOLO(self._model_name)
        self._running = True

    @override
    def stop(self) -> None:
        self._model = None
        self._running = False

    @override
    def is_ready(self) -> bool:
        return self._running and self._model is not None

    def _scale_and_clamp_bbox(self, bbox: list[int], h: int, w: int, scale: float = 1.0):
        x1, y1, x2, y2 = bbox
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2

        x1 = int(max(min(cx + (x1 - cx) * scale, w - 1), 0))
        x2 = int(max(min(cx + (x2 - cx) * scale, w - 1), 0))
        y1 = int(max(min(cy + (y1 - cy) * scale, h - 1), 0))
        y2 = int(max(min(cy + (y2 - cy) * scale, h - 1), 0))

        return [x1, y1, x2, y2]

    @override
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
                    raw = [int(v) for v in box.xyxy[0].tolist()]
                    area = max(0, raw[2] - raw[0]) * max(0, raw[3] - raw[1])
                    x1, y1, x2, y2 = self._scale_and_clamp_bbox(raw, H, W, self._bbox_expand_scale)
                    conf = float(box.conf[0])
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
