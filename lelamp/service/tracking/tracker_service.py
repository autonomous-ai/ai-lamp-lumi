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

# "owlv2"
# "yoloe"

# --- Tuning knobs ---

# Base degrees per pixel. Frame assumed ~640 wide; object at edge ≈ 320px →
# ~7° nudge before clamp. Tuned down from 0.03 to reduce overshoot oscillation
# (observed on Pi: offset ping-ponged ±40-55px when gain was too high).
DEG_PER_PX_YAW = 0.022
DEG_PER_PX_PITCH = 0.022

# Adaptive gain: when object is far from center, multiply gain by this factor
# to catch up faster. Below the threshold, stays at 1.0 for smoothness.
# Reduced from 1.6 to 1.3 — 1.6 was contributing to overshoot (servo moved
# before camera caught up, then had to reverse).
ADAPTIVE_GAIN_PX = 120
ADAPTIVE_GAIN_MULT = 1.3

# Dead zone in pixels — stop nudging when object is within this range
DEAD_ZONE_PX = 12

# Wake zone — when settled, only resume nudging when object moves beyond this.
# Raised from 22 to 40: TrackerVit bbox naturally jitters ±30-50px between
# frames, and a too-small wake zone caused a wake/settle/wake cycle every
# 100ms. 40px is wider than natural jitter, so only real motion wakes it.
WAKE_ZONE_PX = 40

# Maximum nudge per step (degrees) — prevents wild swings while allowing
# catch-up on fast-moving objects. Tuned for TRACK_FPS=20.
MAX_NUDGE_DEG = 4.5

# Tracking loop target FPS — higher = smoother. TrackerVit on Pi runs at
# ~15-25ms/frame so 20 FPS is reachable.
TRACK_FPS = 20

# Settle delay (seconds) after a servo nudge before reading the next frame,
# applied ONLY when _nudge_servo actually dispatched a command (not in dead
# zone / settled hysteresis). Without this, each frame was captured while
# the servo was still rotating from the previous nudge — TrackerVit saw the
# full scene shifting and couldn't distinguish cup motion from camera ego-
# motion, so the bbox bloated within 1-2s on fast-tracked cycles. 50ms is
# enough for a ~2-4° servo step to complete on this STS3215 chain.
SERVO_SETTLE_S = 0.05

# EMA smoothing factor for bbox center (0-1). Higher = more responsive but
# more jitter; lower = smoother but laggier. Dropped from 0.55 to 0.3:
# previous value let too much tracker noise through, causing servo to chase
# jitter instead of real motion.
EMA_ALPHA = 0.3

# Pitch distribution across 3 joints. Primary tilt on base, secondary on
# elbow, minimal on wrist — reduces mechanical interference and makes the
# lamp head lead the motion instead of three joints twitching together.
PITCH_WEIGHT_BASE = 0.55
PITCH_WEIGHT_ELBOW = 0.30
PITCH_WEIGHT_WRIST = 0.15

# Re-detect interval (seconds) — periodically call YOLOWorld to correct drift.
# Shorter interval catches drift faster (TrackerVit can bloat 3x in 1-2s on
# texture-rich cups); freeze during each re-detect is ~650ms so 2s interval
# leaves ~70% of time actively tracking.
REDETECT_INTERVAL_S = 2.0

# If YOLO's re-detect bbox center is within this many pixels of the current
# tracker bbox center, skip the tracker re-init. The tracker already has
# feature lock; re-initializing needlessly causes a confidence dip and a
# few frames of wobble. Only re-init when YOLO actually disagrees with the
# tracker (indicating real drift).
REDETECT_AGREEMENT_PX = 60

# YOLOWorld detection filters. Without these, noisy low-confidence hits
# (e.g. 14x18 px bbox conf=0.27) at the frame edge pass through and
# re-seed the tracker with garbage, killing the session. Observed on-
# device (2026-04-24 15:04): periodic re-detect picked a 15x21 bbox at
# conf 0.305 and the tracker collapsed in the next cycle.
DETECT_MIN_AREA_RATIO = 0.003   # reject bbox smaller than 0.3% of frame
DETECT_MAX_AREA_RATIO = 0.30    # reject bbox larger than 30% (loose/merged)
DETECT_MIN_CONFIDENCE = 0.5     # reject detections under 0.5 (noise floor)

# TrackerVit confidence threshold — below this = lost
CONFIDENCE_THRESHOLD = 0.3

# How many consecutive low-confidence frames before stopping
MAX_LOW_CONFIDENCE_FRAMES = 5

