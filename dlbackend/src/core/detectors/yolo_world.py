"""YOLO-World detector using the ultralytics library."""

import logging

import numpy as np
import torch
from ultralytics import YOLOWorld

from models import DetectionResult
from .base import BaseDetector

logger = logging.getLogger(__name__)


class YOLOWorldDetector(BaseDetector):
    """Zero-shot object detection using YOLO-World.

    Loads the model once at initialization and reuses it for all requests.
    Classes are set per-request via `model.set_classes()`.
    """

    def __init__(self, model_name: str = "yolov8s-worldv2.pt"):
        logger.info(f"Loading YOLO-World model: {model_name}")
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self._model = YOLOWorld(model_name).to(self._device)
        logger.info("YOLO-World model loaded")

    def detect(self, image: np.ndarray, classes: list[str]) -> list[DetectionResult]:
        """Run YOLO-World detection on a BGR image.

        Args:
            image: BGR numpy array (H, W, 3).
            classes: Class names to detect.

        Returns:
            List of DetectionResult with xywh in pixel coordinates.
        """
        self._model.set_classes(classes)
        results = self._model.predict(image, verbose=False)

        detections = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for i in range(len(boxes)):
                xyxy = boxes.xyxy[i].cpu().numpy()
                x1, y1, x2, y2 = xyxy
                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2
                w = x2 - x1
                h = y2 - y1
                conf = float(boxes.conf[i].cpu().numpy())
                cls_idx = int(boxes.cls[i].cpu().numpy())
                class_name = classes[cls_idx] if cls_idx < len(classes) else "unknown"

                detections.append(
                    DetectionResult(
                        class_name=class_name,
                        xywh=[float(cx), float(cy), float(w), float(h)],
                        confidence=conf,
                    )
                )

        return detections

    def is_ready(self) -> bool:
        """Return True — model is loaded at init."""
        return self._model is not None
