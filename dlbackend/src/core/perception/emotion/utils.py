from pathlib import Path

from core.enums import EmotionRecognizerEnum
from core.perception.emotion.recognizer.base import EmotionRecognizer


def create_classifier(
    model_name: EmotionRecognizerEnum,
    model_path: Path | None,
) -> EmotionRecognizer:
    """Create the emotion classifier for the given model type."""
    if model_name == EmotionRecognizerEnum.POSTERV2:
        from core.perception.emotion.recognizer.posterv2 import PosterV2Recognizer

        return PosterV2Recognizer(model_path=model_path)
    elif model_name == EmotionRecognizerEnum.EMONET_8:
        from core.perception.emotion.recognizer.emonet import EmoNetRecognizer

        return EmoNetRecognizer(n_expression=8, model_path=model_path)
    elif model_name == EmotionRecognizerEnum.EMONET_5:
        from core.perception.emotion.recognizer.emonet import EmoNetRecognizer

        return EmoNetRecognizer(n_expression=5, model_path=model_path)
    else:
        msg = f"Unknown emotion recognition model: {model_name}"
        raise ValueError(msg)
