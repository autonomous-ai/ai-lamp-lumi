"""X3D video action recognition-based human action recognizer.

Buffers frames at a configurable interval and runs them through an
X3D ONNX model to classify actions from 400 Kinetics action classes.

The ONNX model is loaded once via X3DModel, and each WebSocket connection
creates a lightweight X3DActionRecognizer that shares the model but
maintains its own frame buffer, whitelist, and timing state.
"""

import logging
import time
from collections import deque
from pathlib import Path
from typing import cast

import cv2
import numpy as np
import numpy.typing as npt
import onnxruntime as ort

from core.models import ActionResponse

from .base import HumanActionRecognizer

logger = logging.getLogger(__name__)

RESOURCES_DIR = Path(__file__).parent / "resources"

DEFAULT_CONFIDENCE_THRESHOLD = 0.3
DEFAULT_MAX_FRAMES = 16
DEFAULT_FRAME_INTERVAL = 1.0
DEFAULT_FRAME_SIZE = (256, 256)


class X3DModel:
    """Shared X3D ONNX model. Loaded once, used by all recognizer sessions."""

    MEAN: npt.NDArray[np.float32] = np.array([114.75, 114.75, 114.75], dtype=np.float32)
    STD: npt.NDArray[np.float32] = np.array([57.38, 57.38, 57.38], dtype=np.float32)

    def __init__(self, model_path: Path | None = None):
        if model_path is None:
            model_path = RESOURCES_DIR / "x3d_m_16x5x1_int8.onnx"

        logger.info("Loading X3D model from %s", model_path)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.add_session_config_entry("session.dynamic_block_base", "4")
        self.session = ort.InferenceSession(
            str(model_path), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self.class_names, self.default_mask = self._load_classes()
        logger.info(
            "X3D model loaded — %d classes, %d whitelisted",
            len(self.class_names),
            int(self.default_mask.sum()),
        )

    @staticmethod
    def _load_classes() -> tuple[list[str], npt.NDArray[np.bool_]]:
        classes_path = RESOURCES_DIR / "kinect_classes.txt"
        whitelist_path = RESOURCES_DIR / "white_list.txt"

        class_names = classes_path.read_text().strip().split("\n")
        mask = np.ones(len(class_names), dtype=np.bool_)

        if whitelist_path.exists():
            whitelist = set(whitelist_path.read_text().strip().split("\n"))
            mask = np.array([name in whitelist for name in class_names], dtype=np.bool_)

        return class_names, mask

    def is_ready(self) -> bool:
        return self.session is not None

    def create_session(
        self,
        threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        max_frames: int = DEFAULT_MAX_FRAMES,
        frame_interval: float = DEFAULT_FRAME_INTERVAL,
        frame_size: tuple[int, int] = DEFAULT_FRAME_SIZE,
    ) -> "X3DActionRecognizer":
        """Create a per-connection recognizer session backed by this model."""
        return X3DActionRecognizer(
            model=self,
            threshold=threshold,
            max_frames=max_frames,
            frame_interval=frame_interval,
            frame_size=frame_size,
        )


class X3DActionRecognizer(HumanActionRecognizer):
    """Per-connection action recognizer session.

    Shares the ONNX model with other sessions but maintains its own
    frame buffer, whitelist mask, and timing state.
    """

    def __init__(
        self,
        model: X3DModel,
        threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        max_frames: int = DEFAULT_MAX_FRAMES,
        frame_interval: float = DEFAULT_FRAME_INTERVAL,
        frame_size: tuple[int, int] = DEFAULT_FRAME_SIZE,
    ):
        self._model = model
        self._threshold = threshold
        self._max_frames = max_frames
        self._frame_interval = frame_interval
        self._frame_size = frame_size

        self._class_mask: npt.NDArray[np.bool_] = model.default_mask.copy()
        self._threshold: float = 0.3
        self._frame_buffer: deque[npt.NDArray[np.uint8]] = deque()
        self._last_ts: float = 0
        self._last_detected: list[tuple[str, float]] = []

    def set_config(self, whitelist: list[str] | None, threshold: float = 0.8) -> None:
        self._threshold = threshold

        if whitelist is None:
            self._class_mask = self._model.default_mask.copy()
        else:
            allowed = set(whitelist)
            self._class_mask = np.array(
                [name in allowed for name in self._model.class_names], dtype=np.bool_
            )
        logger.info(
            "Config updated — %d classes enabled, threshold=%f",
            int(self._class_mask.sum()),
            round(threshold, 2),
        )

    def _preprocess(self, frame: npt.NDArray[np.uint8]) -> npt.NDArray[np.uint8]:
        frame_rgb = cast(npt.NDArray[np.uint8], cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        h, w = frame_rgb.shape[:2]
        target_h, target_w = self._frame_size
        r = max(target_w / w, target_h / h)
        resized = cast(npt.NDArray[np.uint8], cv2.resize(frame_rgb, None, fx=r, fy=r))
        nh, nw = resized.shape[:2]
        half_h, half_w = target_h // 2, target_w // 2
        return resized[nh // 2 - half_h : nh // 2 + half_h, nw // 2 - half_w : nw // 2 + half_w]

    def _infer(self) -> list[tuple[str, float]]:
        frames = np.stack(list(self._frame_buffer), axis=0).astype(np.float32)
        t, h, w, c = frames.shape
        norm_frames = (frames - X3DModel.MEAN) / X3DModel.STD

        if t < self._max_frames:
            pad = np.zeros((self._max_frames - t, h, w, c), dtype=np.float32)
            tensor = np.concatenate([norm_frames, pad], axis=0)
        else:
            tensor = norm_frames

        # Shape: (1, 1, C, T, H, W)
        tensor = tensor.transpose(3, 0, 1, 2)[None, None, ...]

        (pred,) = self._model.session.run(["pred"], {"input": tensor})
        pred = cast(npt.NDArray[np.float32], pred)

        # Softmax over whitelisted classes only
        pred = np.exp(pred - pred.max())
        pred[:, ~self._class_mask] = 0
        total = np.sum(pred, axis=-1, keepdims=True)
        if total.item() == 0:
            return []
        pred = pred / total

        # Collect classes above threshold
        scores = pred[0]
        results = []
        for idx in np.argsort(scores)[::-1]:
            score = float(scores[idx])
            if score < self._threshold:
                break
            results.append((self._model.class_names[idx], score))

        return results

    def update(self, frame: npt.NDArray[np.uint8]) -> ActionResponse | None:
        cur_ts = time.time()
        if cur_ts - self._last_ts >= self._frame_interval:
            processed = self._preprocess(frame)
            self._frame_buffer.append(processed)
            while len(self._frame_buffer) > self._max_frames:
                _ = self._frame_buffer.popleft()

            self._last_detected = self._infer()
            self._last_ts = cur_ts

        for name, conf in self._last_detected:
            logger.info("Detected '%s' (%.3f)", name, conf)

        return ActionResponse(detected_classes=self._last_detected)

    def is_ready(self) -> bool:
        return self._model.is_ready()
