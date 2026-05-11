"""Shared model state for protocol handlers.

Lifespan (server.py) calls setters during startup/shutdown.
Routers call getters to access the loaded models.
"""

from core.action.base import HumanActionRecognizerModel
from core.emotion.emotion import EmotionModel

_action_model: HumanActionRecognizerModel | None = None
_emotion_model: EmotionModel | None = None


def get_action_model() -> HumanActionRecognizerModel | None:
    return _action_model


def set_action_model(model: HumanActionRecognizerModel | None) -> None:
    global _action_model
    _action_model = model


def get_emotion_model() -> EmotionModel | None:
    return _emotion_model


def set_emotion_model(model: EmotionModel | None) -> None:
    global _emotion_model
    _emotion_model = model
