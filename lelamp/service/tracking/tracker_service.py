"""Vision-guided object tracking with servo follow.

Workflow:
  1. Caller provides an initial bounding box (x, y, w, h) on the current frame.
     The bbox can come from any source: LLM vision, YOLO, manual selection, etc.
  2. TrackerVit (ViT-based, ONNX) locks onto the object with confidence scoring.
  3. A background loop grabs frames from the camera, updates the tracker,
     computes the pixel offset from frame center, converts it to yaw/pitch
     degrees, and nudges the servo to keep the object centered.
  4. When confidence drops below threshold or the caller stops tracking,
     the loop exits and servos resume normal idle animation.
"""

import base64
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Tuple

import cv2
import numpy as np
import numpy.typing as npt
import requests

logger = logging.getLogger(__name__)

# --- Model paths ---

_VIT_MODEL = os.path.join(os.path.dirname(__file__), "vittrack.onnx")

# --- YOLOWorld API ---

_YOLO_ENDPOINT = "/detect/yoloworld"
_YOLO_TIMEOUT = 10.0

# --- Tuning knobs ---

# Degrees per pixel — keep low to avoid overshoot.
DEG_PER_PX_YAW = 0.02
DEG_PER_PX_PITCH = 0.02

# Dead zone in pixels — stop nudging when object is within this range
DEAD_ZONE_PX = 15

# Wake zone — when settled, only resume nudging when object moves beyond this
WAKE_ZONE_PX = 50

# Maximum nudge per step (degrees) — prevents wild swings
MAX_NUDGE_DEG = 1.5

# Tracking loop target FPS — higher = smoother
TRACK_FPS = 12

# TrackerVit confidence threshold — below this = lost
CONFIDENCE_THRESHOLD = 0.3

# How many consecutive low-confidence frames before stopping
MAX_LOW_CONFIDENCE_FRAMES = 5

# Bbox jump threshold — if center moves more than this many pixels in one
# frame, consider it a tracker glitch and skip the nudge
BBOX_JUMP_PX = 100

