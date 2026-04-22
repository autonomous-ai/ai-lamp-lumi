import logging
import threading
import time
from typing import TYPE_CHECKING

from devices.video_capture_device import VideoCaptureDeviceBase
from service.sensing.perceptions import (
    ActionPerception,
    EmotionPerception,
    FacePerception,
    LightLevelPerception,
    PoseMotionPerception,
    SoundPerception,
    WellbeingPerception,
)
from service.sensing.perceptions.models import (
    PerceptionConfig,
    PerceptionProcessors,
    PerceptionStateObservers,
)
from service.sensing.perceptions.typing import SendEventCallable
from service.sensing.presence_service import PresenceService
from service.voice.tts_service import TTSService

try:
    import cv2
except ImportError:
    if TYPE_CHECKING:
        import cv2
    else:
        cv2 = None


try:
    import numpy as np
except ImportError:
    if TYPE_CHECKING:
        import numpy as np
    else:
        np = None

try:
    import sounddevice as sd
except ImportError:
    if TYPE_CHECKING:
        import sounddevice as sd
    else:
        sd = None


class PerceptionOrchestrator:
    def __init__(
        self,
        poll_interval_ts: float,
        send_event: SendEventCallable,
        perception_config: PerceptionConfig | None = None,
        sound_device_id: int | str | None = None,
    ):
        self._poll_interval_ts: float = poll_interval_ts
        self._send_event: SendEventCallable = send_event
        self._config: PerceptionConfig = (
            perception_config if perception_config is not None else PerceptionConfig()
        )
        self._sound_device_id: int | str | None = sound_device_id

        self._camera_capture: VideoCaptureDeviceBase | None = None
        self._presence_service: PresenceService | None = None
        self._tts_service: TTSService | None = None

        self._stopped: threading.Event = threading.Event()
        self._main_loop_thread: threading.Thread | None = None
        self._processors: PerceptionProcessors = PerceptionProcessors()
        self._perception_state: PerceptionStateObservers = PerceptionStateObservers()

        self._logger: logging.Logger = logging.getLogger(self.__class__.__name__)

    def with_camera_service(self, camera_capture: VideoCaptureDeviceBase):
        self._camera_capture = camera_capture
        return self

    def with_presence_service(self, presence_service: PresenceService):
        self._presence_service = presence_service
        return self

    def with_tts_service(self, tts_service: TTSService):
        self._tts_service = tts_service
        return self

    def _register_processors(self):
        def on_motion():
            if self._presence_service is not None:
                self._presence_service.on_motion()

        # Perception detectors
        if cv2 is not None:
            if self._config.enable_face:
                self._processors.face_recognizer = FacePerception(
                    cv2=cv2,
                    perception_state=self._perception_state,
                    send_event=self._send_event,
                    on_motion=on_motion,
                )
                _ = self._processors.face_recognizer.load_from_disk()
                self._perception_state.frame.register(
                    self._processors.face_recognizer.check
                )

            if self._config.enable_action:
                self._processors.action_processor = ActionPerception(
                    perception_state=self._perception_state,
                    send_event=self._send_event,
                    on_motion=on_motion,
                )
                self._perception_state.frame.register(
                    self._processors.action_processor.check
                )

            if self._config.enable_pose_motion:
                self._processors.pose_motion_processor = PoseMotionPerception(
                    cv2=cv2,
                    perception_state=self._perception_state,
                    send_event=self._send_event,
                    on_motion=on_motion,
                )
                self._perception_state.frame.register(
                    self._processors.pose_motion_processor.check
                )

            if self._config.enable_emotion:
                self._processors.emotion_processor = EmotionPerception(
                    perception_state=self._perception_state,
                    send_event=self._send_event,
                    on_motion=on_motion,
                )
                self._perception_state.detected_faces.register(
                    self._processors.emotion_processor.check
                )

            if self._config.enable_wellbeing:
                self._processors.wellbeing_processor = WellbeingPerception(
                    perception_state=self._perception_state,
                    cv2=cv2,
                    send_event=self._send_event,
                )
                self._perception_state.frame.register(
                    self._processors.wellbeing_processor.check
                )

            if self._config.enable_light:
                self._processors.light_processor = LightLevelPerception(
                    perception_state=self._perception_state,
                    cv2=cv2,
                    np_module=np,
                    send_event=self._send_event,
                )
                self._perception_state.frame.register(
                    self._processors.light_processor.check
                )

        if sd is not None and np is not None and self._sound_device_id is not None:
            self._processors.sound_recognizer = SoundPerception(
                sd=sd,
                np_module=np,
                send_event=self._send_event,
                input_device=self._sound_device_id,
                tts_service=self._tts_service,
            )
            # TODO: change this to correct data type
            self._perception_state.frame.register(
                self._processors.sound_recognizer.check
            )

    def start(self):
        if self._main_loop_thread is not None:
            self._logger.info(
                "[%s] service has been already started", self.__class__.__name__
            )
            return
        self._register_processors()
        self._main_loop_thread = threading.Thread(
            target=self._loop, daemon=True, name="sensing"
        )
        self._main_loop_thread.start()
        self._logger.info("SensingService started (poll=%.1fs)", self._poll_interval_ts)

    def stop(self):
        self._stopped.set()
        if self._main_loop_thread:
            self._main_loop_thread.join(timeout=5)
            self._main_loop_thread = None
        self._logger.info("SensingService stopped")

    def _loop(self):
        # TODO: Bad practice.
        # Wait a bit for hardware to initialize
        time.sleep(3)

        while not self._stopped.is_set():
            try:
                self._tick()
            except Exception as e:
                self._logger.exception("Sensing tick error: %s", e)

            time.sleep(self._poll_interval_ts)

    def _tick(self):

        # Read camera frame once per tick (shared across detectors)
        if self._camera_capture:
            response = self._camera_capture.capture()
            if response is not None and response.frame is not None:
                self._perception_state.frame.data = response.frame

        # Presence timeout check (dim/off)
        if self._presence_service is not None:
            self._presence_service.tick()
