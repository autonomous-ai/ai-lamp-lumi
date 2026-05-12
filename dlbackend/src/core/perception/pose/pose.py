"""Pose analysis: 2D estimation, optional 3D lifting, and session management.

Wraps a PoseEstimator2D + optional PoseEstimator3DLifting.
Each connection creates a PoseSession via create_session().
"""

import logging
import time
from typing import Any

import cv2.typing as cv2t
import numpy as np
import numpy.typing as npt

from core.models.pose import Point2D, Point3D, Pose2D, Pose3D
from core.perception.pose.graph import coco_to_h36m
from core.perception.pose.pose2d.base import PoseEstimator2D
from core.perception.pose.pose3d.base import PoseEstimator3DLifting


class PoseAnalysis:
    """Pose estimation pipeline. Loaded once, shared by all sessions.

    Runs 2D pose estimation and optionally lifts to 3D.
    """

    DEFAULT_FRAME_INTERVAL: float = 0.0

    def __init__(
        self,
        estimator_2d: PoseEstimator2D,
        lifter_3d: PoseEstimator3DLifting | None = None,
        frame_interval: float | None = None,
    ):
        self._estimator_2d: PoseEstimator2D = estimator_2d
        self._lifter_3d: PoseEstimator3DLifting | None = lifter_3d
        self._frame_interval: float | None = frame_interval
        self._running: bool = False
        self._logger: logging.Logger = logging.getLogger(self.__class__.__name__)

    def start(self) -> None:
        if self._running:
            self._logger.info("[%s] already running", self.__class__.__name__)
            return

        self._estimator_2d.start()
        if self._lifter_3d is not None:
            self._lifter_3d.start()
        self._running = True
        self._logger.info(
            "[%s] ready (3D=%s)", self.__class__.__name__, self._lifter_3d is not None
        )

    def stop(self) -> None:
        self._estimator_2d.stop()
        if self._lifter_3d is not None:
            self._lifter_3d.stop()
        self._running = False
        self._logger.info("[%s] stopped", self.__class__.__name__)

    def is_ready(self) -> bool:
        if not self._running or not self._estimator_2d.is_ready():
            return False
        if self._lifter_3d is not None and not self._lifter_3d.is_ready():
            return False
        return True

    def create_session(
        self,
        frame_interval: float | None = None,
    ) -> "PoseSession":
        if frame_interval is None:
            frame_interval = (
                self._frame_interval
                if self._frame_interval is not None
                else self.DEFAULT_FRAME_INTERVAL
            )
        return PoseSession(
            estimator_2d=self._estimator_2d,
            lifter_3d=self._lifter_3d,
            frame_interval=frame_interval,
        )


class PoseSession:
    """Per-connection session for pose estimation."""

    def __init__(
        self,
        estimator_2d: PoseEstimator2D,
        lifter_3d: PoseEstimator3DLifting | None,
        frame_interval: float,
    ):
        self._estimator_2d: PoseEstimator2D = estimator_2d
        self._lifter_3d: PoseEstimator3DLifting | None = lifter_3d
        self._frame_interval: float = frame_interval
        self._last_ts: float = 0
        self._last_result_cache: dict[str, Any] | None = None
        self._h36m_kps_buffer: list[npt.NDArray[np.float32]] = []
        self._h36m_scores_buffer: list[npt.NDArray[np.float32]] = []
        self._logger: logging.Logger = logging.getLogger(self.__class__.__name__)

    def update(self, frame: cv2t.MatLike) -> dict[str, Any] | None:
        """Run pose estimation if enough time has passed.

        Returns a dict with "pose_2d" (always) and "pose_3d" (when lifter
        is configured), or None if skipping this frame.
        """
        cur_ts: float = time.time()
        if cur_ts - self._last_ts < self._frame_interval:
            return self._last_result_cache

        # 2D estimation
        keypoints, scores = self._estimator_2d.predict_raw(frame)
        kps: npt.NDArray[np.float32] = keypoints[0]
        confs: npt.NDArray[np.float32] = scores[0]

        pose_2d: Pose2D = Pose2D(
            graph_type=self._estimator_2d.GRAPH_TYPE,
            joints=[Point2D(x=float(kps[i, 0]), y=float(kps[i, 1])) for i in range(len(kps))],
            confs=[float(c) for c in confs],
        )

        result: dict[str, Any] = {"pose_2d": pose_2d}

        # Optional 3D lifting — accumulate frames in buffer
        if self._lifter_3d is not None:
            h36m_kps, h36m_scores = coco_to_h36m(keypoints, scores)
            self._h36m_kps_buffer.append(h36m_kps[0])
            self._h36m_scores_buffer.append(h36m_scores[0])

            kps_stack: npt.NDArray[np.float32] = np.stack(self._h36m_kps_buffer, axis=0)
            scores_stack: npt.NDArray[np.float32] = np.stack(self._h36m_scores_buffer, axis=0)

            output: npt.NDArray[np.float32] | None = self._lifter_3d.predict_raw(
                kps_stack, scores_stack
            )
            if output is not None:
                pose_3d: Pose3D = Pose3D(
                    graph_type=self._lifter_3d.GRAPH_TYPE,
                    joints=[
                        Point3D(x=float(output[i, 0]), y=float(output[i, 1]), z=float(output[i, 2]))
                        for i in range(len(output))
                    ],
                    confs=[float(c) for c in h36m_scores[0]],
                )
                result["pose_3d"] = pose_3d

        self._last_ts = cur_ts
        self._last_result_cache = result
        return result

    def set_config(
        self,
        frame_interval: float | None = None,
    ) -> None:
        """Update session config."""
        if frame_interval is not None:
            self._frame_interval = frame_interval
        self._logger.info(
            "[%s] Config updated — frame_interval=%f",
            self.__class__.__name__,
            self._frame_interval,
        )

    def is_ready(self) -> bool:
        if not self._estimator_2d.is_ready():
            return False
        if self._lifter_3d is not None and not self._lifter_3d.is_ready():
            return False
        return True
