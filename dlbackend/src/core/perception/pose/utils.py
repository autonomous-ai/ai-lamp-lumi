"""Factory functions for pose estimators, 3D lifters, and ergonomic assessors."""

from pathlib import Path

from core.enums.pose import ErgoAssessorEnum, PoseEstimator2DEnum, PoseLifter3DEnum
from core.perception.pose.ergo.base import ErgoAssessor
from core.perception.pose.pose2d.base import PoseEstimator2D
from core.perception.pose.pose3d.base import PoseEstimator3DLifting


def create_estimator_2d(
    model_name: PoseEstimator2DEnum,
    model_path: Path | None = None,
) -> PoseEstimator2D:
    """Instantiate the correct 2D pose estimator."""
    if model_name == PoseEstimator2DEnum.RTMPOSE:
        from core.perception.pose.pose2d.rtmpose import RTMPose2D

        return RTMPose2D(model_path=model_path)
    else:
        raise ValueError(f"Unknown 2D pose estimator: {model_name}")


def create_lifter_3d(
    model_name: PoseLifter3DEnum,
    model_path: Path | None = None,
    frame_size: tuple[int, int] | None = None,
    n_frames: int | None = None,
) -> PoseEstimator3DLifting:
    """Instantiate the correct 3D pose lifter."""
    if model_name == PoseLifter3DEnum.TCPFORMER:
        from core.perception.pose.pose3d.tcpformer import TCPFormer3D

        kwargs: dict = {}
        if model_path is not None:
            kwargs["model_path"] = model_path
        if frame_size is not None:
            kwargs["frame_size"] = frame_size
        if n_frames is not None:
            kwargs["n_frames"] = n_frames
        return TCPFormer3D(**kwargs)
    else:
        raise ValueError(f"Unknown 3D pose lifter: {model_name}")


def create_ergo_assessor(
    model_name: ErgoAssessorEnum,
    confidence_threshold: float | None = None,
    muscle_use_score: int = 0,
    force_load_score: int = 0,
) -> ErgoAssessor:
    """Instantiate the correct ergonomic assessor."""
    if model_name == ErgoAssessorEnum.RULA:
        from core.perception.pose.ergo.rula import RULAAssessor

        kwargs: dict = {
            "muscle_use_score": muscle_use_score,
            "force_load_score": force_load_score,
        }
        if confidence_threshold is not None:
            kwargs["confidence_threshold"] = confidence_threshold
        return RULAAssessor(**kwargs)
    else:
        raise ValueError(f"Unknown ergonomic assessor: {model_name}")
