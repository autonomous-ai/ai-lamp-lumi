from abc import ABC, abstractmethod
from typing import Any

import numpy as np
import numpy.typing as npt


class EmotionRecognizer(ABC):
    """Interface for emotion classifiers (EmoNet, PosterV2, etc.)."""

    @abstractmethod
    def start(self) -> None:
        """Load model weights."""

    @abstractmethod
    def stop(self) -> None:
        """Release model resources."""

    @abstractmethod
    def is_ready(self) -> bool:
        """Return True if the model is loaded and ready for inference."""

    @abstractmethod
    def classify(self, face_crop: npt.NDArray[np.uint8]) -> dict[str, Any]:
        """Classify emotion from a BGR face crop.

        Returns dict with at least: emotion (str), confidence (float).
        May also include: valence (float), arousal (float).
        """
