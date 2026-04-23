import re
import threading
from copy import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, TypeVar

if TYPE_CHECKING:
    import cv2

from service.sensing.perceptions.models import FaceDetectionData

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
    current_user: DataObserver[str] = DataObserver[str]()


def normalize_label(label: str) -> str:
    """Lowercase folder-safe label (a-z0-9_-)."""
    s = label.strip().lower()
    s = re.sub(r"[^a-z0-9_-]+", "_", s)
    s = s.strip("_")
    return s[:64] if s else "person"
