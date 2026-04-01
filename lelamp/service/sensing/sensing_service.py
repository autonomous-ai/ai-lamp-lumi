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

import logging
import os
import tempfile
import threading
import time
from typing import Optional

import lelamp.config as config
import requests
from lelamp.service.sensing.perceptions import (
    FaceRecognizer,
    LightLevelPerception,
    MotionPerception,
)
from lelamp.service.sensing.presence_service import PresenceService

logger = logging.getLogger(__name__)


class SensingService:
    """Background sensing loop. Runs in a daemon thread."""

    # Settle time after freezing servos before capturing a frame (seconds)
    FREEZE_SETTLE_S = 0.3

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
        animation_service=None,
    ):
        self._camera = camera_capture
        self._sd = sound_device_module
        self._np = numpy_module
        self._cv2 = cv2_module
        self._input_device = input_device
        self._poll_interval = poll_interval
        self._animation = animation_service

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_event_time: dict[str, float] = {}

        # TTS reference for echo suppression
        self._tts = tts_service

        # Presence auto on/off state machine
        self.presence = PresenceService(rgb_service=rgb_service)

        # Perception detectors (only initialized if cv2 is available)
        self._perceptions = []
        if cv2_module:
            self._perceptions = [
                MotionPerception(
                    cv2=cv2_module,
                    send_event=self._send_event,
                    on_motion=self.presence.on_motion,
                    capture_stable_frame=self._capture_stable_frame,
                    encode_frame=self._encode_frame,
                ),
                FaceRecognizer(
                    cv2=cv2_module,
                    send_event=self._send_event,
                    on_motion=self.presence.on_motion,
                    encode_frame=self._encode_frame,
                ),
                LightLevelPerception(
                    cv2=cv2_module,
                    np_module=numpy_module,
                    send_event=self._send_event,
                ),
            ]

    def set_tts_service(self, tts_service):
        """Set TTS reference after late initialization (echo suppression)."""
        self._tts = tts_service

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
            frame = self._camera.last_frame

        if frame is not None:
            for perception in self._perceptions:
                perception.check(frame)

        # Sound detection
        if self._sd and self._np and self._input_device is not None:
            self._check_sound()

        # Presence timeout check (dim/off)
        self.presence.tick()

    # --- Sound detection ---

    def _check_sound(self):
        # Skip sound check while TTS is speaking (echo suppression)
        if self._tts is not None and self._tts.speaking:
            return

        sd = self._sd
        np = self._np
        try:
            sample_rate = 44100
            frames = int(sample_rate * config.SOUND_SAMPLE_DURATION_S)
            recording = sd.rec(
                frames,
                samplerate=sample_rate,
                channels=1,
                dtype="int16",
                device=self._input_device,
                blocking=True,
            )
            rms = float(np.sqrt(np.mean(recording.astype(np.float64) ** 2)))
            if rms >= config.SOUND_RMS_THRESHOLD:
                self._send_event("sound", f"Loud noise detected (level: {int(rms)})")
        except Exception as e:
            logger.debug("Sound check failed: %s", e)

    # --- Frame encoding ---

    def _capture_stable_frame(self):
        """Freeze servos, wait for settle, capture a fresh frame, then unfreeze.

        Returns a camera frame suitable for _encode_frame(), or None on failure.
        This avoids motion blur when the camera is mounted on a moving arm.
        """
        if not self._camera or not self._cv2:
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

    # Directory and ordered list of saved snapshot paths (oldest first)
    _snapshot_dir: str = os.path.join(tempfile.gettempdir(), "lumi-sensing-snapshots")
    _snapshot_paths: list = []
    _MAX_SNAPSHOTS: int = 20

    def _save_frame(self, frame) -> Optional[str]:
        """Resize and save a camera frame as a JPEG in the snapshot tmp dir.

        Keeps at most _MAX_SNAPSHOTS files; deletes the oldest when exceeded.
        Returns the saved file path, or None on failure.
        """
        cv2 = self._cv2
        try:
            os.makedirs(self._snapshot_dir, exist_ok=True)

            h, w = frame.shape[:2]
            scale = 320 / w
            small = cv2.resize(frame, (320, int(h * scale)))
            _, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])

            filename = f"sensing_{int(time.time() * 1000)}.jpg"
            filepath = os.path.join(self._snapshot_dir, filename)
            with open(filepath, "wb") as f:
                f.write(buf.tobytes())

            self._snapshot_paths.append(filepath)

            # Evict oldest files if over the limit
            while len(self._snapshot_paths) > self._MAX_SNAPSHOTS:
                oldest = self._snapshot_paths.pop(0)
                try:
                    os.remove(oldest)
                except OSError:
                    pass

            return filepath
        except Exception as e:
            logger.debug("Frame save failed: %s", e)
            return None

    def _encode_frame(self, frame) -> Optional[str]:
        """Save frame to disk and return its path (used as image reference in events)."""
        return self._save_frame(frame)

    # --- Event sending ---

    def to_dict(self) -> dict:
        now = time.time()
        last_events = {
            k: int(now - v) for k, v in self._last_event_time.items()
        }
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
        image: Optional[str] = None,
        cooldown: Optional[float] = None,
    ):
        now = time.time()
        cd = cooldown if cooldown is not None else config.EVENT_COOLDOWN_S
        last = self._last_event_time.get(event_type, 0)
        if now - last < cd:
            return

        # image is now a file path (from _save_frame / _encode_frame).
        # Append the path to the message so OpenClaw's hook can pick it up.
        if image:
            message = f"{message}\n[snapshot: {image}]"

        logger.info("[sensing] %s: %s", event_type, message)

        payload = {"type": event_type, "message": message}

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
