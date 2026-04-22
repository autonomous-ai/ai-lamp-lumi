"""YuNet face detector wrapper.

Provides a reusable face detection class backed by OpenCV's FaceDetectorYN.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import numpy.typing as npt

logger = logging.getLogger(__name__)

RESOURCES_DIR = Path(__file__).parent / "resources"
DEFAULT_YUNET_MODEL: Path = RESOURCES_DIR / "face_detection_yunet_2023mar.onnx"


@dataclass
class FaceDetection:
    """Single face detection result."""

    bbox: list[int]  # [x, y, w, h]
    confidence: float
    crop: npt.NDArray[np.uint8]  # face crop from the original frame


class YuNetDetector:
    """YuNet-based face detector using OpenCV's FaceDetectorYN."""

    def __init__(
        self,
        model_path: Path | None = None,
        input_size: tuple[int, int] = (320, 320),
        score_threshold: float = 0.7,
        nms_threshold: float = 0.3,
        top_k: int = 5000,
    ):
        self._model_path = model_path or DEFAULT_YUNET_MODEL
        self._input_size = input_size
        self._score_threshold = score_threshold
        self._nms_threshold = nms_threshold
        self._top_k = top_k
        self._detector: cv2.FaceDetectorYN | None = None

    def start(self) -> None:
        logger.info("[YuNet] Loading model from %s", self._model_path)
        self._detector = cv2.FaceDetectorYN.create(
            str(self._model_path),
            "",
            self._input_size,
            self._score_threshold,
            self._nms_threshold,
            self._top_k,
        )

    def is_ready(self) -> bool:
        return self._detector is not None

    def detect(self, frame: npt.NDArray[np.uint8]) -> list[FaceDetection]:
        """Detect faces in a BGR frame.

        Returns list of FaceDetection with bbox, confidence, and cropped face.
        """
        if self._detector is None:
            return []

        h, w = frame.shape[:2]
        self._detector.setInputSize((w, h))
        _, faces = self._detector.detect(frame)
        if faces is None:
            return []

        results = []
        for face in faces:
            x, y, fw, fh = face[:4].astype(int)
            conf = float(face[14])

            # Clamp to frame bounds
            x1 = max(0, x)
            y1 = max(0, y)
            x2 = min(w, x + fw)
            y2 = min(h, y + fh)
            if x2 <= x1 or y2 <= y1:
                continue

            crop = frame[y1:y2, x1:x2]
            results.append(
                FaceDetection(
                    bbox=[int(x), int(y), int(fw), int(fh)],
                    confidence=conf,
                    crop=crop,
                )
            )

        return results