# Bbox jump threshold — if center moves more than this many pixels in one
# frame, treat it as partial glitch: fall back to EMA-smoothed center so we
# don't drop the frame entirely.
BBOX_JUMP_PX = 120

# Maximum tracking duration (seconds) — auto-stop to save motor/CPU
MAX_TRACK_DURATION_S = 300  # 5 minutes

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

            # Filter out garbage detections. Log every candidate with the
            # decision so we can diagnose mis-detections from the log.
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
            logger.info("YOLOWorld: '%s' found at bbox=%s conf=%.3f", target, bbox, best["confidence"])
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

        If bbox is provided, use it directly. Otherwise, auto-detect using YOLOWorld.
        `target_label` accepts str or list[str] — first non-empty label is used
        for detection/display. List support matches models.ServoTrackRequest which
        accepts candidate synonyms from LLM skills.
        """
        if camera_capture is None or animation_service is None:
            self.last_error = "camera or animation service not available"
            logger.error("tracker start: %s", self.last_error)
            return False

        # Normalize list[str] → first non-empty str.
        if isinstance(target_label, (list, tuple)):
            target_label = next((t for t in target_label if t), "")

        self.stop()

        # Freeze animation servo writes and wait for the arm to settle, so
        # YOLO detection + tracker init run on a sharp (non-motion-blurred)
        # frame. Idle animation or a just-completed /servo/aim interpolation
        # would otherwise leave the arm moving when we grab last_frame, and
        # both the YOLO bbox and TrackerVit feature lock would start
        # misaligned. The track loop sets _tracking_active shortly after
        # this, which supersedes the freeze; we unfreeze only on early-exit
        # failure paths.
        settle_s = 0.30
        animation_service.freeze()
        try:
            time.sleep(settle_s)

            frame = camera_capture.last_frame
            if frame is None:
                self.last_error = "no frame available from camera"
                logger.error("tracker start: %s", self.last_error)
                animation_service.unfreeze()
                return False
            frame = frame.copy()

            # Auto-detect if no bbox provided. YOLO round-trip is 1-2s; the
            # arm stays frozen throughout so the returned bbox coordinates
            # match the same frame we keep for tracker.init (no re-grab).
            if bbox is None:
                if not target_label:
                    self.last_error = "need either bbox or target label"
                    logger.error("tracker start: %s", self.last_error)
                    animation_service.unfreeze()
                    return False
                bbox = self.detect_object(frame, target_label)
                if bbox is None:
                    self.last_error = f"'{target_label}' not found in frame"
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

        # Track loop now owns the servo via _tracking_active; drop the
        # start-time freeze so the loop can send its own nudges.
        animation_service.unfreeze()

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
        # Stricter than hold_mode: animation_service drops any in-progress
        # recording (emotion reactions, idle interpolation) while this is
        # set, and emotion.py blocks its own servo writes. Required so
        # emotion animations triggered during tracking don't fight the
        # tracker's nudges.
        animation_service._tracking_active = True
        logger.info("Servo hold mode + tracking lock ON")

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
        # EMA-smoothed center — reset on start, seeded with first raw center
        self._ema_cx = None
        self._ema_cy = None
        init_area = state.bbox[2] * state.bbox[3] if state.bbox else 0
        self._settled = False
        frame_count = 0
        track_start_t = time.perf_counter()
        last_redetect_t = track_start_t
        fps_t0 = track_start_t

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

                # Detect bbox bloat — tracker drifting to full frame
                bbox_area = bw * bh
                frame_area = frame.shape[0] * frame.shape[1]
                if init_area > 0 and bbox_area > init_area * 3:
                    logger.warning("Bbox bloated to %.0fx initial (area=%d vs init=%d), stopping",
                                   bbox_area / init_area, bbox_area, init_area)
                    break
                if bbox_area > frame_area * 0.5:
                    logger.warning("Bbox covers >50%% of frame (%d/%d), stopping",
                                   bbox_area, frame_area)
                    break

                cx = bx + bw / 2
                cy = by + bh / 2

                # Bbox jump handling: instead of dropping the frame (which
                # causes visible stutter), fall back to the EMA-smoothed
                # center so the servo keeps moving toward the last-known
                # good position. Real glitches get absorbed; genuine fast
                # motion still nudges via smoothed trajectory.
                if prev_cx is not None:
                    jump = ((cx - prev_cx) ** 2 + (cy - prev_cy) ** 2) ** 0.5
                    if jump > BBOX_JUMP_PX and self._ema_cx is not None:
                        logger.debug("Bbox jump %.0fpx, using smoothed center", jump)
                        cx = self._ema_cx
                        cy = self._ema_cy
                prev_cx, prev_cy = cx, cy

                # EMA smoothing on center — reduces tracker jitter before
                # it reaches the servo, so motion looks continuous rather
                # than frame-stepped.
                if self._ema_cx is None:
                    self._ema_cx = cx
                    self._ema_cy = cy
                else:
                    self._ema_cx = EMA_ALPHA * cx + (1 - EMA_ALPHA) * self._ema_cx
                    self._ema_cy = EMA_ALPHA * cy + (1 - EMA_ALPHA) * self._ema_cy

                moved = self._nudge_servo(frame, self._ema_cx, self._ema_cy, animation_service)
                if moved:
                    # Let the servo finish its step before the next frame
                    # read so the tracker sees a static scene rather than
                    # one being rotated by ongoing camera ego-motion.
                    time.sleep(SERVO_SETTLE_S)

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

                # Periodic re-detect to correct tracker drift. Runs
                # synchronously with servo frozen so the YOLO bbox and
                # the tracker.init frame share coordinates — previously
                # this ran on a background thread while the main loop
                # kept nudging servos, so the returned bbox was from a
                # ~500ms-stale frame while tracker.init used the fresh
                # one, producing an immediate coord mismatch that looked
                # like "lost tracking" right after each re-detect.
                now = time.perf_counter()
                if state.target_label and now - last_redetect_t >= REDETECT_INTERVAL_S:
                    last_redetect_t = now
                    redetect_settle_s = 0.15
                    animation_service.freeze()
                    try:
                        time.sleep(redetect_settle_s)
                        det_frame = camera_capture.last_frame
                        if det_frame is not None:
                            det_frame = det_frame.copy()
                            det_bbox = self.detect_object(det_frame, state.target_label)
                            if det_bbox is not None and state.running.is_set():
                                # Compare YOLO bbox with tracker's current
                                # bbox. If they agree, the tracker is on
                                # target — don't disturb it; re-initing
                                # causes a transient conf dip that then
                                # bloats on the next cup motion.
                                should_reinit = True
                                if state.bbox is not None:
                                    cur_cx = state.bbox[0] + state.bbox[2] / 2
                                    cur_cy = state.bbox[1] + state.bbox[3] / 2
                                    det_cx = det_bbox[0] + det_bbox[2] / 2
                                    det_cy = det_bbox[1] + det_bbox[3] / 2
                                    delta_px = ((cur_cx - det_cx) ** 2 + (cur_cy - det_cy) ** 2) ** 0.5
                                    if delta_px < REDETECT_AGREEMENT_PX:
                                        should_reinit = False
                                        logger.info(
                                            "Re-detect agrees with tracker (delta=%.0fpx < %.0fpx), keep tracker",
                                            delta_px, REDETECT_AGREEMENT_PX,
                                        )

                                if should_reinit:
                                    new_tracker = self._create_tracker()
                                    if new_tracker is not None:
                                        try:
                                            ok_r = new_tracker.init(det_frame, det_bbox)
                                        except Exception:
                                            ok_r = False
                                        if ok_r is not False:
                                            state.tracker = new_tracker
                                            state.bbox = det_bbox
                                            state.low_confidence_frames = 0
                                            init_area = det_bbox[2] * det_bbox[3]
                                            logger.info("Re-detect OK (drift corrected): bbox=%s", det_bbox)
                    except Exception as e:
                        logger.warning("Re-detect failed: %s", e)
                    finally:
                        animation_service.unfreeze()

                # Max duration check
                if time.perf_counter() - track_start_t > MAX_TRACK_DURATION_S:
                    logger.warning("Tracking timeout after %ds, stopping", MAX_TRACK_DURATION_S)
                    break

                # Servo at limit but object still far from center → unreachable
                at_yaw_limit = self._track_yaw <= YAW_MIN + 1 or self._track_yaw >= YAW_MAX - 1
                at_pitch_limit = self._track_base_pitch <= BASE_PITCH_MIN + 1 or self._track_base_pitch >= BASE_PITCH_MAX - 1
                if at_yaw_limit or at_pitch_limit:
                    h, w = frame.shape[:2]
                    off = max(abs(cx - w / 2), abs(cy - h / 2))
                    if off > w * 0.3:  # object still >30% off center
                        logger.warning("Servo at limit (yaw=%.1f pitch=%.1f) but object far (off=%.0fpx), stopping",
                                       self._track_yaw, self._track_base_pitch, off)
                        break

                # Maintain target FPS
                dt = time.perf_counter() - t0
                sleep_time = (1.0 / TRACK_FPS) - dt
                if sleep_time > 0:
                    time.sleep(sleep_time)
        finally:
            animation_service._tracking_active = False
            animation_service._hold_mode = False
            state.running.clear()

            # Restart the animation event thread if it stopped, so future
            # commands (user requests, reactions) still work.
            if not animation_service._running.is_set():
                import threading as _threading
                animation_service._running.set()
                animation_service._event_thread = _threading.Thread(
                    target=animation_service._event_loop, daemon=True
                )
                animation_service._event_thread.start()

            # Hold servo at current tracked position. Dispatching idle here
            # used to snap the lamp back to its start pose, which looked like
            # a hard jerk right after tracking ended.
            logger.info("Tracking ended — holding servo at current position")

    def _nudge_servo(
        self,
        frame: npt.NDArray[np.uint8],
        cx_obj: float,
        cy_obj: float,
        animation_service,
    ) -> bool:
        """Nudge servo toward EMA-smoothed object center.

        Returns True if a servo command was actually dispatched, False if
        the call was a no-op (settled / dead zone / clipped to zero / send
        failed). The loop uses this to decide whether to sleep for servo
        settle time before the next frame read.
        """
        h, w = frame.shape[:2]
        cx_frame = w / 2
        cy_frame = h / 2

        dx = cx_obj - cx_frame
        dy = cy_obj - cy_frame

        # Hysteresis: once settled, only wake when object moves far enough
        if self._settled:
            if abs(dx) < WAKE_ZONE_PX and abs(dy) < WAKE_ZONE_PX:
                return False
            self._settled = False
            logger.info("Tracking wake: object moved to offset (%.0f, %.0f)", dx, dy)

        if abs(dx) < DEAD_ZONE_PX and abs(dy) < DEAD_ZONE_PX:
            if not self._settled:
                self._settled = True
                logger.info("Tracking settled: object near center (%.0f, %.0f)", dx, dy)
            return False

        # Adaptive gain: boost when object is far so we catch up quickly,
        # fall back to base gain near center for smoothness.
        offset_max = max(abs(dx), abs(dy))
        gain_mult = ADAPTIVE_GAIN_MULT if offset_max > ADAPTIVE_GAIN_PX else 1.0

        yaw_deg = dx * DEG_PER_PX_YAW * gain_mult
        pitch_deg = dy * DEG_PER_PX_PITCH * gain_mult

        yaw_deg = max(-MAX_NUDGE_DEG, min(MAX_NUDGE_DEG, yaw_deg))
        pitch_deg = max(-MAX_NUDGE_DEG, min(MAX_NUDGE_DEG, pitch_deg))

        if abs(dx) < DEAD_ZONE_PX:
            yaw_deg = 0
        if abs(dy) < DEAD_ZONE_PX:
            pitch_deg = 0

        if yaw_deg == 0 and pitch_deg == 0:
            return False

        try:
            new_yaw = max(YAW_MIN, min(YAW_MAX, self._track_yaw + yaw_deg))

            # Weighted pitch split — base leads the motion, elbow follows,
            # wrist finishes. Avoids the 3-joint twitch of equal thirds.
            new_base_pitch = max(BASE_PITCH_MIN, min(BASE_PITCH_MAX,
                self._track_base_pitch + pitch_deg * PITCH_WEIGHT_BASE))
            new_elbow_pitch = max(ELBOW_PITCH_MIN, min(ELBOW_PITCH_MAX,
                self._track_elbow_pitch + pitch_deg * PITCH_WEIGHT_ELBOW))
            new_wrist_pitch = max(WRIST_PITCH_MIN, min(WRIST_PITCH_MAX,
                self._track_wrist_pitch + pitch_deg * PITCH_WEIGHT_WRIST))

            target = {
                "base_yaw.pos": new_yaw,
                "base_pitch.pos": new_base_pitch,
                "elbow_pitch.pos": new_elbow_pitch,
                "wrist_pitch.pos": new_wrist_pitch,
            }

            logger.debug(
                "Nudge: px=(%.0f,%.0f) gain=%.1f deg=(%.2f,%.2f) yaw=%.1f→%.1f pitch=%.1f/%.1f/%.1f",
                dx, dy, gain_mult, yaw_deg, pitch_deg,
                self._track_yaw, new_yaw,
                new_base_pitch, new_elbow_pitch, new_wrist_pitch,
            )

            with animation_service.bus_lock:
                animation_service.robot.send_action(target)

            self._track_yaw = new_yaw
            self._track_base_pitch = new_base_pitch
            self._track_elbow_pitch = new_elbow_pitch
            self._track_wrist_pitch = new_wrist_pitch
            return True
        except Exception as e:
            logger.warning("Tracker nudge failed: %s", e)
            return False
