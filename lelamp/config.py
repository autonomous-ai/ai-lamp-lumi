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
    180.0  # minimum seconds between motion events forwarded to the agent
)

# --- Sensing: Event cooldown ---
EVENT_COOLDOWN_S = 60.0  # minimum seconds between events of the same type

# --- Sensing: Sound detection ---
SOUND_RMS_THRESHOLD = 3000  # RMS threshold for "loud noise"
SOUND_SAMPLE_DURATION_S = 0.5  # sample window for sound level check

# --- Sensing: Light level detection ---
LIGHT_LEVEL_INTERVAL_S = 30.0  # check every 30 seconds
LIGHT_CHANGE_THRESHOLD = 30  # minimum brightness change (0-255) to trigger event

# --- Sensing: Face detection ---
FACE_COOLDOWN_S = 10.0           # minimum seconds between face presence events
YUNET_CONFIDENCE_THRESHOLD = 0.6  # minimum confidence score for YuNet face detection
FACE_OWNER_FORGET_S = 10 * 60.0     # re-fire presence.enter / fire presence.leave after this many seconds without seeing an owner
FACE_STRANGER_FORGET_S = 5 * 60.0   # same for strangers

# --- Sensing: Wellbeing check ---
# Production: 30*60 and 45*60. Set low for testing.
WELLBEING_HYDRATION_S = 60        # TEST: 1 min (production: 30 min)
WELLBEING_BREAK_S = 60            # TEST: 1 min (production: 45 min)

# --- Presence: Auto light on/off ---
IDLE_TIMEOUT_S = 5 * 60  # 5 min → dim
AWAY_TIMEOUT_S = 15 * 60  # 15 min → off
IDLE_BRIGHTNESS = 0.20
