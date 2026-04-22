import threading
from copy import copy
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, TypeVar

import cv2

from service.sensing.perceptions import (
    ActionPerception,
    EmotionPerception,
    FacePerception,
    LightLevelPerception,
    PoseMotionPerception,
    SoundPerception,
    WellbeingPerception,
)


@dataclass
class PerceptionConfig:
    enable_face: bool = False
    enable_action: bool = False
    enable_pose_motion: bool = False
    enable_emotion: bool = False
    enable_wellbeing: bool = False
    enable_light: bool = False
    enable_sound: bool = False


@dataclass
class PerceptionProcessors:
    face_recognizer: FacePerception | None = None
    action_processor: ActionPerception | None = None
    pose_motion_processor: PoseMotionPerception | None = None
    emotion_processor: EmotionPerception | None = None
    wellbeing_processor: WellbeingPerception | None = None
    light_processor: LightLevelPerception | None = None
    sound_recognizer: SoundPerception | None = None


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


T = TypeVar("T")


class DataObserver[T]:
    def __init__(self):
        self._lock: threading.Lock = threading.Lock()
        self._data: T | None = None
        self._subscriptors: set[Callable[[T], None]] = set()

    def _on_update(self):
        data = self.data
        if data is not None:
            for s in self._subscriptors:
                s(data)

    def register(self, subscriptor: Callable[[T], None]):
        with self._lock:
            self._subscriptors.add(subscriptor)

    def unregister(self, subscriptor: Callable[[T], None]):
        with self._lock:
            self._subscriptors.discard(subscriptor)

    @property
    def data(self):
        with self._lock:
            return copy(self._data)

    @data.setter
    def data(self, data: T):
        with self._lock:
            self._data = data

        self._on_update()


@dataclass
class PerceptionStateObservers:
    frame: DataObserver[cv2.typing.MatLike] = DataObserver[cv2.typing.MatLike]()
    detected_faces: DataObserver[FaceDetectionData] = DataObserver[FaceDetectionData]()
