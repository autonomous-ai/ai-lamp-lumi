"""X3D video action recognition-based human action recognizer.

Buffers frames at a configurable interval and runs them through an
X3D ONNX model to classify actions from 400 Kinetics action classes.
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


class X3DActionRecognizer(HumanActionRecognizer):
    """X3D ONNX-based human action recognizer.

    Buffers BGR frames and runs X3D inference at a configurable interval,
    returning the top detected actions that pass the confidence threshold.
    A whitelist can be set to filter which action classes are considered.
    """

    MEAN: npt.NDArray[np.float32] = np.array([114.75, 114.75, 114.75], dtype=np.float32)
    STD: npt.NDArray[np.float32] = np.array([57.38, 57.38, 57.38], dtype=np.float32)

    def __init__(
        self,
        model_path: Path | None = None,
        threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        max_frames: int = DEFAULT_MAX_FRAMES,
        frame_interval: float = DEFAULT_FRAME_INTERVAL,
        frame_size: tuple[int, int] = DEFAULT_FRAME_SIZE,
    ):
        if model_path is None:
            model_path = RESOURCES_DIR / "x3d_m_16x5x1_int8.onnx"

        self._threshold = threshold
        self._max_frames = max_frames
        self._frame_interval = frame_interval
        self._frame_size = frame_size

        self._session: ort.InferenceSession | None = None
        self._model_path = model_path
        self._class_names: list[str] = []
        self._class_mask: npt.NDArray[np.bool_] | None = None
        self._frame_buffer: deque[npt.NDArray[np.uint8]] = deque()
        self._last_ts: float = 0

        self._load_model()

    def _load_model(self) -> None:
        logger.info("Loading X3D model from %s", self._model_path)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.add_session_config_entry("session.dynamic_block_base", "4")
        self._session = ort.InferenceSession(
            str(self._model_path), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self._class_names, self._class_mask = self._load_classes()
        logger.info(
            "X3D model loaded — %d classes, %d whitelisted",
            len(self._class_names),
            int(self._class_mask.sum()),
        )

    def _load_classes(self) -> tuple[list[str], npt.NDArray[np.bool_]]:
        classes_path = RESOURCES_DIR / "kinect_classes.txt"
        whitelist_path = RESOURCES_DIR / "white_list.txt"

        class_names = classes_path.read_text().strip().split("\n")
        mask = np.ones(len(class_names), dtype=np.bool_)

        if whitelist_path.exists():
            whitelist = set(whitelist_path.read_text().strip().split("\n"))
            mask = np.array([name in whitelist for name in class_names], dtype=np.bool_)

        return class_names, mask

    def set_whitelist(self, whitelist: list[str] | None) -> None:
        """Set or clear the action whitelist.

        When set, only actions in the whitelist will have non-zero probability.
        When None, all classes from the default whitelist file are used.
        """
        if whitelist is None:
            _, self._class_mask = self._load_classes()
        else:
            allowed = set(whitelist)
            self._class_mask = np.array(
                [name in allowed for name in self._class_names], dtype=np.bool_
            )
        logger.info("Whitelist updated — %d classes enabled", int(self._class_mask.sum()))

    def _preprocess(self, frame: npt.NDArray[np.uint8]) -> npt.NDArray[np.uint8]:
        """Resize and center-crop a BGR frame to the target size."""
        frame_rgb = cast(npt.NDArray[np.uint8], cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        h, w = frame_rgb.shape[:2]
        target_h, target_w = self._frame_size
        r = max(target_w / w, target_h / h)
        resized = cast(npt.NDArray[np.uint8], cv2.resize(frame_rgb, None, fx=r, fy=r))
        nh, nw = resized.shape[:2]
        half_h, half_w = target_h // 2, target_w // 2
        return resized[nh // 2 - half_h : nh // 2 + half_h, nw // 2 - half_w : nw // 2 + half_w]

    def _infer(self) -> list[tuple[str, float]]:
        """Run X3D inference on the buffered frames."""
        frames = np.stack(list(self._frame_buffer), axis=0).astype(np.float32)
        t, h, w, c = frames.shape
        norm_frames = (frames - self.MEAN) / self.STD

        if t < self._max_frames:
            pad = np.zeros((self._max_frames - t, h, w, c), dtype=np.float32)
            tensor = np.concatenate([norm_frames, pad], axis=0)
        else:
            tensor = norm_frames

        # Shape: (1, 1, C, T, H, W)
        tensor = tensor.transpose(3, 0, 1, 2)[None, None, ...]

        (pred,) = self._session.run(["pred"], {"input": tensor})
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
            results.append((self._class_names[idx], score))

        return results

    def update(self, frame: npt.NDArray[np.uint8]) -> ActionResponse | None:
        """Buffer a frame and run X3D inference when the interval elapses.

        Returns ActionResponse with detected classes, or None if not enough
        time has passed since the last inference.
        """
        cur_ts = time.time()
        if cur_ts - self._last_ts < self._frame_interval:
            return None

        processed = self._preprocess(frame)
        self._frame_buffer.append(processed)
        while len(self._frame_buffer) > self._max_frames:
            self._frame_buffer.popleft()

        detected = self._infer()
        self._last_ts = cur_ts

        if not detected:
            return ActionResponse(detected_classes=[])

        for name, conf in detected:
            logger.info("Detected '%s' (%.3f)", name, conf)

        return ActionResponse(detected_classes=detected)

    def is_ready(self) -> bool:
        return self._session is not None
