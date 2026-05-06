"""Application configuration loaded from environment variables."""

from typing import ClassVar

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from enums import EmotionRecognizerEnum, HumanActionRecognizerEnum


class HumanActionRecognizerSetting(BaseModel):
    confidence_threshold: float = 0.3
    max_frames: int = 8
    frame_interval: float = 1.0
    w: int = 224
    h: int = 224

    @property
    def frame_size(self) -> tuple[int, int]:
        return (self.w, self.h)


class PersonDetectorSetting(BaseModel):
    enabled: bool = False
    model_name: str = "yolo12x.pt"
    confidence_threshold: float = 0.4
    bbox_expand_scale: float = 2.0


class EmotionRecognizerSetting(BaseModel):
    confidence_threshold: float = 0.5
    frame_interval: float = 1.0


class Settings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env", env_nested_delimiter="__", extra="allow"
    )

    dl_api_key: str = ""
    action_recognition_model: HumanActionRecognizerEnum = HumanActionRecognizerEnum.X3D
    action_recognition_ckpt_path: str | None = None

    emotion_recognition_model: EmotionRecognizerEnum = EmotionRecognizerEnum.POSTERV2
    emotion_recognition_ckpt_path: str | None = None

    videomae: HumanActionRecognizerSetting = HumanActionRecognizerSetting(max_frames=16)
    uniformerv2: HumanActionRecognizerSetting = HumanActionRecognizerSetting()
    x3d: HumanActionRecognizerSetting = HumanActionRecognizerSetting(max_frames=16, w=256, h=256)
    emotion: EmotionRecognizerSetting = EmotionRecognizerSetting()
    person_detector: PersonDetectorSetting = PersonDetectorSetting()


settings = Settings()
