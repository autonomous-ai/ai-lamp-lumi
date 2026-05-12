"""Face emotion recognition using YuNet face detection + configurable classifier.

Supports EmoNet (8-class + valence/arousal) and POSTER V2 (7-class RAF-DB).

Loads YuNet + classifier once via EmotionAnalysis, and each WebSocket connection
creates a lightweight EmotionSession that shares the models but maintains
its own timing state and detection cache.
"""

import logging
import time
from pathlib import Path

import numpy as np
import numpy.typing as npt

from core.enums import EmotionRecognizerEnum
from core.models.emotion import EmotionDetection, EmotionResponse
from core.perception.emotion.recognizer.base import EmotionRecognizer
from core.perception.emotion.utils import create_classifier
from core.perception.faces import YuNetDetector

class EmotionAnalysis:
    """Combined YuNet + emotion classifier. Loaded once, used by all WS sessions."""

    DEFAULT_CONFIDENCE_THRESHOLD: float = 0.5
    DEFAULT_FRAME_INTERVAL: float = 1.0

    def __init__(
        self,
        model_name: EmotionRecognizerEnum,
        yunet_path: Path | None = None,
        emotion_model_path: Path | None = None,
        score_threshold: float = 0.7,
        nms_threshold: float = 0.3,
        top_k: int = 5000,
        confidence_threshold: float | None = None,
        frame_interval: float | None = None,
    ):
        self._face_detector: YuNetDetector = YuNetDetector(
            model_path=yunet_path,
            score_threshold=score_threshold,
            nms_threshold=nms_threshold,
            top_k=top_k,
        )
        self._fer: EmotionRecognizer = create_classifier(model_name, emotion_model_path)
        self._model_name = model_name
        self._confidence_threshold = confidence_threshold
        self._frame_interval = frame_interval
        self._running: bool = False
        self._logger: logging.Logger = logging.getLogger(self.__class__.__name__)

    def start(self):
        if self._running:
            self._logger.info("[%s] already running", self.__class__.__name__)
            return

        self._face_detector.start()
        self._fer.start()

        self._running = True
        self._logger.info("[%s] ready (%s)", self.__class__.__name__, self._model_name)

    def stop(self):
        self._fer.stop()
        self._face_detector.stop()
        self._running = False
        self._logger.info("[%s] stopped", self.__class__.__name__)

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
        threshold: float | None = None,
        frame_interval: float | None = None,
    ) -> "EmotionSession":
        if threshold is None:
            threshold = self._confidence_threshold if self._confidence_threshold is not None else self.DEFAULT_CONFIDENCE_THRESHOLD
        if frame_interval is None:
            frame_interval = self._frame_interval if self._frame_interval is not None else self.DEFAULT_FRAME_INTERVAL
        return EmotionSession(
            model=self,
            threshold=threshold,
            frame_interval=frame_interval,
        )


class EmotionSession:
    """Per-connection session for emotion detection."""

    def __init__(
        self,
        model: EmotionAnalysis,
        threshold: float,
        frame_interval: float,
    ):
        self._model: EmotionAnalysis = model
        self._threshold: float = threshold
        self._frame_interval: float = frame_interval
        self._last_ts: float = 0
        self._last_detected: list[EmotionDetection] = []
        self._logger: logging.Logger = logging.getLogger(self.__class__.__name__)

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
