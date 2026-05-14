from typing import Generic, TypeVar

INPUT_T = TypeVar("INPUT_T")
OUTPUT_T = TypeVar("OUTPUT_T")


class Predictor(Generic[INPUT_T, OUTPUT_T]):
    pass