# Servo move duration per nudge step (seconds)
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
    confidence: float = 0.0
    low_confidence_frames: int = 0
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
            "confidence": round(s.confidence, 3),
        }

    def detect_object(self, frame: npt.NDArray[np.uint8], target: str) -> Optional[Tuple[int, int, int, int]]:
        """Detect an object by name using YOLOWorld API.

        Returns (x, y, w, h) top-left bbox or None if not found.
        """
        from lelamp.config import DL_BACKEND_URL, DL_API_KEY
        if not DL_BACKEND_URL:
            logger.error("YOLOWorld: DL_BACKEND_URL not configured")
            return None

        url = DL_BACKEND_URL.rstrip("/") + "/" + _YOLO_ENDPOINT.strip("/")
        try:
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            img_b64 = base64.b64encode(buf.tobytes()).decode()

            resp = requests.post(
                url,
                json={"image_b64": img_b64, "classes": [target]},
                headers={"x-api-key": DL_API_KEY} if DL_API_KEY else {},
                timeout=_YOLO_TIMEOUT,
            )
            if resp.status_code != 200:
                logger.warning("YOLOWorld HTTP %d: %s", resp.status_code, resp.text[:200])
                return None

            detections = resp.json()
            if not detections:
                logger.info("YOLOWorld: '%s' not found in frame", target)
                return None

            # Pick highest confidence detection
            best = max(detections, key=lambda d: d.get("confidence", 0))
            cx, cy, w, h = best["xywh"]
            # Convert center format to top-left format
            x = int(cx - w / 2)
            y = int(cy - h / 2)
            bbox = (x, y, int(w), int(h))
            logger.info("YOLOWorld: '%s' found at bbox=%s conf=%.3f", target, bbox, best["confidence"])
            return bbox
        except Exception as e:
            logger.error("YOLOWorld detect failed: %s", e)
            return None

    def start(
        self,
        bbox: Optional[Tuple[int, int, int, int]] = None,
        target_label: str = "",
        camera_capture=None,
        animation_service=None,
    ) -> bool:
        """Start tracking an object.

        If bbox is provided, use it directly. Otherwise, auto-detect using YOLOWorld.
        """
        if camera_capture is None or animation_service is None:
            logger.error("tracker start: camera or animation service not available")
            return False

        self.stop()

        frame = camera_capture.last_frame
        if frame is None:
            logger.error("tracker start: no frame available from camera")
            return False

        # Auto-detect if no bbox provided
        if bbox is None:
            if not target_label:
                logger.error("tracker start: need either bbox or target label")
                return False
            bbox = self.detect_object(frame, target_label)
            if bbox is None:
                return False
            # Re-grab fresh frame right after detection
            fresh = camera_capture.last_frame
            if fresh is not None:
                frame = fresh

        tracker = self._create_tracker()
        if tracker is None:
            logger.error("No OpenCV tracker available")
            return False

        try:
            ok = tracker.init(frame, bbox)
        except Exception as e:
            logger.error("tracker init exception for bbox %s: %s", bbox, e)
            return False
        if ok is False:
            logger.error("tracker init failed for bbox %s", bbox)
            return False
        logger.info("tracker init OK for bbox %s (frame %dx%d)", bbox, frame.shape[1], frame.shape[0])

        with self._lock:
            self._state = TrackingState(
                target_label=target_label,
                tracker=tracker,
                bbox=bbox,
                confidence=1.0,
                low_confidence_frames=0,
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
            self._state.confidence = 1.0
            self._state.low_confidence_frames = 0
            logger.info("Tracker re-initialized with bbox %s", bbox)
            return True

    @staticmethod
    def _create_tracker():
        """Create TrackerVit (best available) or fall back to MIL."""
        # TrackerVit: ViT-based, has confidence score, good accuracy
        if os.path.exists(_VIT_MODEL):
            try:
                params = cv2.TrackerVit_Params()
                params.net = _VIT_MODEL
                tracker = cv2.TrackerVit.create(params)
                logger.info("Using OpenCV tracker: Vit (model=%s)", _VIT_MODEL)
                return tracker
            except Exception as e:
                logger.warning("TrackerVit failed: %s", e)

        # Fallback chain
        candidates = [
            ("CSRT", lambda: cv2.TrackerCSRT.create()),
            ("KCF", lambda: cv2.TrackerKCF.create()),
            ("MIL", lambda: cv2.TrackerMIL.create()),
        ]
        for name, factory in candidates:
            try:
                tracker = factory()
                logger.info("Using OpenCV tracker: %s (no confidence scoring)", name)
                return tracker
            except (AttributeError, cv2.error, Exception):
                continue
        return None

    def _get_confidence(self) -> float:
        """Get tracker confidence score. Only TrackerVit supports this."""
        try:
            return self._state.tracker.getTrackingScore()
        except (AttributeError, Exception):
            return 1.0  # assume OK for trackers without confidence

    # --- Internal tracking loop ---

    def _track_loop(self, camera_capture, animation_service):
        """Background loop: grab frame → update tracker → nudge servo."""
        state = self._state

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

        prev_cx, prev_cy = None, None
        self._settled = False
        frame_count = 0
        fps_t0 = time.perf_counter()

        try:
            while state.running.is_set():
                t0 = time.perf_counter()

                frame = camera_capture.last_frame
                if frame is None:
                    time.sleep(1.0 / TRACK_FPS)
                    continue

                ok, new_bbox = state.tracker.update(frame)
                tracker_dt = time.perf_counter() - t0
                confidence = self._get_confidence()
                state.confidence = confidence

                if not ok or confidence < CONFIDENCE_THRESHOLD:
                    state.low_confidence_frames += 1
                    logger.info("Tracker low confidence: %.3f (frame %d/%d) target='%s'",
                                confidence, state.low_confidence_frames,
                                MAX_LOW_CONFIDENCE_FRAMES, state.target_label)
                    if state.low_confidence_frames >= MAX_LOW_CONFIDENCE_FRAMES:
                        logger.warning("Tracker lost target '%s' (confidence=%.3f), stopping",
                                       state.target_label, confidence)
                        break
                    time.sleep(1.0 / TRACK_FPS)
                    continue

                state.low_confidence_frames = 0
                state.bbox = tuple(int(v) for v in new_bbox)
                bx, by, bw, bh = state.bbox
                cx = bx + bw / 2
                cy = by + bh / 2

                # Detect bbox jump (tracker glitch)
                if prev_cx is not None:
                    jump = ((cx - prev_cx) ** 2 + (cy - prev_cy) ** 2) ** 0.5
                    if jump > BBOX_JUMP_PX:
                        logger.warning("Bbox jump %.0fpx, skipping nudge", jump)
                        prev_cx, prev_cy = cx, cy
                        time.sleep(1.0 / TRACK_FPS)
                        continue
                prev_cx, prev_cy = cx, cy

                self._nudge_servo(frame, state.bbox, animation_service)

                # Log every ~2 seconds
                frame_count += 1
                fps_elapsed = time.perf_counter() - fps_t0
                if fps_elapsed >= 2.0:
                    logger.info(
                        "Tracker: fps=%.1f dt=%.0fms conf=%.3f bbox=%s target='%s'",
                        frame_count / fps_elapsed, tracker_dt * 1000,
                        confidence, state.bbox, state.target_label,
                    )
                    frame_count = 0
                    fps_t0 = time.perf_counter()

                # Maintain target FPS
                dt = time.perf_counter() - t0
                sleep_time = (1.0 / TRACK_FPS) - dt
                if sleep_time > 0:
                    time.sleep(sleep_time)
        finally:
            animation_service._hold_mode = False
            state.running.clear()

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

        bx, by, bw, bh = bbox
        cx_obj = bx + bw / 2
        cy_obj = by + bh / 2

        dx = cx_obj - cx_frame
        dy = cy_obj - cy_frame

        # Hysteresis: once settled, only wake when object moves far enough
        if self._settled:
            if abs(dx) < WAKE_ZONE_PX and abs(dy) < WAKE_ZONE_PX:
                return
            self._settled = False
            logger.info("Tracking wake: object moved to offset (%.0f, %.0f)", dx, dy)

        if abs(dx) < DEAD_ZONE_PX and abs(dy) < DEAD_ZONE_PX:
            if not self._settled:
                self._settled = True
                logger.info("Tracking settled: object near center (%.0f, %.0f)", dx, dy)
            return

        yaw_deg = dx * DEG_PER_PX_YAW
        pitch_deg = dy * DEG_PER_PX_PITCH

        yaw_deg = max(-MAX_NUDGE_DEG, min(MAX_NUDGE_DEG, yaw_deg))
        pitch_deg = max(-MAX_NUDGE_DEG, min(MAX_NUDGE_DEG, pitch_deg))

        if abs(dx) < DEAD_ZONE_PX:
            yaw_deg = 0
        if abs(dy) < DEAD_ZONE_PX:
            pitch_deg = 0

        if yaw_deg == 0 and pitch_deg == 0:
            return

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

            logger.debug(
                "Nudge: px=(%.0f,%.0f) deg=(%.2f,%.2f) yaw=%.1f→%.1f pitch=%.1f/%.1f/%.1f",
                dx, dy, yaw_deg, pitch_deg,
                self._track_yaw, new_yaw,
                new_base_pitch, new_elbow_pitch, new_wrist_pitch,
            )

            with animation_service.bus_lock:
                animation_service.robot.send_action(target)

            self._track_yaw = new_yaw
            self._track_base_pitch = new_base_pitch
            self._track_elbow_pitch = new_elbow_pitch
            self._track_wrist_pitch = new_wrist_pitch
        except Exception as e:
            logger.warning("Tracker nudge failed: %s", e)
