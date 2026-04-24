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
from typing import List, Optional, Tuple, Union

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
#
# Architecture note: this service uses a "move-then-freeze" loop. Each cycle
# reads a camera frame while the servo is stationary, decides on a nudge,
# sends it, then waits long enough for the servo to physically complete the
# motion before the next frame is read. This avoids motion-blurred frames
# and the camera-ego-motion feedback loop that comes from commanding servo
# targets faster than the motor can execute them.

# Base degrees per pixel. Frame assumed ~640 wide; object at edge ≈ 320px.
DEG_PER_PX_YAW = 0.022
DEG_PER_PX_PITCH = 0.022

# Dead zone in pixels — skip nudge when object is within this range of center.
# Small value is fine because the move-then-freeze cadence already suppresses
# micro-jitter without needing a hysteresis wake zone.
DEAD_ZONE_PX = 18

# Maximum nudge per step (degrees). Higher than the 20-FPS value because each
# cycle is now longer (~150ms) and needs to make bigger, deliberate moves.
MAX_NUDGE_DEG = 6.0

# Tracking loop target FPS. Dropped from 20 to 7 so the servo has time to
# physically finish each command before the next frame is read. At 20 FPS,
# commands were stacking up faster than the motor could execute them, and
# the camera was capturing blurred frames mid-motion. ~7 Hz = 143ms/cycle.
TRACK_FPS = 7

# Settling delay (seconds) after sending a nudge, before reading the next
# frame. Gives the motor time to stop so the tracker reads a sharp frame.
# Tuned to roughly match a typical servo step duration for moves up to
# MAX_NUDGE_DEG. Only applied when a nudge was actually sent.
SERVO_SETTLE_S = 0.08

# Pitch driven entirely by base_pitch — a single joint, symmetric with how
# yaw uses base_yaw. Earlier versions split pitch across 3 joints (base /
# elbow / wrist) but the elbow and wrist joints *translate* the camera as
# they tilt, not just rotate it, so the view shifted in ways the pixel-
# to-degree model didn't predict. Single joint = clean rotation around
# the camera's own axis, same mental model as yaw.
#
# Trade-off: base_pitch range is -90°..+30° (120°), narrower than yaw's
# ±135°. Pitch will hit the servo limit sooner, but motion within range
# is stable and predictable.
PITCH_WEIGHT_BASE = 1.0
PITCH_WEIGHT_ELBOW = 0.0
PITCH_WEIGHT_WRIST = 0.0

# Close-object gain attenuation. When the bbox covers a large fraction of
# the frame, the object is physically close to the camera. In that regime:
#   - bbox noise (±a few pixels) produces a large apparent offset
#   - a given servo rotation shifts the object by many more pixels in view
# Both push the tracker to overcorrect. Lowering gain in this regime makes
# close-range tracking feel much less twitchy.
CLOSE_OBJECT_RATIO = 0.35
CLOSE_OBJECT_GAIN = 0.5

# YOLOWorld detection size sanity range. Observed on Pi: when given a
# multi-label target like ["cup", "mug", "coffee cup"], YOLOWorld can
# return confident (0.85-0.97) detections with bboxes covering 30-60% of
# the frame — likely from merging overlapping class predictions. Init-ing
# the tracker on those loose bboxes makes it lock onto background and
# drift within seconds. Reject detections outside this area ratio range.
DETECT_MIN_AREA_RATIO = 0.003  # below this tracker has too few pixels
DETECT_MAX_AREA_RATIO = 0.30   # above this the box is too loose to trust

# Reject YOLO detections below this confidence — in logs, real matches
# sit at 0.65+ while noise ranges 0.1-0.4. 0.3 rejects the obvious
# spurious detections without being aggressive.
DETECT_MIN_CONFIDENCE = 0.3

# TrackerVit confidence threshold — below this = lost
CONFIDENCE_THRESHOLD = 0.3

# How many consecutive low-confidence frames before stopping
MAX_LOW_CONFIDENCE_FRAMES = 5

# Maximum tracking duration (seconds) — auto-stop to save motor/CPU
MAX_TRACK_DURATION_S = 300  # 5 minutes

# Hardware servo position limits (degrees) — absolute safety bounds.
YAW_MIN, YAW_MAX = -135.0, 135.0
BASE_PITCH_MIN, BASE_PITCH_MAX = -90.0, 30.0
ELBOW_PITCH_MIN, ELBOW_PITCH_MAX = -90.0, 90.0
WRIST_PITCH_MIN, WRIST_PITCH_MAX = -90.0, 90.0

