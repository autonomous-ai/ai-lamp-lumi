"""Action analysis: model lifecycle, person detection, and session management.

Wraps a HumanActionRecognizerModel + optional PersonDetector.
Each WebSocket connection creates an ActionSession via create_session().
"""

import logging
import secrets
import time
from collections import deque
from pathlib import Path

import numpy as np
import numpy.typing as npt

from config import settings
from core.enums import HumanActionRecognizerEnum, PersonDetectorEnum
from core.models.action import ActionDetection, ActionResponse
from core.perception.action.constants import (
    UNIFORMERV2_DEFAULTS,
    VIDEOMAE_DEFAULTS,
    X3D_DEFAULTS,
)
from core.perception.action.recognizer.base import HumanActionRecognizerModel
from core.perception.persondetector import PersonDetector, YOLOPersonDetector

logger = logging.getLogger(__name__)

# Map model enum → its defaults dict
_MODEL_DEFAULTS: dict[HumanActionRecognizerEnum, dict] = {
    HumanActionRecognizerEnum.VIDEOMAE: VIDEOMAE_DEFAULTS,
    HumanActionRecognizerEnum.UNIFORMERV2: UNIFORMERV2_DEFAULTS,
    HumanActionRecognizerEnum.X3D: X3D_DEFAULTS,
}


def _create_recognizer(
    model_name: HumanActionRecognizerEnum,
    model_path: Path | None,
) -> HumanActionRecognizerModel:
    """Instantiate the correct recognizer model, applying config overrides."""
    s = settings.action
    defaults = _MODEL_DEFAULTS[model_name]

    max_frames = s.max_frames if s.max_frames is not None else defaults["max_frames"]
    if s.w is not None and s.h is not None:
        frame_size = (s.h, s.w)
    else:
        frame_size = defaults["frame_size"]

    if model_name == HumanActionRecognizerEnum.VIDEOMAE:
        from core.perception.action.recognizer.videomae import VideoMAEModel

        return VideoMAEModel(model_path, max_frames=max_frames, frame_size=frame_size)
    elif model_name == HumanActionRecognizerEnum.UNIFORMERV2:
        from core.perception.action.recognizer.uniformerv2 import UniformerV2Model

        return UniformerV2Model(model_path, max_frames=max_frames, frame_size=frame_size)
    elif model_name == HumanActionRecognizerEnum.X3D:
        from core.perception.action.recognizer.x3d import X3DModel

        return X3DModel(model_path, max_frames=max_frames, frame_size=frame_size)
    else:
        msg = f"Unknown action recognition model: {model_name}"
        raise ValueError(msg)


def _create_person_detector() -> PersonDetector | None:
    """Create and start the person detector if enabled in config."""
    pd_cfg = settings.person_detector
    if not pd_cfg.enabled:
        return None

    if pd_cfg.model == PersonDetectorEnum.YOLO:
        detector = YOLOPersonDetector()
    else:
        raise ValueError(f"Unknown person detector: {pd_cfg.model}")

    detector.start()
    logger.info("Person detector ready (%s: %s)", pd_cfg.model, pd_cfg.model_name)
    return detector


