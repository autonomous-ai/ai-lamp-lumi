import logging
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

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
    def predict(self, input: list[INPUT_T]) -> list[OUTPUT_T]:
        """Make prediction on a batch of input."""
        pass
