"""
Sensing Service — background loop that detects motion/sound/faces/light and pushes events to Lumi Server.

Lumi Server (Go, port 5000) then forwards these events to OpenClaw via WebSocket chat.send,
so the AI agent can react proactively (Pillar 4: "It acts on its own").

Detectors:
  - Motion: camera frame differencing (grayscale → absdiff → threshold → contour area)
  - Face: InsightFace recognition — owner/stranger classification (presence.enter/leave)
  - Light level: mean brightness of camera frame (auto-adjust lamp)
  - Sound: RMS level from microphone (loud noise detection)

Also drives the PresenceService state machine for automatic light on/off.

Events are POST-ed to http://localhost:5000/api/sensing/event as:
  {"type": "motion", "message": "...", "image": "<base64 jpeg>"}
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from typing import Optional

import requests

import lelamp.config as config
from lelamp.service.sensing.perceptions import (
    EmotionPerception,
    FaceRecognizer,
    LightLevelPerception,
    MotionPerception,
    PoseMotionPerception,
    SoundPerception,
    WellbeingPerception,
)
from lelamp.service.sensing.presence_service import PresenceService

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

try:
    import cv2
except ImportError:
    cv2 = None  # type: ignore[assignment]

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]

try:
    import sounddevice as sd
except ImportError:
    sd = None  # type: ignore[assignment]

class SensingService:
    """Background sensing loop. Runs in a daemon thread."""

    # Settle time after freezing servos before capturing a frame (seconds)
    FREEZE_SETTLE_S: float = 0.3

    def __init__(
        self,
        camera_capture=None,
        input_device: int | str | None = None,
        poll_interval: float = 2.0,
        rgb_service=None,
        tts_service=None,
        animation_service=None,
        on_restore_aim=None,
        is_sleeping=None,
    ):
        self._camera = camera_capture
        self._is_sleeping = is_sleeping  # callable → bool; suppresses non-wake events
        self._poll_interval = poll_interval
        self._animation = animation_service

        self._running: bool = False
        self._thread: threading.Thread | None = None
        self._last_event_time: dict[str, float] = {}
        self._face_recognizer: FaceRecognizer | None = None
        self._wellbeing: WellbeingPerception | None = None

        # Presence auto on/off state machine
        self.presence: PresenceService = PresenceService(
            rgb_service=rgb_service,
            send_event=self._send_event,
            on_restore_aim=on_restore_aim,
        )

        # Perception detectors
        self._perceptions = []
        if cv2 is not None:
            face_recognizer = FaceRecognizer(
                cv2=cv2,
                send_event=self._send_event,
                on_motion=self.presence.on_motion,
            )
            self._face_recognizer = face_recognizer
            _ = face_recognizer.load_from_disk()
            self._wellbeing = WellbeingPerception(
                cv2=cv2,
                send_event=self._send_event,
                presence_service=self.presence,
                capture_stable_frame=self._capture_stable_frame,
            )
            if config.MOTION_ENABLED:
                self._perceptions.append(
                    MotionPerception(
                        send_event=self._send_event,
                        on_motion=self.presence.on_motion,
                        capture_stable_frame=self._capture_stable_frame,
                        presence_service=self.presence,
                        face_recognizer=face_recognizer,
                    )
                )
            if config.EMOTION_ENABLED:
                self._perceptions.append(
                    EmotionPerception(
                        send_event=self._send_event,
                        on_motion=self.presence.on_motion,
                        capture_stable_frame=self._capture_stable_frame,
                        presence_service=self.presence,
                        face_recognizer=face_recognizer,
                    )
                )
            if config.POSE_MOTION_ENABLED:
                self._perceptions.append(
                    PoseMotionPerception(
                        cv2=cv2,
                        send_event=self._send_event,
                        on_motion=self.presence.on_motion,
                        capture_stable_frame=self._capture_stable_frame,
                        presence_service=self.presence,
                        face_recognizer=face_recognizer,
                    )
                )
            self._perceptions += [
                face_recognizer,
                LightLevelPerception(
                    cv2=cv2,
                    np_module=np,
                    send_event=self._send_event,
                ),
                self._wellbeing,
            ]
        if sd is not None and np is not None and input_device is not None:
            self._sound_perception = SoundPerception(
                sd=sd,
                np_module=np,
                send_event=self._send_event,
                input_device=input_device,
                tts_service=tts_service,
            )
            self._perceptions.append(self._sound_perception)
        else:
            self._sound_perception = None

    def set_tts_service(self, tts_service):
        """Set TTS reference after late initialization (echo suppression)."""
        if self._sound_perception is not None:
            self._sound_perception.set_tts_service(tts_service)

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
        self._tick_count = 0
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.error("Sensing tick error: %s", e, exc_info=True)
            self._tick_count += 1
            time.sleep(self._poll_interval)

    def _tick(self):
        frame = None

        # Read camera frame once per tick (shared across detectors)
        if self._camera and cv2:
            frame = self._camera.last_frame

        for perception in self._perceptions:
            # Run heavy perceptions (face/pose) every other tick to save CPU
            if isinstance(perception, (FaceRecognizer, PoseMotionPerception)):
                if self._tick_count % 2 != 0:
                    continue
            perception.check(frame)

        # Presence timeout check (dim/off)
        self.presence.tick()

    # --- Frame encoding ---

    def _capture_stable_frame(self):
        """Freeze servos, wait for settle, capture a fresh frame, then unfreeze.

        Returns a camera frame suitable for _encode_frame(), or None on failure.
        Always freezes regardless of whether an animation is playing — a 0.3s
        pause is imperceptible but eliminates motion blur from the servo arm.
        """
        if not self._camera or not cv2:
            return None

        anim = self._animation
        if anim:
            anim.freeze()
            time.sleep(self.FREEZE_SETTLE_S)
        frame = self._camera.last_frame
        if anim:
            anim.unfreeze()

        if frame is None:
            return None
        return frame

    # --- Snapshot storage (two-tier) ---
    # Tmp: fast rotation buffer, lost on reboot
    _snapshot_tmp_paths: list = []
    # Persist: survives reboot, agent can look back (TTL + size rotation)

    def _save_frame(self, frame) -> Optional[str]:
        """Save a camera frame as a JPEG to the tmp snapshot dir at original resolution.

        Keeps at most SNAPSHOT_TMP_MAX_COUNT files; deletes the oldest when exceeded.
        Returns the saved file path, or None on failure.
        """
        try:
            os.makedirs(config.SNAPSHOT_TMP_DIR, exist_ok=True)

            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])

            filename = f"sensing_{int(time.time() * 1000)}.jpg"
            filepath = os.path.join(config.SNAPSHOT_TMP_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(buf.tobytes())

            self._snapshot_tmp_paths.append(filepath)

            # Evict oldest files if over the limit
            while len(self._snapshot_tmp_paths) > config.SNAPSHOT_TMP_MAX_COUNT:
                oldest = self._snapshot_tmp_paths.pop(0)
                try:
                    os.remove(oldest)
                except OSError:
                    pass

            return filepath
        except Exception as e:
            logger.debug("Frame save failed: %s", e)
            return None

    def _persist_snapshot(self, tmp_path: str) -> Optional[str]:
        """Copy a tmp snapshot to the persistent dir with TTL + size rotation.

        Returns the persistent file path, or None on failure.
        """
        try:
            persist_dir = config.SNAPSHOT_PERSIST_DIR
            os.makedirs(persist_dir, exist_ok=True)

            # Rotate: remove files older than TTL
            now = time.time()
            for f in os.listdir(persist_dir):
                fp = os.path.join(persist_dir, f)
                try:
                    if now - os.path.getmtime(fp) > config.SNAPSHOT_PERSIST_TTL_S:
                        os.remove(fp)
                except OSError:
                    pass

            # Rotate: if total size exceeds max, remove oldest files
            files = []
            for f in os.listdir(persist_dir):
                fp = os.path.join(persist_dir, f)
                try:
                    files.append((fp, os.path.getmtime(fp), os.path.getsize(fp)))
                except OSError:
                    pass
            files.sort(key=lambda x: x[1])  # oldest first
            total = sum(s for _, _, s in files)
            while total > config.SNAPSHOT_PERSIST_MAX_BYTES and files:
                oldest_path, _, oldest_size = files.pop(0)
                try:
                    os.remove(oldest_path)
                    total -= oldest_size
                except OSError:
                    pass

            # Copy snapshot to persistent dir
            dest = os.path.join(persist_dir, os.path.basename(tmp_path))
            shutil.copy2(tmp_path, dest)
            return dest
        except Exception as e:
            logger.debug("Persist snapshot failed: %s", e)
            return None

    # --- Event sending ---

    def to_dict(self) -> dict:
        now = time.time()
        last_events = {k: int(now - v) for k, v in self._last_event_time.items()}
        return {
            "running": self._running,
            "poll_interval": self._poll_interval,
            "last_event_seconds_ago": last_events,
            "perceptions": [p.to_dict() for p in self._perceptions],
            "presence": self.presence.to_dict(),
        }

    def _send_event(
        self,
        event_type: str,
        message: str,
        image=None,
        images: list | None = None,
        cooldown: Optional[float] = None,
    ):
        # Suppress sensing events while sleeping — only allow presence.enter to wake up
        if self._is_sleeping and self._is_sleeping() and event_type != "presence.enter":
            logger.debug("[sensing] sleeping — suppressed %s", event_type)
            return

        # New presence session — clear MotionPerception dedup so the next
        # motion.activity isn't silently dropped by the 5-min window.
        # Otherwise a friend arriving while someone was already sitting would
        # wait out the remainder of the old window before the agent saw them.
        #
        # Pass the *current* user so perceptions can skip the reset when the
        # visible user hasn't actually changed (e.g. stranger_79 → stranger_77,
        # both collapse to "unknown"). Without this guard, face-recognition
        # flicker between stranger IDs wipes the dedup every few seconds.
        if event_type == "presence.enter":
            new_user = ""
            if self._face_recognizer is not None:
                try:
                    new_user = self._face_recognizer.current_user() or ""
                except Exception:
                    logger.exception("[sensing] face_recognizer.current_user() failed")
            for perception in self._perceptions:
                reset = getattr(perception, "reset_dedup", None)
                if callable(reset):
                    try:
                        reset(new_user)
                    except Exception:
                        logger.exception(
                            "[sensing] %s.reset_dedup() failed",
                            perception.__class__.__name__,
                        )

        now = time.time()
        # motion.activity has its own 5-min dedup in MotionPerception —
        # skip the global cooldown so different activities (drink vs
        # sedentary) are never silently dropped.
        if event_type not in ("motion.activity", "emotion.detected"):
            cd = cooldown if cooldown is not None else config.EVENT_COOLDOWN_S
            last = self._last_event_time.get(event_type, 0)
            if now - last < cd:
                return

        # Collect all images to save (single image or list)
        frames = []
        if images:
            frames = list(images)
        elif image is not None:
            frames = [image]

        # Save each frame and append snapshot paths to the message.
        for frame in frames:
            tmp_path = self._save_frame(frame)
            if tmp_path:
                persist_path = self._persist_snapshot(tmp_path)
                ref = persist_path or tmp_path
                message = f"{message}\n[snapshot: {ref}]"

        logger.info("[sensing] %s: %s", event_type, message)

        payload: dict[str, object] = {"type": event_type, "message": message}
        # Include LeLamp's effective current_user so Lumi handler doesn't
        # have to re-derive it from the message text. Text parsing breaks
        # when a stranger-only enter event fires while a friend is still
        # present (extractUserName sees no friend in the message and
        # downgrades mood.CurrentUser() to "unknown", even though the
        # friend is still within forget window). LeLamp's current_user()
        # is the source of truth — ship it.
        if self._face_recognizer is not None:
            try:
                cu = self._face_recognizer.current_user() or ""
            except Exception:
                logger.exception("[sensing] face_recognizer.current_user() failed")
                cu = ""
            payload["current_user"] = cu
        logger.debug("[sensing] payload = %s", payload)

        try:
            resp = requests.post(
                config.LUMI_SENSING_URL,
                json=payload,
                timeout=5,
            )
            if resp.status_code != 200:
                logger.warning(
                    "[sensing] Lumi returned %d: %s", resp.status_code, resp.text
                )
            else:
                self._last_event_time[event_type] = now
        except requests.RequestException as e:
            logger.warning("[sensing] Failed to send event to Lumi: %s", e)
