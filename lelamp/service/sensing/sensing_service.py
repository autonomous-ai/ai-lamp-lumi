"""
Sensing Service — background loop that detects motion/sound/faces/light and pushes events to Lumi Server.

Lumi Server (Go, port 5000) then forwards these events to OpenClaw via WebSocket chat.send,
so the AI agent can react proactively (Pillar 4: "It acts on its own").

Detectors:
  - Motion: camera frame differencing (grayscale → absdiff → threshold → contour area)
  - Face: OpenCV Haar cascade for face/body detection (presence.enter/leave)
  - Light level: mean brightness of camera frame (auto-adjust lamp)
  - Sound: RMS level from microphone (loud noise detection)

Also drives the PresenceService state machine for automatic light on/off.

Events are POST-ed to http://localhost:5000/api/sensing/event as:
  {"type": "motion", "message": "...", "image": "<base64 jpeg>"}
"""

import base64
import logging
import threading
import time
from typing import Optional

import requests

from lelamp.service.sensing.presence_service import PresenceService

logger = logging.getLogger("lelamp.sensing")

LUMI_SENSING_URL = "http://127.0.0.1:5000/api/sensing/event"

# Motion detection thresholds
MOTION_THRESHOLD = 50  # pixel intensity change to count as "changed"
MOTION_MIN_AREA_RATIO = 0.08  # minimum fraction of frame that must change (8%)
MOTION_LARGE_AREA_RATIO = 0.25  # fraction for "large movement" (25%)

# Cooldown: don't spam events. Minimum seconds between events of the same type.
EVENT_COOLDOWN_S = 60.0

# Sound detection
SOUND_RMS_THRESHOLD = 3000  # RMS threshold for "loud noise"
SOUND_SAMPLE_DURATION_S = 0.5  # sample window for sound level check

# Light level detection
LIGHT_LEVEL_INTERVAL_S = 30.0  # check every 30 seconds
LIGHT_CHANGE_THRESHOLD = 30  # minimum brightness change (0-255) to trigger event

# Face detection
FACE_COOLDOWN_S = 10.0  # minimum seconds between face presence events
FACE_CASCADE_FILE = "haarcascade_frontalface_default.xml"


