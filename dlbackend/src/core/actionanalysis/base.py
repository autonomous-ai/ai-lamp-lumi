"""Abstract base class for human action recognizers."""

from abc import ABC, abstractmethod

import numpy as np

from core.models import ActionResponse


class HumanActionRecognizer(ABC):
    """Base interface for all action recognition backends."""

    @abstractmethod
    def update(self, frame: np.ndarray) -> ActionResponse | None:
        """Buffer a frame and optionally run inference.

        Args:
            frame: BGR numpy array (H, W, 3).

        Returns:
            ActionResponse if inference was run this cycle, None otherwise.
        """
        ...

    @abstractmethod
    def set_whitelist(self, whitelist: list[str] | None) -> None:
        """Set or clear the action whitelist.

        Args:
            whitelist: List of allowed action names, or None to allow all.
        """
        ...

    @abstractmethod
    def is_ready(self) -> bool:
        """Return True if the model is loaded and ready for inference."""
        ...
