"""Abstract base class for person detectors."""

import logging
from abc import ABC

import cv2
import cv2.typing as cv2t

from core.models.person import RawPersonDetection
from core.perception.base import PredictorBase

logger = logging.getLogger(__name__)


class PersonDetector(PredictorBase[cv2t.MatLike, RawPersonDetection | None], ABC):
    """Base interface for person detectors.

    Subclasses implement ``start``, ``stop``, ``is_ready``, and ``detect``.
    ``detect_largest_crop`` is provided by the base class.
    """

    def extract_largest_crop(
        self,
        input: list[cv2t.MatLike],
        min_area_ratio: float = 0.0,
    ) -> list[cv2.typing.MatLike | None]:
        """Return a crop of the largest detected person in *frame*.

        Skips persons whose area is below ``min_area_ratio`` of the frame.
        Returns ``None`` when no qualifying person is found.
        """
        detections = self.predict(input)

        cropped_input: list[cv2.typing.MatLike | None] = []
        for i, detected_people in enumerate(detections):
            if detected_people is None:
                cropped_input.append(None)
                continue

            h, w = input[i].shape[:2]
            frame_area = h * w
            filter_mask = (detected_people.area / frame_area) > min_area_ratio

            if filter_mask.sum() == 0:
                cropped_input.append(None)
                continue

            largest_id = detected_people.area.argmax(0)

            x1, y1, x2, y2 = detected_people.bbox_xyxy[largest_id]

            x1, y1 = int(max(0, x1)), int(max(0, y1))
            x2, y2 = int(min(w, x2)), int(min(h, y2))

            if x1 >= x2 or y1 >= y2:
                cropped_input.append(None)
                continue

            cropped_input.append(input[i][y1:y2, x1:x2])

        return cropped_input
