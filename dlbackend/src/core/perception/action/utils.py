"""Factory functions for action recognizer models."""

from pathlib import Path

from core.enums import HumanActionRecognizerEnum
from core.perception.action.recognizer.base import HumanActionRecognizerModel


def create_recognizer(
    model_name: HumanActionRecognizerEnum,
    model_path: Path | None,
    max_frames: int | None = None,
    frame_size: tuple[int, int] | None = None,
) -> HumanActionRecognizerModel:
    """Instantiate the correct recognizer model."""
    if model_name == HumanActionRecognizerEnum.VIDEOMAE:
        from core.perception.action.recognizer.videomae import VideoMAEModel as cls
    elif model_name == HumanActionRecognizerEnum.UNIFORMERV2:
        from core.perception.action.recognizer.uniformerv2 import UniformerV2Model as cls
    elif model_name == HumanActionRecognizerEnum.X3D:
        from core.perception.action.recognizer.x3d import X3DModel as cls
    else:
        msg = f"Unknown action recognition model: {model_name}"
        raise ValueError(msg)

    mf = max_frames if max_frames is not None else cls.DEFAULT_MAX_FRAMES
    fs = frame_size if frame_size is not None else cls.DEFAULT_FRAME_SIZE
    return cls(model_path, max_frames=mf, frame_size=fs)
