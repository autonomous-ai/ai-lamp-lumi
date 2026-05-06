from abc import ABC, abstractmethod
from typing import Any

import numpy as np
import numpy.typing as npt


class EmotionRecognizer(ABC):
    """Interface for emotion classifiers (EmoNet, PosterV2, etc.)."""

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def is_ready(self) -> bool: ...

    @abstractmethod
    def classify(self, face_crop: npt.NDArray[np.uint8]) -> dict[str, Any]: ...
