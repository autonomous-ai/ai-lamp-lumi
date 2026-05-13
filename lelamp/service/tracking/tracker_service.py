"""Vision-guided object tracking with servo follow — gimbal hybrid mode.

Workflow:
  1. Caller provides a target label (or bbox). YOLO finds the object in the
     current frame and initialises a CSRT local tracker.
  2. A fast loop (FAST_LOOP_FPS) updates CSRT each frame, computes the pixel
     offset from frame center, and applies EMA smoothing before nudging servos.
  3. A background YOLO thread fires every YOLO_REDETECT_S to correct tracker
     drift — it does NOT block the fast loop (non-freezing, queue-based).
  4. If CSRT loses the object YOLO_MAX_MISS times in a row, tracking stops.
"""

import base64
import logging
import math
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Tuple

import cv2
import numpy as np
import numpy.typing as npt
import requests

logger = logging.getLogger(__name__)

# --- Detection API ---

# Available models on the autonomous backend:
#   "owlv2"
#   "yoloe"
#   "grounding-dino"
#   "yoloworld"
_DETECT_MODEL = "yoloworld"
_YOLO_ENDPOINT = f"/detect/{_DETECT_MODEL}"
_YOLO_TIMEOUT = 10.0

# --- Tuning knobs ---

# Fast loop target FPS — CSRT on Pi runs ~15-25ms/frame so 15 FPS is stable.
FAST_LOOP_FPS = 15

# Camera field-of-view in degrees (horizontal). Used to convert px offset → degrees.
CAMERA_FOV_DEG = 60.0

# Gimbal gain: fraction of offset to correct each step (0-1).
# 0.25 = 25% correction per fire — converges in ~4-5 cooldown cycles.
GIMBAL_GAIN = 0.9

# Maximum servo step per fire (degrees). 5° balances convergence speed vs camera shake.
GIMBAL_MAX_STEP = 5.0

# Adaptive step: when offset > ADAPTIVE_GAIN_PX, multiply max step by ADAPTIVE_GAIN_MULT.
# Large offsets get bigger steps (fast chase), small offsets keep fine control.
ADAPTIVE_GAIN_PX = 60
ADAPTIVE_GAIN_MULT = 2.0

# Dead zone in pixels — no servo command if offset is within this radius.
DEAD_ZONE_PX = 7

# EMA smoothing on pixel offset before servo command (0-1).
# Lower = smoother (less jitter) but slower response.
EMA_ALPHA = 0.5

# Settle delay (seconds) after each servo command.
# Short enough for 15fps; long enough for the servo to physically move.
SERVO_SETTLE_S = 0.02

# YOLO background re-detect interval (seconds).
YOLO_REDETECT_S = 2.0

# How many consecutive CSRT miss frames before stopping (YOLO may recover first).
YOLO_MAX_MISS = 4

# Motion detection: EMA-offset delta between consecutive frames to count as "moving".
# Tuned for ~10fps CSRT (100ms/frame) — stationary CSRT jitter ≈ 5-15px EMA delta.
MOTION_THRESHOLD_PX = 20

# Consecutive stable frames needed to declare object "settled".
# At 10fps: 2 frames ≈ 200ms of stillness before servo fires.
MOTION_SETTLE_FRAMES = 2

# Cooldown after servo fire (seconds) — ignore motion detection while camera
# stabilises after a move. Prevents servo shake → fake MOVE → immediate re-fire loop.
SERVO_COOLDOWN_S = 0.10

SERVO_SUBSTEP_DEG   = 10.0  # max degrees per sub-step
SERVO_SUBSTEP_SLEEP = 0.02  # seconds between sub-steps

# Pitch distribution across 3 joints.
PITCH_WEIGHT_BASE  = 0.10
PITCH_WEIGHT_ELBOW = 0.70
PITCH_WEIGHT_WRIST = 0.20

# Edge proximity boost — when object nears frame edge, multiply correction
# to pull it back toward center before it exits the frame.
EDGE_BOOST_THRESHOLD = 0.30   # fraction of frame (30%)
EDGE_BOOST_MULT      = 1.5

# Maximum tracking duration (seconds) — auto-stop to save motor/CPU.
MAX_TRACK_DURATION_S = 300  # 5 minutes

