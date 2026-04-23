"""Vision-guided object tracking with servo follow.

Workflow:
  1. Caller provides an initial bounding box (x, y, w, h) on the current frame.
     The bbox can come from any source: LLM vision, YOLO, manual selection, etc.
  2. An OpenCV CSRT tracker locks onto the object.
  3. A background loop grabs frames from the camera, updates the tracker,
     computes the pixel offset from frame center, converts it to yaw/pitch
     degrees, and nudges the servo to keep the object centered.
  4. When the tracker loses confidence or the caller stops tracking, the loop
     exits and servos resume normal idle animation.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Tuple

import cv2
import numpy as np
import numpy.typing as npt

logger = logging.getLogger(__name__)

# --- Tuning knobs ---

# Degrees per pixel — controls how aggressively servo reacts to offset.
# Depends on camera FOV; 640px width ≈ 60° horizontal → ~0.094 deg/px.
# Start conservative; can be calibrated per device.
DEG_PER_PX_YAW = 0.08
DEG_PER_PX_PITCH = 0.08

# Dead zone in pixels — ignore small jitter around center
DEAD_ZONE_PX = 20

# Maximum nudge per step (degrees) — prevents wild swings
MAX_NUDGE_DEG = 10.0

# Tracking loop target FPS
TRACK_FPS = 10

# How many consecutive frames the tracker can fail before giving up
MAX_LOST_FRAMES = 15  # ~1.5 seconds at 10 FPS

# Servo move duration per nudge step (seconds) — short for responsiveness
NUDGE_DURATION = 0.15


@dataclass
class TrackingState:
    """Mutable state for the active tracking session."""
    target_label: str = ""
    tracker: Optional[cv2.Tracker] = None
    bbox: Optional[Tuple[int, int, int, int]] = None  # (x, y, w, h)
    lost_frames: int = 0
    running: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None


class TrackerService:
    """Manages a single object-tracking session with servo follow."""

    def __init__(self):
        self._state = TrackingState()
        self._lock = threading.Lock()

    @property
    def is_tracking(self) -> bool:
        return self._state.running.is_set()

    @property
    def status(self) -> dict:
        s = self._state
        return {
            "tracking": s.running.is_set(),
            "target": s.target_label or None,
            "bbox": list(s.bbox) if s.bbox else None,
            "lost_frames": s.lost_frames,
        }

    def start(
        self,
        bbox: Tuple[int, int, int, int],
        target_label: str = "",
        camera_capture=None,
        animation_service=None,
    ) -> bool:
        """Start tracking an object defined by *bbox* on the current frame.

        Args:
            bbox: (x, y, w, h) bounding box in pixel coordinates.
            target_label: human-readable label (for logging / status).
            camera_capture: LocalVideoCaptureDevice instance (app_state.camera_capture).
            animation_service: AnimationService instance (app_state.animation_service).

        Returns:
            True if tracking started successfully.
        """
        if camera_capture is None or animation_service is None:
            logger.error("tracker start: camera or animation service not available")
            return False

        # Stop any existing session
        self.stop()

        frame = camera_capture.last_frame
        if frame is None:
            logger.error("tracker start: no frame available from camera")
            return False

        # Create CSRT tracker (good accuracy, reasonable speed on Pi)
        try:
            tracker = cv2.TrackerCSRT.create()
        except AttributeError:
            # opencv-python (non-contrib) may not have CSRT; fall back to KCF
            logger.warning("CSRT not available, falling back to KCF tracker")
            tracker = cv2.TrackerKCF.create()

        ok = tracker.init(frame, bbox)
        if not ok:
            logger.error("tracker init failed for bbox %s", bbox)
            return False

        with self._lock:
            self._state = TrackingState(
                target_label=target_label,
                tracker=tracker,
                bbox=bbox,
                lost_frames=0,
            )
            self._state.running.set()
            self._state.thread = threading.Thread(
                target=self._track_loop,
                args=(camera_capture, animation_service),
                daemon=True,
                name="servo-tracker",
            )
            self._state.thread.start()

        logger.info("Tracking started: '%s' bbox=%s", target_label, bbox)
        return True

    def stop(self):
        """Stop the current tracking session."""
        with self._lock:
            if not self._state.running.is_set():
                return
            self._state.running.clear()
            t = self._state.thread

        if t and t.is_alive():
            t.join(timeout=3.0)

        logger.info("Tracking stopped: '%s'", self._state.target_label)

    def update_bbox(self, bbox: Tuple[int, int, int, int], camera_capture=None):
        """Re-initialize tracker with a new bounding box (e.g. after LLM re-detect)."""
        with self._lock:
            if not self._state.running.is_set():
                return False
            frame = camera_capture.last_frame if camera_capture else None
            if frame is None:
                return False
            try:
                tracker = cv2.TrackerCSRT.create()
            except AttributeError:
                tracker = cv2.TrackerKCF.create()
            ok = tracker.init(frame, bbox)
            if ok:
                self._state.tracker = tracker
                self._state.bbox = bbox
                self._state.lost_frames = 0
                logger.info("Tracker re-initialized with bbox %s", bbox)
            return ok

    # --- Internal tracking loop ---

    def _track_loop(self, camera_capture, animation_service):
        """Background loop: grab frame → update tracker → nudge servo."""
        state = self._state

        # Suppress idle animations during tracking
        animation_service._hold_mode = True
        logger.info("Servo hold mode ON for tracking")

        try:
            while state.running.is_set():
                t0 = time.perf_counter()

                frame = camera_capture.last_frame
                if frame is None:
                    time.sleep(1.0 / TRACK_FPS)
                    continue

                ok, new_bbox = state.tracker.update(frame)

                if ok:
                    state.bbox = tuple(int(v) for v in new_bbox)
                    state.lost_frames = 0
                    self._nudge_servo(frame, state.bbox, animation_service)
                else:
                    state.lost_frames += 1
                    logger.debug("Tracker lost frame %d/%d", state.lost_frames, MAX_LOST_FRAMES)
                    if state.lost_frames >= MAX_LOST_FRAMES:
                        logger.warning("Tracker lost target '%s' for %d frames, stopping",
                                       state.target_label, MAX_LOST_FRAMES)
                        break

                # Maintain target FPS
                dt = time.perf_counter() - t0
                sleep_time = (1.0 / TRACK_FPS) - dt
                if sleep_time > 0:
                    time.sleep(sleep_time)
        finally:
            # Resume idle animations
            animation_service._hold_mode = False
            logger.info("Servo hold mode OFF — tracking ended")
            state.running.clear()

    def _nudge_servo(
        self,
        frame: npt.NDArray[np.uint8],
        bbox: Tuple[int, int, int, int],
        animation_service,
    ):
        """Compute offset from frame center and nudge servo."""
        h, w = frame.shape[:2]
        cx_frame = w / 2
        cy_frame = h / 2

        # Object center
        bx, by, bw, bh = bbox
        cx_obj = bx + bw / 2
        cy_obj = by + bh / 2

        # Pixel offset (positive = object is right/below center)
        dx = cx_obj - cx_frame
        dy = cy_obj - cy_frame

        # Dead zone
        if abs(dx) < DEAD_ZONE_PX and abs(dy) < DEAD_ZONE_PX:
            return

        # Convert to degrees — negate yaw because camera is mirrored
        # (object moves right in frame → servo should turn right → positive yaw)
        yaw_deg = -dx * DEG_PER_PX_YAW
        pitch_deg = -dy * DEG_PER_PX_PITCH

        # Clamp
        yaw_deg = max(-MAX_NUDGE_DEG, min(MAX_NUDGE_DEG, yaw_deg))
        pitch_deg = max(-MAX_NUDGE_DEG, min(MAX_NUDGE_DEG, pitch_deg))

        # Apply dead zone per axis
        if abs(dx) < DEAD_ZONE_PX:
            yaw_deg = 0
        if abs(dy) < DEAD_ZONE_PX:
            pitch_deg = 0

        if yaw_deg == 0 and pitch_deg == 0:
            return

        # Direct servo nudge — bypass HTTP for speed
        try:
            with animation_service.bus_lock:
                obs = animation_service.robot.get_observation()
            current = {k: v for k, v in obs.items() if k.endswith(".pos")}

            positions = dict(current)
            positions["base_yaw.pos"] = current.get("base_yaw.pos", 0) + yaw_deg
            positions["base_pitch.pos"] = current.get("base_pitch.pos", 0) + pitch_deg

            animation_service.move_to(positions, duration=NUDGE_DURATION)
        except Exception as e:
            logger.warning("Tracker nudge failed: %s", e)
