import logging
from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

INPUT_T = TypeVar("INPUT_T")
OUTPUT_T = TypeVar("OUTPUT_T")


class PredictorBase(Generic[INPUT_T, OUTPUT_T], ABC):
    def __init__(self) -> None:
        self._logger: logging.Logger = logging.getLogger(
            f"{self.__class__.__module__}.{self.__class__.__name__}"
        )
        self._logger.setLevel(logging.DEBUG)

    @abstractmethod
    def start(self) -> None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @abstractmethod
    def is_ready(self) -> bool:
        pass

    @abstractmethod
    def preprocess(self, input: list[INPUT_T]) -> list[Any]:
        """Preprocess a batch of inputs for inference."""

    @abstractmethod
    def predict(self, input: list[INPUT_T], *, preprocess: bool = True) -> list[OUTPUT_T]:
        """Make prediction on a batch of input.

        Args:
            input: Batch of inputs.
            preprocess: If True (default), run preprocess on each input
                before inference. Set to False when input is already
                preprocessed (e.g. from a buffer).
        """
