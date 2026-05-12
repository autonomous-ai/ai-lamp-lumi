"""Factory functions for pose estimators and 3D lifters."""

from pathlib import Path

from core.enums.pose import PoseEstimator2DEnum, PoseLifter3DEnum
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
) -> PoseEstimator3DLifting:
    """Instantiate the correct 3D pose lifter."""
    if model_name == PoseLifter3DEnum.TCPFORMER:
        from core.perception.pose.pose3d.tcpformer import TCPFormer3D

        kwargs: dict = {}
        if model_path is not None:
            kwargs["model_path"] = model_path
        if frame_size is not None:
            kwargs["frame_size"] = frame_size
        return TCPFormer3D(**kwargs)
    else:
        raise ValueError(f"Unknown 3D pose lifter: {model_name}")
