# LeLamp runtime configuration constants

# --- Sensing: Lumi integration ---
LUMI_SENSING_URL = "http://127.0.0.1:5000/api/sensing/event"

# --- Sensing: Motion detection ---
MOTION_THRESHOLD = 50  # pixel intensity change to count as "changed"
MOTION_BIGGEST_CONTOURS_RATIO = 0.1  # top percentage to classify big contours
MOTION_MIN_BIGGEST_COUNTOURS_TO_TOTAL = 0.01  # minimum fraction of the biggest contours to total pixels that must change (1%)
MOTION_MIN_BIGGEST_COUNTOURS_TO_CONTOURS = 0.5  # minimum fraction of the biggest contours to total area of all contoures that must change (50%)
MOTION_LARGE_TOTAL_RATIO = 0.25  # fraction of changing areas to total pixels for "large movement" (25%)

# --- Sensing: Event cooldown ---
EVENT_COOLDOWN_S = 60.0  # minimum seconds between events of the same type

# --- Sensing: Sound detection ---
SOUND_RMS_THRESHOLD = 3000  # RMS threshold for "loud noise"
SOUND_SAMPLE_DURATION_S = 0.5  # sample window for sound level check

# --- Sensing: Light level detection ---
LIGHT_LEVEL_INTERVAL_S = 30.0  # check every 30 seconds
LIGHT_CHANGE_THRESHOLD = 30  # minimum brightness change (0-255) to trigger event

# --- Sensing: Face detection ---
FACE_COOLDOWN_S = 10.0  # minimum seconds between face presence events
YUNET_CONFIDENCE_THRESHOLD = 0.6  # minimum confidence score for YuNet face detection

# --- Presence: Auto light on/off ---
IDLE_TIMEOUT_S = 5 * 60   # 5 min → dim
AWAY_TIMEOUT_S = 15 * 60  # 15 min → off
IDLE_BRIGHTNESS = 0.20
