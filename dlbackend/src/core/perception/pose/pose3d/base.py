import logging
from abc import ABC
from pathlib import Path
from typing import cast

import numpy as np
import numpy.typing as npt
import onnxruntime as ort

from core.enums.pose import GraphEnum
from core.models.pose import Point3D, Pose3D


class PoseEstimator3DLifting(ABC):
    GRAPH_TYPE: GraphEnum

    DEFAULT_MODEL: Path

    DEFAULT_N_FRAMES: int
    DEFAULT_FRAME_SIZE: tuple[int, int]

    def __init__(
        self,
        model_path: Path | None = None,
        frame_size: tuple[int, int] | None = None,
        n_frames: int | None = None,
    ):
        """
        Args:
            model_path: Path to the TCPFormer ONNX model.
            frame_size: (width, height) of the input video, used to
                        normalize 2D coordinates to [-1, 1].
            n_frames:   Number of frames in the temporal buffer.
        """
        if model_path is None:
            model_path = self.DEFAULT_MODEL

        if frame_size is None:
            frame_size = self.DEFAULT_FRAME_SIZE

        if n_frames is None:
            n_frames = self.DEFAULT_N_FRAMES

        self._model_path: Path = model_path
        self._input_w: int = int(frame_size[0])
        self._input_h: int = int(frame_size[1])
        self._n_frames: int = n_frames
        self._session: ort.InferenceSession | None = None
        self._running: bool = False

        self._logger: logging.Logger = logging.getLogger(self.__class__.__name__)

    def start(self) -> None:
        if self._running:
            self._logger.info("[%s] already running", self.__class__.__name__)
            return
        self._logger.info("[%s] Loading model from %s", self.__class__.__name__, self._model_path)
        self._session = self._prepare_session(self._model_path)
        self._running = True
        self._logger.info("[%s] ready", self.__class__.__name__)

    def stop(self) -> None:
        self._session = None
        self._running = False

    def is_ready(self) -> bool:
        return self._running and self._session is not None

    def predict(
        self,
        keypoints: npt.NDArray[np.float32],
        scores: npt.NDArray[np.float32],
    ) -> Pose3D | None:
        """Lift 2D H36M keypoints to 3D.

        Args:
            keypoints: (17, 2) H36M keypoints in pixel coordinates.
            scores:    (17,) confidence scores.

        Returns:
            Pose3D with H36M joints, or None if the buffer is not yet full.
        """
        output = self.predict_raw(keypoints, scores)
        if output is None:
            return None

        joints = [
            Point3D(x=float(output[i, 0]), y=float(output[i, 1]), z=float(output[i, 2]))
            for i in range(len(output))
        ]
        return Pose3D(
            graph_type=self.GRAPH_TYPE,
            joints=joints,
            confs=[float(s) for s in scores],
        )

    def predict_raw(
        self,
        keypoints: npt.NDArray[np.float32],
        scores: npt.NDArray[np.float32],
    ) -> npt.NDArray[np.float32] | None:
        """Lift 2D H36M keypoints to 3D, returning raw (17, 3) array.

        Returns None if there are fewer than half of n_frames accumulated.
        """
        if self._session is None:
            raise RuntimeError("Lifter session not started")

        T: int = keypoints.shape[0]
        if T < self._n_frames // 2:
            return None

        frames = self._normalize_2d(keypoints, scores)
        inp = frames[np.newaxis].astype(np.float32)  # (1, n_frames, 17, 3)

        (output,) = self._session.run(["output"], {"input": inp})
        output = cast(npt.NDArray[np.float32], output)
        # output: (1, n_frames, 17, 3) -- take the last frame
        return output[0, -1]  # (17, 3)

    def _normalize_2d(
        self,
        keypoints: npt.NDArray[np.float32],
        scores: npt.NDArray[np.float32],
    ) -> npt.NDArray[np.float32]:
        """Normalize 2D keypoints to [-1, 1] and append confidence.

        Args:
            keypoints: (T, 17, 2) H36M keypoints in pixel coordinates.
            scores:    (T, 17,) confidence scores.

        Returns:
            (T, 17, 3) array of (norm_x, norm_y, confidence).
        """
        norm_kps = keypoints.copy()
        norm_kps[..., 0] = norm_kps[..., 0] / self._input_w * 2 - 1
        norm_kps[..., 1] = norm_kps[..., 1] / self._input_w * 2 - self._input_h / self._input_h
        norm = np.concatenate([norm_kps, scores[..., None]], axis=-1).astype(np.float32)
        if norm.shape[0] < self._n_frames:
            norm = np.concatenate(
                [norm, np.zeros((self._n_frames - norm.shape[0], *norm.shape[1:]), dtype=norm.dtype)],
                axis=0,
            )
        return norm

    @staticmethod
    def _prepare_session(model_path: Path, n_threads: int = 4) -> ort.InferenceSession:
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = n_threads
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        providers: list[str] = []
        if "CUDAExecutionProvider" in ort.get_available_providers():
            providers.append("CUDAExecutionProvider")
        providers.append("CPUExecutionProvider")
        return ort.InferenceSession(str(model_path), sess_options=opts, providers=providers)
