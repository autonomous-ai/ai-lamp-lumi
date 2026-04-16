"""
LeLamp runtime configuration — all values read from environment variables.

Import: from lelamp.config import LAMP_ID, SERVO_PORT, ...
"""

import os
from pathlib import Path
from typing import Optional, Union

# --- Hardware ---
SERVO_PORT = os.environ.get("LELAMP_SERVO_PORT", "/dev/ttyACM0")
LAMP_ID = os.environ.get("LELAMP_LAMP_ID", "lelamp")
SERVO_FPS = int(os.environ.get("LELAMP_SERVO_FPS", "30"))
SERVO_HOLD_S = float(os.environ.get("LELAMP_SERVO_HOLD_S", "3.0"))
HTTP_PORT = int(os.environ.get("LELAMP_HTTP_PORT", "5001"))
CAMERA_INDEX = int(os.environ.get("LELAMP_CAMERA_INDEX", "0"))
CAMERA_WIDTH = int(os.environ.get("LELAMP_CAMERA_WIDTH", "640"))
CAMERA_HEIGHT = int(os.environ.get("LELAMP_CAMERA_HEIGHT", "480"))

# --- Audio ---
# Hardware overrides — set in .env to bypass auto-detection
# e.g. LELAMP_AUDIO_INPUT_ALSA=plughw:1,0  LELAMP_AUDIO_OUTPUT_ALSA=plughw:2,0
AUDIO_INPUT_ALSA: Optional[str] = os.environ.get("LELAMP_AUDIO_INPUT_ALSA") or None
AUDIO_OUTPUT_ALSA: Optional[str] = os.environ.get("LELAMP_AUDIO_OUTPUT_ALSA") or None
# Separate mic device for SoundPerception (noise sensing).
# Accepts int (sounddevice index) or string (ALSA device name like "plughw:6,0").
_sensing_device_env = os.environ.get("LELAMP_AUDIO_SENSING_DEVICE")
AUDIO_SENSING_DEVICE: Optional[Union[int, str]] = None
if _sensing_device_env:
    try:
        AUDIO_SENSING_DEVICE = int(_sensing_device_env)
    except ValueError:
        AUDIO_SENSING_DEVICE = _sensing_device_env
# TTS speed multiplier — 1.0=normal, 1.3=faster, max 4.0
TTS_SPEED: float = float(os.environ.get("LELAMP_TTS_SPEED", "1.3"))
# TTS voice — one of: alloy, ash, coral, echo, fable, onyx, nova, sage, shimmer
TTS_VOICE: str = os.environ.get("TTS_VOICE", "alloy")

# --- Data layout ---

# --- Sensing: Lumi integration ---
LUMI_SENSING_URL = "http://127.0.0.1:5000/api/sensing/event"

# --- Sensing: Event cooldown ---
EVENT_COOLDOWN_S = float(os.environ.get("LELAMP_EVENT_COOLDOWN_S", "60.0"))

# --- Sensing: Sound detection ---
SOUND_RMS_THRESHOLD = int(os.environ.get("LELAMP_SOUND_RMS_THRESHOLD", "8000"))
SOUND_SAMPLE_DURATION_S = float(os.environ.get("LELAMP_SOUND_SAMPLE_DURATION_S", "0.5"))

# --- Sensing: Light level detection ---
LIGHT_LEVEL_INTERVAL_S = float(os.environ.get("LELAMP_LIGHT_LEVEL_INTERVAL_S", "300.0"))
LIGHT_CHANGE_THRESHOLD = int(os.environ.get("LELAMP_LIGHT_CHANGE_THRESHOLD", "50"))

# --- Sensing: Face detection ---
USERS_DIR: str = os.environ.get("LELAMP_USERS_DIR", "/root/local/users")
STRANGERS_DIR: str = os.environ.get("LELAMP_STRANGERS_DIR", "/root/local/strangers")
YUNET_CONFIDENCE_THRESHOLD = float(
    os.environ.get("LELAMP_YUNET_CONFIDENCE_THRESHOLD", "0.6")
)
FACE_COOLDOWN_S = float(os.environ.get("LELAMP_FACE_COOLDOWN_S", "10.0"))
FACE_OWNER_FORGET_S = float(os.environ.get("LELAMP_FACE_OWNER_FORGET_S", "300.0"))
FACE_STRANGER_FORGET_S = float(os.environ.get("LELAMP_FACE_STRANGER_FORGET_S", "300.0"))
FACE_STRANGER_FLUSH_S = float(os.environ.get("LELAMP_FACE_STRANGER_FLUSH_S", "10.0"))

# --- Sensing: Motion detection (X3D video action recognition) ---
MOTION_ENABLED = os.environ.get("LELAMP_MOTION_ENABLED", "true").lower() == "true"
MOTION_X3D_CONFIDENCE_THRESHOLD = float(
    os.environ.get("LELAMP_MOTION_X3D_CONFIDENCE_THRESHOLD", "0.3")
)
MOTION_FLUSH_S = float(os.environ.get("LELAMP_MOTION_FLUSH_S", "10.0"))
MOTION_EVENT_COOLDOWN_S = float(
    os.environ.get("LELAMP_MOTION_EVENT_COOLDOWN_S", "360.0")
)
DL_BACKEND_URL = os.environ.get("DL_BACKEND_URL", "")
DL_API_KEY = os.environ.get("DL_API_KEY", "")

# --- Sensing: Pose-based motion detection (RTMPose ONNX) ---
POSE_MOTION_ENABLED = (
    os.environ.get("LELAMP_POSE_MOTION_ENABLED", "true").lower() == "true"
)
POSE_MOTION_MODEL_PATH = Path(os.environ.get("LELAMP_POSE_MODEL_PATH", "/root/local/models/rtmpose-m.onnx"))
POSE_MOTION_ANGLE_THRESHOLD = float(
    os.environ.get("LELAMP_POSE_MOTION_ANGLE_THRESHOLD", "30.0")
)

# --- Sensing: Snapshot storage ---
SNAPSHOT_TMP_DIR = os.environ.get(
    "LELAMP_SNAPSHOT_TMP_DIR", "/tmp/lumi-sensing-snapshots"
)
SNAPSHOT_TMP_MAX_COUNT = int(os.environ.get("LELAMP_SNAPSHOT_TMP_MAX_COUNT", "50"))
SNAPSHOT_PERSIST_DIR = os.environ.get(
    "LELAMP_SNAPSHOT_PERSIST_DIR", "/var/log/lumi/snapshots"
)
SNAPSHOT_PERSIST_TTL_S = float(
    os.environ.get("LELAMP_SNAPSHOT_PERSIST_TTL_S", str(72 * 3600))
)
SNAPSHOT_PERSIST_MAX_BYTES = int(
    os.environ.get("LELAMP_SNAPSHOT_PERSIST_MAX_BYTES", str(50 * 1024 * 1024))
)

# --- Presence: Auto light on/off ---
IDLE_TIMEOUT_S = float(os.environ.get("LELAMP_IDLE_TIMEOUT_S", "300"))
AWAY_TIMEOUT_S = float(os.environ.get("LELAMP_AWAY_TIMEOUT_S", "900"))
IDLE_BRIGHTNESS = float(os.environ.get("LELAMP_IDLE_BRIGHTNESS", "0.20"))
