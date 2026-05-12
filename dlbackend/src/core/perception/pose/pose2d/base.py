from abc import ABC, abstractmethod

from cv2.typing import MatLike

from core.models.pose import Pose2D


class PoseEstimator2D(ABC):
    @abstractmethod
    def predict(self, frame: MatLike) -> Pose2D:
        pass
