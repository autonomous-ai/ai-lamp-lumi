"""Abstract base class for human action recognizer models.

Pure ONNX model wrapper: load weights, preprocess frames, run inference.
Session management, person detection, and config live in ActionAnalysis.
"""

import logging
from abc import ABC
from collections import deque
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import cv2
import numpy as np
import numpy.typing as npt
import onnxruntime as ort

from core.perception.action.constants import RESOURCES_DIR

logger = logging.getLogger(__name__)


class HumanActionRecognizerModel(ABC):
    """Base interface for all action recognition ONNX models."""

    DEFAULT_MODEL: Path | None = None
    DEFAULT_CLASSES_PATH: Path = RESOURCES_DIR / "kinect_classes.txt"
    DEFAULT_WHITELIST_PATH: Path | None = None

    MEAN: npt.NDArray[np.float32] = np.array([0, 0, 0], dtype=np.float32)
    STD: npt.NDArray[np.float32] = np.array([0, 0, 0], dtype=np.float32)

    def __init__(
        self,
        model_path: Path | None,
        max_frames: int,
        frame_size: tuple[int, int],
    ):
        if model_path is None:
            model_path = self.__class__.DEFAULT_MODEL
        if model_path is None:
            msg = f"{self.__class__.__name__} model_path cannot be None"
            raise ValueError(msg)

        self._max_frames: int = max_frames
        self._frame_size: tuple[int, int] = frame_size
        self._class_names: list[str] = []
        self._default_mask: npt.NDArray[np.bool_] = np.ones(0, dtype=np.bool_)

        self._model_path: Path = model_path
        self._running: bool = False
        self._session: ort.InferenceSession | None = None
        self._logger: logging.Logger = logging.getLogger(self.__class__.__name__)

    @property
    def max_frames(self) -> int:
        return self._max_frames

    @property
    def frame_size(self) -> tuple[int, int]:
        return self._frame_size

    @property
    def class_names(self) -> list[str]:
        return self._class_names

    @property
    def default_mask(self) -> npt.NDArray[np.bool_]:
        return self._default_mask

    def start(self) -> None:
        if self._running:
            self._logger.info("[%s] Model is already running", self.__class__.__name__)
            return

        self._logger.info("[%s] Loading model from %s", self.__class__.__name__, self._model_path)
        self._session = self._prepare_session(self._model_path)
        class_names, default_mask = self._load_classes()
        self._class_names = class_names
        self._default_mask = default_mask
        self._running = True

        self._logger.info(
            "[%s] Model loaded - %d classes, %d whitelisted",
            self.__class__.__name__,
            len(self._class_names),
            int(self._default_mask.sum()),
        )

    def stop(self) -> None:
        self._session = None
        self._running = False
        self._logger.info("[%s] stopped", self.__class__.__name__)

    def is_ready(self) -> bool:
        return self._running and self._session is not None

    def preprocess(
        self,
        new_frame: npt.NDArray[np.uint8],
        frame_buffer: deque[npt.NDArray[np.uint8]],
    ) -> deque[npt.NDArray[np.uint8]]:
        """Resize, center-crop, and append to frame buffer."""
        frame_rgb = cast(npt.NDArray[np.uint8], cv2.cvtColor(new_frame, cv2.COLOR_BGR2RGB))

        h, w = frame_rgb.shape[:2]
        target_h, target_w = self._frame_size
        r = max(target_w / w, target_h / h)
        resized = cast(npt.NDArray[np.uint8], cv2.resize(frame_rgb, None, fx=r, fy=r))
        nh, nw = resized.shape[:2]
        half_h, half_w = target_h // 2, target_w // 2
        preprocessed_frame = resized[
            nh // 2 - half_h : nh // 2 + half_h, nw // 2 - half_w : nw // 2 + half_w
        ]

        frame_buffer.append(preprocessed_frame)
        while len(frame_buffer) > self._max_frames:
            _ = frame_buffer.popleft()

        return frame_buffer

    def predict(
        self,
        frame_buffer: Sequence[npt.NDArray[np.uint8]],
        class_mask: npt.NDArray[np.bool_] | None = None,
    ) -> list[tuple[str, float]]:
        """Run inference on buffered frames, return (class_name, score) pairs."""
        if self._session is None:
            raise RuntimeError("Session has not been started yet.")

        frames = np.stack(frame_buffer, axis=0).astype(np.float32)
        t, h, w, c = frames.shape
        norm_frames = (frames - self.__class__.MEAN) / self.__class__.STD

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
        if class_mask is not None:
            class_mask = np.logical_and(class_mask, self._default_mask)
        else:
            class_mask = self._default_mask

        total = np.sum(pred, axis=-1, keepdims=True)
        if total.item() == 0:
            return []

        pred = pred / total
        pred[:, ~class_mask] = 0

        scores = pred[0]
        results = [
            (self._class_names[int(idx)], scores[int(idx)]) for idx in np.where(class_mask)[0]
        ]
        results = sorted(results, key=lambda x: x[1], reverse=True)
        return results

    def _prepare_session(self, model_path: Path) -> ort.InferenceSession:
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 0
        opts.inter_op_num_threads = 0
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.add_session_config_entry("session.dynamic_block_base", "4")
        providers: list[str] = []
        if "CUDAExecutionProvider" in ort.get_available_providers():
            providers.append("CUDAExecutionProvider")
        providers.append("CPUExecutionProvider")

        session = ort.InferenceSession(str(model_path), sess_options=opts, providers=providers)
        self._logger.info("ONNX providers: %s", session.get_providers())
        return session

    @classmethod
    def _load_classes(cls) -> tuple[list[str], npt.NDArray[np.bool_]]:
        classes_path = cls.DEFAULT_CLASSES_PATH
        whitelist_path = cls.DEFAULT_WHITELIST_PATH

        class_names = classes_path.read_text().strip().split("\n")
        mask = np.ones(len(class_names), dtype=np.bool_)

        if whitelist_path is not None and whitelist_path.exists():
            whitelist = set(whitelist_path.read_text().strip().split("\n"))
            mask = np.array([name in whitelist for name in class_names], dtype=np.bool_)

        return class_names, mask
