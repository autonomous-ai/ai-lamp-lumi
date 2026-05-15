"""Factory functions for pose estimators, 3D lifters, and ergonomic assessors."""

from pathlib import Path

from core.enums.pose import ErgoAssessorEnum, PoseEstimator2DEnum, PoseLifter3DEnum
from core.perception.pose.predictors.ergo.base import ErgoAssessor
from core.perception.pose.predictors.pose2d.base import PoseEstimator2D
from core.perception.pose.predictors.pose3d.base import PoseEstimator3DLifting


def create_estimator_2d(
    model_name: PoseEstimator2DEnum,
    model_path: Path | None = None,
) -> PoseEstimator2D:
    """Instantiate the correct 2D pose estimator."""
    if model_name == PoseEstimator2DEnum.RTMPOSE:
        from core.perception.pose.predictors.pose2d.rtmpose import RTMPose2D as estimator_cls
    else:
        raise ValueError(f"Unknown 2D pose estimator: {model_name}")

    return estimator_cls(model_path=model_path)


def create_lifter_3d(
    model_name: PoseLifter3DEnum,
    model_path: Path | None = None,
    input_size: tuple[int, int] | None = None,
    n_frames: int | None = None,
) -> PoseEstimator3DLifting:
    """Instantiate the correct 3D pose lifter."""
    if model_name == PoseLifter3DEnum.TCPFORMER:
        from core.perception.pose.predictors.pose3d.tcpformer import TCPFormer3D as lifter_cls
    else:
        raise ValueError(f"Unknown 3D pose lifter: {model_name}")

    return lifter_cls(model_path=model_path, input_size=input_size, n_frames=n_frames)


def create_ergo_assessor(
    model_name: ErgoAssessorEnum,
    confidence_threshold: float | None = None,
    muscle_use_score: int | None = None,
    force_load_score: int | None = None,
) -> ErgoAssessor:
    """Instantiate the correct ergonomic assessor."""
    if model_name == ErgoAssessorEnum.RULA:
        from core.perception.pose.predictors.ergo.rula import RULAAssessor as assessor_cls
    else:
        raise ValueError(f"Unknown ergonomic assessor: {model_name}")

    return assessor_cls(
        confidence_threshold=confidence_threshold,
        muscle_use_score=muscle_use_score,
        force_load_score=force_load_score,
    )
