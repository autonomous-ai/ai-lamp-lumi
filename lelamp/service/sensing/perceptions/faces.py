import logging
from typing import Callable, Optional

import numpy as np

import lelamp.config as config
from .base import Perception

logger = logging.getLogger(__name__)


class FacePerception(Perception):
    """Detects face presence/absence via OpenCV Haar cascade."""

    def __init__(
        self,
        cv2,
        send_event: Callable,
        on_motion: Callable,
        capture_stable_frame: Callable,
        encode_frame: Callable,
    ):
        super().__init__(send_event)
        self._cv2 = cv2
        self._on_motion = on_motion
        self._capture_stable_frame = capture_stable_frame
        self._encode_frame = encode_frame

        self._face_cascade = None
        self._face_present: bool = False
        self._face_absent_count: int = 0

        self._init_cascade()

    def _init_cascade(self):
        cv2 = self._cv2
        try:
            cascade_path = cv2.data.haarcascades + config.FACE_CASCADE_FILE
            cascade = cv2.CascadeClassifier(cascade_path)
            if cascade.empty():
                logger.warning("Face cascade failed to load from %s", cascade_path)
            else:
                self._face_cascade = cascade
                logger.info("Face cascade loaded: %s", cascade_path)
        except Exception as e:
            logger.warning("Failed to init face cascade: %s", e)

    def check(self, frame: np.ndarray) -> None:
        if not self._face_cascade:
            return

        cv2 = self._cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (0, 0), fx=0.5, fy=0.5)

        faces = self._face_cascade.detectMultiScale(
            small,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(30, 30),
        )

        face_found = len(faces) > 0
        prev_present = self._face_present

        if face_found and not prev_present:
            self._face_present = True
            self._face_absent_count = 0
            self._on_motion()
            stable = self._capture_stable_frame()
            image_b64 = (
                self._encode_frame(stable)
                if stable is not None
                else self._encode_frame(frame)
            )
            self._send_event(
                "presence.enter",
                f"Person detected — {len(faces)} face(s) visible in camera view",
                image=image_b64,
                cooldown=config.FACE_COOLDOWN_S,
            )
        elif not face_found and prev_present:
            self._face_absent_count += 1
            if self._face_absent_count >= 3:
                self._face_present = False
                self._face_absent_count = 0
                self._send_event(
                    "presence.leave",
                    "No face detected — person may have left the area",
                    cooldown=config.FACE_COOLDOWN_S,
                )
        else:
            self._face_absent_count = 0
