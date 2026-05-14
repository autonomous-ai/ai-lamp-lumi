import logging
from abc import ABC
from pathlib import Path

import cv2
import cv2.typing as cv2t
import numpy as np
import numpy.typing as npt
import onnxruntime as ort

from core.enums.pose import GraphEnum
from core.models.pose import Point2D, Pose2D

RESOURCES_DIR = Path(__file__).parent / "resources"


class PoseEstimator2D(ABC):
    GRAPH_TYPE: GraphEnum
    DEFAULT_MODEL: Path

    DEFAULT_FRAME_SIZE: tuple[int, int]

    INPUT_MEAN: npt.NDArray[np.float32]
    INPUT_STD: npt.NDArray[np.float32]

    def __init__(self, model_path: Path | None = None, frame_size: tuple[int, int] | None = None):
        if model_path is None:
            model_path = self.DEFAULT_MODEL

        if frame_size is None:
            frame_size = self.DEFAULT_FRAME_SIZE

        self._model_path: Path = model_path
        self._input_w: int = int(frame_size[0])
        self._input_h: int = int(frame_size[1])

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

    def predict(self, frame: cv2t.MatLike) -> Pose2D:
        keypoints, scores = self.predict_raw(frame)
        # (N, K, 2) → take first batch
        kps = keypoints[0]
        confs = scores[0]

        joints = [Point2D(x=float(kps[i, 0]), y=float(kps[i, 1])) for i in range(len(kps))]

        return Pose2D(
            graph_type=self.GRAPH_TYPE,
            joints=joints,
            confs=[float(c) for c in confs],
        )

    def predict_raw(
        self, frame: cv2t.MatLike
    ) -> tuple[npt.NDArray[np.float32], npt.NDArray[np.float32]]:
        """Return raw (N, K, 2) keypoints and (N, K) scores arrays.

        Useful for downstream consumers that need numpy arrays
        (e.g. 3D lifting, motion analysis) rather than Pydantic models.
        """
        if self._session is None:
            raise RuntimeError("RTMPose2D session not started")

        H, W = frame.shape[:2]
        inp = self._preprocess(frame)
        simcc_x, simcc_y = self._session.run(["simcc_x", "simcc_y"], {"input": inp})
        simcc_x = np.asarray(simcc_x, dtype=np.float32)
        simcc_y = np.asarray(simcc_y, dtype=np.float32)

        loc_x = simcc_x.argmax(-1) * W / self._input_w * 0.5
        loc_y = simcc_y.argmax(-1) * H / self._input_h * 0.5
        keypoints = np.stack([loc_x, loc_y], axis=-1).astype(np.float32)
        scores = np.minimum(simcc_x.max(-1), simcc_y.max(-1)).astype(np.float32)

        return keypoints, scores

    def _preprocess(self, frame: cv2t.MatLike) -> npt.NDArray[np.float32]:
        img = cv2.resize(frame, (self._input_w, self._input_h))
        img = (img.astype(np.float32) - self.INPUT_MEAN) / self.INPUT_STD
        return np.expand_dims(img.transpose(2, 0, 1), axis=0).astype(np.float32)

    @staticmethod
    def _prepare_session(model_path: Path, n_threads: int = 4) -> ort.InferenceSession:
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = n_threads
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.add_session_config_entry("session.dynamic_block_base", "4")
        providers: list[str] = []
        if "CUDAExecutionProvider" in ort.get_available_providers():
            providers.append("CUDAExecutionProvider")
        providers.append("CPUExecutionProvider")
        return ort.InferenceSession(str(model_path), sess_options=opts, providers=providers)
