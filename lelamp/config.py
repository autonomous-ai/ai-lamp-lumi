# LeLamp runtime configuration constants

import os
from pathlib import Path

# --- Data layout ---
LELAMP_DATA_DIR = Path(os.environ.get("LELAMP_DATA_DIR", "/root/lelamp/data"))
# Per-owner JPEGs for face enrollment; subdir name = normalized label.
# Override to keep using a pre-existing tree (e.g. legacy /opt/lumi/owners).
OWNER_PHOTOS_DIR = os.environ.get(
    "LELAMP_OWNER_PHOTOS_DIR", str(LELAMP_DATA_DIR / "owner_photos")
)

# --- Sensing: Lumi integration ---
LUMI_SENSING_URL = "http://127.0.0.1:5000/api/sensing/event"

# --- Sensing: Motion detection (optical flow) ---
MOTION_ENABLED = False  # feature flag — set True to enable motion events

# --- Sensing: Pose-based motion detection (RTMPose ONNX) ---
POSE_MOTION_ENABLED = True  # feature flag — set True to enable pose motion events
POSE_MOTION_MODEL_PATH = LELAMP_DATA_DIR / "models" / "rtmpose-m.onnx"
POSE_MOTION_ANGLE_THRESHOLD = (
    30.0  # minimum arm joint angle change (degrees) to classify as FOREGROUND
)

# MotionChecker thresholds
MOTION_PIXEL_THRESHOLD = (
    1.0  # minimum flow magnitude (px/frame) to count a pixel as moving
)
MOTION_BG_RATIO = (
    0.7  # if more than this fraction of pixels are moving → background (camera shake)
)
MOTION_FLOW_THRESHOLD = (
    3.0  # minimum mean flow magnitude of moving pixels → foreground (person/object)
)
# MotionPerception event cooldown
MOTION_EVENT_COOLDOWN_S = (
    360.0  # minimum seconds between motion events forwarded to the agent
)

# --- Sensing: Event cooldown ---
EVENT_COOLDOWN_S = 60.0  # minimum seconds between events of the same type

# --- Sensing: Sound detection ---
SOUND_RMS_THRESHOLD = 8000  # RMS threshold for "loud noise"
SOUND_SAMPLE_DURATION_S = 0.5  # sample window for sound level check

# --- Sensing: Light level detection ---
LIGHT_LEVEL_INTERVAL_S = 30.0  # check every 30 seconds
LIGHT_CHANGE_THRESHOLD = 30  # minimum brightness change (0-255) to trigger event

# --- Sensing: Face detection ---
FACE_COOLDOWN_S = 10.0           # minimum seconds between face presence events
YUNET_CONFIDENCE_THRESHOLD = 0.6  # minimum confidence score for YuNet face detection
FACE_OWNER_FORGET_S = 10 * 60.0     # re-fire presence.enter / fire presence.leave after this many seconds without seeing an owner
FACE_STRANGER_FORGET_S = 3 * 60.0   # same for strangers

# --- Sensing: Wellbeing check (override via .env) ---
WELLBEING_HYDRATION_S = int(os.environ.get("LELAMP_WELLBEING_HYDRATION_S", 5 * 60))    # default 5 min
WELLBEING_BREAK_S = int(os.environ.get("LELAMP_WELLBEING_BREAK_S", 6 * 60))            # default 6 min
WELLBEING_MUSIC_S = int(os.environ.get("LELAMP_WELLBEING_MUSIC_S", 60 * 60))           # default 60 min

# --- Sensing: Snapshot storage ---
# Temporary buffer (fast rotation, lost on reboot)
SNAPSHOT_TMP_DIR = "/tmp/lumi-sensing-snapshots"
SNAPSHOT_TMP_MAX_COUNT = 50

# Persistent storage (survives reboot, agent can look back)
SNAPSHOT_PERSIST_DIR = "/var/log/lumi/snapshots"
SNAPSHOT_PERSIST_TTL_S = 72 * 3600   # 72 hours
SNAPSHOT_PERSIST_MAX_BYTES = 50 * 1024 * 1024  # 50 MB

# --- Presence: Auto light on/off ---
IDLE_TIMEOUT_S = 5 * 60   # 5 min → dim
AWAY_TIMEOUT_S = 15 * 60  # 15 min → off
IDLE_BRIGHTNESS = 0.20