class SensingService:
    """Background sensing loop. Runs in a daemon thread."""

    def __init__(
        self,
        camera_capture=None,
        sound_device_module=None,
        numpy_module=None,
        cv2_module=None,
        input_device: Optional[int] = None,
        poll_interval: float = 2.0,
        rgb_service=None,
        tts_service=None,
    ):
        self._camera = camera_capture
        self._sd = sound_device_module
        self._np = numpy_module
        self._cv2 = cv2_module
        self._input_device = input_device
        self._poll_interval = poll_interval

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_event_time: dict[str, float] = {}

        # Previous frame for motion detection (grayscale)
        self._prev_gray = None

        # Face detection
        self._face_cascade = None
        self._face_present = False  # track face presence state for enter/leave events

        # Light level tracking
        self._last_light_level: Optional[float] = None
        self._last_light_check: float = 0.0

        # TTS reference for echo suppression
        self._tts = tts_service

        # Presence auto on/off state machine
        self.presence = PresenceService(rgb_service=rgb_service)

        # Initialize face cascade
        if cv2_module:
            self._init_face_cascade()

    def set_tts_service(self, tts_service):
        """Set TTS reference after late initialization (echo suppression)."""
        self._tts = tts_service

    def _init_face_cascade(self):
        """Load Haar cascade for face detection."""
        cv2 = self._cv2
        try:
            cascade_path = cv2.data.haarcascades + FACE_CASCADE_FILE
            self._face_cascade = cv2.CascadeClassifier(cascade_path)
            if self._face_cascade.empty():
                logger.warning("Face cascade failed to load from %s", cascade_path)
                self._face_cascade = None
            else:
                logger.info("Face cascade loaded: %s", cascade_path)
        except Exception as e:
            logger.warning("Failed to init face cascade: %s", e)
            self._face_cascade = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="sensing")
        self._thread.start()
        logger.info("SensingService started (poll=%.1fs)", self._poll_interval)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("SensingService stopped")

    def _loop(self):
        # Wait a bit for hardware to initialize
        time.sleep(3)
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.error("Sensing tick error: %s", e)
            time.sleep(self._poll_interval)

    def _tick(self):
        frame = None

        # Read camera frame once per tick (shared across detectors)
        if self._camera and self._cv2:
            ret, frame = self._camera.read()
            if not ret:
                frame = None

            frame = cv2.rotate(frame, cv2.ROTATE_180)

        if frame is not None:
            # Motion detection
            self._check_motion(frame)

            # Face detection (presence.enter/leave)
            self._check_faces(frame)

            # Light level (every LIGHT_LEVEL_INTERVAL_S)
            self._check_light_level(frame)

        # Sound detection
        if self._sd and self._np and self._input_device is not None:
            self._check_sound()

        # Presence timeout check (dim/off)
        self.presence.tick()

    # --- Motion detection ---

    def _check_motion(self, frame):
        cv2 = self._cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if self._prev_gray is None:
            self._prev_gray = gray
            return

        delta = cv2.absdiff(self._prev_gray, gray)
        self._prev_gray = gray

        thresh = cv2.threshold(delta, MOTION_THRESHOLD, 255, cv2.THRESH_BINARY)[1]
        changed_pixels = cv2.countNonZero(thresh)
        total_pixels = thresh.shape[0] * thresh.shape[1]
        change_ratio = changed_pixels / total_pixels

        if change_ratio < MOTION_MIN_AREA_RATIO:
            return

        # Notify presence state machine (any motion = someone is here)
        self.presence.on_motion()

        if change_ratio >= MOTION_LARGE_AREA_RATIO:
            msg = "Large movement detected in camera view — someone may have entered or left the room"
        else:
            msg = "Small movement detected in camera view"

        # Attach snapshot for large movements so AI can see what's happening
        image_b64 = None
        if change_ratio >= MOTION_LARGE_AREA_RATIO:
            image_b64 = self._encode_frame(frame)

        self._send_event("motion", msg, image=image_b64)

    # --- Face detection (presence enter/leave) ---

    def _check_faces(self, frame):
        if not self._face_cascade:
            return

        cv2 = self._cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Downscale for faster detection on Pi4
        small = cv2.resize(gray, (0, 0), fx=0.5, fy=0.5)

        faces = self._face_cascade.detectMultiScale(
            small,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(30, 30),
        )

        face_found = len(faces) > 0
        prev_present = self._face_present

        if face_found and not prev_present:
            # Face entered
            self._face_present = True
            self.presence.on_motion()
            image_b64 = self._encode_frame(frame)
            self._send_event(
                "presence.enter",
                f"Person detected — {len(faces)} face(s) visible in camera view",
                image=image_b64,
                cooldown=FACE_COOLDOWN_S,
            )
        elif not face_found and prev_present:
            # Face left — only trigger after sustained absence (3 consecutive ticks)
            if not hasattr(self, "_face_absent_count"):
                self._face_absent_count = 0
            self._face_absent_count += 1
            if self._face_absent_count >= 3:
                self._face_present = False
                self._face_absent_count = 0
                self._send_event(
                    "presence.leave",
                    "No face detected — person may have left the area",
                    cooldown=FACE_COOLDOWN_S,
                )
        else:
            self._face_absent_count = 0

    # --- Light level detection ---

    def _check_light_level(self, frame):
        now = time.time()
        if now - self._last_light_check < LIGHT_LEVEL_INTERVAL_S:
            return
        self._last_light_check = now

        cv2 = self._cv2
        np = self._np
        if np is None:
            return

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        brightness = float(np.mean(gray))  # 0-255

        prev = self._last_light_level

        if prev is not None:
            change = brightness - prev
            if abs(change) >= LIGHT_CHANGE_THRESHOLD:
                if change < 0:
                    msg = f"Ambient light decreased significantly (level: {brightness:.0f}/255, change: {change:.0f})"
                else:
                    msg = f"Ambient light increased significantly (level: {brightness:.0f}/255, change: {change:+.0f})"
                self._send_event("light.level", msg, cooldown=LIGHT_LEVEL_INTERVAL_S)

        self._last_light_level = brightness

    # --- Sound detection ---

    def _check_sound(self):
        # Skip sound check while TTS is speaking (echo suppression)
        if self._tts is not None and self._tts.speaking:
            return

        sd = self._sd
        np = self._np
        try:
            sample_rate = 44100
            frames = int(sample_rate * SOUND_SAMPLE_DURATION_S)
            recording = sd.rec(frames, samplerate=sample_rate, channels=1,
                               dtype="int16", device=self._input_device, blocking=True)
            rms = float(np.sqrt(np.mean(recording.astype(np.float64) ** 2)))
            if rms >= SOUND_RMS_THRESHOLD:
                self._send_event("sound", f"Loud noise detected (level: {int(rms)})")
        except Exception as e:
            logger.debug("Sound check failed: %s", e)

    # --- Frame encoding ---

    def _encode_frame(self, frame) -> Optional[str]:
        """Encode a camera frame as base64 JPEG for sending to Lumi/OpenClaw."""
        cv2 = self._cv2
        try:
            # Resize to 320px wide for bandwidth efficiency
            h, w = frame.shape[:2]
            scale = 320 / w
            small = cv2.resize(frame, (320, int(h * scale)))
            _, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])
            return base64.b64encode(buf.tobytes()).decode("ascii")
        except Exception as e:
            logger.debug("Frame encode failed: %s", e)
            return None

    # --- Event sending ---

    def _send_event(self, event_type: str, message: str, image: Optional[str] = None, cooldown: Optional[float] = None):
        now = time.time()
        cd = cooldown if cooldown is not None else EVENT_COOLDOWN_S
        last = self._last_event_time.get(event_type, 0)
        if now - last < cd:
            return

        logger.info("[sensing] %s: %s", event_type, message)

        payload = {"type": event_type, "message": message}
        if image:
            payload["image"] = image

        try:
            resp = requests.post(
                LUMI_SENSING_URL,
                json=payload,
                timeout=5,
            )
            if resp.status_code != 200:
                logger.warning("[sensing] Lumi returned %d: %s", resp.status_code, resp.text)
            else:
                self._last_event_time[event_type] = now
        except requests.RequestException as e:
            logger.warning("[sensing] Failed to send event to Lumi: %s", e)
