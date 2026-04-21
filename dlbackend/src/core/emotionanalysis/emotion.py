"""Face emotion recognition using YuNet face detection + VGG-FER classifier.

Loads two ONNX models once via EmotionModel, and each WebSocket connection
creates a lightweight EmotionSession that shares the models but maintains
its own timing state and detection cache.

Reference: /Users/macbookpro/programming/tmp/opencv/core/emotion.py
"""

import logging
import time
from pathlib import Path

import cv2
import numpy as np
import numpy.typing as npt
import onnxruntime as ort

from config import settings
from core.models import EmotionDetection, EmotionResponse

logger = logging.getLogger(__name__)

RESOURCES_DIR = Path(__file__).parent / "resources"

EMOTIONS = ["Angry", "Disgust", "Fear", "Happy", "Sad", "Surprise", "Neutral"]


class EmotionModel:
    """Shared emotion recognition model. Loaded once, used by all sessions."""

    DEFAULT_YUNET_MODEL: Path = RESOURCES_DIR / "face_detection_yunet_2023mar.onnx"
    DEFAULT_FER_MODEL: Path = RESOURCES_DIR / "vgg-fer.onnx"

    def __init__(
        self,
        yunet_path: Path | None = None,
        fer_path: Path | None = None,
        score_threshold: float = 0.7,
        nms_threshold: float = 0.3,
        top_k: int = 5000,
    ):
        self._yunet_path: Path = yunet_path or self.DEFAULT_YUNET_MODEL
        self._fer_path: Path = fer_path or self.DEFAULT_FER_MODEL
        self._score_threshold: float = score_threshold
        self._nms_threshold: float = nms_threshold
        self._top_k: int = top_k

        self._face_detector: cv2.FaceDetectorYN | None = None
        self._fer_session: ort.InferenceSession | None = None
        self._fer_input_name: str = ""
        self._running: bool = False

    def start(self):
        if self._running:
            logger.info("[EmotionModel] already running")
            return

        logger.info("[EmotionModel] Loading YuNet from %s", self._yunet_path)
        self._face_detector = cv2.FaceDetectorYN.create(
            str(self._yunet_path),
            "",
            (320, 320),
            self._score_threshold,
            self._nms_threshold,
            self._top_k,
        )

        logger.info("[EmotionModel] Loading VGG-FER from %s", self._fer_path)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 0
        opts.inter_op_num_threads = 0
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        providers = []
        if "CUDAExecutionProvider" in ort.get_available_providers():
            providers.append("CUDAExecutionProvider")
        providers.append("CPUExecutionProvider")

        self._fer_session = ort.InferenceSession(
            str(self._fer_path),
            sess_options=opts,
            providers=providers,
        )
        self._fer_input_name = self._fer_session.get_inputs()[0].name
        active = self._fer_session.get_providers()
        logger.info("[EmotionModel] ONNX providers: %s", active)

        self._running = True
        logger.info("[EmotionModel] ready — 7 emotion classes")

    def stop(self):
        self._running = False

    def is_ready(self) -> bool:
        return self._running and self._face_detector is not None and self._fer_session is not None

    def detect(
        self,
        frame: npt.NDArray[np.uint8],
    ) -> list[EmotionDetection]:
        """Detect faces and classify emotions.

        Returns list of {"emotion": str, "confidence": float, "bbox": [x,y,w,h]}.
        """
        if self._face_detector is None or self._fer_session is None:
            return []

        h, w = frame.shape[:2]
        self._face_detector.setInputSize((w, h))
        _, faces = self._face_detector.detect(frame)
        if faces is None:
            return []

        results = []
        for face in faces:
            x, y, fw, fh = face[:4].astype(int)
            face_conf = float(face[14])

            # Clamp to frame bounds
            x1 = max(0, x)
            y1 = max(0, y)
            x2 = min(w, x + fw)
            y2 = min(h, y + fh)
            if x2 <= x1 or y2 <= y1:
                continue

            face_crop = frame[y1:y2, x1:x2]
            inp = self._preprocess_face(face_crop)

            logits = self._fer_session.run(None, {self._fer_input_name: inp})[0][0]
            probs = _softmax(logits)
            emotion_idx = int(np.argmax(probs))
            emotion_label = EMOTIONS[emotion_idx]
            emotion_conf = float(probs[emotion_idx])

            results.append(
                EmotionDetection(
                    emotion=emotion_label,
                    confidence=emotion_conf,
                    face_confidence=face_conf,
                    bbox=[int(x), int(y), int(fw), int(fh)],
                )
            )

        return results

    @staticmethod
    def _preprocess_face(face_bgr: npt.NDArray[np.uint8]) -> npt.NDArray[np.float32]:
        gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, (40, 40))
        tensor = resized.astype(np.float32) / 255.0
        return tensor.reshape(1, 1, 40, 40)

    def create_session(
        self,
        threshold: float = settings.emotion.confidence_threshold,
        frame_interval: float = settings.emotion.frame_interval,
    ) -> "EmotionSession":
        return EmotionSession(
            model=self,
            threshold=threshold,
            frame_interval=frame_interval,
        )


class EmotionSession:
    """Per-connection session for emotion detection."""

    def __init__(
        self,
        model: EmotionModel,
        threshold: float,
        frame_interval: float,
    ):
        self._model = model
        self._threshold = threshold
        self._frame_interval = frame_interval
        self._last_ts: float = 0
        self._last_detected: list[EmotionDetection] = []
        self._logger = logging.getLogger(self.__class__.__name__)

    def update(self, frame: npt.NDArray[np.uint8]) -> EmotionResponse | None:
        """Run emotion detection if enough time has passed since last inference.

        Returns EmotionResponse with detections above threshold, or None
        if skipping this frame (frame interval not elapsed).
        """
        cur_ts = time.time()
        if cur_ts - self._last_ts < self._frame_interval:
            return EmotionResponse(detections=self._filter(self._last_detected))

        self._last_detected = self._model.detect(frame)
        self._last_ts = cur_ts

        filtered = self._filter(self._last_detected)
        self._logger.info(
            "Detected %d face(s): %s",
            len(filtered),
            ", ".join(f"{d.emotion} ({d.confidence:.2f})" for d in filtered) or "none",
        )

        return EmotionResponse(detections=filtered)

    def _filter(self, detections: list[EmotionDetection]) -> list[EmotionDetection]:
        return [d for d in detections if d.confidence >= self._threshold]

    def set_config(self, threshold: float) -> None:
        self._threshold = threshold
        self._logger.info("Config updated — threshold=%.2f", threshold)

    def is_ready(self) -> bool:
        return self._model.is_ready()


def _softmax(x: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    e = np.exp(x - np.max(x))
    return e / e.sum()
