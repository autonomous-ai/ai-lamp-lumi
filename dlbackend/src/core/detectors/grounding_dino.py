"""Grounding DINO detector using HuggingFace transformers."""

import logging

import numpy as np
import torch
from PIL import Image
from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

from models import DetectionResult
from .base import BaseDetector

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "IDEA-Research/grounding-dino-tiny"
DEFAULT_THRESHOLD = 0.25
DEFAULT_TEXT_THRESHOLD = 0.25


class GroundingDINODetector(BaseDetector):
    """Zero-shot object detection using Grounding DINO.

    Loads the model from HuggingFace Hub at initialization.
    Classes are joined into a period-separated text prompt per request.
    """

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        threshold: float = DEFAULT_THRESHOLD,
        text_threshold: float = DEFAULT_TEXT_THRESHOLD,
    ):
        self._threshold = threshold
        self._text_threshold = text_threshold
        self._device = "cuda" if torch.cuda.is_available() else "cpu"

        logger.info(f"Loading Grounding DINO model: {model_id} on {self._device}")
        self._processor = AutoProcessor.from_pretrained(model_id)
        self._model = AutoModelForZeroShotObjectDetection.from_pretrained(
            model_id
        ).to(self._device)
        logger.info("Grounding DINO model loaded")

    @torch.no_grad()
    def detect(self, image: np.ndarray, classes: list[str]) -> list[DetectionResult]:
        """Run Grounding DINO detection on a BGR image.

        Args:
            image: BGR numpy array (H, W, 3).
            classes: Class names to detect.

        Returns:
            List of DetectionResult with xywh in pixel coordinates.
        """
        rgb = image[:, :, ::-1]
        pil_image = Image.fromarray(rgb)
        img_h, img_w = image.shape[:2]

        text_prompt = " . ".join(classes) + " ."

        inputs = self._processor(
            images=pil_image, text=text_prompt, return_tensors="pt"
        ).to(self._device)

        self._model.eval()
        outputs = self._model(**inputs)

        results = self._processor.post_process_grounded_object_detection(
            outputs,
            inputs["input_ids"],
            threshold=self._threshold,
            text_threshold=self._text_threshold,
            target_sizes=[(img_h, img_w)],
        )[0]

        detections = []
        boxes = results["boxes"].cpu().numpy()
        scores = results["scores"].cpu().numpy()
        labels = results["labels"]

        for box, score, label in zip(boxes, scores, labels):
            x1, y1, x2, y2 = box
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            w = x2 - x1
            h = y2 - y1

            detections.append(
                DetectionResult(
                    class_name=label.strip(),
                    xywh=[float(cx), float(cy), float(w), float(h)],
                    confidence=float(score),
                )
            )

        return detections

    def is_ready(self) -> bool:
        """Return True if model and processor are loaded."""
        return self._model is not None and self._processor is not None
