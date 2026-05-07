from pathlib import Path

from config import settings
from core.emotion.recognizer.base import EmotionRecognizer
from enums import EmotionRecognizerEnum


def create_classifier(model_path: Path | None) -> EmotionRecognizer:
    """Create the emotion classifier based on the configured model."""
    model_type = settings.emotion_recognition_model

    if model_type == EmotionRecognizerEnum.POSTERV2:
        from core.emotion.recognizer.posterv2 import PosterV2Recognizer

        return PosterV2Recognizer(model_path=model_path)
    elif model_type == EmotionRecognizerEnum.EMONET_8:
        from core.emotion.recognizer.emonet import EmoNetRecognizer

        return EmoNetRecognizer(n_expression=8, model_path=model_path)
    elif model_type == EmotionRecognizerEnum.EMONET_5:
        from core.emotion.recognizer.emonet import EmoNetRecognizer

        return EmoNetRecognizer(n_expression=5, model_path=model_path)
    else:
        msg = f"Unknown emotion recognition model: {model_type}"
        raise ValueError(msg)
