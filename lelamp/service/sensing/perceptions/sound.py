import logging
from typing import Callable, Optional, override

import lelamp.config as config
import numpy as np

from .base import Perception

logger = logging.getLogger(__name__)


class SoundPerception(Perception):
    """Detects loud sounds via microphone RMS energy."""

    def __init__(
        self,
        sd,
        np_module,
        send_event: Callable,
        input_device: Optional[int] = None,
        tts_service=None,
    ):
        super().__init__(send_event)
        self._sd = sd
        self._np = np_module
        self._input_device = input_device
        self._tts = tts_service

    def set_tts_service(self, tts_service) -> None:
        self._tts = tts_service

    @override
    def check(self, frame: np.ndarray) -> None:
        # Sound detection is independent of the camera frame.
        if self._input_device is None:
            return

        # Skip while TTS is speaking to avoid echo triggering a sound event.
        if self._tts is not None and self._tts.speaking:
            return

        try:
            sample_rate = 44100
            frames = int(sample_rate * config.SOUND_SAMPLE_DURATION_S)
            recording = self._sd.rec(
                frames,
                samplerate=sample_rate,
                channels=1,
                dtype="int16",
                device=self._input_device,
                blocking=True,
            )
            rms = float(self._np.sqrt(self._np.mean(recording.astype(self._np.float64) ** 2)))
            if rms >= config.SOUND_RMS_THRESHOLD:
                self._send_event("sound", f"Loud noise detected (level: {int(rms)})")
        except Exception as e:
            logger.debug("Sound check failed: %s", e)

    def to_dict(self) -> dict:
        return {
            "type": "sound",
            "input_device": self._input_device,
            "echo_suppression": self._tts is not None,
        }
