"""POSTER V2 emotion classifier (7-class, RAF-DB).

Pure emotion classification from a face crop — no face detection.
Accepts a pre-cropped face image and returns emotion + confidence.

POSTER V2 outputs 7 emotion classes (RAF-DB label order):
Surprise, Fear, Disgust, Happy, Sad, Angry, Neutral

Input: 224x224 RGB face crop, ImageNet-normalised.
"""

import logging
from pathlib import Path

import cv2
import numpy as np
import numpy.typing as npt
import onnxruntime as ort
from typing import Any, cast

from typing_extensions import override

from core.emotion.recognizer.base import EmotionRecognizer

logger = logging.getLogger(__name__)

RESOURCES_DIR = Path(__file__).parent / "resources"

# RAF-DB original label order (1-7 → 0-indexed).
# "Angry" is remapped to "Anger" for consistency with the downstream pipeline
# (LeLamp emotion processor uses EmoNet-style labels).
_RAW_EMOTIONS = ["Surprise", "Fear", "Disgust", "Happy", "Sad", "Angry", "Neutral"]
EMOTIONS = ["Surprise", "Fear", "Disgust", "Happy", "Sad", "Anger", "Neutral"]


class PosterV2Recognizer(EmotionRecognizer):
    """POSTER V2 ONNX emotion classifier. Loaded once, shared across requests."""

    DEFAULT_MODEL: Path = RESOURCES_DIR / "posterv2_7cls.onnx"

    MEAN: npt.NDArray[np.float32] = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    STD: npt.NDArray[np.float32] = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    def __init__(self, model_path: Path | None = None):
        self._model_path: Path = model_path or self.DEFAULT_MODEL
        self._session: ort.InferenceSession | None = None
        self._running: bool = False

    @override
    def start(self) -> None:
        if self._running:
            logger.info("[PosterV2] already running")
            return

        logger.info("[PosterV2] Loading model from %s", self._model_path)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 0
        opts.inter_op_num_threads = 0
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        providers = []
        if "CUDAExecutionProvider" in ort.get_available_providers():
            providers.append("CUDAExecutionProvider")
        providers.append("CPUExecutionProvider")

        self._session = ort.InferenceSession(
            str(self._model_path),
            sess_options=opts,
            providers=providers,
        )
        active = self._session.get_providers()
        logger.info("[PosterV2] ONNX providers: %s", active)

        self._running = True
        logger.info("[PosterV2] ready — %d emotion classes", len(EMOTIONS))

    @override
    def stop(self) -> None:
        self._running = False

    @override
    def is_ready(self) -> bool:
        return self._running and self._session is not None

    @override
    def classify(self, face_crop: npt.NDArray[np.uint8]) -> dict[str, Any]:
        """Classify emotion from a BGR face crop.

        Returns dict with keys: emotion, confidence.
        """
        if self._session is None:
            raise RuntimeError("PosterV2 session not started")

        inp = self._preprocess(face_crop)
        (logits,) = self._session.run(None, {"input": inp})
        logits = cast(npt.NDArray[np.float32], logits)
        probs = _softmax(logits[0])
        emotion_idx = int(np.argmax(probs))

        return {
            "emotion": EMOTIONS[emotion_idx],
            "confidence": float(probs[emotion_idx]),
        }

    @staticmethod
    def _preprocess(face_bgr: npt.NDArray[np.uint8]) -> npt.NDArray[np.float32]:
        """Preprocess face crop: resize to 224x224 with padding, BGR→RGB, ImageNet normalize."""
        h, w = face_bgr.shape[:2]
        scale = 224 / max(h, w)
        new_w, new_h = int(w * scale), int(h * scale)
        resized = cv2.resize(face_bgr, (new_w, new_h))

        padded = np.zeros((224, 224, 3), dtype=np.uint8)
        y_off = (224 - new_h) // 2
        x_off = (224 - new_w) // 2
        padded[y_off : y_off + new_h, x_off : x_off + new_w] = resized

        rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
        tensor = rgb.astype(np.float32) / 255.0
        tensor = (tensor - PosterV2Recognizer.MEAN) / PosterV2Recognizer.STD
        tensor = tensor.transpose(2, 0, 1)  # HWC -> CHW
        return tensor[np.newaxis]  # (1, 3, 224, 224)


def _softmax(x: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    e = np.exp(x - np.max(x))
    return e / e.sum()
