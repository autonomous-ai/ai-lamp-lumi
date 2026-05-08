"""Vision-guided object tracking with servo follow — gimbal mode.

Architecture:
  1. detect_object() calls YOLOWorld to locate the target (initial + background re-detect).
  2. OpenCV CSRT tracker runs at ~15fps for continuous low-latency corrections.
  3. A background thread calls YOLO every YOLO_REDETECT_S to correct tracker drift.
  4. Each CSRT frame: compute pixel offset → small servo correction → gimbal-like follow.
"""

import base64
import logging
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

# --- Model paths ---
_VIT_MODEL = os.path.join(os.path.dirname(__file__), "vittrack.onnx")

# --- YOLOWorld API ---
_YOLO_ENDPOINT = "/detect/yoloworld"
_YOLO_TIMEOUT = 10.0

# --- Tuning ---

# Detection filters
DETECT_MIN_AREA_RATIO = 0.003
DETECT_MAX_AREA_RATIO = 0.55
DETECT_MIN_CONFIDENCE = 0.20

# Gimbal loop rate (fps). CSRT on Pi runs ~15-20fps.
FAST_LOOP_FPS = 15

# Background YOLO re-detection interval (seconds). Corrects CSRT drift.
YOLO_REDETECT_S = 1.5

# How many consecutive YOLO misses (each YOLO_REDETECT_S) before stopping.
YOLO_MAX_MISS = 4

# Gimbal correction gain: fraction of error corrected per frame.
# 0.25 at 15fps → smooth ~4-frame convergence, no overshoot.
GIMBAL_GAIN = 0.28

# EMA smoothing on raw CSRT offset before it reaches the servo.
# Filters per-frame tracker jitter so the servo only reacts to real motion.
# Lower = smoother (less jitter) but slightly laggier.
EMA_ALPHA = 0.45

# Max correction per frame (degrees/units). Keeps motion smooth even for
# large offsets. At 15fps × 2° = 30°/s max angular speed.
GIMBAL_MAX_STEP = 2.0

# Dead zone in pixels — no command when object is within this of center.
DEAD_ZONE_PX = 5

# FOV mapping for correction magnitude.
CAMERA_FOV_DEG = 60.0

# Servo settle after each direct send_action (seconds).
# Must be < 1/FAST_LOOP_FPS so we don't slow the loop.
SERVO_SETTLE_S = 0.02

# Pitch distribution across joints (must match arm kinematics).
PITCH_WEIGHT_BASE  = 0.55
PITCH_WEIGHT_ELBOW = 0.30
PITCH_WEIGHT_WRIST = 0.15

# Servo limits
YAW_MIN, YAW_MAX                       = -135.0, 135.0
BASE_PITCH_MIN, BASE_PITCH_MAX         = -90.0,  30.0
ELBOW_PITCH_MIN, ELBOW_PITCH_MAX       = -90.0,  90.0
WRIST_PITCH_MIN, WRIST_PITCH_MAX       = -90.0,  90.0

# Maximum tracking duration (seconds)
MAX_TRACK_DURATION_S = 300


@dataclass
class TrackingState:
    target_label: str = ""
    bbox: Optional[Tuple[int, int, int, int]] = None
    confidence: float = 0.0
    running: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None


