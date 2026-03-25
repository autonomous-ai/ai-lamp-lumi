"""
Sensing Service — background loop that detects motion/sound and pushes events to Lumi Server.

Lumi Server (Go, port 5000) then forwards these events to OpenClaw via WebSocket chat.send,
so the AI agent can react proactively (Pillar 4: "It acts on its own").

Detectors:
  - Motion: camera frame differencing (grayscale → absdiff → threshold → contour area)
  - Sound: RMS level from microphone (loud noise detection)

Events are POST-ed to http://localhost:5000/api/sensing/event as:
  {"type": "motion", "message": "Person detected — large movement in camera view"}
"""

import logging
import threading
import time
from typing import Optional, Callable

import requests

logger = logging.getLogger("lelamp.sensing")

LUMI_SENSING_URL = "http://127.0.0.1:5000/api/sensing/event"

# Motion detection thresholds
MOTION_THRESHOLD = 30  # pixel intensity change to count as "changed"
MOTION_MIN_AREA_RATIO = 0.02  # minimum fraction of frame that must change (2%)
MOTION_LARGE_AREA_RATIO = 0.15  # fraction for "large movement" (15%)

# Cooldown: don't spam events. Minimum seconds between events of the same type.
EVENT_COOLDOWN_S = 10.0

# Sound detection
SOUND_RMS_THRESHOLD = 3000  # RMS threshold for "loud noise"
SOUND_SAMPLE_DURATION_S = 0.5  # sample window for sound level check


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
        # Motion detection
        if self._camera and self._cv2:
            self._check_motion()

        # Sound detection
        if self._sd and self._np and self._input_device is not None:
            self._check_sound()

    # --- Motion detection ---

    def _check_motion(self):
        cv2 = self._cv2
        ret, frame = self._camera.read()
        if not ret:
            return

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

        if change_ratio >= MOTION_LARGE_AREA_RATIO:
            msg = "Large movement detected in camera view — someone may have entered or left the room"
        else:
            msg = "Small movement detected in camera view"

        self._send_event("motion", msg)

    # --- Sound detection ---

    def _check_sound(self):
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

    # --- Event sending ---

    def _send_event(self, event_type: str, message: str):
        now = time.time()
        last = self._last_event_time.get(event_type, 0)
        if now - last < EVENT_COOLDOWN_S:
            return

        self._last_event_time[event_type] = now
        logger.info("[sensing] %s: %s", event_type, message)

        try:
            resp = requests.post(
                LUMI_SENSING_URL,
                json={"type": event_type, "message": message},
                timeout=5,
            )
            if resp.status_code != 200:
                logger.warning("[sensing] Lumi returned %d: %s", resp.status_code, resp.text)
        except requests.RequestException as e:
            logger.warning("[sensing] Failed to send event to Lumi: %s", e)