class ActionAnalysis:
    """Action recognition pipeline. Loaded once, shared by all WS sessions."""

    def __init__(
        self,
        model_name: HumanActionRecognizerEnum,
        model_path: Path | None = None,
    ):
        self._model_name = model_name
        self._recognizer: HumanActionRecognizerModel = _create_recognizer(model_name, model_path)
        self._person_detector: PersonDetector | None = _create_person_detector()
        self._running: bool = False

    def start(self) -> None:
        if self._running:
            logger.info("[ActionAnalysis] already running")
            return

        self._recognizer.start()
        self._running = True
        logger.info("[ActionAnalysis] ready (%s)", self._model_name)

    def stop(self) -> None:
        self._recognizer.stop()
        if self._person_detector is not None:
            self._person_detector.stop()
        self._running = False
        logger.info("[ActionAnalysis] stopped")

    def is_ready(self) -> bool:
        return self._running and self._recognizer.is_ready()

    def create_session(
        self,
        threshold: float | None = None,
        frame_interval: float | None = None,
    ) -> "ActionSession":
        defaults = _MODEL_DEFAULTS[self._model_name]
        s = settings.action
        if threshold is None:
            threshold = s.confidence_threshold if s.confidence_threshold is not None else defaults["confidence_threshold"]
        if frame_interval is None:
            frame_interval = s.frame_interval if s.frame_interval is not None else defaults["frame_interval"]
        return ActionSession(
            recognizer=self._recognizer,
            person_detector=self._person_detector,
            threshold=threshold,
            frame_interval=frame_interval,
        )


class ActionSession:
    """Per-connection session for action recognition."""

    def __init__(
        self,
        recognizer: HumanActionRecognizerModel,
        person_detector: PersonDetector | None,
        threshold: float,
        frame_interval: float,
    ):
        self._recognizer = recognizer
        self._person_detector = person_detector
        self._threshold = threshold
        self._frame_interval = frame_interval

        self._class_mask: npt.NDArray[np.bool_] = recognizer.default_mask.copy()
        self._frame_buffer: deque[npt.NDArray[np.uint8]] = deque()
        self._last_ts: float = 0
        self._last_detected: list[tuple[str, float]] = []
        self._logger = logging.getLogger(self.__class__.__name__)
        self._session_id: str = secrets.token_hex(4)
        self._person_detection_enabled: bool = person_detector is not None

    def update(self, frame: npt.NDArray[np.uint8]) -> ActionResponse:
        """Buffer a frame and optionally run inference.

        Returns ActionResponse with detected classes above threshold.
        Returns an empty ActionResponse when person detection is active
        but no person is found in the frame.
        """
        cur_ts = time.time()
        if cur_ts - self._last_ts >= self._frame_interval:
            input_frame = frame
            if self._person_detector is not None and self._person_detection_enabled:
                crop = self._person_detector.detect_largest_crop(frame)
                if crop is None:
                    return ActionResponse(detected_classes=[])
                input_frame = crop

            self._frame_buffer = self._recognizer.preprocess(input_frame, self._frame_buffer)
            self._last_detected = self._recognizer.predict(self._frame_buffer, self._class_mask)
            self._last_ts = cur_ts

        detected_classes = [
            ActionDetection(class_name=name, conf=conf)
            for name, conf in self._last_detected
            if conf > self._threshold
        ]
        if detected_classes:
            self._logger.info(
                "[%s] Detected top-%d: %s",
                self._session_id,
                min(3, len(detected_classes)),
                ", ".join(f"{d.class_name} ({d.conf:.2f})" for d in detected_classes[:3]),
            )

        return ActionResponse(detected_classes=detected_classes)

    def set_config(
        self,
        whitelist: list[str] | None,
        threshold: float = 0.3,
        person_detection_enabled: bool | None = None,
        person_min_area_ratio: float | None = None,
    ) -> None:
        """Update whitelist, threshold, and person detector settings."""
        if whitelist is None:
            self._class_mask = self._recognizer.default_mask.copy()
        else:
            allowed = set(whitelist)
            self._class_mask = np.array(
                [name in allowed for name in self._recognizer.class_names], dtype=np.bool_
            )

        self._threshold = threshold

        if person_detection_enabled is not None:
            self._person_detection_enabled = person_detection_enabled

        if person_min_area_ratio is not None and self._person_detector is not None:
            self._person_detector.min_area_ratio = person_min_area_ratio

        self._logger.info(
            "[%s] Config updated — %d classes enabled, threshold=%f",
            self._session_id,
            int(self._class_mask.sum()),
            round(threshold, 2),
        )

    def is_ready(self) -> bool:
        return self._recognizer.is_ready()
