"""Pose estimation pipeline: model lifecycle and session management."""

from typing_extensions import override

from core.models.pose import PosePerceptionSessionConfig
from core.perception.base import PerceptionBase
from core.perception.pose.predictors.ergo.base import ErgoAssessor
from core.perception.pose.predictors.pose2d.base import PoseEstimator2D
from core.perception.pose.predictors.pose3d.base import PoseEstimator3DLifting
from core.perception.pose.session import PosePerceptionSession


class PosePerception(PerceptionBase[PosePerceptionSession]):
    """Pose estimation pipeline. Loaded once, shared by all WS sessions."""

    def __init__(
        self,
        estimator_2d: PoseEstimator2D,
        lifter_3d: PoseEstimator3DLifting | None = None,
        ergo_assessor: ErgoAssessor | None = None,
        default_config: PosePerceptionSessionConfig | None = None,
    ) -> None:
        super().__init__()

        self._estimator_2d: PoseEstimator2D = estimator_2d
        self._lifter_3d: PoseEstimator3DLifting | None = lifter_3d
        self._ergo_assessor: ErgoAssessor | None = ergo_assessor
        self._default_config: PosePerceptionSessionConfig | None = default_config

        self._running: bool = False

    @override
    def start(self) -> None:
        if self._running:
            self._logger.info("Already running")
            return

        self._estimator_2d.start()

        if self._lifter_3d is not None:
            self._lifter_3d.start()

        if self._ergo_assessor is not None:
            self._ergo_assessor.start()

        self._running = True
        self._logger.info("Ready")

    @override
    def stop(self) -> None:
        self._estimator_2d.stop()

        if self._lifter_3d is not None:
            self._lifter_3d.stop()

        if self._ergo_assessor is not None:
            self._ergo_assessor.stop()

        self._running = False
        self._logger.info("Stopped")

    @override
    def is_ready(self) -> bool:
        if not self._estimator_2d.is_ready():
            return False
        if self._lifter_3d is not None and not self._lifter_3d.is_ready():
            return False
        return self._running

    @override
    def create_session(self) -> PosePerceptionSession:
        config = self._default_config or PosePerceptionSession.DEFAULT_CONFIG
        return PosePerceptionSession(
            estimator_2d=self._estimator_2d,
            lifter_3d=self._lifter_3d,
            ergo_assessor=self._ergo_assessor,
            config=config,
        )
