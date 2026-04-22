"""EmoNet emotion classifier.

Pure emotion classification from a face crop — no face detection.
Accepts a pre-cropped face image and returns emotion, valence, arousal.

EmoNet outputs 8 emotion classes plus valence and arousal.
"""

import logging
from pathlib import Path

import cv2
import numpy as np
import numpy.typing as npt
import onnxruntime as ort

logger = logging.getLogger(__name__)

RESOURCES_DIR = Path(__file__).parent / "resources"

EMOTIONS = ["Neutral", "Happy", "Sad", "Surprise", "Fear", "Disgust", "Anger", "Contempt"]


class EmoNetRecognizer:
    """EmoNet ONNX emotion classifier. Loaded once, shared across requests."""

    DEFAULT_MODEL: Path = RESOURCES_DIR / "emonet_8.onnx"

    def __init__(self, model_path: Path | None = None):
        self._model_path: Path = model_path or self.DEFAULT_MODEL
        self._session: ort.InferenceSession | None = None
        self._running: bool = False

    def start(self) -> None:
        if self._running:
            logger.info("[EmoNet] already running")
            return

        logger.info("[EmoNet] Loading model from %s", self._model_path)
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
        logger.info("[EmoNet] ONNX providers: %s", active)

        self._running = True
        logger.info("[EmoNet] ready — %d emotion classes", len(EMOTIONS))

    def stop(self) -> None:
        self._running = False

    def is_ready(self) -> bool:
        return self._running and self._session is not None

    def classify(
        self, face_crop: npt.NDArray[np.uint8]
    ) -> dict:
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
            "emotion": EMOTIONS[emotion_idx],
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
