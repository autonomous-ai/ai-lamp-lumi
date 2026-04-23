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
# Keep low to avoid overshoot — servo feedback is slow.
DEG_PER_PX_YAW = 0.02
DEG_PER_PX_PITCH = 0.02

# Dead zone in pixels — ignore small jitter around center
DEAD_ZONE_PX = 25

# Maximum nudge per step (degrees) — prevents wild swings
MAX_NUDGE_DEG = 2.0

# Tracking loop target FPS — higher = smoother but more CPU
TRACK_FPS = 8

# How many consecutive frames the tracker can fail before giving up
MAX_LOST_FRAMES = 15  # ~3 seconds at 5 FPS

# Servo move duration per nudge step (seconds) — short for responsiveness
NUDGE_DURATION = 0.15

# Servo position limits (degrees) — prevent runaway
YAW_MIN, YAW_MAX = -135.0, 135.0
BASE_PITCH_MIN, BASE_PITCH_MAX = -90.0, 30.0
ELBOW_PITCH_MIN, ELBOW_PITCH_MAX = -90.0, 90.0
WRIST_PITCH_MIN, WRIST_PITCH_MAX = -90.0, 90.0


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

        tracker = self._create_tracker()
        if tracker is None:
            logger.error("No OpenCV tracker available")
            return False

        try:
            ok = tracker.init(frame, bbox)
        except Exception as e:
            logger.error("tracker init exception for bbox %s: %s", bbox, e)
            return False
        # OpenCV 4.13+: init() returns None on success, older returns True
        if ok is False:
            logger.error("tracker init failed for bbox %s", bbox)
            return False
        logger.info("tracker init OK for bbox %s (frame %dx%d)", bbox, frame.shape[1], frame.shape[0])

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
            tracker = self._create_tracker()
            if tracker is None:
                return False
            try:
                ok = tracker.init(frame, bbox)
            except Exception as e:
                logger.error("Tracker re-init exception: %s", e)
                return False
            if ok is False:
                return False
            self._state.tracker = tracker
            self._state.bbox = bbox
            self._state.lost_frames = 0
            logger.info("Tracker re-initialized with bbox %s", bbox)
            return True

    @staticmethod
    def _create_tracker():
        """Create the best available OpenCV tracker.

        Priority: CSRT > KCF > TrackerNano > TrackerMIL (most widely available).
        """
        # CSRT/KCF: best quality, need opencv-contrib.
        # MIL: always available, no extra models needed.
        # Nano/Vit: need ONNX model files — skip unless present.
        candidates = [
            ("CSRT", lambda: cv2.TrackerCSRT.create()),
            ("KCF", lambda: cv2.TrackerKCF.create()),
            ("MIL", lambda: cv2.TrackerMIL.create()),
        ]
        for name, factory in candidates:
            try:
                tracker = factory()
                logger.info("Using OpenCV tracker: %s", name)
                return tracker
            except (AttributeError, cv2.error, Exception):
                continue
        return None

    # --- Internal tracking loop ---

    def _track_loop(self, camera_capture, animation_service):
        """Background loop: grab frame → update tracker → nudge servo."""
        state = self._state

        # Suppress idle animations during tracking
        animation_service._hold_mode = True
        logger.info("Servo hold mode ON for tracking")

        # Read initial servo position once — track internally after that
        try:
            from lelamp.service.motors.animation_service import _motor_positions_from_bus
            with animation_service.bus_lock:
                init_pos = _motor_positions_from_bus(animation_service.robot)
            self._track_yaw = init_pos.get("base_yaw.pos", 0.0)
            self._track_base_pitch = init_pos.get("base_pitch.pos", 0.0)
            self._track_elbow_pitch = init_pos.get("elbow_pitch.pos", 0.0)
            self._track_wrist_pitch = init_pos.get("wrist_pitch.pos", 0.0)
        except Exception:
            self._track_yaw = 0.0
            self._track_base_pitch = 0.0
            self._track_elbow_pitch = 0.0
            self._track_wrist_pitch = 0.0
        logger.info("Tracking start servo pos: yaw=%.1f base_pitch=%.1f elbow=%.1f wrist=%.1f",
                     self._track_yaw, self._track_base_pitch, self._track_elbow_pitch, self._track_wrist_pitch)

        frame_count = 0
        fps_t0 = time.perf_counter()

        try:
            while state.running.is_set():
                t0 = time.perf_counter()

                frame = camera_capture.last_frame
                if frame is None:
                    logger.debug("Tracker: no frame from camera, skipping")
                    time.sleep(1.0 / TRACK_FPS)
                    continue

                ok, new_bbox = state.tracker.update(frame)
                tracker_dt = time.perf_counter() - t0

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

                # Log FPS + bbox every ~2 seconds
                frame_count += 1
                fps_elapsed = time.perf_counter() - fps_t0
                if fps_elapsed >= 2.0:
                    actual_fps = frame_count / fps_elapsed
                    logger.info(
                        "Tracker: fps=%.1f tracker_dt=%.0fms bbox=%s lost=%d target='%s'",
                        actual_fps, tracker_dt * 1000, state.bbox, state.lost_frames, state.target_label,
                    )
                    frame_count = 0
                    fps_t0 = time.perf_counter()

                # Maintain target FPS
                dt = time.perf_counter() - t0
                sleep_time = (1.0 / TRACK_FPS) - dt
                if sleep_time > 0:
                    time.sleep(sleep_time)
        finally:
            # Resume idle animations
            animation_service._hold_mode = False
            state.running.clear()

            # Restart animation event loop + play idle
            from lelamp.presets import SERVO_CMD_PLAY
            if not animation_service._running.is_set():
                import threading as _threading
                animation_service._running.set()
                animation_service._event_thread = _threading.Thread(
                    target=animation_service._event_loop, daemon=True
                )
                animation_service._event_thread.start()
            animation_service.dispatch(SERVO_CMD_PLAY, animation_service.idle_recording)
            logger.info("Servo resumed idle — tracking ended")

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

        # Convert to degrees
        # Object left of center (dx < 0) → servo turn left (yaw < 0) → same sign
        # Object below center (dy > 0) → servo tilt down (pitch < 0) → negate
        yaw_deg = dx * DEG_PER_PX_YAW
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

        # Update internal position and send to servo
        # Split pitch across 3 joints for full range of motion
        try:
            new_yaw = max(YAW_MIN, min(YAW_MAX, self._track_yaw + yaw_deg))

            pitch_each = pitch_deg / 3.0
            new_base_pitch = max(BASE_PITCH_MIN, min(BASE_PITCH_MAX, self._track_base_pitch + pitch_each))
            new_elbow_pitch = max(ELBOW_PITCH_MIN, min(ELBOW_PITCH_MAX, self._track_elbow_pitch + pitch_each))
            new_wrist_pitch = max(WRIST_PITCH_MIN, min(WRIST_PITCH_MAX, self._track_wrist_pitch + pitch_each))

            target = {
                "base_yaw.pos": new_yaw,
                "base_pitch.pos": new_base_pitch,
                "elbow_pitch.pos": new_elbow_pitch,
                "wrist_pitch.pos": new_wrist_pitch,
            }

            logger.info(
                "Nudge: offset_px=(%.0f,%.0f) deg=(%.2f,%.2f) yaw=%.1f→%.1f pitch=%.1f/%.1f/%.1f",
                dx, dy, yaw_deg, pitch_deg,
                self._track_yaw, new_yaw,
                new_base_pitch, new_elbow_pitch, new_wrist_pitch,
            )

            animation_service.move_to(target, duration=NUDGE_DURATION)

            self._track_yaw = new_yaw
            self._track_base_pitch = new_base_pitch
            self._track_elbow_pitch = new_elbow_pitch
            self._track_wrist_pitch = new_wrist_pitch
        except Exception as e:
            logger.warning("Tracker nudge failed: %s", e)
