"""Emotion perception: model lifecycle, session management, and single-shot prediction.

Wraps an EmotionRecognizer + FaceDetector.
Each WebSocket connection creates an EmotionPerceptionSession via create_session().
Single-shot methods (predict_face, predict_image) are provided for HTTP endpoints.
"""

import cv2.typing as cv2t
import numpy as np
import numpy.typing as npt
from typing_extensions import override

from core.models.emotion import (
    Emotion,
    EmotionDetection,
    EmotionPerceptionSessionConfig,
    RawEmotionDetection,
)
from core.perception.base import PerceptionBase
from core.perception.emotion.predictors.base import EmotionRecognizer
from core.perception.emotion.session import EmotionPerceptionSession
from core.models.face import FaceCrop
from core.perception.face.predictors.base import FaceDetector


class EmotionPerception(PerceptionBase[EmotionPerceptionSession]):
    """Emotion detection pipeline. Loaded once, shared by all WS sessions."""

    def __init__(
        self,
        emotion_recognizer: EmotionRecognizer,
        face_detector: FaceDetector,
        default_config: EmotionPerceptionSessionConfig | None = None,
    ) -> None:
        super().__init__()

        self._emotion_recognizer: EmotionRecognizer = emotion_recognizer
        self._face_detector: FaceDetector = face_detector
        self._default_config: EmotionPerceptionSessionConfig | None = default_config
        self._running: bool = False

    @override
    def start(self) -> None:
        if self._running:
            self._logger.info("Already running")
            return

        self._emotion_recognizer.start()
        self._face_detector.start()
        self._running = True
        self._logger.info("Ready")

    @override
    def stop(self) -> None:
        self._emotion_recognizer.stop()
        self._face_detector.stop()
        self._running = False
        self._logger.info("Stopped")

    @override
    def is_ready(self) -> bool:
        return (
            self._running
            and self._emotion_recognizer.is_ready()
            and self._face_detector.is_ready()
        )

    @override
    def create_session(self) -> EmotionPerceptionSession:
        config: EmotionPerceptionSessionConfig = (
            self._default_config or EmotionPerceptionSession.DEFAULT_CONFIG
        )
        return EmotionPerceptionSession(
            emotion_recognizer=self._emotion_recognizer,
            face_detector=self._face_detector,
            config=config,
        )

    # --- Single-shot prediction (for HTTP endpoints) ---

    def predict_face(self, face_crop: cv2t.MatLike) -> Emotion | None:
        """Classify emotion from a single pre-cropped face image.

        No face detection — the input is assumed to be a face crop.
        Returns an Emotion or None if the model produces no result.
        """
        raw_results: list[RawEmotionDetection] = self._emotion_recognizer.predict([face_crop])
        if not raw_results:
            return None

        raw: RawEmotionDetection = raw_results[0]
        emotion_idx: int = int(np.argmax(raw.expression_probs))
        H, W = face_crop.shape[:2]

        return Emotion(
            emotion=self._emotion_recognizer.class_names[emotion_idx],
            confidence=float(raw.expression_probs[emotion_idx]),
            face_confidence=1.0,
            bbox=[0, 0, W, H],
            valence=raw.valence,
            arousal=raw.arousal,
        )

    def predict_image(self, frame: npt.NDArray[np.uint8]) -> EmotionDetection:
        """Detect faces in a full frame and classify emotion for each.

        Runs face detection, then classifies each crop.
        Returns EmotionDetection with all detected emotions (unfiltered).
        """
        face_crops: list[FaceCrop] = self._face_detector.extract_crops([frame])[0]
        if not face_crops:
            return EmotionDetection(emotions=[])

        crops: list[cv2t.MatLike] = [fc.crop for fc in face_crops]
        raw_results: list[RawEmotionDetection] = self._emotion_recognizer.predict(crops)

        emotions: list[Emotion] = []
        for fc, raw in zip(face_crops, raw_results):
            emotion_idx: int = int(np.argmax(raw.expression_probs))
            emotions.append(
                Emotion(
                    emotion=self._emotion_recognizer.class_names[emotion_idx],
                    confidence=float(raw.expression_probs[emotion_idx]),
                    face_confidence=fc.confidence,
                    bbox=fc.bbox_xyxy,
                    valence=raw.valence,
                    arousal=raw.arousal,
                )
            )

        return EmotionDetection(emotions=emotions)
