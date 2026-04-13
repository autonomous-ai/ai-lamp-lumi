"""
LeLamp runtime configuration — all values read from environment variables.

Import: from lelamp.config import LAMP_ID, SERVO_PORT, ...
"""

import os
from pathlib import Path
from typing import Optional

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
# Separate mic device index for SoundPerception (noise sensing).
_sensing_device_env = os.environ.get("LELAMP_AUDIO_SENSING_DEVICE")
AUDIO_SENSING_DEVICE: Optional[int] = int(_sensing_device_env) if _sensing_device_env else None
# TTS speed multiplier — 1.0=normal, 1.3=faster, max 4.0
TTS_SPEED: float = float(os.environ.get("LELAMP_TTS_SPEED", "1.3"))

# --- Data layout ---
LELAMP_DATA_DIR = Path(os.environ.get("LELAMP_DATA_DIR", "/root/lelamp/data"))

# --- Sensing: Lumi integration ---
LUMI_SENSING_URL = "http://127.0.0.1:5000/api/sensing/event"

# --- Sensing: Event cooldown ---
EVENT_COOLDOWN_S = 60.0  # minimum seconds between events of the same type

# --- Sensing: Sound detection ---
SOUND_RMS_THRESHOLD = int(os.environ.get("LELAMP_SOUND_RMS_THRESHOLD", "8000"))  # RMS threshold for "loud noise"
SOUND_SAMPLE_DURATION_S = 0.5    # sample window for sound level check

# --- Sensing: Light level detection ---
LIGHT_LEVEL_INTERVAL_S = 300.0   # check every 5 minutes
LIGHT_CHANGE_THRESHOLD = 50      # minimum brightness change (0-255) to trigger event

# --- Sensing: Face detection ---
USERS_DIR: str = os.environ.get("LELAMP_USERS_DIR", "/root/local/users")
YUNET_CONFIDENCE_THRESHOLD = 0.6  # minimum confidence score for YuNet face detection
FACE_COOLDOWN_S = 10.0            # minimum seconds between face presence events
FACE_OWNER_FORGET_S = 30 * 60.0   # re-fire presence.enter / fire presence.leave after this many seconds without seeing an owner
FACE_STRANGER_FORGET_S = 5 * 60.0  # same for strangers
FACE_STRANGER_FLUSH_S = 10.0      # flush stranger snapshots every 10 seconds

# --- Sensing: Motion detection (X3D video action recognition) ---
MOTION_ENABLED = False  # feature flag — set True to enable motion events
MOTION_X3D_CONFIDENCE_THRESHOLD = 0.3  # minimum softmax confidence to accept an action prediction
MOTION_FLUSH_S = 10.0  # flush motion snapshots every 10 seconds
MOTION_EVENT_COOLDOWN_S = 360.0   # minimum seconds between motion events forwarded to the agent

# --- Sensing: Pose-based motion detection (RTMPose ONNX) ---
POSE_MOTION_ENABLED = True
POSE_MOTION_MODEL_PATH = LELAMP_DATA_DIR / "models" / "rtmpose-m.onnx"
POSE_MOTION_ANGLE_THRESHOLD = 30.0  # minimum arm joint angle change (degrees) to classify as FOREGROUND

# --- Sensing: Snapshot storage ---
SNAPSHOT_TMP_DIR = "/tmp/lumi-sensing-snapshots"
SNAPSHOT_TMP_MAX_COUNT = 50
SNAPSHOT_PERSIST_DIR = "/var/log/lumi/snapshots"
SNAPSHOT_PERSIST_TTL_S = 72 * 3600       # 72 hours
SNAPSHOT_PERSIST_MAX_BYTES = 50 * 1024 * 1024  # 50 MB

# --- Presence: Auto light on/off ---
IDLE_TIMEOUT_S = 5 * 60    # 5 min → dim
AWAY_TIMEOUT_S = 15 * 60   # 15 min → off
IDLE_BRIGHTNESS = 0.20
