"""Application configuration loaded from environment variables."""

from typing import ClassVar

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.enums import (
    EmotionRecognizerEnum,
    HumanActionRecognizerEnum,
    PersonDetectorEnum,
    PoseEstimator2DEnum,
    SpeechEmotionRecognizerEnum,
)
from core.enums.pose import PoseLifter3DEnum


class PersonDetectorSetting(BaseModel):
    enabled: bool = False
    model: PersonDetectorEnum = PersonDetectorEnum.YOLO
    model_name: str = "yolo12x.pt"
    confidence_threshold: float = 0.4
    bbox_expand_scale: float = 2.0
    min_area_ratio: float = 0.25  # skip persons covering less than 1/4 of frame


class ActionSetting(BaseModel):
    enabled: bool = True
    model: HumanActionRecognizerEnum = HumanActionRecognizerEnum.X3D
    ckpt_path: str | None = None
    # Optional overrides — None means use model-specific class defaults
    confidence_threshold: float | None = None
    max_frames: int | None = None
    frame_interval: float | None = None
    w: int | None = None
    h: int | None = None


class EmotionSetting(BaseModel):
    enabled: bool = True
    model: EmotionRecognizerEnum = EmotionRecognizerEnum.POSTERV2
    ckpt_path: str | None = None
    # Optional overrides — None means use model-specific class defaults
    confidence_threshold: float | None = None
    frame_interval: float | None = None


class PoseSetting(BaseModel):
    enabled: bool = False
    model: PoseEstimator2DEnum = PoseEstimator2DEnum.RTMPOSE
    ckpt_path: str | None = None
    lifter_3d: PoseLifter3DEnum | None = None
    lifter_3d_ckpt_path: str | None = None
    lifter_3d_frame_w: int | None = None
    lifter_3d_frame_h: int | None = None


class SpeechEmotionRecognizerSetting(BaseModel):
    """Service-level knobs for the SER engine.

    Engine selection and model-file path live at top level
    (``ser_recognition_model`` / ``ser_recognition_ckpt_path``) to mirror
    the action / emotion configs. The settings here are runtime tunables
    forwarded to the engine constructor.
    """

    sample_rate: int = 16000
    intra_op_threads: int = 4
    # ONNX Runtime execution providers, comma-separated. Leave empty for
    providers: str = ""


class Settings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env", env_nested_delimiter="__", extra="allow"
    )

    dl_api_key: str = ""

    ser_recognition_model: SpeechEmotionRecognizerEnum = (
        SpeechEmotionRecognizerEnum.EMOTION2VEC_PLUS_LARGE
    )
    ser_recognition_ckpt_path: str | None = None
    ser_recognition_labels_path: str | None = None
    ser: SpeechEmotionRecognizerSetting = SpeechEmotionRecognizerSetting()
    action: ActionSetting = ActionSetting()
    emotion: EmotionSetting = EmotionSetting()
    pose: PoseSetting = PoseSetting()
    person_detector: PersonDetectorSetting = PersonDetectorSetting()


settings = Settings()
