"""
LeLamp runtime configuration — all values read from environment variables.

Import: from lelamp.config import LAMP_ID, SERVO_PORT, ...
"""

import os
from typing import Optional

SERVO_PORT = os.environ.get("LELAMP_SERVO_PORT", "/dev/ttyACM0")
LAMP_ID = os.environ.get("LELAMP_LAMP_ID", "lelamp")
SERVO_FPS = int(os.environ.get("LELAMP_SERVO_FPS", "30"))
SERVO_HOLD_S = float(os.environ.get("LELAMP_SERVO_HOLD_S", "3.0"))
HTTP_PORT = int(os.environ.get("LELAMP_HTTP_PORT", "5001"))
CAMERA_INDEX = int(os.environ.get("LELAMP_CAMERA_INDEX", "0"))
CAMERA_WIDTH = int(os.environ.get("LELAMP_CAMERA_WIDTH", "640"))
CAMERA_HEIGHT = int(os.environ.get("LELAMP_CAMERA_HEIGHT", "480"))

# Audio hardware overrides — set in .env to bypass auto-detection
# e.g. LELAMP_AUDIO_INPUT_ALSA=plughw:1,0  LELAMP_AUDIO_OUTPUT_ALSA=plughw:2,0
AUDIO_INPUT_ALSA: Optional[str] = os.environ.get("LELAMP_AUDIO_INPUT_ALSA") or None
AUDIO_OUTPUT_ALSA: Optional[str] = os.environ.get("LELAMP_AUDIO_OUTPUT_ALSA") or None

# Separate mic device index for SoundPerception (noise sensing).
# Set to sounddevice card index (see: python3 -c "import sounddevice; print(sounddevice.query_devices())")
# Useful when using a dedicated mic for ambient noise detection separate from the STT mic.
_sensing_device_env = os.environ.get("LELAMP_AUDIO_SENSING_DEVICE")
AUDIO_SENSING_DEVICE: Optional[int] = int(_sensing_device_env) if _sensing_device_env else None
# --- Sensing: Motion detection (X3D video action recognition) ---
MOTION_ENABLED = False  # feature flag — set True to enable motion events
MOTION_X3D_CONFIDENCE_THRESHOLD = 0.3  # minimum softmax confidence to accept an action prediction
MOTION_EVENT_COOLDOWN_S = (
    360.0  # minimum seconds between motion events forwarded to the agent
)

# TTS speed multiplier — 1.0=normal, 1.3=faster, max 4.0
TTS_SPEED: float = float(os.environ.get("LELAMP_TTS_SPEED", "1.3"))
