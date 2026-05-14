from typing import Any

import numpy as np
import numpy.typing as npt

EPSILON: float = 1e-8


def softmax(x: npt.NDArray[np.number[Any]], axis: int = -1) -> npt.NDArray[np.float32]:
    e: npt.NDArray[np.float32] = np.exp(x - x.max(axis=axis, keepdims=True)).astype(np.float32)
    return e / (e.sum(axis=axis, keepdims=True) + EPSILON)
