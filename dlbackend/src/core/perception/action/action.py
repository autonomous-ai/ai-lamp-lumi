"""Action analysis: model lifecycle, person detection, and session management.

Wraps a HumanActionRecognizerModel + optional PersonDetector.
Each WebSocket connection creates an ActionSession via create_session().
"""

import logging
import secrets
import time
from collections import deque

import numpy as np
import numpy.typing as npt

from core.models.action import ActionDetection, ActionResponse
from core.perception.action.recognizer.base import HumanActionRecognizerModel
from core.perception.persondetector import PersonDetector


class ActionAnalysis:
    """Action recognition pipeline. Loaded once, shared by all WS sessions."""

    def __init__(
        self,
        recognizer: HumanActionRecognizerModel,
        person_detector: PersonDetector | None = None,
        confidence_threshold: float | None = None,
        frame_interval: float | None = None,
    ):
        self._recognizer: HumanActionRecognizerModel = recognizer
        self._person_detector: PersonDetector | None = person_detector
        self._confidence_threshold: float | None = confidence_threshold
        self._frame_interval: float | None = frame_interval
        self._running: bool = False
        self._logger: logging.Logger = logging.getLogger(self.__class__.__name__)

    def start(self) -> None:
        if self._running:
            self._logger.info("[%s] already running", self.__class__.__name__)
            return

        self._recognizer.start()
        self._running = True
        self._logger.info("[%s] ready", self.__class__.__name__)

    def stop(self) -> None:
        self._recognizer.stop()
        if self._person_detector is not None:
            self._person_detector.stop()
        self._running = False
        self._logger.info("[%s] stopped", self.__class__.__name__)

    def is_ready(self) -> bool:
        return self._running and self._recognizer.is_ready()

    def create_session(
        self,
        threshold: float | None = None,
        frame_interval: float | None = None,
    ) -> "ActionSession":
        recognizer_cls: type[HumanActionRecognizerModel] = type(self._recognizer)
        if threshold is None:
            threshold = (
                self._confidence_threshold
                if self._confidence_threshold is not None
                else recognizer_cls.DEFAULT_CONFIDENCE_THRESHOLD
            )
        if frame_interval is None:
            frame_interval = (
                self._frame_interval
                if self._frame_interval is not None
                else recognizer_cls.DEFAULT_FRAME_INTERVAL
            )
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
        self._recognizer: HumanActionRecognizerModel = recognizer
        self._person_detector: PersonDetector | None = person_detector
        self._threshold: float = threshold
        self._frame_interval: float = frame_interval

        self._class_mask: npt.NDArray[np.bool_] = recognizer.default_mask.copy()
        self._frame_buffer: deque[npt.NDArray[np.uint8]] = deque()
        self._last_ts: float = 0
        self._last_detected: list[tuple[str, float]] = []
        self._logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self._session_id: str = secrets.token_hex(4)
        self._person_detection_enabled: bool = person_detector is not None

    def update(self, frame: npt.NDArray[np.uint8]) -> ActionResponse:
        """Buffer a frame and optionally run inference.

        Returns ActionResponse with detected classes above threshold.
        Returns an empty ActionResponse when person detection is active
        but no person is found in the frame.
        """
        cur_ts: float = time.time()
        if cur_ts - self._last_ts >= self._frame_interval:
            input_frame: npt.NDArray[np.uint8] = frame
            if self._person_detector is not None and self._person_detection_enabled:
                crop = self._person_detector.detect_largest_crop(frame)
                if crop is None:
                    return ActionResponse(detected_classes=[])
                input_frame = crop

            self._frame_buffer = self._recognizer.preprocess(input_frame, self._frame_buffer)
            self._last_detected = self._recognizer.predict(self._frame_buffer, self._class_mask)
            self._last_ts = cur_ts

        detected_classes: list[ActionDetection] = [
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
            allowed: set[str] = set(whitelist)
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