# Tracker-allowed range for base_pitch — narrower than the hardware limits so
# the tracker stops reaching for the physical extreme. Observed on-device:
# after /servo/aim desk (base_pitch=+5), tracker chasing a cup near the top
# edge of the frame could drive base_pitch to the hardware MAX (+30) in ~1s.
# The motor then held torque at that limit — the lamp felt "stuck". Keeping
# ~15° headroom on each side gives a graceful stop via the at-limit check.
TRACK_BASE_PITCH_MIN = -75.0
TRACK_BASE_PITCH_MAX = 15.0


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

    def detect_object(self, frame: npt.NDArray[np.uint8], targets: List[str]) -> Optional[Tuple[int, int, int, int]]:
        """Detect an object by name(s) using YOLOWorld API.

        `targets` is a list of candidate labels. YOLOWorld evaluates all of
        them and we pick the single highest-confidence detection across the
        set. Useful when the caller (e.g. an LLM skill) is unsure of the
        right word for the object — passing synonyms increases hit rate.

        Returns (x, y, w, h) top-left bbox or None if not found.
        """
        from lelamp.config import DL_BACKEND_URL, DL_API_KEY
        if not DL_BACKEND_URL:
            logger.error("YOLOWorld: DL_BACKEND_URL not configured")
            return None
        if not targets:
            logger.error("YOLOWorld: empty target list")
            return None

        label = " | ".join(targets)
        url = DL_BACKEND_URL.rstrip("/") + "/" + _YOLO_ENDPOINT.strip("/")
        try:
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            img_b64 = base64.b64encode(buf.tobytes()).decode()

            resp = requests.post(
                url,
                json={"image_b64": img_b64, "classes": list(targets)},
                headers={"x-api-key": DL_API_KEY} if DL_API_KEY else {},
                timeout=_YOLO_TIMEOUT,
            )
            if resp.status_code != 200:
                logger.warning("YOLOWorld HTTP %d: %s", resp.status_code, resp.text[:200])
                return None

            detections = resp.json()
            if not detections:
                logger.info("YOLOWorld: '%s' not found in frame", label)
                return None

            # Filter detections by size AND confidence. Log every candidate
            # with ACCEPTED / REJECTED (reason) so we can see what YOLO
            # actually returned and why it was kept or dropped.
            frame_area = float(frame.shape[0] * frame.shape[1])
            valid = []
            for d in detections:
                cx, cy, w, h = d["xywh"]
                area_ratio = (w * h) / frame_area if frame_area > 0 else 0.0
                conf = d.get("confidence", 0)
                cname = d.get("class_name", "?")
                if conf < DETECT_MIN_CONFIDENCE:
                    reason = "REJECTED (conf)"
                elif not (DETECT_MIN_AREA_RATIO <= area_ratio <= DETECT_MAX_AREA_RATIO):
                    reason = "REJECTED (size)"
                else:
                    reason = "ACCEPTED"
                    valid.append(d)
                logger.info(
                    "  YOLO candidate: class='%s' conf=%.3f bbox=(%d,%d,%d,%d) area=%.1f%% %s",
                    cname, conf, int(cx - w / 2), int(cy - h / 2), int(w), int(h),
                    area_ratio * 100, reason,
                )

            if not valid:
                logger.warning(
                    "YOLOWorld: '%s' — %d detection(s) but none passed filters "
                    "[conf >= %.2f, size %.1f%%–%.1f%% of frame]",
                    label, len(detections),
                    DETECT_MIN_CONFIDENCE,
                    DETECT_MIN_AREA_RATIO * 100, DETECT_MAX_AREA_RATIO * 100,
                )
                return None

            # Pick highest confidence among size-valid detections
            best = max(valid, key=lambda d: d.get("confidence", 0))
            cx, cy, w, h = best["xywh"]
            x = int(cx - w / 2)
            y = int(cy - h / 2)
            bbox = (x, y, int(w), int(h))
            matched = best.get("class_name", "?")
            logger.info("YOLOWorld: '%s' matched '%s' at bbox=%s conf=%.3f",
                        label, matched, bbox, best["confidence"])
            return bbox
        except Exception as e:
            logger.error("YOLOWorld detect failed: %s", e)
            return None

    def start(
        self,
        bbox: Optional[Tuple[int, int, int, int]] = None,
        target_label: Union[str, List[str]] = "",
        camera_capture=None,
        animation_service=None,
    ) -> bool:
        """Start tracking an object.

        `target_label` can be a single string or a list of candidate labels
        (e.g. synonyms from an LLM that's unsure of the exact word). If
        `bbox` is provided, `target_label` is only used for display and
        logging; otherwise YOLOWorld auto-detects using these labels.
        """
        if camera_capture is None or animation_service is None:
            self.last_error = "camera or animation service not available"
            logger.error("tracker start: %s", self.last_error)
            return False

        # Normalize target_label → list of non-empty strings, plus a
        # human-readable display form.
        if isinstance(target_label, str):
            targets = [target_label] if target_label else []
        else:
            targets = [t for t in target_label if t]
        display_label = " | ".join(targets) if targets else ""

        self.stop()

        # Wait for any in-progress animation (typically a preceding
        # /servo/aim) to finish before grabbing the frame for YOLO.
        # Without this, the camera captures a frame mid-motion — YOLO is
        # robust enough to still return *a* detection, but the tracker
        # can't lock because the next frame looks materially different
        # once the servo settles. A 50ms extra idle pad covers the motor's
        # own settle time after the animation loop has released the pose.
        animation_wait_budget_s = 7.0
        animation_idle_deadline = time.perf_counter() + animation_wait_budget_s
        while time.perf_counter() < animation_idle_deadline:
            busy = bool(getattr(animation_service, "_current_recording", None)) \
                or getattr(animation_service, "_interpolation_frames", 0) > 0
            if not busy:
                break
            time.sleep(0.05)
        else:
            logger.warning("tracker start: animation still busy after %.0fs, proceeding anyway",
                           animation_wait_budget_s)
        time.sleep(0.05)

        # Snapshot a single frame and keep it throughout detect + tracker init.
        # The YOLO call takes 1-2s, during which the scene may change. The
        # returned bbox is in *this* frame's coordinates — re-grabbing a
        # fresh frame for init would pair bbox with a different image and
        # start the tracker mis-aligned.
        frame = camera_capture.last_frame
        if frame is None:
            self.last_error = "no frame available from camera"
            logger.error("tracker start: %s", self.last_error)
            return False
        frame = frame.copy()

        # Auto-detect if no bbox provided
        if bbox is None:
            if not targets:
                self.last_error = "need either bbox or target label"
                logger.error("tracker start: %s", self.last_error)
                return False
            bbox = self.detect_object(frame, targets)
            if bbox is None:
                self.last_error = f"'{display_label}' not found in frame"
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
        if ok is False:
            logger.error("tracker init failed for bbox %s", bbox)
            return False
        logger.info("tracker init OK for bbox %s (frame %dx%d)", bbox, frame.shape[1], frame.shape[0])

        with self._lock:
            self._state = TrackingState(
                target_label=display_label,
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

        logger.info("Tracking started: '%s' bbox=%s", display_label, bbox)
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
        animation_service._tracking_active = True
        logger.info("Servo hold mode + tracking lock ON")

        from lelamp.service.motors.animation_service import _motor_positions_from_bus

        def _sync_pose_from_bus() -> bool:
            """Re-read actual servo position from the bus. Returns True on success."""
            try:
                with animation_service.bus_lock:
                    pos = _motor_positions_from_bus(animation_service.robot)
                self._track_yaw = pos.get("base_yaw.pos", self._track_yaw)
                self._track_base_pitch = pos.get("base_pitch.pos", self._track_base_pitch)
                self._track_elbow_pitch = pos.get("elbow_pitch.pos", self._track_elbow_pitch)
                self._track_wrist_pitch = pos.get("wrist_pitch.pos", self._track_wrist_pitch)
                return True
            except Exception:
                return False

        # Seed internal pose. Zeros are a last-resort fallback.
        self._track_yaw = 0.0
        self._track_base_pitch = 0.0
        self._track_elbow_pitch = 0.0
        self._track_wrist_pitch = 0.0
        _sync_pose_from_bus()

        init_area = state.bbox[2] * state.bbox[3] if state.bbox else 0
        frame_count = 0
        track_start_t = time.perf_counter()
        fps_t0 = track_start_t

        cycle_period = 1.0 / TRACK_FPS

        try:
            while state.running.is_set():
                t0 = time.perf_counter()

                # Re-sync internal pose from the bus each cycle. If something
                # external (emotion reaction from a loud noise, manual servo
                # command, stale animation from before hold_mode took effect)
                # moved the servo since our last nudge, we detect it here and
                # resume tracking from the real pose instead of compounding
                # stale deltas. At 7 Hz the extra ~10ms bus read is cheap.
                _sync_pose_from_bus()

                # Read one frame while servo is stationary. Move-then-freeze
                # cadence guarantees this: the previous iteration finished
                # with a SERVO_SETTLE_S sleep after the motor command.
                frame = camera_capture.last_frame
                if frame is None:
                    time.sleep(cycle_period)
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
                    time.sleep(cycle_period)
                    continue

                state.low_confidence_frames = 0
                state.bbox = tuple(int(v) for v in new_bbox)
                bx, by, bw, bh = state.bbox

                # Detect bbox bloat — tracker drifting toward full frame.
                # Was 3x; tightened to 2x because on-device every lost session
                # ended here, and by the time 3x hit the servo had already
                # been pushed to an extreme pose. Stopping earlier keeps the
                # lamp closer to the last good pose.
                bbox_area = bw * bh
                frame_area = frame.shape[0] * frame.shape[1]
                if init_area > 0 and bbox_area > init_area * 2:
                    logger.warning("Bbox bloated to %.1fx initial (area=%d vs init=%d), stopping",
                                   bbox_area / init_area, bbox_area, init_area)
                    break
                if bbox_area > frame_area * 0.5:
                    logger.warning("Bbox covers >50%% of frame (%d/%d), stopping",
                                   bbox_area, frame_area)
                    break

                cx = bx + bw / 2
                cy = by + bh / 2

                # Object is physically close when bbox occupies a big chunk
                # of the frame — reduce gain to avoid twitchy overcorrection.
                close = bbox_area > CLOSE_OBJECT_RATIO * frame_area

                moved = self._nudge_servo(frame, cx, cy, close, animation_service)

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

                # Max duration check
                if time.perf_counter() - track_start_t > MAX_TRACK_DURATION_S:
                    logger.warning("Tracking timeout after %ds, stopping", MAX_TRACK_DURATION_S)
                    break

                # Servo at limit but object still far from center → unreachable.
                # Compare against the tracker-allowed pitch range (narrower
                # than hardware) so we bail out before the motor hits a stop.
                at_yaw_limit = self._track_yaw <= YAW_MIN + 1 or self._track_yaw >= YAW_MAX - 1
                at_pitch_limit = (self._track_base_pitch <= TRACK_BASE_PITCH_MIN + 1
                                  or self._track_base_pitch >= TRACK_BASE_PITCH_MAX - 1)
                if at_yaw_limit or at_pitch_limit:
                    h, w = frame.shape[:2]
                    off = max(abs(cx - w / 2), abs(cy - h / 2))
                    if off > w * 0.3:  # object still >30% off center
                        logger.warning("Servo at limit (yaw=%.1f pitch=%.1f) but object far (off=%.0fpx), stopping",
                                       self._track_yaw, self._track_base_pitch, off)
                        break

                # If a nudge was actually sent, wait for the servo to finish
                # physically moving before reading the next frame. This is
                # the "freeze" half of the move-then-freeze loop — without
                # it the next frame is motion-blurred and the tracker lies.
                if moved:
                    time.sleep(SERVO_SETTLE_S)

                # Pad the rest of the cycle to hit TRACK_FPS cadence.
                dt = time.perf_counter() - t0
                sleep_time = cycle_period - dt
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
        close: bool,
        animation_service,
    ) -> bool:
        """Nudge servo toward object center. Returns True if a command was sent."""
        h, w = frame.shape[:2]
        dx = cx_obj - w / 2
        dy = cy_obj - h / 2

        gain_mult = CLOSE_OBJECT_GAIN if close else 1.0

        yaw_deg = 0.0 if abs(dx) < DEAD_ZONE_PX else dx * DEG_PER_PX_YAW * gain_mult

        # Pitch sign is NEGATED because base_pitch increases = lamp tilts UP
        # (per AIM_UP base_pitch=+10 vs AIM_DOWN base_pitch=-50 in presets).
        # To bring an object at the TOP of the frame (dy < 0) toward the
        # centre, the lamp must tilt UP → base_pitch must INCREASE →
        # pitch_deg must be POSITIVE. Without this negation, tracker drove
        # the lamp *away* from the object on the vertical axis, observed as
        # "cup near top edge, servo keeps tilting down until it hits MAX
        # and stalls".
        pitch_deg = 0.0 if abs(dy) < DEAD_ZONE_PX else -dy * DEG_PER_PX_PITCH * gain_mult

        yaw_deg = max(-MAX_NUDGE_DEG, min(MAX_NUDGE_DEG, yaw_deg))
        pitch_deg = max(-MAX_NUDGE_DEG, min(MAX_NUDGE_DEG, pitch_deg))

        if yaw_deg == 0 and pitch_deg == 0:
            return False

        try:
            new_yaw = max(YAW_MIN, min(YAW_MAX, self._track_yaw + yaw_deg))

            # Pitch on base joint only. Elbow/wrist weights are 0 so they
            # stay at their start pose, matching how yaw leaves the other
            # joints alone.
            # Clamp to tracker-allowed range (narrower than hardware limits)
            # so tracking never drives the motor against a physical stop.
            new_base_pitch = max(TRACK_BASE_PITCH_MIN, min(TRACK_BASE_PITCH_MAX,
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
                "Nudge: px=(%.0f,%.0f) close=%s gain=%.1f deg=(%.2f,%.2f) yaw=%.1f→%.1f pitch=%.1f→%.1f",
                dx, dy, close, gain_mult, yaw_deg, pitch_deg,
                self._track_yaw, new_yaw,
                self._track_base_pitch, new_base_pitch,
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