class TrackerService:
    """Gimbal-mode tracker: CSRT at ~15fps + YOLO background re-detect."""

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
            "confidence": round(s.confidence, 3),
        }

    def detect_object(self, frame: npt.NDArray[np.uint8], target: str) -> Optional[Tuple[int, int, int, int]]:
        """Detect object via YOLOWorld API. Returns (x,y,w,h) or None."""
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
                return None
            frame_area = float(frame.shape[0] * frame.shape[1])
            valid = []
            for d in detections:
                cx, cy, w, h = d["xywh"]
                conf = d.get("confidence", 0)
                area_ratio = (w * h) / frame_area if frame_area > 0 else 0.0
                if conf < DETECT_MIN_CONFIDENCE:
                    logger.info("  YOLO: REJECTED (conf=%.2f) %s", conf, d.get("class_name"))
                elif not (DETECT_MIN_AREA_RATIO <= area_ratio <= DETECT_MAX_AREA_RATIO):
                    logger.info("  YOLO: REJECTED (size=%.1f%%) %s", area_ratio * 100, d.get("class_name"))
                else:
                    logger.info("  YOLO: ACCEPTED conf=%.2f area=%.1f%%", conf, area_ratio * 100)
                    valid.append(d)
            if not valid:
                return None
            best = max(valid, key=lambda d: d.get("confidence", 0))
            cx, cy, w, h = best["xywh"]
            bbox = (int(cx - w / 2), int(cy - h / 2), int(w), int(h))
            logger.info("YOLOWorld: '%s' at bbox=%s conf=%.3f", target, bbox, best["confidence"])
            return bbox
        except Exception as e:
            logger.error("YOLOWorld detect failed: %s", e)
            return None

    def start(
        self,
        bbox: Optional[Tuple[int, int, int, int]] = None,  # noqa: ARG002
        target_label="",
        camera_capture=None,
        animation_service=None,
    ) -> bool:
        if camera_capture is None or animation_service is None:
            self.last_error = "camera or animation service not available"
            return False
        if isinstance(target_label, (list, tuple)):
            target_label = next((t for t in target_label if t), "")
        if not target_label:
            self.last_error = "target_label required"
            return False

        self.stop()

        # Quick camera sanity check
        animation_service.freeze()
        try:
            time.sleep(0.20)
            if camera_capture.last_frame is None:
                self.last_error = "no frame from camera"
                return False
        finally:
            animation_service.unfreeze()

        with self._lock:
            self._state = TrackingState(target_label=target_label)
            self._state.running.set()
            self._state.thread = threading.Thread(
                target=self._track_loop,
                args=(camera_capture, animation_service),
                daemon=True,
                name="servo-tracker",
            )
            self._state.thread.start()

        logger.info("Tracking started (gimbal): '%s'", target_label)
        return True

    def stop(self):
        with self._lock:
            if not self._state.running.is_set():
                return
            self._state.running.clear()
            t = self._state.thread
        if t and t.is_alive():
            t.join(timeout=3.0)
        logger.info("Tracking stopped: '%s'", self._state.target_label)

    def update_bbox(self, _bbox, _camera_capture=None):
        return False

    # --- Core tracking loop ---

    def _track_loop(self, camera_capture, animation_service):
        state = self._state

        animation_service._hold_mode = True
        animation_service._tracking_active = True
        logger.info("Gimbal tracking: hold mode + tracking lock ON")

        try:
            from lelamp.service.motors.animation_service import _motor_positions_from_bus
        except ImportError:
            _motor_positions_from_bus = None

        def _read_pos():
            if _motor_positions_from_bus is None:
                return {}
            try:
                with animation_service.bus_lock:
                    return _motor_positions_from_bus(animation_service.robot) or {}
            except Exception:
                return {}

        # Read initial servo position
        p = _read_pos()
        yaw   = p.get("base_yaw.pos", 0.0)
        pitch = p.get("base_pitch.pos", 0.0)
        elbow = p.get("elbow_pitch.pos", 0.0)
        wrist = p.get("wrist_pitch.pos", 0.0)

        # --- Initial YOLO detection ---
        logger.info("Gimbal: initial YOLO detection for '%s'", state.target_label)
        animation_service.freeze()
        time.sleep(0.10)
        snap = camera_capture.last_frame
        if snap is None:
            animation_service.unfreeze()
            logger.error("Gimbal: no frame for initial detection")
            return
        snap = snap.copy()
        animation_service.unfreeze()

        init_bbox = self.detect_object(snap, state.target_label)
        if init_bbox is None:
            logger.warning("Gimbal: '%s' not found in initial detection", state.target_label)
            # Don't abort — YOLO background will keep trying

        # Init local tracker
        local_tracker = self._make_local_tracker()
        tracker_ok = False
        if local_tracker and init_bbox is not None:
            try:
                tracker_ok = local_tracker.init(snap, init_bbox) is not False
                if tracker_ok:
                    state.bbox = init_bbox
                    logger.info("Gimbal: local tracker initialized bbox=%s", init_bbox)
            except Exception as e:
                logger.warning("Gimbal: local tracker init failed: %s", e)

        # --- Background YOLO re-detection thread ---
        # Queue carries (bbox | None) from the latest YOLO call.
        _yolo_q: "queue.Queue[Optional[Tuple[int,int,int,int]]]" = queue.Queue(maxsize=1)
        _yolo_running = threading.Event()
        yolo_miss_count = 0

        def _yolo_worker(frame_snap):
            try:
                result = self.detect_object(frame_snap, state.target_label)
                try:
                    _yolo_q.put_nowait(result)
                except queue.Full:
                    pass
            finally:
                _yolo_running.clear()

        last_yolo_t = time.perf_counter()
        ema_dx: Optional[float] = None
        ema_dy: Optional[float] = None
        last_yolo_cx: Optional[float] = None  # x3: last YOLO ground-truth center
        last_yolo_cy: Optional[float] = None
        last_yolo_area: Optional[float] = None   # area of last accepted YOLO bbox
        yolo_cx_this_frame: Optional[float] = None

        # Schedule first YOLO immediately if initial detection failed
        if not tracker_ok:
            _yolo_running.set()
            threading.Thread(target=_yolo_worker, args=(snap,), daemon=True).start()

        track_start_t = time.perf_counter()

        try:
            while state.running.is_set():
                t0 = time.perf_counter()

                # --- Grab frame (light freeze to avoid ego-motion blur) ---
                animation_service.freeze()
                time.sleep(0.01)
                raw = camera_capture.last_frame
                if raw is None:
                    animation_service.unfreeze()
                    time.sleep(1.0 / FAST_LOOP_FPS)
                    continue
                frame = raw.copy()
                animation_service.unfreeze()

                w_fr, h_fr = frame.shape[1], frame.shape[0]

                # Do NOT read back hardware position during tracking — the animation
                # service fights back to its hold position immediately after each
                # tracking command, so _read_pos() always returns the hold value and
                # resets yaw/pitch, preventing incremental accumulation.
                # We trust commanded positions instead.

                yolo_cx_this_frame = None

                # --- Consume YOLO result if available ---
                try:
                    yolo_bbox = _yolo_q.get_nowait()
                    if yolo_bbox is not None:
                        yolo_miss_count = 0
                        cx3 = yolo_bbox[0] + yolo_bbox[2] / 2.0
                        cy3 = yolo_bbox[1] + yolo_bbox[3] / 2.0
                        new_area = yolo_bbox[2] * yolo_bbox[3]
                        # Reject bbox if area jumps >4x vs last — likely a different
                        # object or noise. Skip update but don't count as miss.
                        if last_yolo_area is not None and (
                            new_area > last_yolo_area * 4.0
                            or new_area < last_yolo_area / 4.0
                        ):
                            logger.info(
                                "YOLO: size jump rejected area=%d vs last=%d — skipping",
                                new_area, last_yolo_area,
                            )
                        else:
                            state.bbox = yolo_bbox
                            last_yolo_area = new_area
                            last_yolo_cx, last_yolo_cy = cx3, cy3
                            yolo_cx_this_frame = cx3
                        # Prime EMA with YOLO ground-truth aim error (no cold-start).
                        ema_dx = cx3 - w_fr / 2.0
                        ema_dy = cy3 - h_fr / 2.0
                        if local_tracker:
                            try:
                                ok = local_tracker.init(frame, yolo_bbox)
                                tracker_ok = ok is not False
                                logger.info("Gimbal: re-init tracker from YOLO bbox=%s", yolo_bbox)
                            except Exception as e:
                                logger.warning("Gimbal: tracker re-init failed: %s", e)
                    else:
                        yolo_miss_count += 1
                        logger.info("Gimbal: YOLO miss %d/%d", yolo_miss_count, YOLO_MAX_MISS)
                        if yolo_miss_count >= YOLO_MAX_MISS:
                            logger.warning("Gimbal: lost '%s' after %d YOLO misses", state.target_label, YOLO_MAX_MISS)
                            break
                except queue.Empty:
                    pass

                # --- Schedule next YOLO if due ---
                now = time.perf_counter()
                if not _yolo_running.is_set() and (now - last_yolo_t) >= YOLO_REDETECT_S:
                    last_yolo_t = now
                    _yolo_running.set()
                    threading.Thread(target=_yolo_worker, args=(frame,), daemon=True).start()

                # --- Local tracker update ---
                # Only use fresh YOLO position for servo correction. Stale fallback
                # causes servo to keep accumulating in one direction (spin-out) since
                # the error never decreases without a local tracker updating it.
                cx_obj = yolo_cx_this_frame
                cy_obj = last_yolo_cy if yolo_cx_this_frame is not None else None
                if local_tracker and tracker_ok:
                    try:
                        ok, tb = local_tracker.update(frame)
                        if ok:
                            bx, by, bw, bh = (int(v) for v in tb)
                            state.bbox = (bx, by, bw, bh)
                            cx_obj = bx + bw / 2.0
                            cy_obj = by + bh / 2.0
                            state.confidence = self._get_tracker_score(local_tracker)
                        else:
                            tracker_ok = False
                    except Exception as e:
                        logger.debug("Gimbal: local tracker update error: %s", e)
                        tracker_ok = False

                # --- Gimbal correction ---
                if cx_obj is not None and cy_obj is not None:
                    x1, y1 = w_fr / 2.0, h_fr / 2.0   # crosshair (screen center)
                    x2, y2 = cx_obj, cy_obj             # tracker box center
                    x3 = last_yolo_cx                   # last YOLO ground-truth
                    y3 = last_yolo_cy

                    raw_dx = x2 - x1
                    raw_dy = y2 - y1

                    logger.info(
                        "scope| x1=(%.0f,%.0f) x2=(%.0f,%.0f) x3=%s err=(%.0f,%.0f)",
                        x1, y1,
                        x2, y2,
                        "(%.0f,%.0f)" % (x3, y3) if x3 is not None else "none",
                        raw_dx, raw_dy,
                    )

                    # EMA smoothing: absorbs per-frame tracker jitter.
                    if ema_dx is None or ema_dy is None:
                        ema_dx, ema_dy = raw_dx, raw_dy
                    else:
                        ema_dx = EMA_ALPHA * raw_dx + (1.0 - EMA_ALPHA) * ema_dx
                        ema_dy = EMA_ALPHA * raw_dy + (1.0 - EMA_ALPHA) * ema_dy

                    dx, dy = float(ema_dx), float(ema_dy)

                    if abs(dx) > DEAD_ZONE_PX or abs(dy) > DEAD_ZONE_PX:
                        deg_per_px = (CAMERA_FOV_DEG / w_fr) * GIMBAL_GAIN

                        # Each axis handled independently — zero if within dead zone.
                        # Yaw: positive dx → turn right (increase yaw)
                        if abs(dx) > DEAD_ZONE_PX:
                            yaw_step = max(-GIMBAL_MAX_STEP, min(GIMBAL_MAX_STEP, dx * deg_per_px))
                        else:
                            yaw_step = 0.0

                        # Pitch: positive dy (below center) → look down (increase pitch)
                        if abs(dy) > DEAD_ZONE_PX:
                            pitch_step = max(-GIMBAL_MAX_STEP, min(GIMBAL_MAX_STEP, dy * deg_per_px))
                        else:
                            pitch_step = 0.0

                        if yaw_step != 0.0 or pitch_step != 0.0:
                            new_yaw   = max(YAW_MIN,         min(YAW_MAX,         yaw   + yaw_step))
                            new_pitch = max(BASE_PITCH_MIN,  min(BASE_PITCH_MAX,  pitch + pitch_step * PITCH_WEIGHT_BASE))
                            new_elbow = max(ELBOW_PITCH_MIN, min(ELBOW_PITCH_MAX, elbow + pitch_step * PITCH_WEIGHT_ELBOW))
                            new_wrist = max(WRIST_PITCH_MIN, min(WRIST_PITCH_MAX, wrist + pitch_step * PITCH_WEIGHT_WRIST))

                            logger.info(
                                "servo| ema=(%.0f,%.0f) step=(%.2f°,%.2f°)"
                                " yaw=%.1f→%.1f pitch=%.1f→%.1f"
                                " elbow=%.1f→%.1f wrist=%.1f→%.1f",
                                dx, dy, yaw_step, pitch_step,
                                yaw, new_yaw, pitch, new_pitch,
                                elbow, new_elbow, wrist, new_wrist,
                            )

                            try:
                                with animation_service.bus_lock:
                                    animation_service.robot.send_action({
                                        "base_yaw.pos":    new_yaw,
                                        "base_pitch.pos":  new_pitch,
                                        "elbow_pitch.pos": new_elbow,
                                        "wrist_pitch.pos": new_wrist,
                                    })
                                yaw, pitch, elbow, wrist = new_yaw, new_pitch, new_elbow, new_wrist
                                time.sleep(SERVO_SETTLE_S)
                            except Exception as e:
                                logger.warning("Gimbal: servo command failed: %s", e)
                    else:
                        logger.info("scope| in dead zone (%.0f,%.0f) ≤ %dpx — no servo", dx, dy, DEAD_ZONE_PX)

                # Max duration guard
                if time.perf_counter() - track_start_t > MAX_TRACK_DURATION_S:
                    logger.warning("Gimbal: timeout after %ds", MAX_TRACK_DURATION_S)
                    break

                # Pace to FAST_LOOP_FPS
                elapsed = time.perf_counter() - t0
                time.sleep(max(0.0, 1.0 / FAST_LOOP_FPS - elapsed))

        finally:
            animation_service._tracking_active = False
            animation_service._zero_mode = False
            with animation_service._event_lock:
                animation_service._event_queue.clear()
            animation_service._hold_mode = True
            state.running.clear()
            logger.info("Gimbal tracking ended — holding servo at last position")

    @staticmethod
    def _make_local_tracker():
        """Create best available fast OpenCV tracker for gimbal use.
        MIL excluded — it freezes on Pi (updates too slow, bbox locks up)."""
        for name, factory in [
            ("CSRT", lambda: cv2.TrackerCSRT.create()),
            ("KCF",  lambda: cv2.TrackerKCF.create()),
        ]:
            try:
                t = factory()
                logger.info("Gimbal: using local tracker %s", name)
                return t
            except Exception:
                continue
        logger.info("Gimbal: no local tracker available — running YOLO-only")
        return None

    @staticmethod
    def _get_tracker_score(tracker) -> float:
        try:
            return float(tracker.getTrackingScore())
        except Exception:
            return 1.0

    @staticmethod
    def _create_tracker():
        """Kept for API compatibility."""
        if os.path.exists(_VIT_MODEL):
            try:
                params = cv2.TrackerVit_Params()
                params.net = _VIT_MODEL
                return cv2.TrackerVit.create(params)
            except Exception:
                pass
        for _, factory in [
            ("CSRT", lambda: cv2.TrackerCSRT.create()),
            ("KCF",  lambda: cv2.TrackerKCF.create()),
            ("MIL",  lambda: cv2.TrackerMIL.create()),
        ]:
            try:
                return factory()
            except Exception:
                continue
        return None
