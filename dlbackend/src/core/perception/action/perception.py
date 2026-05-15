"""Action analysis: model lifecycle, person detection, and session management.

Wraps a HumanActionRecognizerModel + optional PersonDetector.
Each WebSocket connection creates an ActionSession via create_session().
"""

from typing_extensions import override

from core.models.action import ActionPerceptionSessionConfig
from core.perception.action.predictors.base import HumanActionRecognizer
from core.perception.action.session import ActionPerceptionSession
from core.perception.base import PerceptionBase
from core.perception.person.predictors import PersonDetector


class ActionPerception(PerceptionBase[ActionPerceptionSession]):
    """Action recognition pipeline. Loaded once, shared by all WS sessions."""

    def __init__(
        self,
        action_recognizer: HumanActionRecognizer,
        person_detector: PersonDetector | None = None,
        default_config: ActionPerceptionSessionConfig | None = None,
    ):
        super().__init__()

        self._action_recognizer: HumanActionRecognizer = action_recognizer
        self._person_detector: PersonDetector | None = person_detector

        self._default_config: ActionPerceptionSessionConfig | None = default_config

        self._running: bool = False

    @override
    def start(self) -> None:
        if self._running:
            self._logger.info("Already running")
            return

        self._action_recognizer.start()

        if self._person_detector is not None:
            self._person_detector.start()

        self._running = True
        self._logger.info("Ready")

    @override
    def stop(self) -> None:
        self._action_recognizer.stop()

        if self._person_detector is not None:
            self._person_detector.stop()

        self._running = False
        self._logger.info("Stopped")

    @override
    def is_ready(self) -> bool:
        if not self._action_recognizer.is_ready():
            return False

        if self._person_detector and not self._action_recognizer.is_ready():
            return False

        return self._running

    @override
    def create_session(self) -> ActionPerceptionSession:
        config = self._default_config or ActionPerceptionSession.DEFAULT_CONFIG
        return ActionPerceptionSession(
            action_recognizer=self._action_recognizer,
            person_detector=self._person_detector,
            config=config,
        )
