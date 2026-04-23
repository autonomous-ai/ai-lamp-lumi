from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import cv2


class PersonKind(StrEnum):
    FRIEND = "friend"
    STRANGER = "stranger"
    UNSURE = "unsure"


@dataclass
class Face:
    bbox: list[int]
    kind: PersonKind
    person_id: str


@dataclass
class PersonData:
    id: str
    kind: PersonKind
    last_seen: float | None = None
    last_session_time: float | None = None


@dataclass
class FaceDetectionData:
    frame: cv2.typing.MatLike | None = None
    faces: list[Face] = []


@dataclass
class PerceptionData:
    frame: cv2.typing.MatLike | None = None
    detected_faces: FaceDetectionData | None = None


@dataclass
class PerceptionConfig:
    enable_face: bool = False
    enable_motion: bool = False
    enable_emotion: bool = False
    enable_light: bool = False
    enable_sound: bool = False
