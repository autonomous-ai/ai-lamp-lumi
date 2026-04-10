import logging
import time
from collections import deque
from enum import Enum
from pathlib import Path
from typing import Callable, Optional, cast, override

import lelamp.config as config
import numpy as np
import numpy.typing as npt
import onnxruntime as ort

from .base import Perception

logger = logging.getLogger(__name__)

RESOURCES_DIR = Path(__file__).parent / "resources"


class MoveEnum(Enum):
    BACKGROUND = "background"  # whole scene shifting — camera shake or very close object
    FOREGROUND = "foreground"  # localized movement — person walking, object moving
    NONE = "none"


class MotionChecker:
    """X3D video action recognition-based motion detector.

    Buffers frames at a configurable interval and runs them through an
    X3D ONNX model to classify the action from 400 Kinect action classes.
    """

    MEAN: npt.NDArray[np.float32] = np.array([114.75, 114.75, 114.75], dtype=np.float32)
    STD: npt.NDArray[np.float32] = np.array([57.38, 57.38, 57.38], dtype=np.float32)

    def __init__(
        self,
        model_path: Path | None = None,
        threshold: float = config.MOTION_X3D_CONFIDENCE_THRESHOLD,
        max_frames: int = 16,
        frame_interval: float = 1.0,
        frame_size: tuple[int, int] = (256, 256),
    ):
        if model_path is None:
            model_path = RESOURCES_DIR / "x3d_m_16x5x1.onnx"
        self._session: ort.InferenceSession = self._prepare_session(model_path)

        self._threshold: float = threshold
        self._max_frames: int = max_frames
        self._frame_interval: float = frame_interval

        self._frame_buffer: deque[npt.NDArray[np.uint8]] = deque()
        self._last_ts: float = 0
        self._last_action: str | None = None
        self._classes_names: list[str] = self._load_classes_names()
        self._frame_size = frame_size

    def _load_classes_names(self):
        file_path = RESOURCES_DIR / "kinect_classes.txt"
        return file_path.read_text().strip().split("\n")

    def _prepare_session(self, model_path: Path, n_threads: int = 4):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = n_threads
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.add_session_config_entry("session.dynamic_block_base", "4")
        return ort.InferenceSession(
            str(model_path), sess_options=opts, providers=["CPUExecutionProvider"]
        )

    def _get_action(self, frame_buffer: deque[npt.NDArray[np.uint8]]) -> tuple[str, float]:
        frames = np.stack(list(frame_buffer), axis=0)
        T, H, W, C = frames.shape
        norm_frames = (frames - self.MEAN) / self.STD

        if T < self._max_frames:
            input = np.concatenate(
                [
                    norm_frames,
                    np.zeros((self._max_frames - T, H, W, C), dtype=np.float32),
                ],
                axis=0,
            )
            input = input.transpose(3, 0, 1, 2)[None, None, ...]
        else:
            input = norm_frames.transpose(3, 0, 1, 2)[None, None, ...]

        (pred,) = self._session.run(["pred"], {"input": input})
        pred = cast(npt.NDArray[np.float32], pred)
        pred = np.exp(pred)
        pred = pred / np.sum(pred, axis=-1, keepdims=True)
        idx = pred[0].argmax()
        return self._classes_names[idx], float(pred[0][idx])

    def update(self, frame: npt.NDArray[np.uint8]) -> str | None:
        """Buffer a frame and run X3D inference when the interval elapses.

        Returns the predicted action name, or None if not enough time has passed.
        """
        import cv2

        cur_ts = time.time()
        if cur_ts - self._last_ts > self._frame_interval:
            H, W = frame.shape[:2]
            frame = cast(npt.NDArray[np.uint8], cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            r = max(256 / W, 256 / H)
            frame = cast(npt.NDArray[np.uint8], cv2.resize(frame, None, fx=r, fy=r))
            NH, NW = frame.shape[:2]
            frame = frame[NH // 2 - 128 : NH // 2 + 128, NW // 2 - 128 : NW // 2 + 128]
            self._frame_buffer.append(frame)
            while len(self._frame_buffer) > self._max_frames:
                _ = self._frame_buffer.popleft()

            action, confidence = self._get_action(self._frame_buffer)
            self._last_action = action if confidence >= self._threshold else None
            self._last_ts = cur_ts

        return self._last_action

    @property
    def last_action(self) -> str | None:
        return self._last_action


class MotionPerception(Perception):
    """Detects motion via X3D video action recognition (400 Kinect action classes)."""

    def __init__(
        self,
        send_event: Callable,
        on_motion: Callable,
        capture_stable_frame: Callable,
        presence_service,
        model_path: Path | None = None,
        motion_update_ts: float = config.MOTION_EVENT_COOLDOWN_S,
    ):
        super().__init__(send_event)
        self._on_motion = on_motion
        self._capture_stable_frame = capture_stable_frame
        self._presence = presence_service
        self._motion_update_ts: float = motion_update_ts
        self._last_motion_time: Optional[float] = None
        self._last_motion_event_ts: float = 0.0
        self._checker = MotionChecker(model_path=model_path)

    @override
    def check(self, frame: npt.NDArray[np.uint8]) -> None:
        if not config.MOTION_ENABLED or frame is None:
            return

        try:
            action = self._checker.update(frame)
        except Exception:
            logger.exception("[motion] X3D inference error")
            return

        if action is None:
            return

        cur_ts = time.time()
        self._last_motion_time = cur_ts
        self._on_motion()

        if (cur_ts - self._last_motion_event_ts) < self._motion_update_ts:
            return
        self._last_motion_event_ts = cur_ts

        stable = self._capture_stable_frame()
        image = stable if stable is not None else frame

        from ..presence_service import PresenceState

        if self._presence.state == PresenceState.PRESENT:
            logger.info("[motion] activity: %s (PRESENT)", action)
            self._send_event(
                "motion.activity",
                f"Action detected via video recognition: '{action}'. "
                "Look at the attached image — describe what the user appears to be doing. "
                "If nothing noteworthy, reply NO_REPLY.",
                image=image,
            )
        else:
            self._send_event(
                "motion",
                f"Action detected via video recognition: '{action}' — someone may have entered or left the room",
                image=image,
            )

    def to_dict(self) -> dict:
        seconds_since = (
            int(time.time() - self._last_motion_time)
            if self._last_motion_time is not None
            else None
        )
        return {
            "type": "motion",
            "last_action": self._checker.last_action,
            "motion_detected": self._last_motion_time is not None,
            "seconds_since_motion": seconds_since,
        }
