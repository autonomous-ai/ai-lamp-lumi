"""Shared model state for protocol handlers.

Lifespan (server.py) calls setters during startup/shutdown.
Routers call getters to access the loaded models.
"""

from core.perception.action.perception import ActionPerception
from core.perception.emotion.emotion import EmotionAnalysis
from core.perception.pose.pose import PoseAnalysis

_action_model: ActionPerception | None = None
_emotion_model: EmotionAnalysis | None = None
_pose_model: PoseAnalysis | None = None


def get_action_model() -> ActionPerception | None:
    return _action_model


def set_action_model(model: ActionPerception | None) -> None:
    global _action_model
    _action_model = model


def get_emotion_model() -> EmotionAnalysis | None:
    return _emotion_model


def set_emotion_model(model: EmotionAnalysis | None) -> None:
    global _emotion_model
    _emotion_model = model


def get_pose_model() -> PoseAnalysis | None:
    return _pose_model


def set_pose_model(model: PoseAnalysis | None) -> None:
    global _pose_model
    _pose_model = model
