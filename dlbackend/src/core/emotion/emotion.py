"""Face emotion recognition using YuNet face detection + configurable classifier.

Supports EmoNet (8-class + valence/arousal) and POSTER V2 (7-class RAF-DB).
Selection via EMOTION_RECOGNITION_MODEL env var.

Loads YuNet + classifier once via EmotionModel, and each WebSocket connection
creates a lightweight EmotionSession that shares the models but maintains
its own timing state and detection cache.
"""

import logging
import time
from pathlib import Path
from typing import Protocol

import numpy as np
import numpy.typing as npt

from config import settings
from enums import EmotionRecognizerEnum
from core.faces import YuNetDetector
from core.models import EmotionDetection, EmotionResponse

logger = logging.getLogger(__name__)


class EmotionClassifier(Protocol):
    """Interface for emotion classifiers (EmoNet, PosterV2, etc.)."""

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def is_ready(self) -> bool: ...
    def classify(self, face_crop: npt.NDArray[np.uint8]) -> dict: ...


def _create_classifier(fer_path: Path | None) -> EmotionClassifier:
    """Create the emotion classifier based on the configured model."""
    model_type = settings.emotion_recognition_model

    if model_type == EmotionRecognizerEnum.POSTERV2:
        from core.emotion.posterv2 import PosterV2Recognizer
        return PosterV2Recognizer(model_path=fer_path)
    elif model_type == EmotionRecognizerEnum.EMONET:
        from core.emotion.emonet import EmoNetRecognizer
        return EmoNetRecognizer(model_path=fer_path)
    else:
        msg = f"Unknown emotion recognition model: {model_type}"
        raise ValueError(msg)


class EmotionModel:
    """Combined YuNet + emotion classifier. Loaded once, used by all WS sessions."""

    def __init__(
        self,
        yunet_path: Path | None = None,
        fer_path: Path | None = None,
        score_threshold: float = 0.7,
        nms_threshold: float = 0.3,
        top_k: int = 5000,
    ):
        self._face_detector = YuNetDetector(
            model_path=yunet_path,
            score_threshold=score_threshold,
            nms_threshold=nms_threshold,
            top_k=top_k,
        )
        self._fer = _create_classifier(fer_path)
        self._running: bool = False

    def start(self):
        if self._running:
            logger.info("[EmotionModel] already running")
            return

        self._face_detector.start()
        self._fer.start()

        self._running = True
        logger.info("[EmotionModel] ready (%s)", settings.emotion_recognition_model)

    def stop(self):
        self._fer.stop()
        self._running = False

    def is_ready(self) -> bool:
        return self._running and self._face_detector.is_ready() and self._fer.is_ready()

    def detect_single_face(
        self,
        face: npt.NDArray[np.uint8],
    ) -> list[EmotionDetection]:
        if not self.is_ready():
            return []

        H, W = face.shape[:2]
        cls = self._fer.classify(face)
        return [
            EmotionDetection(
                emotion=cls["emotion"],
                confidence=cls["confidence"],
                face_confidence=1,
                bbox=[0, 0, W, H],
                valence=cls.get("valence"),
                arousal=cls.get("arousal"),
            )
        ]

    def detect(
        self,
        frame: npt.NDArray[np.uint8],
    ) -> list[EmotionDetection]:
        """Detect faces and classify emotions.

        Returns list of EmotionDetection with emotion and confidence.
        Valence/arousal are included when supported by the classifier (EmoNet).
        """
        if not self.is_ready():
            return []

        faces = self._face_detector.detect(frame)

        results = []
        for face in faces:
            cls = self._fer.classify(face.crop)
            results.append(
                EmotionDetection(
                    emotion=cls["emotion"],
                    confidence=cls["confidence"],
                    face_confidence=face.confidence,
                    bbox=face.bbox,
                    valence=cls.get("valence"),
                    arousal=cls.get("arousal"),
                )
            )

        return results

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
        if len(filtered) > 0:
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
