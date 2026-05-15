from dataclasses import dataclass

import numpy as np
import numpy.typing as npt


@dataclass
class HumanAction:
    class_name: str
    conf: float


@dataclass
class HumanActionDetection:
    actions: list[HumanAction]


@dataclass
class RawHumanActionDetection:
    prob_np: npt.NDArray[np.float32]
    """Shape: (C,)"""


@dataclass
class ActionPerceptionSessionConfig:
    frame_interval: float = 1.0
    whitelist: list[str] | None = None
    threshold: float = 0.3
    person_detection_enabled: bool | None = None
    person_min_area_ratio: float = 0
