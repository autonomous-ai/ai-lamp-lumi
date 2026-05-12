"""Shared model state for protocol handlers.

Lifespan (server.py) calls setters during startup/shutdown.
Routers call getters to access the loaded models.
"""

from core.perception.action.action import ActionAnalysis
from core.perception.emotion.emotion import EmotionAnalysis

_action_model: ActionAnalysis | None = None
_emotion_model: EmotionAnalysis | None = None


def get_action_model() -> ActionAnalysis | None:
    return _action_model


def set_action_model(model: ActionAnalysis | None) -> None:
    global _action_model
    _action_model = model


def get_emotion_model() -> EmotionAnalysis | None:
    return _emotion_model


def set_emotion_model(model: EmotionAnalysis | None) -> None:
    global _emotion_model
    _emotion_model = model