# Servo position limits (degrees).
YAW_MIN, YAW_MAX = -135.0, 135.0
BASE_PITCH_MIN, BASE_PITCH_MAX = -90.0, 30.0
ELBOW_PITCH_MIN, ELBOW_PITCH_MAX = -90.0, 90.0
WRIST_PITCH_MIN, WRIST_PITCH_MAX = -90.0, 90.0

# YOLOWorld detection quality filters.
DETECT_MIN_AREA_RATIO = 0.003
DETECT_MAX_AREA_RATIO = 0.80
DETECT_MIN_CONFIDENCE = 0.45


@dataclass
class TrackingState:
    """Mutable state for the active tracking session."""
    target_label: str = ""
    tracker: Optional[cv2.Tracker] = None
    bbox: Optional[Tuple[int, int, int, int]] = None
    running: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None


class TrackerService:
    """Manages a single object-tracking session with gimbal-style servo follow."""

    def __init__(self):
        self._state = TrackingState()
        self._lock = threading.Lock()
        self.last_error: str = ""

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
        logger.info("[tracking_yolo_request] target='%s' url=%s", target, url)
        t_req = time.perf_counter()
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

            frame_area = float(frame.shape[0] * frame.shape[1])
            valid = []
            for d in detections:
                cx, cy, w, h = d["xywh"]
                conf = d.get("confidence", 0)
                area_ratio = (w * h) / frame_area if frame_area > 0 else 0.0
                cname = d.get("class_name", "?")
                if conf < DETECT_MIN_CONFIDENCE:
                    reason = "REJECTED (conf)"
                elif not (DETECT_MIN_AREA_RATIO <= area_ratio <= DETECT_MAX_AREA_RATIO):
                    reason = "REJECTED (size)"
                else:
                    reason = "ACCEPTED"
                logger.info(
                    "  YOLO candidate: class='%s' conf=%.3f bbox=(%d,%d,%d,%d) area=%.1f%% %s",
                    cname, conf, int(cx - w / 2), int(cy - h / 2), int(w), int(h),
                    area_ratio * 100, reason,
                )
                if reason == "ACCEPTED":
                    valid.append(d)

            if not valid:
                logger.warning(
                    "YOLOWorld: '%s' — %d detection(s) but none passed filters "
                    "(conf >= %.2f, area %.1f%%–%.1f%%)",
                    target, len(detections), DETECT_MIN_CONFIDENCE,
                    DETECT_MIN_AREA_RATIO * 100, DETECT_MAX_AREA_RATIO * 100,
                )
                return None

            best = max(valid, key=lambda d: d.get("confidence", 0))
            cx, cy, w, h = best["xywh"]
            x = int(cx - w / 2)
            y = int(cy - h / 2)
            bbox = (x, y, int(w), int(h))
            latency_ms = (time.perf_counter() - t_req) * 1000
            logger.info("YOLOWorld: '%s' found at bbox=%s conf=%.3f", target, bbox, best["confidence"])
            logger.info("[tracking_yolo_response] target='%s' found=True bbox=%s conf=%.3f latency=%.0fms",
                        target, bbox, best["confidence"], latency_ms)
            return bbox
        except Exception as e:
            logger.error("YOLOWorld detect failed: %s", e)
            return None

    def start(
        self,
        bbox: Optional[Tuple[int, int, int, int]] = None,
        target_label="",
        camera_capture=None,
        animation_service=None,
    ) -> bool:
        """Start tracking an object.

        If bbox is provided, use it directly. Otherwise, auto-detect via YOLOWorld.
        target_label accepts str or list[str] — first non-empty label is used.
        """
        if camera_capture is None or animation_service is None:
            self.last_error = "camera or animation service not available"
            logger.error("tracker start: %s", self.last_error)
            return False

        if isinstance(target_label, (list, tuple)):
            target_label = next((t for t in target_label if t), "")

        self.stop()

        # Freeze servos so YOLO + tracker init see a sharp, stable frame.
        settle_s = 0.30
        t_req = time.perf_counter()
        animation_service.freeze()
        try:
            time.sleep(settle_s)
            t_after_settle = time.perf_counter()

            frame = camera_capture.last_frame
            if frame is None:
                self.last_error = "no frame available from camera"
                logger.error("tracker start: %s", self.last_error)
                animation_service.unfreeze()
                return False
            frame = frame.copy()

            t_yolo_ms = 0.0
            if bbox is None:
                if not target_label:
                    self.last_error = "need either bbox or target label"
                    logger.error("tracker start: %s", self.last_error)
                    animation_service.unfreeze()
                    return False
                t_yolo0 = time.perf_counter()
                bbox = self.detect_object(frame, target_label)
                t_yolo_ms = (time.perf_counter() - t_yolo0) * 1000
                if bbox is None:
                    self.last_error = f"'{target_label}' not found in frame"
                    logger.info("[track-start] settle=%.0fms yolo=%.0fms result=missed target='%s'",
                                (t_after_settle - t_req) * 1000, t_yolo_ms, target_label)
                    animation_service.unfreeze()
                    return False
        except Exception:
            animation_service.unfreeze()
            raise

        tracker = self._create_tracker()
        if tracker is None:
            logger.error("No OpenCV tracker available")
            animation_service.unfreeze()
            return False

        t_init0 = time.perf_counter()
        try:
            ok = tracker.init(frame, bbox)
        except Exception as e:
            logger.error("tracker init exception for bbox %s: %s", bbox, e)
            animation_service.unfreeze()
            return False
        if ok is False:
            logger.error("tracker init failed for bbox %s", bbox)
            animation_service.unfreeze()
            return False
        t_init_ms = (time.perf_counter() - t_init0) * 1000
        t_total_ms = (time.perf_counter() - t_req) * 1000
        logger.info(
            "[track-start] settle=%.0fms yolo=%.0fms init=%.0fms total=%.0fms bbox=%s target='%s'",
            (t_after_settle - t_req) * 1000, t_yolo_ms, t_init_ms, t_total_ms, bbox, target_label,
        )

        with self._lock:
            self._state = TrackingState(
                target_label=target_label,
                tracker=tracker,
                bbox=bbox,
            )
            self._state.running.set()
            self._state.thread = threading.Thread(
                target=self._track_loop,
                args=(camera_capture, animation_service),
                daemon=True,
                name="servo-tracker",
            )
            self._state.thread.start()

        animation_service.unfreeze()
        animation_service.dispatch("play", "tracking")
        logger.info("Tracking started: '%s' bbox=%s — playing tracking animation", target_label, bbox)
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

    def _fire_gimbal(self, dx: float, dy: float, frame_width: int, frame_height: int, animation_service) -> float:
        """Send one proportional gimbal correction toward the target offset.

        Args:
            dx: horizontal pixel offset from frame center (+ = right).
            dy: vertical pixel offset from frame center (+ = below center).
            frame_width: frame width in pixels.
            frame_height: frame height in pixels (used for edge boost).
            animation_service: provides bus_lock and robot.send_action().

        Returns:
            Servo command round-trip time in milliseconds.
        """
        target = self._compute_gimbal_target(dx, dy, frame_width, frame_height)
        logger.info(
            "[servo-pending] yaw=%.1f→%.1f pitch=%.1f→%.1f elbow=%.1f→%.1f offset=(%.0f,%.0f)",
            self._track_yaw, target["base_yaw.pos"],
            self._track_base_pitch, target["base_pitch.pos"],
            self._track_elbow_pitch, target["elbow_pitch.pos"],
            dx, dy,
        )
        return self._send_gimbal_target(target, animation_service)

    def _compute_gimbal_target(self, dx: float, dy: float, frame_width: int, _frame_height: int = 480) -> dict:
        """Compute target servo positions from pixel offset — no API call."""
        offset_mag = (dx ** 2 + dy ** 2) ** 0.5
        step_cap = GIMBAL_MAX_STEP * (ADAPTIVE_GAIN_MULT if offset_mag > ADAPTIVE_GAIN_PX else 1.0)
        deg_per_px = CAMERA_FOV_DEG / frame_width

        yaw_step    = max(-step_cap, min(step_cap, GIMBAL_GAIN * dx * deg_per_px))
        pitch_total = max(-step_cap, min(step_cap, GIMBAL_GAIN * dy * deg_per_px))
        return {
            "base_yaw.pos":    max(YAW_MIN,         min(YAW_MAX,         self._track_yaw         + yaw_step)),
            "base_pitch.pos":  max(BASE_PITCH_MIN,  min(BASE_PITCH_MAX,  self._track_base_pitch  + pitch_total * PITCH_WEIGHT_BASE)),
            "elbow_pitch.pos": max(ELBOW_PITCH_MIN, min(ELBOW_PITCH_MAX, self._track_elbow_pitch + pitch_total * PITCH_WEIGHT_ELBOW)),
            "wrist_pitch.pos": max(WRIST_PITCH_MIN, min(WRIST_PITCH_MAX, self._track_wrist_pitch - pitch_total * PITCH_WEIGHT_WRIST)),
        }

    def _send_gimbal_target(self, target: dict, animation_service) -> float:
        """Send servo to target via smooth sub-steps ≤ SERVO_SUBSTEP_DEG each.

        All 4 joints move together per step — avoids partial-command issues.
        move_to() was tried but its 200ms ramp caused CSRT drift during camera
        motion, leading to erratic corrections. Sub-step (~40-80ms) is fast
        enough that the tracker stays stable.
        Returns total command time in ms.
        """
        start = {
            "base_yaw.pos":    self._track_yaw,
            "base_pitch.pos":  self._track_base_pitch,
            "elbow_pitch.pos": self._track_elbow_pitch,
            "wrist_pitch.pos": self._track_wrist_pitch,
        }
        deltas = {k: target[k] - start[k] for k in start}
        max_delta = max(abs(v) for v in deltas.values())
        n_steps = max(1, math.ceil(max_delta / SERVO_SUBSTEP_DEG))

        t0 = time.perf_counter()
        for i in range(1, n_steps + 1):
            alpha = i / n_steps
            step = {k: start[k] + deltas[k] * alpha for k in start}
            with animation_service.bus_lock:
                animation_service.robot.send_action(step)
            if i < n_steps:
                time.sleep(SERVO_SUBSTEP_SLEEP)
        t_ms = (time.perf_counter() - t0) * 1000

        logger.info(
            "[servo-actual] FIRE yaw=%.1f→%.1f pitch=%.1f→%.1f elbow=%.1f→%.1f wrist=%.1f→%.1f steps=%d cmd=%.0fms",
            start["base_yaw.pos"],    target["base_yaw.pos"],
            start["base_pitch.pos"],  target["base_pitch.pos"],
            start["elbow_pitch.pos"], target["elbow_pitch.pos"],
            start["wrist_pitch.pos"], target["wrist_pitch.pos"],
            n_steps, t_ms,
        )
        self._track_yaw         = target["base_yaw.pos"]
        self._track_base_pitch  = target["base_pitch.pos"]
        self._track_elbow_pitch = target["elbow_pitch.pos"]
        self._track_wrist_pitch = target["wrist_pitch.pos"]
        time.sleep(SERVO_SETTLE_S)
        return t_ms

    _VIT_MODEL = os.path.join(os.path.dirname(__file__), "vittrack.onnx")

    @staticmethod
    def _create_tracker():
        """Create best available OpenCV tracker. CSRT/KCF removed in cv2 4.10+.
        Prefer TrackerVit (ViT-based, accurate) → MIL fallback."""
        def _make_vit():
            params = cv2.TrackerVit_Params()
            params.net = TrackerService._VIT_MODEL
            return cv2.TrackerVit.create(params)

        candidates = [
            ("MIL",  lambda: cv2.TrackerMIL.create()),
            ("CSRT", lambda: cv2.TrackerCSRT.create()),
            ("KCF",  lambda: cv2.TrackerKCF.create()),
            ("ViT",  _make_vit),
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
        """Background loop: CSRT at FAST_LOOP_FPS + YOLO background correction."""
        state = self._state

        animation_service._hold_mode = True
        animation_service._tracking_active = True
        animation_service._tracking_mode = True
        logger.info("Servo hold mode + tracking lock ON")

        # Read initial servo positions — track internally after this.
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


        ema_dx: Optional[float] = None
        ema_dy: Optional[float] = None
        prev_dx: Optional[float] = None   # EMA offset from previous frame (motion detection)
        prev_dy: Optional[float] = None
        motion_state = "INIT"             # INIT → STILL or MOVING
        stable_count = 0                  # consecutive stable frames counter
        last_servo_t: float = 0.0         # timestamp of last servo fire (for cooldown)
        last_obj_log_t: float = 0.0       # throttle tracking_object log to 1/s
        miss_count = 0
        yolo_miss_count = 0   # consecutive YOLO misses — ghost tracking detection
        retry_count = 0
        MAX_TRACKING_RETRIES = 4
        frame_count = 0
        t_csrt_acc = 0.0   # accumulated CSRT update time
        t_servo_acc = 0.0  # accumulated servo command time (only frames that fired)
        servo_count = 0    # frames where servo actually fired
        track_start_t = time.perf_counter()
        last_yolo_t = track_start_t
        fps_t0 = track_start_t

        # Queue for background YOLO results (maxsize=1 → latest result only).
        yolo_q: queue.Queue = queue.Queue(maxsize=1)
        yolo_running = threading.Event()

        def _do_retry() -> bool:
            """Play search animation, try YOLO, reinit tracker. Returns True to continue."""
            nonlocal retry_count, miss_count, yolo_miss_count, ema_dx, ema_dy
            nonlocal prev_dx, prev_dy, motion_state, stable_count, last_yolo_t
            retry_count += 1
            if retry_count > MAX_TRACKING_RETRIES:
                logger.warning("[retry] exhausted %d retries, stopping", MAX_TRACKING_RETRIES)
                return False
            anim = "tracking"
            logger.info("[retry] attempt %d/%d → %s", retry_count, MAX_TRACKING_RETRIES, anim)
            animation_service._tracking_active = False
            # Sync animation _current_state from bus so interpolation starts from actual position
            try:
                with animation_service.bus_lock:
                    _bus = {k: v for k, v in animation_service.robot.get_observation().items() if k.endswith(".pos")}
                if _bus:
                    animation_service._current_state = _bus.copy()
            except Exception as _e:
                logger.warning("[retry] pre-animation state sync failed: %s", _e)
            animation_service.dispatch("play", anim)
            time.sleep(4.0)
            animation_service._tracking_active = True
            # Try YOLO detect on fresh frame
            _f = camera_capture.last_frame
            if _f is not None:
                _bbox = self.detect_object(_f, state.target_label)
                if _bbox is not None:
                    _t = self._create_tracker()
                    if _t is not None:
                        try:
                            if _t.init(_f, _bbox) is not False:
                                state.tracker = _t
                                state.bbox = _bbox
                                logger.info("[retry] tracker reinit OK bbox=%s", _bbox)
                        except Exception as _e:
                            logger.warning("[retry] tracker init failed: %s", _e)
            # Sync _track_* from bus after animation moved servos
            try:
                with animation_service.bus_lock:
                    _bus = {k: v for k, v in animation_service.robot.get_observation().items() if k.endswith(".pos")}
                self._track_yaw         = _bus.get("base_yaw.pos",    self._track_yaw)
                self._track_base_pitch  = _bus.get("base_pitch.pos",  self._track_base_pitch)
                self._track_elbow_pitch = _bus.get("elbow_pitch.pos", self._track_elbow_pitch)
                self._track_wrist_pitch = _bus.get("wrist_pitch.pos", self._track_wrist_pitch)
                logger.info("[retry] servo sync: yaw=%.1f pitch=%.1f elbow=%.1f wrist=%.1f",
                            self._track_yaw, self._track_base_pitch,
                            self._track_elbow_pitch, self._track_wrist_pitch)
            except Exception as _e:
                logger.warning("[retry] servo sync failed: %s", _e)
            # Reset per-attempt state
            miss_count = 0
            yolo_miss_count = 0
            ema_dx = ema_dy = None
            prev_dx = prev_dy = None
            motion_state = "INIT"
            stable_count = 0
            last_yolo_t = 0  # force YOLO on next frame
            while True:  # drain stale YOLO queue
                try: yolo_q.get_nowait()
                except queue.Empty: break
            return True

        def _fire_yolo(frame_snap: npt.NDArray[np.uint8]) -> None:
            t0_yolo = time.perf_counter()
            result = self.detect_object(frame_snap, state.target_label)
            t_yolo_ms = (time.perf_counter() - t0_yolo) * 1000
            logger.info("[yolo-bg] detect=%.0fms result=%s bbox=%s target='%s'",
                        t_yolo_ms, "found" if result is not None else "missed", result, state.target_label)
            if result is None:
                logger.info("[tracking_yolo_response] target='%s' found=False latency=%.0fms", state.target_label, t_yolo_ms)
            try:
                yolo_q.put_nowait(result)
            except queue.Full:
                pass
            finally:
                yolo_running.clear()

        try:
            while state.running.is_set():
                t0 = time.perf_counter()

                frame = camera_capture.last_frame
                if frame is None:
                    time.sleep(1.0 / FAST_LOOP_FPS)
                    continue

                h_fr, w_fr = frame.shape[:2]
                t_csrt0 = time.perf_counter()
                ok, new_bbox = state.tracker.update(frame)
                t_csrt_ms = (time.perf_counter() - t_csrt0) * 1000
                t_csrt_acc += t_csrt_ms

                if not ok:
                    miss_count += 1
                    logger.info("[search] CSRT miss %d/%d target='%s'", miss_count, YOLO_MAX_MISS, state.target_label)
                    if miss_count == 1:
                        # First miss: force YOLO immediately instead of waiting for interval
                        last_yolo_t = 0
                    # Sweep base_yaw to search for object — alternates direction every 8 frames
                    _sweep_dir = 1 if ((miss_count - 1) // 8) % 2 == 0 else -1
                    _new_yaw = max(YAW_MIN, min(YAW_MAX, self._track_yaw + 2.0 * _sweep_dir))
                    with animation_service.bus_lock:
                        animation_service.robot.send_action({"base_yaw.pos": _new_yaw})
                    self._track_yaw = _new_yaw
                    if miss_count >= YOLO_MAX_MISS:
                        if _do_retry():
                            continue
                        break
                    time.sleep(1.0 / FAST_LOOP_FPS)
                    continue

                miss_count = 0
                state.bbox = tuple(int(v) for v in new_bbox)
                bx, by, bw, bh = state.bbox

                frame_area = float(h_fr * w_fr)
                bbox_ratio = (bw * bh) / frame_area
                # Object too close — bbox takes up too much frame, stop tracking.
                if bbox_ratio > 0.45:
                    logger.warning("[bbox] object too close (%.1f%% of frame), stopping", bbox_ratio * 100)
                    break

                # Bbox drifted (tracker expanded) — trigger YOLO to correct.
                if bbox_ratio > DETECT_MAX_AREA_RATIO:
                    logger.warning("[bbox] too large (%.1f%% > %.1f%%) → reinit YOLO",
                                   bbox_ratio * 100, DETECT_MAX_AREA_RATIO * 100)
                    ema_dx = ema_dy = None
                    if not yolo_running.is_set() and state.target_label:
                        yolo_running.set()
                        snap = frame.copy()
                        threading.Thread(
                            target=_fire_yolo, args=(snap,), daemon=True, name="yolo-worker"
                        ).start()
                    time.sleep(1.0 / FAST_LOOP_FPS)
                    continue

                cx_obj = bx + bw / 2.0
                cy_obj = by + bh / 2.0

                # EMA smoothing on pixel offset (not on absolute position).
                raw_dx = cx_obj - w_fr / 2.0
                raw_dy = cy_obj - h_fr / 2.0
                if ema_dx is None or ema_dy is None:
                    ema_dx, ema_dy = raw_dx, raw_dy
                else:
                    ema_dx = EMA_ALPHA * raw_dx + (1.0 - EMA_ALPHA) * ema_dx
                    ema_dy = EMA_ALPHA * raw_dy + (1.0 - EMA_ALPHA) * ema_dy
                dx, dy = float(ema_dx), float(ema_dy)

                # --- tracking_object log: position, motion, direction ---
                offset_mag = (dx ** 2 + dy ** 2) ** 0.5
                screen_x_pct = (cx_obj / w_fr) * 100
                screen_y_pct = (cy_obj / h_fr) * 100
                quadrant = ("TOP" if dy < 0 else "BOT") + "_" + ("LEFT" if dx < 0 else "RIGHT")
                if prev_dx is not None and prev_dy is not None:
                    ddx, ddy = dx - prev_dx, dy - prev_dy
                    if (ddx ** 2 + ddy ** 2) ** 0.5 > 2:
                        angle = ["→", "↗", "↑", "↖", "←", "↙", "↓", "↘"]
                        import math as _math
                        sector = int((_math.degrees(_math.atan2(-ddy, ddx)) + 180 + 22.5) / 45) % 8
                        direction = angle[sector]
                    else:
                        direction = "·"
                    moving_str = motion_state
                else:
                    direction, moving_str = "·", "INIT"
                _now = time.perf_counter()
                if _now - last_obj_log_t >= 1.0:
                    logger.info("[tracking_object] target='%s' pos=(%.0f%%,%.0f%%) quad=%s offset=(%.0f,%.0f) dist=%.0fpx state=%s dir=%s bbox_area=%.1f%%",
                                state.target_label, screen_x_pct, screen_y_pct, quadrant,
                                dx, dy, offset_mag, moving_str, direction, bbox_ratio * 100)
                    last_obj_log_t = _now

                # --- Motion state machine ---
                # During cooldown: accumulate stable_count but suppress firing.
                # This way when cooldown expires and object is already settled,
                # the next frame fires immediately instead of waiting MOTION_SETTLE_FRAMES more.
                if time.perf_counter() - last_servo_t < SERVO_COOLDOWN_S:
                    if prev_dx is not None and prev_dy is not None:
                        delta_px = ((dx - prev_dx) ** 2 + (dy - prev_dy) ** 2) ** 0.5
                        if delta_px > MOTION_THRESHOLD_PX:
                            stable_count = 0
                        else:
                            stable_count = min(stable_count + 1, MOTION_SETTLE_FRAMES)
                    prev_dx, prev_dy = dx, dy
                elif prev_dx is not None and prev_dy is not None:
                    delta_px = ((dx - prev_dx) ** 2 + (dy - prev_dy) ** 2) ** 0.5
                    if delta_px > MOTION_THRESHOLD_PX:
                        stable_count = 0
                        if motion_state != "MOVING":
                            motion_state = "MOVING"
                            logger.info("[motion] MOVE  offset=(%.0f,%.0f) delta=%.0fpx target='%s'",
                                        dx, dy, delta_px, state.target_label)
                    else:
                        stable_count += 1
                        if stable_count >= MOTION_SETTLE_FRAMES and motion_state != "STILL":
                            motion_state = "STILL"
                            in_zone = abs(dx) <= DEAD_ZONE_PX and abs(dy) <= DEAD_ZONE_PX
                            if in_zone:
                                logger.info("[motion] STILL offset=(%.0f,%.0f) → hold (dead-zone) target='%s'",
                                            dx, dy, state.target_label)
                            else:
                                logger.info("[motion] STILL offset=(%.0f,%.0f) → FIRE servo target='%s'",
                                            dx, dy, state.target_label)
                                t_servo_ms = self._fire_gimbal(dx, dy, w_fr, h_fr, animation_service)
                                t_servo_acc += t_servo_ms
                                servo_count += 1
                                last_servo_t = time.perf_counter()
                                # Keep STILL — no re-fire until phone moves again (STILL→MOVING→STILL).
                    prev_dx, prev_dy = dx, dy
                else:
                    # First frame — no previous offset to compare yet.
                    motion_state = "INIT"
                    stable_count = 0
                    prev_dx, prev_dy = dx, dy

                # Drain YOLO result queue — re-init CSRT if a new bbox arrived.
                try:
                    yolo_bbox = yolo_q.get_nowait()
                    if yolo_bbox is not None:
                        miss_count = 0
                        # Reset EMA so stale offset doesn't bias new lock position.
                        ema_dx = ema_dy = None
                        new_tracker = self._create_tracker()
                        if new_tracker is not None:
                            reinit_frame = camera_capture.last_frame
                            if reinit_frame is not None:
                                try:
                                    ok_r = new_tracker.init(reinit_frame, yolo_bbox)
                                    if ok_r is not False:
                                        state.tracker = new_tracker
                                        state.bbox = yolo_bbox
                                        logger.info("YOLO drift-correct OK: bbox=%s", yolo_bbox)
                                        # Re-arm motion machine so servo can fire again if
                                        # object is still off-center after reinit.
                                        motion_state = "INIT"
                                        stable_count = 0
                                except Exception as e:
                                    logger.warning("YOLO re-init failed: %s", e)
                    else:
                        yolo_miss_count += 1
                        logger.debug("YOLO scan: target not found (%d consecutive)", yolo_miss_count)
                        if yolo_miss_count >= 5:
                            logger.warning("YOLO missed %d times in a row — ghost tracking", yolo_miss_count)
                            if _do_retry():
                                continue
                            break
                except queue.Empty:
                    pass
                else:
                    if yolo_bbox is not None:
                        yolo_miss_count = 0

                # Force immediate YOLO redetect when object drifts to frame edge —
                # CSRT will lose lock before the normal interval fires.
                if (abs(dx) > w_fr * 0.25 or abs(dy) > h_fr * 0.25) and not yolo_running.is_set():
                    last_yolo_t = 0
                    logger.info("[edge] offset=(%.0f,%.0f) > 25%% frame → force YOLO target='%s'",
                                dx, dy, state.target_label)

                # Fire background YOLO scan every YOLO_REDETECT_S.
                now = time.perf_counter()
                if state.target_label and not yolo_running.is_set() and now - last_yolo_t >= YOLO_REDETECT_S:
                    last_yolo_t = now
                    yolo_running.set()
                    snap = frame.copy()
                    threading.Thread(
                        target=_fire_yolo, args=(snap,), daemon=True, name="yolo-worker"
                    ).start()

                # Log every ~2 seconds.
                frame_count += 1
                fps_elapsed = time.perf_counter() - fps_t0
                if fps_elapsed >= 2.0:
                    csrt_avg = t_csrt_acc / frame_count if frame_count else 0.0
                    servo_avg = t_servo_acc / servo_count if servo_count else 0.0
                    frame_avg = fps_elapsed * 1000 / frame_count if frame_count else 0.0
                    logger.info(
                        "[track-loop] fps=%.1f csrt=%.0fms servo=%.0fms(%d) frame=%.0fms"
                        " offset=(%.0f,%.0f) bbox=%s target='%s'",
                        frame_count / fps_elapsed,
                        csrt_avg, servo_avg, servo_count,
                        frame_avg, dx, dy, state.bbox, state.target_label,
                    )
                    # System metrics snapshot
                    try:
                        import subprocess as _sp
                        cpu = float(open("/proc/loadavg").read().split()[0])
                        mem_info = open("/proc/meminfo").read()
                        mem_total = int(next(l.split()[1] for l in mem_info.splitlines() if "MemTotal" in l))
                        mem_avail = int(next(l.split()[1] for l in mem_info.splitlines() if "MemAvailable" in l))
                        mem_used_pct = (mem_total - mem_avail) / mem_total * 100
                        volt = _sp.check_output(["vcgencmd", "measure_volts", "core"],
                                                stderr=_sp.DEVNULL, text=True).strip()
                        logger.info("[tracking_system] cpu_load1=%.2f ram_used=%.0f%% voltage=%s", cpu, mem_used_pct, volt)
                    except Exception:
                        pass
                    frame_count = 0
                    t_csrt_acc = 0.0
                    t_servo_acc = 0.0
                    servo_count = 0
                    fps_t0 = time.perf_counter()

                if time.perf_counter() - track_start_t > MAX_TRACK_DURATION_S:
                    logger.warning("Tracking timeout after %ds, stopping", MAX_TRACK_DURATION_S)
                    break

                dt = time.perf_counter() - t0
                sleep_time = (1.0 / FAST_LOOP_FPS) - dt
                if sleep_time > 0:
                    time.sleep(sleep_time)

        finally:
            animation_service._tracking_active = False
            animation_service._tracking_mode = False
            animation_service._hold_mode = False
            state.running.clear()

            if not animation_service._running.is_set():
                animation_service._running.set()
                animation_service._event_thread = threading.Thread(
                    target=animation_service._event_loop, daemon=True
                )
                animation_service._event_thread.start()

            logger.info("Tracking ended — resetting servo to neutral")
            try:
                animation_service.move_to({
                    "base_yaw.pos": 0.0, "base_pitch.pos": 0.0,
                    "elbow_pitch.pos": 0.0, "wrist_pitch.pos": 0.0, "wrist_roll.pos": 0.0,
                }, duration=2.0)
            except Exception as _e:
                logger.warning("Servo reset to neutral failed: %s", _e)
