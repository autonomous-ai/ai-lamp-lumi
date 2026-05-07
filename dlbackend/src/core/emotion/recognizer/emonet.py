"""EmoNet emotion classifier (5-class and 8-class variants).

Pure emotion classification from a face crop — no face detection.
Accepts a pre-cropped face image and returns emotion, valence, arousal.

Both variants output expression logits + valence + arousal.
The only difference is the number of expression classes:
  - EmoNet-8: Neutral, Happy, Sad, Surprise, Fear, Disgust, Anger, Contempt
  - EmoNet-5: Neutral, Happy, Sad, Surprise, Anger

Input: 256x256 RGB face crop, normalized to [0, 1].
"""

import logging
from pathlib import Path

import cv2
import numpy as np
import numpy.typing as npt
import onnxruntime as ort
from typing import Any

from typing_extensions import override

from core.emotion.recognizer.base import EmotionRecognizer

logger = logging.getLogger(__name__)

RESOURCES_DIR = Path(__file__).parent / "resources"

EMOTIONS_8 = ["Neutral", "Happy", "Sad", "Surprise", "Fear", "Disgust", "Anger", "Contempt"]
EMOTIONS_5 = ["Neutral", "Happy", "Sad", "Surprise", "Anger"]


class EmoNetRecognizer(EmotionRecognizer):
    """EmoNet ONNX emotion classifier. Supports both 5-class and 8-class variants.

    The variant is determined by ``n_expression`` (5 or 8). Each variant
    uses a different ONNX model file but shares the same preprocessing
    and inference logic.
    """

    DEFAULT_MODELS: dict[int, Path] = {
        8: RESOURCES_DIR / "emonet_8.onnx",
        5: RESOURCES_DIR / "emonet_5.onnx",
    }

    def __init__(self, n_expression: int = 8, model_path: Path | None = None):
        if n_expression not in (5, 8):
            msg = f"n_expression must be 5 or 8, got {n_expression}"
            raise ValueError(msg)

        self._n_expression: int = n_expression
        self._emotions: list[str] = EMOTIONS_8 if n_expression == 8 else EMOTIONS_5
        self._model_path: Path = model_path or self.DEFAULT_MODELS[n_expression]
        self._session: ort.InferenceSession | None = None
        self._running: bool = False

    @override
    def start(self) -> None:
        if self._running:
            logger.info("[EmoNet-%d] already running", self._n_expression)
            return

        logger.info("[EmoNet-%d] Loading model from %s", self._n_expression, self._model_path)
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
        logger.info("[EmoNet-%d] ONNX providers: %s", self._n_expression, active)

        self._running = True
        logger.info("[EmoNet-%d] ready — %d emotion classes", self._n_expression, len(self._emotions))

    @override
    def stop(self) -> None:
        self._running = False

    @override
    def is_ready(self) -> bool:
        return self._running and self._session is not None

    @override
    def classify(self, face_crop: npt.NDArray[np.uint8]) -> dict[str, Any]:
        """Classify emotion from a BGR face crop.

        Returns dict with keys: emotion, confidence, valence, arousal.
        """
        if self._session is None:
            raise RuntimeError("EmoNet session not started")

        inp = self._preprocess(face_crop)
        expression, valence, arousal = self._session.run(None, {"input": inp})
        probs = _softmax(expression[0])
        emotion_idx = int(np.argmax(probs))

        return {
            "emotion": self._emotions[emotion_idx],
            "confidence": float(probs[emotion_idx]),
            "valence": float(valence[0]),
            "arousal": float(arousal[0]),
        }

    @staticmethod
    def _preprocess(face_bgr: npt.NDArray[np.uint8]) -> npt.NDArray[np.float32]:
        """Preprocess face crop: resize to 256x256, BGR→RGB, normalize."""
        resized = cv2.resize(face_bgr, (256, 256))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        tensor = rgb.astype(np.float32) / 255.0
        tensor = tensor.transpose(2, 0, 1)  # HWC -> CHW
        return tensor[np.newaxis]  # (1, 3, 256, 256)


def _softmax(x: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    e = np.exp(x - np.max(x))
    return e / e.sum()
