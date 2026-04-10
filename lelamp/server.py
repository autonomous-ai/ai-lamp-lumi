"""
LeLamp Hardware Runtime — FastAPI server on port 5001.

Only starts the drivers we need. LiveKit/OpenAI code stays untouched but never imported.
Lumi Server (Go, port 5000) bridges requests here.
"""

import base64
import csv
import io
import logging
import logging.handlers
import math
import os
import random
import re
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Union

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from lelamp.presets import (
    AIM_PRESETS,
    EMOTION_PRESETS,
    SCENE_PRESETS,
    VALID_LED_EFFECTS,
)
from pydantic import BaseModel, Field

# Load .env from the install dir (/opt/lelamp/.env) — no-op if missing
load_dotenv(Path(__file__).parent / ".env", override=False)

# --- Logging: colored stdout + rotating file ---
LOG_DIR = Path(os.environ.get("LELAMP_LOG_DIR", "/var/log/lelamp"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

_LEVEL_COLORS = {
    logging.DEBUG: "\033[37m",  # gray
    logging.INFO: "\033[32m",  # green
    logging.WARNING: "\033[33m",  # yellow
    logging.ERROR: "\033[31m",  # red
    logging.CRITICAL: "\033[1;31m",  # bold red
}
_RESET = "\033[0m"


class _ColorFormatter(logging.Formatter):
    """Adds ANSI colors to levelname for console output."""

    _fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"

    def format(self, record):
        color = _LEVEL_COLORS.get(record.levelno, "")
        record.levelname = f"{color}{record.levelname}{_RESET}"
        formatter = logging.Formatter(self._fmt)
        return formatter.format(record)


_root = logging.getLogger()
_log_level = os.environ.get("LELAMP_LOG_LEVEL", "INFO").upper()
_root.setLevel(getattr(logging, _log_level, logging.INFO))

# Console handler (colored)
_console = logging.StreamHandler()
_console.setFormatter(_ColorFormatter())
_root.addHandler(_console)

# File handler: 1 MB per file, keep 3 backups (~4 MB max) — no color codes
_file = logging.handlers.RotatingFileHandler(
    LOG_DIR / "server.log",
    maxBytes=1 * 1024 * 1024,
    backupCount=3,
)
_file.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
_root.addHandler(_file)

logger = logging.getLogger("lelamp.server")
logger.info("Logging to %s/server.log", LOG_DIR)

# --- Lazy imports for hardware drivers (may not be available on dev machines) ---

AnimationService = None
RGBService = None
sd = None
np = None

try:
    from lelamp.service.motors.animation_service import AnimationService
except ImportError as e:
    logger.warning(f"Servo drivers not available: {e}")

try:
    from lelamp.service.rgb.rgb_service import RGBService
except ImportError as e:
    logger.warning(f"LED drivers not available: {e}")

try:
    import numpy as np
    import sounddevice as sd
except ImportError as e:
    logger.warning(f"Audio drivers not available: {e}")

cv2 = None
try:
    import cv2
except ImportError as e:
    logger.warning(f"Camera drivers (opencv) not available: {e}")

LocalVideoCaptureDevice = None
VideoCaptureDeviceInfo = None
try:
    from lelamp.devices.models import VideoCaptureDeviceInfo
    from lelamp.devices.video_capture_device import LocalVideoCaptureDevice
except ImportError as e:
    logger.warning(f"Video capture device not available: {e}")

# --- Config ---

SERVO_PORT = os.environ.get("LELAMP_SERVO_PORT", "/dev/ttyACM0")
LAMP_ID = os.environ.get("LELAMP_LAMP_ID", "lelamp")
SERVO_FPS = int(os.environ.get("LELAMP_SERVO_FPS", "30"))
SERVO_HOLD_S = float(os.environ.get("LELAMP_SERVO_HOLD_S", "3.0"))
HTTP_PORT = int(os.environ.get("LELAMP_HTTP_PORT", "5001"))
CAMERA_INDEX = int(os.environ.get("LELAMP_CAMERA_INDEX", "0"))
CAMERA_WIDTH = int(os.environ.get("LELAMP_CAMERA_WIDTH", "640"))
CAMERA_HEIGHT = int(os.environ.get("LELAMP_CAMERA_HEIGHT", "480"))

# Audio hardware overrides — set in .env to bypass auto-detection
# e.g. LELAMP_AUDIO_INPUT_ALSA=plughw:1,0  LELAMP_AUDIO_OUTPUT_ALSA=plughw:2,0
AUDIO_INPUT_ALSA: Optional[str] = os.environ.get("LELAMP_AUDIO_INPUT_ALSA") or None
AUDIO_OUTPUT_ALSA: Optional[str] = os.environ.get("LELAMP_AUDIO_OUTPUT_ALSA") or None
# Separate mic device index for SoundPerception (noise sensing).
# Set to sounddevice card index (see: python3 -c "import sounddevice; print(sounddevice.query_devices())")
# Useful when using a dedicated mic for ambient noise detection separate from the STT mic.
_sensing_device_env = os.environ.get("LELAMP_AUDIO_SENSING_DEVICE")
AUDIO_SENSING_DEVICE: Optional[int] = int(_sensing_device_env) if _sensing_device_env else None

# TTS speed multiplier — 1.0=normal, 1.3=faster, max 4.0
TTS_SPEED: float = float(os.environ.get("LELAMP_TTS_SPEED", "1.3"))

# --- Lazy import for sensing ---

SensingService = None
FaceRecognizer = None
try:
    from lelamp.service.sensing.perceptions.facerecognizer import FaceRecognizer
    from lelamp.service.sensing.sensing_service import SensingService
except ImportError as e:
    logger.warning(f"Sensing service not available: {e}")
    SensingService = None
    FaceRecognizer = None

# --- Lazy import for voice ---

VoiceService = None
DeepgramSTT = None
AutonomousSTT = None
TTSService = None
try:
    from lelamp.service.voice.stt_autonomous import AutonomousSTT
    from lelamp.service.voice.stt_deepgram import DeepgramSTT
    from lelamp.service.voice.voice_service import VoiceService
except ImportError as e:
    logger.warning(f"Voice service not available: {e}")

try:
    from lelamp.service.voice.tts_service import TTSService
except ImportError as e:
    logger.warning(f"TTS service not available: {e}")

MusicService = None
try:
    from lelamp.service.voice.music_service import MusicService
except ImportError as e:
    logger.warning(f"Music service not available: {e}")

# --- Lazy import for display ---

DisplayService = None
try:
    from lelamp.service.display.display_service import DisplayService
except ImportError as e:
    logger.warning(f"Display service not available: {e}")

# --- Services (initialized on startup) ---

animation_service = None
rgb_service = None
camera_capture = None
sensing_service = None
voice_service = None
display_service = None
tts_service = None
music_service = None
_gpio_stop_button = None  # GPIO17 stop-speaker button (kept alive to prevent GC)


def _find_audio_device(output: bool = True) -> Optional[int]:
    """Find audio device index by known hardware names, with USB fallback.

    Priority:
      1. Known hardware keywords (Seeed ReSpeaker, CD002, webcam, etc.)
      2. USB dedicated audio devices (prefer "usb audio" over composite/webcam)
      3. Any USB device with the right channel type
    """
    if not sd:
        return None
    # Known hardware — checked in order (first match wins)
    output_names = ["seeed", "cd002"]
    input_names = ["seeed", "webcam"]
    # Keywords that indicate a camera/video device — lower priority for input
    # Note: "composite" removed — USB Composite Device is often a valid mic
    # Note: "usb audio" removed — it matches USB Audio Device (speakers) in daemon mode
    input_skip = ["camera", "video"]
    names = output_names if output else input_names
    try:
        devices = list(sd.query_devices())
        # Pass 1: match known hardware keywords
        for keyword in names:
            for i, d in enumerate(devices):
                name = d["name"].lower()
                if keyword not in name:
                    continue
                if output and d["max_output_channels"] > 0:
                    return i
                if not output and d["max_input_channels"] > 0:
                    return i
        # Pass 2: fallback — USB dedicated audio (skip composite/camera devices for input)
        for i, d in enumerate(devices):
            name = d["name"].lower()
            if "usb" not in name:
                continue
            if not output and any(s in name for s in input_skip):
                continue
            if output and d["max_output_channels"] > 0:
                logger.info("Audio fallback: using USB device %d '%s' for output", i, d["name"])
                return i
            if not output and d["max_input_channels"] > 0:
                logger.info("Audio fallback: using USB device %d '%s' for input", i, d["name"])
                return i
        # Pass 3: last resort — any USB device including composite
        if not output:
            for i, d in enumerate(devices):
                name = d["name"].lower()
                if "usb" in name and d["max_input_channels"] > 0:
                    logger.info("Audio last-resort: using %d '%s' for input", i, d["name"])
                    return i
        # Pass 4: probe ALSA (arecord -l / aplay -l) and match card description to sounddevice
        alsa_cmd = ["aplay", "-l"] if output else ["arecord", "-l"]
        try:
            result = subprocess.run(alsa_cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if not line.startswith("card "):
                        continue
                    m = re.search(r"card \d+: \S+ \[(.+?)\]", line)
                    if not m:
                        continue
                    label_words = [w.lower() for w in m.group(1).split() if len(w) > 2]
                    for i, d in enumerate(devices):
                        dname = d["name"].lower()
                        if any(w in dname for w in label_words):
                            if output and d["max_output_channels"] > 0:
                                logger.info("ALSA probe: device %d '%s' for output", i, d["name"])
                                return i
                            if not output and d["max_input_channels"] > 0:
                                logger.info("ALSA probe: device %d '%s' for input", i, d["name"])
                                return i
        except Exception:
            pass
        # Pass 5: absolute last resort — first non-HDMI device with right channel type
        skip = ["hdmi", "spdif", "iec958"]
        for i, d in enumerate(devices):
            dname = d["name"].lower()
            if any(s in dname for s in skip):
                continue
            if output and d["max_output_channels"] > 0:
                logger.info("Audio fallback (any): device %d '%s' for output", i, d["name"])
                return i
            if not output and d["max_input_channels"] > 0:
                logger.info("Audio fallback (any): device %d '%s' for input", i, d["name"])
                return i
    except Exception:
        pass
    return None


audio_output_device: Optional[int] = None
audio_input_device: Optional[int] = None

_DEFAULT_AGENT_NAME = "lumi"
_OPENCLAW_WORKSPACE = os.environ.get("OPENCLAW_WORKSPACE", "/root/.openclaw/workspace")


def _read_agent_name(lumi_cfg: dict) -> str:
    """Read agent name from IDENTITY.md. Falls back to default 'lumi'."""
    identity_path = os.path.join(_OPENCLAW_WORKSPACE, "IDENTITY.md")
    try:
        with open(identity_path) as f:
            for line in f:
                lower = line.lower()
                idx = lower.find("**name:**")
                if idx >= 0:
                    name = line[idx + len("**name:**"):].strip().split("—")[0].split("-")[0].strip()
                    if name:
                        return name.lower()
    except Exception:
        pass
    return _DEFAULT_AGENT_NAME


def _build_wake_words(name: str) -> list[str]:
    """Generate wake word variants from agent name."""
    n = name.lower()
    return [f"hey {n}", n, f"này {n}", f"ê {n}", f"{n} ơi"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global animation_service, rgb_service, camera_capture, sensing_service
    global voice_service, tts_service, display_service
    global audio_output_device, audio_input_device

    # --- Phase 1: Fire slow hardware init in background threads ---
    # Servo, LED, and camera can take 1-5s each. Run them concurrently so they
    # don't delay the voice pipeline which has no hardware dependencies.

    def _init_servo():
        global animation_service
        if not AnimationService:
            return
        try:
            svc = AnimationService(
                port=SERVO_PORT, lamp_id=LAMP_ID, fps=SERVO_FPS, hold_s=SERVO_HOLD_S
            )
            svc.start()
            animation_service = svc
            logger.info("AnimationService started")
        except Exception as e:
            logger.warning(f"AnimationService failed to start: {e}")

    def _init_led():
        global rgb_service
        if not RGBService:
            return
        try:
            svc = RGBService(led_count=64)
            svc.start()
            rgb_service = svc
            logger.info("RGBService started")
        except Exception as e:
            logger.warning(f"RGBService failed to start: {e}")

    def _init_camera():
        global camera_capture
        if not (LocalVideoCaptureDevice and VideoCaptureDeviceInfo and cv2):
            return
        try:
            cap = LocalVideoCaptureDevice(
                VideoCaptureDeviceInfo(
                    device_id=CAMERA_INDEX,
                    max_width=CAMERA_WIDTH,
                    max_height=CAMERA_HEIGHT,
                )
            )
            cap.start()
            camera_capture = cap
            logger.info(
                f"Camera opened (index={CAMERA_INDEX}, {CAMERA_WIDTH}x{CAMERA_HEIGHT})"
            )
        except Exception as e:
            logger.warning(f"Camera failed to start: {e}")

    hw_threads = []
    for fn in (_init_servo, _init_led, _init_camera):
        t = threading.Thread(target=fn, daemon=True, name=fn.__name__)
        t.start()
        hw_threads.append(t)

    # --- Phase 2: Audio detect + TTS + VoiceService (runs while hardware inits above) ---

    # Detect audio devices — run output and input detection in parallel (each may
    # invoke subprocess aplay/arecord with up to 5s timeout, so do them concurrently).
    global music_service
    if sd:
        _audio_results = [None, None]

        def _detect_output():
            _audio_results[0] = _find_audio_device(output=True)

        def _detect_input():
            _audio_results[1] = _find_audio_device(output=False)

        _t_out = threading.Thread(target=_detect_output, daemon=True)
        _t_in = threading.Thread(target=_detect_input, daemon=True)
        _t_out.start()
        _t_in.start()
        _t_out.join()
        _t_in.join()

        audio_output_device, audio_input_device = _audio_results
        if audio_output_device is not None:
            logger.info(f"Audio output device: {audio_output_device}")
        if audio_input_device is not None:
            logger.info(f"Audio input device: {audio_input_device}")

    # Auto-start voice pipeline from Lumi config if keys are available
    lumi_config_path = os.environ.get("LUMI_CONFIG_PATH", "/root/config/config.json")
    try:
        import json

        with open(lumi_config_path) as f:
            lumi_cfg = json.load(f)
        dgk = lumi_cfg.get("deepgram_api_key", "")
        llm_key = lumi_cfg.get("llm_api_key", "")
        llm_url = lumi_cfg.get("llm_base_url", "")
        if llm_key and llm_url and TTSService and not tts_service:
            tts_service = TTSService(
                api_key=llm_key,
                base_url=llm_url,
                sound_device_module=sd,
                numpy_module=np,
                output_device=audio_output_device,
                speed=TTS_SPEED,
            )
            logger.info(
                "TTSService auto-started from lumi config (base_url=%s, output_device=%s, available=%s)",
                llm_url,
                audio_output_device,
                tts_service.available,
            )
        if VoiceService and not voice_service:
            # Read agent name from IDENTITY.md for wake words / Deepgram keyword hints
            agent_name = _read_agent_name(lumi_cfg)
            wake_words = _build_wake_words(agent_name)
            stt_provider = None
            logger.info("STT selection: deepgram_key=%s, DeepgramSTT=%s, AutonomousSTT=%s, agent=%s",
                        bool(dgk), DeepgramSTT is not None, AutonomousSTT is not None, agent_name)
            if dgk and DeepgramSTT:
                dg_keywords = [f"{agent_name}:3"]
                if " " in agent_name:
                    # Also boost space-separated pronunciation variant
                    dg_keywords.append(" ".join(agent_name) + ":2")
                stt_provider = DeepgramSTT(api_key=dgk, keywords=dg_keywords)
            elif llm_key and llm_url and AutonomousSTT:
                stt_model = (lumi_cfg.get("stt_model") or "").strip() or None
                stt_language = (lumi_cfg.get("stt_language") or "").strip() or None
                stt_kwargs = {}
                if stt_model:
                    stt_kwargs["model"] = stt_model
                if stt_language:
                    stt_kwargs["language"] = stt_language
                stt_provider = AutonomousSTT(
                    api_key=llm_key, base_url=llm_url, **stt_kwargs
                )
            if stt_provider:
                voice_service = VoiceService(
                    stt_provider=stt_provider,
                    input_device=audio_input_device,
                    tts_service=tts_service,
                    music_service=music_service,
                    wake_words=wake_words,
                    alsa_device=AUDIO_INPUT_ALSA,
                )
                voice_service.start()
                logger.info("VoiceService auto-started (%s, wake_words=%s)", stt_provider.name, wake_words)
    except FileNotFoundError:
        logger.info(
            f"Lumi config not found at {lumi_config_path}, voice will wait for /voice/start"
        )
    except Exception as e:
        logger.warning(f"Auto-start voice from lumi config failed: {e}")

    # Start music service (uses ffmpeg + ALSA directly, no sounddevice needed)
    if MusicService:
        try:
            music_service = MusicService(on_complete=_on_music_complete)
            # Wire TTS so music pauses during speech
            if tts_service:
                music_service._tts_service = tts_service
            # Wire music to VoiceService so STT pauses during playback
            if voice_service:
                voice_service.set_music_service(music_service)
            logger.info("MusicService started")
        except Exception as e:
            logger.warning(f"MusicService failed to start: {e}")

    # --- Phase 3: Wait for hardware threads, then start hardware-dependent services ---
    for t in hw_threads:
        t.join(timeout=10)

    # Start sensing loop (motion + sound detection → push events to Lumi → OpenClaw)
    # Needs camera_capture + animation_service from hardware threads (now joined above).
    sensing_enabled = os.environ.get("LELAMP_SENSING_ENABLED", "true").lower() in (
        "true",
        "1",
        "yes",
    )
    if SensingService and sensing_enabled:
        try:
            def _presence_restore_aim():
                """Re-aim lamp to active scene direction when presence restores light."""
                if not _active_scene:
                    logger.info("Presence aim restore: no active scene — skipping aim")
                    return
                if not animation_service:
                    logger.warning("Presence aim restore: animation_service not available")
                    return
                preset = SCENE_PRESETS.get(_active_scene)
                aim_dir = preset.get("aim") if preset else None
                if aim_dir:
                    logger.info("Presence aim restore: scene=%s aim=%s", _active_scene, aim_dir)
                    threading.Thread(
                        target=aim_servo,
                        args=(ServoAimRequest(direction=aim_dir),),
                        daemon=True,
                        name=f"presence-aim-{aim_dir}",
                    ).start()
                else:
                    logger.debug("Presence aim restore: scene=%s has no aim — skipping", _active_scene)

            sensing_service = SensingService(
                camera_capture=camera_capture,
                sound_device_module=sd,
                numpy_module=np,
                cv2_module=cv2,
                input_device=AUDIO_SENSING_DEVICE if AUDIO_SENSING_DEVICE is not None else audio_input_device,
                poll_interval=float(os.environ.get("LELAMP_SENSING_INTERVAL", "2.0")),
                rgb_service=rgb_service,
                tts_service=tts_service,
                animation_service=animation_service,
                on_restore_aim=_presence_restore_aim,
            )
            sensing_service.start()
            logger.info("SensingService started")
        except Exception as e:
            logger.warning(f"SensingService failed to start: {e}")
            sensing_service = None

    # Start display (GC9A01 eyes)
    if DisplayService:
        try:
            display_service = DisplayService()
            display_service.start()
            logger.info("DisplayService started")
        except Exception as e:
            logger.warning(f"DisplayService failed to start: {e}")
            display_service = None

    # GPIO17 stop-speaker button — press stops TTS + music immediately
    global _gpio_stop_button
    try:
        from gpiozero import Button as _GpioButton

        def _on_stop_button():
            logger.info("GPIO17 stop button pressed — stopping speaker")
            stop_tts()
            audio_stop()

        _gpio_stop_button = _GpioButton(pin=17, pull_up=True, bounce_time=0.1)
        _gpio_stop_button.when_pressed = _on_stop_button
        logger.info("GPIO stop button ready on pin 17")
    except Exception as e:
        logger.warning(f"GPIO stop button init failed: {e}")

    yield

    # Shutdown
    _stop_current_effect()
    if display_service:
        display_service.stop()
    if music_service and music_service.playing:
        music_service.stop()

    # Stop voice and sensing concurrently — each joins a thread with up to 5s timeout.
    _shutdown_threads = []
    if voice_service:
        _shutdown_threads.append(threading.Thread(target=voice_service.stop, daemon=True))
    if sensing_service:
        _shutdown_threads.append(threading.Thread(target=sensing_service.stop, daemon=True))
    for t in _shutdown_threads:
        t.start()
    for t in _shutdown_threads:
        t.join(timeout=6)

    # Servo shutdown: only stop the animation event loop, do NOT disconnect/release
    # torque so servos hold their current position and prevent gravity drop.
    if animation_service:
        animation_service._running.clear()
        if (
            animation_service._event_thread
            and animation_service._event_thread.is_alive()
        ):
            animation_service._event_thread.join(timeout=3.0)
    if rgb_service:
        rgb_service.stop()
    if camera_capture:
        camera_capture.stop()


app = FastAPI(
    title="LeLamp Hardware Runtime",
    description=(
        "Hardware driver API for Lumi AI Lamp. "
        "Controls servo motors (5-axis Feetech), RGB LEDs (64x WS2812), "
        "camera, audio (mic/speaker), display, and AI voice pipeline. "
        "Lumi Server (Go, port 5000) bridges requests here."
    ),
    version=(Path(__file__).parent / "VERSION_LELAMP").read_text().strip()
    if (Path(__file__).parent / "VERSION_LELAMP").exists()
    else "dev",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {
            "name": "Servo",
            "description": "5-axis Feetech servo motor control. Play pre-recorded animations or send direct joint positions.",
        },
        {
            "name": "LED",
            "description": "WS2812 RGB LED strip (64 LEDs). Set solid color, paint individual pixels, or turn off.",
        },
        {
            "name": "Camera",
            "description": "USB camera for snapshots and MJPEG streaming.",
        },
        {
            "name": "Audio",
            "description": "Low-level audio hardware control. Volume (amixer), raw recording (mic), and test tones. No AI — just hardware.",
        },
        {
            "name": "Emotion",
            "description": "High-level orchestration: single call coordinates servo animation + LED color + display expression for an emotion.",
        },
        {
            "name": "Scene",
            "description": "Lighting scene presets (reading, focus, relax, movie, night, energize). Sets LED color temperature and brightness.",
        },
        {
            "name": "Presence",
            "description": "PIR motion sensor presence detection. Auto-dims lights when user is idle/away.",
        },
        {
            "name": "Display",
            "description": "Round LCD display: pixel art eye expressions (default) or info mode (time, weather, text).",
        },
        {
            "name": "Voice",
            "description": "AI voice pipeline. Deepgram STT (always-on listening) + LLM-based TTS (text-to-speech). Requires API keys.",
        },
        {
            "name": "System",
            "description": "Health checks and system status.",
        },
    ],
)


class ProxyPrefixMiddleware:
    """ASGI middleware: reads X-Forwarded-Prefix and sets root_path before FastAPI processes the request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            prefix = headers.get(b"x-forwarded-prefix", b"").decode()
            if prefix:
                scope["root_path"] = prefix
        await self.app(scope, receive, send)


app.add_middleware(ProxyPrefixMiddleware)


@app.middleware("http")
async def request_logging_middleware(request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.debug(
        "%s %s → %d (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


# --- Request/Response models ---


class ServoRequest(BaseModel):
    recording: str

    model_config = {"json_schema_extra": {"examples": [{"recording": "curious"}]}}


class ServoStateResponse(BaseModel):
    available_recordings: list[str]
    current: Optional[str]

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "available_recordings": [
                        "nod",
                        "curious",
                        "happy_wiggle",
                        "idle",
                        "sad",
                        "excited",
                        "shy",
                        "shock",
                        "listening",
                        "thinking_deep",
                        "laugh",
                        "confused",
                        "sleepy",
                        "greeting",
                        "goodbye",
                        "acknowledge",
                        "stretching",
                        "scanning",
                        "wake_up",
                        "headshake",
                        "music_groove",
                        "music_chill",
                        "music_hype",
                    ],
                    "current": "idle",
                }
            ]
        }
    }


class LEDSolidRequest(BaseModel):
    color: Union[list[int], int]

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"color": [255, 100, 0]},
                {"color": 16711680},
            ]
        }
    }


class LEDPaintRequest(BaseModel):
    colors: list[Union[list[int], int]]

    model_config = {
        "json_schema_extra": {
            "examples": [{"colors": [[255, 0, 0], [0, 255, 0], [0, 0, 255]]}]
        }
    }


class LEDStateResponse(BaseModel):
    led_count: int


class LEDColorResponse(BaseModel):
    led_count: int
    on: bool  # True if any pixel is lit
    color: list[int]  # [R, G, B] — actual pixel 0 from strip
    hex: str  # e.g. "#ff8800"
    brightness: float  # 0.0–1.0 derived from max channel
    effect: Optional[str]  # running effect name, or null
    scene: Optional[str]  # active scene name, or null


class LEDEffectRequest(BaseModel):
    effect: str = Field(
        ...,
        description="Effect name: breathing, candle, rainbow, notification_flash, pulse",
    )
    color: Optional[list[int]] = Field(
        None, description="Base RGB color for the effect (default: current color)"
    )
    speed: float = Field(
        1.0,
        ge=0.1,
        le=5.0,
        description="Speed multiplier (0.1=slow, 1.0=normal, 5.0=fast)",
    )
    duration_ms: Optional[int] = Field(
        None, ge=100, le=60000, description="Auto-stop after duration (null=indefinite)"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"effect": "breathing", "color": [255, 100, 0], "speed": 1.0},
                {"effect": "rainbow", "speed": 0.5},
                {
                    "effect": "notification_flash",
                    "color": [255, 0, 0],
                    "duration_ms": 3000,
                },
            ]
        }
    }


class LEDEffectResponse(BaseModel):
    status: str
    effect: str
    speed: float


class StatusResponse(BaseModel):
    status: str


class VolumeRequest(BaseModel):
    volume: int = Field(..., ge=0, le=100, description="Volume percentage 0-100")

    model_config = {"json_schema_extra": {"examples": [{"volume": 75}]}}


class AudioDevicesResponse(BaseModel):
    output_device: Optional[int]
    input_device: Optional[int]
    available: bool


class CameraInfoResponse(BaseModel):
    available: bool
    width: Optional[int]
    height: Optional[int]


class EmotionRequest(BaseModel):
    emotion: str = Field(
        ...,
        description="Emotion name: curious, happy, sad, thinking, idle, excited, shy, shock",
    )
    intensity: float = Field(0.7, ge=0.0, le=1.0, description="Intensity 0.0-1.0")

    model_config = {
        "json_schema_extra": {"examples": [{"emotion": "curious", "intensity": 0.8}]}
    }


class EmotionResponse(BaseModel):
    status: str
    emotion: str
    servo: Optional[str]
    led: Optional[list[int]]


class SceneRequest(BaseModel):
    scene: str = Field(
        ..., description="Scene name: reading, focus, relax, movie, night, energize"
    )

    model_config = {"json_schema_extra": {"examples": [{"scene": "reading"}]}}


class SceneResponse(BaseModel):
    status: str
    scene: str
    brightness: float
    color: list[int]


class SpeakRequest(BaseModel):
    text: str = Field(
        ..., min_length=1, max_length=2000, description="Text to speak via TTS"
    )

    model_config = {
        "json_schema_extra": {"examples": [{"text": "Hi there! I am Lumi."}]}
    }


class MusicPlayRequest(BaseModel):
    query: str = Field(
        ..., min_length=1, max_length=500, description="Song name or search query"
    )

    model_config = {
        "json_schema_extra": {"examples": [{"query": "Bohemian Rhapsody Queen"}]}
    }


class MusicStatusResponse(BaseModel):
    available: bool
    playing: bool


class VolumeResponse(BaseModel):
    control: str
    volume: int


class ServoPositionResponse(BaseModel):
    positions: dict[str, float]


class ServoDetail(BaseModel):
    id: int
    angle: Optional[float]
    online: bool
    error: Optional[str] = None


class ServoStatusResponse(BaseModel):
    servos: dict[str, ServoDetail]


class ServoAimRequest(BaseModel):
    direction: str = Field(
        ...,
        description="Named direction: desk, wall, left, right, up, down, center, user",
    )
    duration: float = Field(
        2.0, ge=0.0, le=10.0, description="Move duration in seconds (default: 2.0)"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{"direction": "desk"}, {"direction": "left", "duration": 3.0}]
        }
    }


class ServoAimResponse(BaseModel):
    status: str
    direction: str
    positions: dict[str, float]


class SceneListResponse(BaseModel):
    scenes: list[str]
    active: Optional[str]  # currently active scene name, or null


class PresenceResponse(BaseModel):
    state: str
    enabled: bool
    seconds_since_motion: int
    idle_timeout: int
    away_timeout: int


class FaceEnrollRequest(BaseModel):
    image_base64: str = Field(..., description="Base64-encoded image (JPEG or PNG)")
    label: str = Field(..., min_length=1, max_length=64, description="Person name")
    role: str = Field("owner", description="Role: 'owner' or 'friend'")


class FaceEnrollResponse(BaseModel):
    status: str
    label: str
    role: str
    photo_path: str
    enrolled_count: int


class FaceStatusResponse(BaseModel):
    owner_count: int
    owner_names: list[str]


class FacePersonDetail(BaseModel):
    label: str
    role: str
    photo_count: int
    photos: list[str]  # filenames, e.g. ["1711929600000.jpg"]
    mood_days: list[str] = []  # e.g. ["2026-04-09"]
    files: list[str] = []  # all non-photo files, e.g. ["metadata.json"]


class FaceOwnersDetailResponse(BaseModel):
    enrolled_count: int
    persons: list[FacePersonDetail]


class FaceSetRoleRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=64)
    role: str = Field(..., description="Role: 'owner' or 'friend'")


class FaceSetRoleResponse(BaseModel):
    status: str
    label: str
    role: str


class FaceRemoveRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=64)


class FaceRemoveResponse(BaseModel):
    status: str
    label: str
    owner_count: int


class FaceResetResponse(BaseModel):
    status: str
    owner_count: int


class SensingResponse(BaseModel):
    running: bool
    poll_interval: float
    last_event_seconds_ago: dict[str, int]
    perceptions: list[dict]
    presence: dict


class DisplayStateResponse(BaseModel):
    mode: str
    hardware: bool
    available_expressions: list[str]


class VoiceStatusResponse(BaseModel):
    voice_available: bool
    voice_listening: bool
    tts_available: bool
    tts_speaking: bool
    tts_detail: Optional[dict] = None


class HealthResponse(BaseModel):
    status: str
    servo: bool
    led: bool
    camera: bool
    audio: bool
    sensing: bool
    voice: bool
    tts: bool
    music: bool
    display: bool


# --- Servo endpoints ---


@app.get("/servo", response_model=ServoStateResponse, tags=["Servo"])
def get_servo_state():
    """Get available recordings and current animation state."""
    if not animation_service:
        raise HTTPException(503, "Servo not available")
    return {
        "available_recordings": animation_service.get_available_recordings(),
        "current": animation_service._current_recording,
    }


# --- Servo recording upload (CSV) ---
# LeLamp servo recordings are CSV files under ./recordings.
# Each row is a frame; header must include "timestamp" and one or more "<joint>.pos" columns.
_SERVO_JOINT_FIELD_RE = re.compile(r"^[A-Za-z0-9_]+\.pos$")
_MAX_SERVO_RECORDING_UPLOAD_BYTES = 2 * 1024 * 1024  # 2MB
_MAX_SERVO_RECORDING_ROWS = 20000


def _sanitize_recording_name(name: str) -> str:
    name = (name or "").strip()
    # Prevent path traversal and keep names readable.
    name = re.sub(r"[^a-zA-Z0-9_-]+", "_", name)
    name = name.strip("_- ")
    if not name:
        raise ValueError("empty recording name")
    return name[:64]


@app.post("/servo/upload", response_model=StatusResponse, tags=["Servo"])
async def upload_servo_recording(
    file: UploadFile = File(...),
    recording_name: Optional[str] = Form(None),
):
    """Upload a servo recording CSV and make it available in GET /servo.

    Expected CSV format:
    - Header contains "timestamp" plus one or more joint columns ending with ".pos"
      (e.g. "base_pitch.pos", "elbow_pitch.pos", ...).
    - All non-timestamp columns must be numeric floats.
    """
    if not animation_service:
        raise HTTPException(503, "Servo not available")

    orig_filename = file.filename or "recording.csv"
    if orig_filename.lower().endswith(".csv") is False:
        raise HTTPException(400, "upload must be a .csv file")

    rec_name = recording_name or Path(orig_filename).stem
    try:
        rec_name = _sanitize_recording_name(rec_name)
    except ValueError as e:
        raise HTTPException(400, str(e))

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "empty csv")
    if len(content) > _MAX_SERVO_RECORDING_UPLOAD_BYTES:
        raise HTTPException(
            413, f"csv too large (max {_MAX_SERVO_RECORDING_UPLOAD_BYTES} bytes)"
        )

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "csv must be utf-8 text")

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []

    if "timestamp" not in fieldnames:
        raise HTTPException(400, 'missing required column "timestamp"')

    joint_fields = [f for f in fieldnames if f != "timestamp"]
    if not joint_fields:
        raise HTTPException(400, "missing joint columns (expected *.pos fields)")

    invalid_joint_fields = [f for f in joint_fields if not _SERVO_JOINT_FIELD_RE.match(f)]
    if invalid_joint_fields:
        raise HTTPException(
            400, f"invalid joint columns: {invalid_joint_fields}. Expected <name>.pos"
        )

    # If we have robot/joint metadata, reject unknown columns to prevent unsafe dispatch.
    valid_joints = None
    try:
        if (
            animation_service.robot
            and animation_service.robot.bus
            and animation_service.robot.bus.motors
        ):
            valid_joints = {f"{m}.pos" for m in animation_service.robot.bus.motors}
    except Exception:
        valid_joints = None

    if valid_joints is not None:
        unknown = [j for j in joint_fields if j not in valid_joints]
        if unknown:
            raise HTTPException(
                400,
                f"unknown joint columns: {unknown}. Valid: {sorted(valid_joints)}",
            )

    # Parse frames to validate numeric conversion before saving.
    actions: list[dict[str, float]] = []
    for row_idx, row in enumerate(reader):
        if len(actions) >= _MAX_SERVO_RECORDING_ROWS:
            raise HTTPException(
                400, f"too many rows (max {_MAX_SERVO_RECORDING_ROWS})"
            )

        ts_val = row.get("timestamp")
        try:
            _ = float(ts_val)  # validated, but not stored in actions
        except Exception:
            raise HTTPException(400, f"invalid timestamp at row {row_idx + 2}")

        action: dict[str, float] = {}
        for joint in joint_fields:
            v = row.get(joint)
            if v is None or v == "":
                raise HTTPException(400, f"missing value for {joint} at row {row_idx + 2}")
            try:
                action[joint] = float(v)
            except Exception:
                raise HTTPException(400, f"invalid float for {joint} at row {row_idx + 2}")

        actions.append(action)

    recordings_dir = os.path.join(os.path.dirname(__file__), "recordings")
    Path(recordings_dir).mkdir(parents=True, exist_ok=True)
    csv_path = os.path.join(recordings_dir, f"{rec_name}.csv")

    # Save decoded text (preserves original formatting). Ensure trailing newline for consistency.
    with open(csv_path, "w", newline="") as f:
        f.write(text if text.endswith("\n") else text + "\n")

    # Update cache so the new recording can be played immediately.
    try:
        animation_service._recording_cache[rec_name] = actions
    except Exception:
        pass

    return {"status": "ok"}


@app.post("/servo/play", response_model=StatusResponse, tags=["Servo"])
def play_recording(req: ServoRequest):
    """Play a pre-recorded servo animation by name."""
    logger.debug("POST /servo/play recording=%s", req.recording)
    if not animation_service:
        raise HTTPException(503, "Servo not available")
    # Zero-hold mode is active — block external play calls (e.g. ambient micro-movements)
    if getattr(animation_service, "_zero_mode", False):
        logger.debug("servo/play blocked: zero-hold mode active")
        return {"status": "ok"}
    # Restart event loop if it was stopped (e.g. after /servo/release)
    if not animation_service._running.is_set():
        animation_service._running.set()
        animation_service._event_thread = threading.Thread(
            target=animation_service._event_loop, daemon=True
        )
        animation_service._event_thread.start()
        logger.info("Animation event loop restarted via /servo/play")
    t0 = time.perf_counter()
    animation_service.dispatch("play", req.recording)
    logger.debug("servo dispatch took %.1fms", (time.perf_counter() - t0) * 1000)
    return {"status": "ok"}


@app.post("/servo/resume", response_model=StatusResponse, tags=["Servo"])
def resume_servos():
    """Exit zero-hold mode and resume normal animation loop (plays idle).

    Call this after /servo/zero to return to normal operation.
    """
    if not animation_service:
        raise HTTPException(503, "Servo not available")
    animation_service._zero_mode = False
    if not animation_service._running.is_set():
        animation_service._running.set()
        animation_service._event_thread = threading.Thread(
            target=animation_service._event_loop, daemon=True
        )
        animation_service._event_thread.start()
        logger.info("Animation event loop restarted via /servo/resume")
    animation_service.dispatch("play", animation_service.idle_recording)
    logger.info("Servo resumed from zero-hold mode")
    return {"status": "ok"}


class ServoMoveRequest(BaseModel):
    positions: dict[str, float] = Field(
        ...,
        description=(
            "Joint positions (degrees). Ordered by servo ID: "
            "base_yaw.pos (ID 1, min -90 max 90), "
            "base_pitch.pos (ID 2, min -90 max 90), "
            "elbow_pitch.pos (ID 3, min -90 max 90), "
            "wrist_roll.pos (ID 4, min -90 max 90), "
            "wrist_pitch.pos (ID 5, min -90 max 90). "
            "Values are clamped to safe limits automatically."
        ),
    )
    duration: float = Field(
        2.0,
        ge=0.0,
        le=10.0,
        description="Move duration in seconds. 0 = instant jump, >0 = smooth interpolation (default: 2.0)",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "positions": {
                        "base_yaw.pos": 0.0,
                        "base_pitch.pos": 10.0,
                        "elbow_pitch.pos": -5.0,
                        "wrist_roll.pos": 0.0,
                        "wrist_pitch.pos": 0.0,
                    },
                    "_comment": "ID1 base_yaw [-90,90] | ID2 base_pitch [-90,90] | ID3 elbow_pitch [-90,90] | ID4 wrist_roll [-90,90] | ID5 wrist_pitch [-90,90]",
                },
                {
                    "positions": {"base_pitch.pos": 5.0, "elbow_pitch.pos": 5.0},
                    "duration": 3.0,
                },
            ]
        }
    }


class ServoMoveResponse(BaseModel):
    status: str
    requested: dict[str, float]
    clamped: dict[str, float]  # kept for API compat, same as requested
    duration: float
    errors: Optional[dict[str, str]] = None


@app.post("/servo/move", response_model=ServoMoveResponse, tags=["Servo"])
def move_servo(req: ServoMoveRequest):
    """Send joint positions to servo motors with smooth interpolation.

    Uses software interpolation at 30 FPS to smoothly move from current position
    to the target over the given duration. Set duration=0 for instant jump.

    Response includes requested vs clamped positions and any per-joint errors.
    """
    if not animation_service:
        raise HTTPException(503, "Servo not available")
    if not animation_service.robot:
        raise HTTPException(503, "Servo robot not connected")
    # Reject unknown joint names at the API boundary
    valid_joints = {f"{m}.pos" for m in animation_service.robot.bus.motors}
    unknown = [j for j in req.positions if j not in valid_joints]
    if unknown:
        raise HTTPException(
            400, f"Unknown joints: {unknown}. Valid: {sorted(valid_joints)}"
        )

    errors = {}

    try:
        if req.duration > 0:
            animation_service.move_to(req.positions, duration=req.duration)
        else:
            with animation_service.bus_lock:
                animation_service.robot.send_action(req.positions)
    except Exception as e:
        errors["move"] = str(e)

    # Read back actual positions to check errors
    try:
        with animation_service.bus_lock:
            obs = animation_service.robot.get_observation()
        for joint, target in req.positions.items():
            actual = obs.get(joint)
            if actual is not None:
                error = abs(actual - target)
                if error > 5.0:
                    errors[joint] = (
                        f"position error {error:.1f} deg (target={target:.1f}, actual={actual:.1f})"
                    )
    except Exception as e:
        errors["read_position"] = str(e)

    return {
        "status": "error" if "move" in errors else "ok",
        "requested": req.positions,
        "clamped": req.positions,
        "duration": req.duration,
        "errors": errors if errors else None,
    }


@app.post("/servo/zero", response_model=StatusResponse, tags=["Servo"])
def zero_servos():
    """Move all servos to 0° and hold (torque stays ON). Stops the animation loop.

    Useful for calibration and testing range-of-motion from a known reference.
    While in zero-hold mode, /servo/play and other dispatch calls are blocked
    until the animation loop is restarted (call /servo/play to resume).
    """
    if not animation_service:
        raise HTTPException(503, "Servo not available")
    if not animation_service.robot:
        raise HTTPException(503, "Servo robot not connected")
    # Set zero-hold flag before stopping loop — blocks /servo/play from restarting it
    animation_service._zero_mode = True
    # Stop animation loop so move_to has exclusive bus access
    animation_service._running.clear()
    if animation_service._event_thread and animation_service._event_thread.is_alive():
        animation_service._event_thread.join(timeout=3.0)
    # Move all joints to their practical zero (0° where reachable, actual min otherwise).
    # elbow_pitch physical minimum is 24° — sending 0° causes it to stall against the stop.
    zero_pos = {f"{m}.pos": 0.0 for m in animation_service.robot.bus.motors}
    zero_pos["elbow_pitch.pos"] = 0.0
    try:
        animation_service.move_to(zero_pos, duration=2.0)
    except Exception as e:
        logger.warning(f"Could not move to zero: {e}")
    # Sync internal state so next interpolation starts from here
    animation_service._current_state = {k: 0.0 for k in zero_pos}
    return {"status": "ok"}


@app.post("/servo/release", response_model=StatusResponse, tags=["Servo"])
def release_servos():
    """Move servos to idle position then disable torque (safe release).

    First smoothly moves to idle position over 2s to prevent gravity drop,
    then sends Torque_Enable=0 to every servo. If a servo is temporarily
    offline it will fail silently for that servo but still release the rest.
    """
    if not animation_service:
        raise HTTPException(503, "Servo not available")
    if not animation_service.robot:
        raise HTTPException(503, "Servo robot not connected")
    # Stop animation loop so move_to has exclusive bus access
    animation_service._running.clear()
    if animation_service._event_thread and animation_service._event_thread.is_alive():
        animation_service._event_thread.join(timeout=3.0)
    # Move to rest position first to prevent damage from gravity drop
    rest_pos = {
        "base_yaw.pos": 3.0,
        "base_pitch.pos": -30.0,
        "elbow_pitch.pos": 57.0,
        "wrist_roll.pos": 0.0,
        "wrist_pitch.pos": 18.0,
    }
    try:
        animation_service.move_to(rest_pos, duration=2.0)
    except Exception as e:
        logger.warning(f"Could not move to rest before release: {e}")
    bus = animation_service.robot.bus
    errors = {}
    with animation_service.bus_lock:
        for motor_name in bus.motors:
            try:
                bus.write("Torque_Enable", motor_name, 0)
            except Exception as e:
                errors[motor_name] = str(e)
    if errors:
        logger.warning(f"Servo release errors (offline?): {errors}")
    return {"status": "ok"}


@app.get("/servo/position", response_model=ServoPositionResponse, tags=["Servo"])
def get_servo_position():
    """Read current servo joint positions."""
    if not animation_service:
        raise HTTPException(503, "Servo not available")
    if not animation_service.robot:
        raise HTTPException(503, "Servo robot not connected")
    try:
        with animation_service.bus_lock:
            obs = animation_service.robot.get_observation()
        positions = {k: v for k, v in obs.items() if k.endswith(".pos")}
        return {"positions": positions}
    except Exception as e:
        raise HTTPException(500, f"Failed to read position: {e}")


@app.get("/servo/status", response_model=ServoStatusResponse, tags=["Servo"])
def get_servo_status():
    """Ping each servo and return per-joint online/offline status with angle."""
    if not animation_service:
        raise HTTPException(503, "Servo not available")
    if not animation_service.robot:
        raise HTTPException(503, "Servo robot not connected")
    bus = animation_service.robot.bus
    ph = bus.port_handler
    pk = bus.packet_handler
    from scservo_sdk import COMM_SUCCESS

    servos = {}
    with animation_service.bus_lock:
        for motor_name, motor_obj in bus.motors.items():
            key = f"{motor_name}.pos"
            sid = motor_obj.id
            detail = {"id": sid, "angle": None, "online": False, "error": None}
            try:
                _, result, _ = pk.ping(ph, sid)
                if result != COMM_SUCCESS:
                    detail["error"] = "no status packet"
                else:
                    detail["online"] = True
                    try:
                        pos = bus.read("Present_Position", motor_name)
                        detail["angle"] = float(pos)
                    except Exception as e:
                        detail["error"] = f"read failed: {e}"
            except Exception as e:
                detail["error"] = str(e)
            servos[key] = detail
    return {"servos": servos}


@app.get("/servo/aim", tags=["Servo"])
def list_aim_directions():
    """List available aim directions."""
    return {"directions": list(AIM_PRESETS.keys())}


@app.post("/servo/aim", response_model=ServoAimResponse, tags=["Servo"])
def aim_servo(req: ServoAimRequest):
    """Aim the lamp head to a named direction (desk, wall, left, right, up, down, center, user)."""
    if not animation_service:
        raise HTTPException(503, "Servo not available")
    if not animation_service.robot:
        raise HTTPException(503, "Servo robot not connected")

    preset = AIM_PRESETS.get(req.direction)
    if preset is None:
        available = list(AIM_PRESETS.keys())
        raise HTTPException(
            400, f"Unknown direction '{req.direction}'. Available: {available}"
        )

    # Stop the animation event loop so move_to has exclusive bus access.
    # Without this, _continue_playback() fights move_to() every frame via bus_lock,
    # causing the servo to oscillate between aim target and animation frames.
    was_running = animation_service._running.is_set()
    if was_running:
        animation_service._running.clear()
        if animation_service._event_thread and animation_service._event_thread.is_alive():
            animation_service._event_thread.join(timeout=2.0)

    try:
        # Get current positions to preserve joints not being overridden
        with animation_service.bus_lock:
            obs = animation_service.robot.get_observation()
        current = {k: v for k, v in obs.items() if k.endswith(".pos")}

        if req.direction in ("left", "right"):
            # Keep current pose, only rotate yaw
            positions = {**current, "base_yaw.pos": preset["base_yaw.pos"]}
        else:
            # All other directions: use preset posture but keep current yaw
            positions = {**preset, "base_yaw.pos": current.get("base_yaw.pos", preset["base_yaw.pos"])}

        if req.duration > 0:
            animation_service.move_to(positions, duration=req.duration)
        else:
            with animation_service.bus_lock:
                animation_service.robot.send_action(positions)
        return {"status": "ok", "direction": req.direction, "positions": positions}
    except Exception as e:
        raise HTTPException(500, f"Servo aim failed: {e}")
    finally:
        # Restart animation loop. Hold aim position for 5s then smoothly return to idle.
        if was_running and not animation_service._running.is_set():
            hold_pos = animation_service._current_state
            if hold_pos:
                # Use existing hold mechanism: single-frame non-idle recording + _hold_until
                animation_service._current_recording = "__aim_hold__"
                animation_service._current_actions = [hold_pos]
                animation_service._current_frame_index = 0
                animation_service._hold_until = time.time() + 5.0
            animation_service._running.set()
            animation_service._event_thread = threading.Thread(
                target=animation_service._event_loop, daemon=True
            )
            animation_service._event_thread.start()
            if not hold_pos:
                # No state available — fall back to immediate idle
                animation_service.dispatch("play", animation_service.idle_recording)


# --- LED endpoints ---


@app.get("/led", response_model=LEDStateResponse, tags=["LED"])
def get_led_state():
    """Get LED strip info."""
    if not rgb_service:
        raise HTTPException(503, "LED not available")
    return {"led_count": rgb_service.led_count}


@app.get("/led/color", response_model=LEDColorResponse, tags=["LED"])
def get_led_color():
    """Get current LED state: actual pixel color read from strip, effect, scene, brightness."""
    if not rgb_service:
        raise HTTPException(503, "LED not available")
    effect_running = (
        _effect_name is not None
        and _effect_thread is not None
        and _effect_thread.is_alive()
    )
    if effect_running and _effect_base_color:
        # Use the base color the effect was started with — pixel reads are unreliable during animation
        r, g, b = _effect_base_color
    else:
        # Read actual pixel 0 directly from the strip hardware buffer
        raw = rgb_service.strip.getPixelColor(0)
        r = (raw >> 16) & 0xFF
        g = (raw >> 8) & 0xFF
        b = raw & 0xFF
    brightness = round(max(r, g, b) / 255.0, 3)
    is_on = (r, g, b) != (0, 0, 0) or effect_running
    return {
        "led_count": rgb_service.led_count,
        "on": is_on,
        "color": [r, g, b],
        "hex": f"#{r:02x}{g:02x}{b:02x}",
        "brightness": brightness,
        "effect": _effect_name,
        "scene": _active_scene,
    }


@app.post("/led/solid", response_model=StatusResponse, tags=["LED"])
def set_led_solid(req: LEDSolidRequest):
    """Fill entire LED strip with a single color. Color as [R,G,B] or packed int."""
    if not rgb_service:
        raise HTTPException(503, "LED not available")
    global _active_scene
    color = tuple(req.color) if isinstance(req.color, list) else req.color
    rgb_service.dispatch("solid", color)
    _active_scene = None  # manual solid color clears scene context
    # Track for presence restore
    if sensing_service and isinstance(color, tuple):
        sensing_service.presence.set_last_color(color)
    # Save as user LED state so emotion calls can restore it afterward
    _save_user_led_state({"type": "solid", "color": list(color)})
    return {"status": "ok"}


@app.post("/led/paint", response_model=StatusResponse, tags=["LED"])
def set_led_paint(req: LEDPaintRequest):
    """Set individual pixel colors. Array length up to 64 (one per LED)."""
    if not rgb_service:
        raise HTTPException(503, "LED not available")
    colors = [tuple(c) if isinstance(c, list) else c for c in req.colors]
    rgb_service.dispatch("paint", colors)
    return {"status": "ok"}


@app.post("/led/off", response_model=StatusResponse, tags=["LED"])
def turn_off_leds():
    """Turn off all LEDs."""
    if not rgb_service:
        raise HTTPException(503, "LED not available")
    global _active_scene
    _stop_current_effect()
    rgb_service.clear()
    _active_scene = None
    if sensing_service:
        sensing_service.presence.set_last_color((0, 0, 0))
    _save_user_led_state({"type": "off"})
    return {"status": "ok"}


# --- LED effects helpers ---

_effect_thread: Optional[threading.Thread] = None
_effect_stop: threading.Event = threading.Event()
_effect_name: Optional[str] = None
_effect_base_color: Optional[tuple] = None
_active_scene: Optional[str] = None

# --- User LED state tracking (for emotion restore) ---
# Tracks the last LED state explicitly set by the user (solid/effect/scene/off).
# Emotion calls are temporary — after the servo animation finishes, we restore this state.
# None means user has never set anything; restore falls back to idle breathing.
_user_led_state: Optional[dict] = None
_restore_timer: Optional[threading.Timer] = None


def _get_recording_duration(recording_name: str) -> float:
    """Return the playback duration (seconds) of a servo recording CSV.

    Reads the first and last timestamp row. Falls back to 3.0s if the file
    is missing or unreadable — a safe default for most short emotion clips.
    """
    recordings_dir = os.path.join(os.path.dirname(__file__), "recordings")
    path = os.path.join(recordings_dir, f"{recording_name}.csv")
    try:
        with open(path, newline="") as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            rows = list(reader)
        if len(rows) < 2:
            return 3.0
        t0 = float(rows[0][0])
        t1 = float(rows[-1][0])
        return max(0.5, t1 - t0)
    except Exception:
        return 3.0


def _save_user_led_state(state: dict):
    """Save the user-set LED state and cancel any pending emotion restore."""
    global _user_led_state, _restore_timer
    logger.info("User LED state saved: %s", state)
    _user_led_state = state
    if _restore_timer is not None and _restore_timer.is_alive():
        _restore_timer.cancel()
        _restore_timer = None


def _restore_user_led():
    """Restore LED to user state after emotion animation completes.

    Called by a Timer after the servo recording finishes.
    - If user had explicitly set a color/effect/scene: restore it.
    - If LED was off or never set: leave emotion color in place (it's better
      than going dark when the lamp wakes up from sleep/off).
    """
    global _restore_timer
    _restore_timer = None

    if not rgb_service:
        return

    state = _user_led_state
    if state is None or state.get("type") == "off":
        logger.info("LED restore: no active user state (state=%s) — keeping emotion color", state)
        return

    stype = state.get("type")
    logger.info("LED restore: restoring user state type=%s", stype)
    try:
        if stype == "solid":
            _stop_current_effect()
            rgb_service.dispatch("solid", tuple(state["color"]))
            logger.info("LED restore: solid color=%s", state["color"])
        elif stype == "effect":
            _stop_current_effect()
            global _effect_thread, _effect_name, _effect_base_color
            color = tuple(state["color"])
            speed = state.get("speed", 1.0)
            effect = state["effect"]
            _effect_stop.clear()
            _effect_name = effect
            _effect_base_color = color
            _effect_thread = threading.Thread(
                target=_run_effect,
                args=(effect, color, speed, None, _effect_stop, rgb_service),
                daemon=True,
                name=f"led-restore-{effect}",
            )
            _effect_thread.start()
            logger.info("LED restore: effect=%s color=%s speed=%s", effect, color, speed)
        elif stype == "scene":
            preset = SCENE_PRESETS.get(state["scene"])
            if preset:
                _stop_current_effect()
                scaled = tuple(int(c * preset["brightness"]) for c in preset["color"])
                rgb_service.dispatch("solid", scaled)
                aim_dir = preset.get("aim")
                logger.info("LED restore: scene=%s color=%s aim=%s", state["scene"], scaled, aim_dir)
                if aim_dir and animation_service:
                    threading.Thread(
                        target=aim_servo,
                        args=(ServoAimRequest(direction=aim_dir),),
                        daemon=True,
                        name=f"restore-aim-{aim_dir}",
                    ).start()
            else:
                logger.warning("LED restore: scene=%s not found in SCENE_PRESETS", state["scene"])
    except Exception as e:
        logger.warning("LED restore failed: %s", e)


def _schedule_led_restore(delay_s: float):
    """Schedule _restore_user_led to run after delay_s seconds.

    Cancels any previously scheduled restore so overlapping emotions don't
    fire multiple restores.
    """
    global _restore_timer
    if _restore_timer is not None and _restore_timer.is_alive():
        _restore_timer.cancel()
    t = threading.Timer(delay_s, _restore_user_led)
    t.daemon = True
    t.start()
    _restore_timer = t


def _stop_current_effect():
    """Signal the running effect thread to stop and wait for it."""
    global _effect_thread, _effect_name, _effect_base_color
    if _effect_thread and _effect_thread.is_alive():
        _effect_stop.set()
        _effect_thread.join(timeout=2.0)
    _effect_thread = None
    _effect_name = None
    _effect_base_color = None


def _run_effect(
    effect: str,
    color: tuple,
    speed: float,
    duration_ms: Optional[int],
    stop_event: threading.Event,
    svc,
):
    """Dispatch to the appropriate effect loop. Runs in a background thread."""
    deadline = None
    if duration_ms is not None:
        deadline = time.monotonic() + duration_ms / 1000.0

    try:
        if effect == "breathing":
            _effect_breathing(color, speed, deadline, stop_event, svc)
        elif effect == "candle":
            _effect_candle(color, speed, deadline, stop_event, svc)
        elif effect == "rainbow":
            _effect_rainbow(speed, deadline, stop_event, svc)
        elif effect == "notification_flash":
            _effect_notification_flash(color, speed, stop_event, svc)
        elif effect == "pulse":
            _effect_pulse(color, speed, deadline, stop_event, svc)
    except Exception as e:
        logger.warning(f"LED effect '{effect}' error: {e}")


def _is_done(deadline: Optional[float], stop_event: threading.Event) -> bool:
    """Check if the effect should stop."""
    if stop_event.is_set():
        return True
    if deadline is not None and time.monotonic() >= deadline:
        return True
    return False


def _effect_breathing(
    color: tuple,
    speed: float,
    deadline: Optional[float],
    stop_event: threading.Event,
    svc,
):
    """Fade in/out with the given color."""
    step_delay = 0.03 / speed
    while not _is_done(deadline, stop_event):
        # Full cycle: 0 -> 1 -> 0 over ~3s at speed=1
        for i in range(100):
            if _is_done(deadline, stop_event):
                return
            brightness = math.sin(math.pi * i / 100.0)
            scaled = tuple(int(c * brightness) for c in color)
            svc.dispatch("solid", scaled)
            time.sleep(step_delay)


def _effect_candle(
    color: tuple,
    speed: float,
    deadline: Optional[float],
    stop_event: threading.Event,
    svc,
):
    """Warm flicker effect with randomized warm tones."""
    step_delay = 0.05 / speed
    led_count = getattr(svc, "led_count", 64)
    while not _is_done(deadline, stop_event):
        pixels = []
        for _ in range(led_count):
            flicker = random.uniform(0.4, 1.0)
            # Warm tone bias: keep red high, vary green, minimal blue
            r = int(min(255, color[0] * flicker + random.randint(0, 20)))
            g = int(min(255, color[1] * flicker * random.uniform(0.6, 0.9)))
            b = int(min(255, color[2] * flicker * 0.3))
            pixels.append((r, g, b))
        svc.dispatch("paint", pixels)
        time.sleep(step_delay)


def _effect_rainbow(
    speed: float, deadline: Optional[float], stop_event: threading.Event, svc
):
    """Cycle through hue spectrum across all pixels."""
    step_delay = 0.03 / speed
    led_count = getattr(svc, "led_count", 64)
    offset = 0.0
    while not _is_done(deadline, stop_event):
        pixels = []
        for i in range(led_count):
            hue = (offset + i / led_count) % 1.0
            r, g, b = _hsv_to_rgb(hue, 1.0, 1.0)
            pixels.append((r, g, b))
        svc.dispatch("paint", pixels)
        offset += 0.01
        time.sleep(step_delay)


def _effect_notification_flash(
    color: tuple, speed: float, stop_event: threading.Event, svc
):
    """3 quick flashes then stop."""
    flash_on = 0.15 / speed
    flash_off = 0.1 / speed
    for _ in range(3):
        if stop_event.is_set():
            return
        svc.dispatch("solid", color)
        time.sleep(flash_on)
        if stop_event.is_set():
            return
        svc.dispatch("solid", (0, 0, 0))
        time.sleep(flash_off)


def _effect_pulse(
    color: tuple,
    speed: float,
    deadline: Optional[float],
    stop_event: threading.Event,
    svc,
):
    """Single color pulse outward from center."""
    step_delay = 0.04 / speed
    led_count = getattr(svc, "led_count", 64)
    center = led_count // 2
    max_radius = center + 1
    while not _is_done(deadline, stop_event):
        for radius in range(max_radius + 1):
            if _is_done(deadline, stop_event):
                return
            pixels = [(0, 0, 0)] * led_count
            for i in range(led_count):
                dist = abs(i - center)
                if dist <= radius:
                    # Brightness falls off with distance from the wavefront
                    falloff = max(
                        0.0, 1.0 - abs(dist - radius) / max(max_radius * 0.3, 1)
                    )
                    pixels[i] = tuple(int(c * falloff) for c in color)
            svc.dispatch("paint", pixels)
            time.sleep(step_delay)


def _hsv_to_rgb(h: float, s: float, v: float) -> tuple:
    """Convert HSV (0-1 range) to RGB (0-255 ints)."""
    if s == 0.0:
        val = int(v * 255)
        return (val, val, val)
    i = int(h * 6.0)
    f = (h * 6.0) - i
    p = int(255 * v * (1.0 - s))
    q = int(255 * v * (1.0 - s * f))
    t = int(255 * v * (1.0 - s * (1.0 - f)))
    v_int = int(255 * v)
    i %= 6
    if i == 0:
        return (v_int, t, p)
    if i == 1:
        return (q, v_int, p)
    if i == 2:
        return (p, v_int, t)
    if i == 3:
        return (p, q, v_int)
    if i == 4:
        return (t, p, v_int)
    return (v_int, p, q)


# --- LED effect endpoints ---


@app.post("/led/effect", response_model=LEDEffectResponse, tags=["LED"])
def start_led_effect(req: LEDEffectRequest):
    """Start a LED effect (breathing, candle, rainbow, notification_flash, pulse).

    Any previously running effect is stopped first. Effects run in a background
    thread and update LEDs continuously until stopped or duration expires.
    """
    global _effect_thread, _effect_name, _effect_base_color
    if not rgb_service:
        raise HTTPException(503, "LED not available")
    if req.effect not in VALID_LED_EFFECTS:
        raise HTTPException(
            400, f"Unknown effect '{req.effect}'. Available: {VALID_LED_EFFECTS}"
        )

    # Stop any running effect
    global _active_scene
    _stop_current_effect()
    _active_scene = None  # explicit effect replaces any scene context

    # Default color: warm white if none provided
    base_color = tuple(req.color) if req.color else (255, 180, 100)

    _effect_stop.clear()
    _effect_name = req.effect
    _effect_base_color = base_color
    _effect_thread = threading.Thread(
        target=_run_effect,
        args=(
            req.effect,
            base_color,
            req.speed,
            req.duration_ms,
            _effect_stop,
            rgb_service,
        ),
        daemon=True,
        name=f"led-effect-{req.effect}",
    )
    _effect_thread.start()
    logger.info(
        "LED effect started: %s (speed=%.1f, duration=%s)",
        req.effect,
        req.speed,
        req.duration_ms,
    )

    # Save as user LED state so emotion calls can restore it afterward
    _save_user_led_state(
        {
            "type": "effect",
            "effect": req.effect,
            "color": list(base_color),
            "speed": req.speed,
        }
    )

    return {"status": "ok", "effect": req.effect, "speed": req.speed}


@app.post("/led/effect/stop", response_model=StatusResponse, tags=["LED"])
def stop_led_effect():
    """Stop the currently running LED effect."""
    if not rgb_service:
        raise HTTPException(503, "LED not available")
    _stop_current_effect()
    return {"status": "ok"}


# --- Camera endpoints ---


@app.get("/camera", response_model=CameraInfoResponse, tags=["Camera"])
def get_camera_info():
    """Get camera availability and resolution."""
    if not camera_capture or cv2 is None:
        return {"available": False, "width": None, "height": None}

    return {
        "available": True,
        "width": CAMERA_WIDTH,
        "height": CAMERA_HEIGHT,
    }


_SNAPSHOT_DIR = "/tmp/lumi-snapshots"
_SNAPSHOT_MAX = 20
_snapshot_paths: list = []


@app.get("/camera/snapshot", tags=["Camera"])
def camera_snapshot(save: bool = False):
    """Capture a single JPEG frame from the camera (freezes servos for stability).

    When save=true, writes the frame to a timestamped file and returns
    JSON ``{"path": "/tmp/lumi-snapshots/snap_<ms>.jpg"}`` instead of raw bytes.
    Old files are evicted when the count exceeds _SNAPSHOT_MAX.
    """
    if not camera_capture or cv2 is None:
        raise HTTPException(503, "Camera not available")

    # Freeze servos so camera stays still during capture
    if animation_service:
        animation_service.freeze()
        time.sleep(0.3)

    frame = camera_capture.last_frame

    if animation_service:
        animation_service.unfreeze()

    if frame is None:
        raise HTTPException(500, "Failed to capture frame")
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])

    if not save:
        return Response(content=buf.tobytes(), media_type="image/jpeg")

    # save=true: write to timestamped file, return path
    os.makedirs(_SNAPSHOT_DIR, exist_ok=True)
    filename = f"snap_{int(time.time() * 1000)}.jpg"
    filepath = os.path.join(_SNAPSHOT_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(buf.tobytes())
    _snapshot_paths.append(filepath)

    # Evict oldest files
    while len(_snapshot_paths) > _SNAPSHOT_MAX:
        oldest = _snapshot_paths.pop(0)
        try:
            os.remove(oldest)
        except OSError:
            pass

    return JSONResponse({"path": filepath})


@app.get("/camera/stream", tags=["Camera"])
def camera_stream():
    """MJPEG stream from the camera (multipart/x-mixed-replace)."""
    if not camera_capture or cv2 is None:
        raise HTTPException(503, "Camera not available")

    # MJPEG is CPU/bandwidth heavy: encode in this endpoint at a controlled rate
    # and downscale frames for smoother live viewing.
    # These defaults can be tuned via env vars.
    stream_fps = float(os.environ.get("LELAMP_CAMERA_STREAM_FPS", "10"))
    stream_width = int(os.environ.get("LELAMP_CAMERA_STREAM_WIDTH", "320"))
    stream_quality = int(os.environ.get("LELAMP_CAMERA_STREAM_JPEG_QUALITY", "65"))
    min_interval_s = 1.0 / stream_fps if stream_fps > 0 else 0.0

    def generate():
        last_sent_s = 0.0
        while True:
            # Throttle encoding to avoid pegging CPU and causing buffering on the browser side.
            if min_interval_s > 0:
                now_s = time.time()
                elapsed_s = now_s - last_sent_s
                if elapsed_s < min_interval_s:
                    time.sleep(min(0.01, min_interval_s - elapsed_s))
                    continue

            frame = camera_capture.last_frame
            if frame is None:
                time.sleep(0.05)
                continue

            # Downscale for streaming bandwidth while preserving aspect ratio.
            if stream_width and frame.shape[1] > stream_width:
                scale = stream_width / float(frame.shape[1])
                frame = cv2.resize(
                    frame,
                    None,
                    fx=scale,
                    fy=scale,
                    interpolation=cv2.INTER_AREA,
                )

            _, buf = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, int(stream_quality)]
            )
            last_sent_s = time.time()
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
            )

    return StreamingResponse(
        generate(), media_type="multipart/x-mixed-replace; boundary=frame"
    )


# --- Audio endpoints ---


@app.get("/audio", response_model=AudioDevicesResponse, tags=["Audio"])
def get_audio_info():
    """Get audio device availability."""
    return {
        "output_device": audio_output_device,
        "input_device": audio_input_device,
        "available": audio_output_device is not None or audio_input_device is not None,
    }


def _audio_output_card() -> Optional[int]:
    """Derive ALSA card index from LELAMP_AUDIO_OUTPUT_ALSA (e.g. 'plughw:3,0' → 3)."""
    if AUDIO_OUTPUT_ALSA:
        import re
        m = re.search(r":(\d+)", AUDIO_OUTPUT_ALSA)
        if m:
            return int(m.group(1))
    return None


def _detect_playback_controls() -> tuple[list[str], Optional[int]]:
    """Return (playback_control_names, card_index) from amixer.

    Uses LELAMP_AUDIO_OUTPUT_ALSA card if set, otherwise tries default.
    Filters out capture-only controls (Capture, Mic, AGC).
    """
    import re
    card = _audio_output_card()
    cmd = ["amixer", "-c", str(card), "scontrols"] if card is not None else ["amixer", "scontrols"]
    _CAPTURE_KEYWORDS = {"capture", "mic", "gain control", "agc", "auto gain"}
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            all_controls = re.findall(r"Simple mixer control '([^']+)'", result.stdout)
            playback = [c for c in all_controls if not any(k in c.lower() for k in _CAPTURE_KEYWORDS)]
            return playback, card
    except Exception:
        pass
    return [], card


@app.post("/audio/volume", response_model=StatusResponse, tags=["Audio"])
def set_volume(req: VolumeRequest):
    """Set system speaker volume (0-100%). Uses amixer on the Pi."""
    controls, card = _detect_playback_controls()
    if not controls:
        raise HTTPException(503, "No audio mixer controls found")
    cmd_prefix = ["amixer", "-c", str(card)] if card is not None else ["amixer"]
    for ctrl in controls:
        try:
            subprocess.run(
                [*cmd_prefix, "sset", ctrl, f"{req.volume}%"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            pass
    return {"status": "ok"}


@app.get("/audio/volume", response_model=VolumeResponse, tags=["Audio"])
def get_volume():
    """Get current speaker volume from amixer."""
    import re

    controls, card = _detect_playback_controls()
    cmd_prefix = ["amixer", "-c", str(card)] if card is not None else ["amixer"]
    for ctrl in controls:
        try:
            result = subprocess.run(
                [*cmd_prefix, "sget", ctrl],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                match = re.search(r"\[(\d+)%\]", result.stdout)
                if match:
                    return {"control": ctrl, "volume": int(match.group(1))}
        except Exception:
            continue
    raise HTTPException(503, "Audio volume control not available")


@app.post("/audio/play-tone", response_model=StatusResponse, tags=["Audio"])
def play_tone(frequency: int = 440, duration_ms: int = 500):
    """Play a test tone through the speaker."""
    if not sd or not np:
        raise HTTPException(503, "Audio not available")
    if audio_output_device is None:
        raise HTTPException(503, "No output audio device found")
    # Use device native rate (48kHz for CD002-AUDIO on Pi 5, 44.1/48kHz for Seeed on Pi 4)
    dev_info = sd.query_devices(audio_output_device)
    sample_rate = int(dev_info["default_samplerate"])
    t = np.linspace(
        0, duration_ms / 1000, int(sample_rate * duration_ms / 1000), endpoint=False
    )
    tone = 0.5 * np.sin(2 * np.pi * frequency * t).astype(np.float32)
    sd.play(tone, samplerate=sample_rate, device=audio_output_device)
    return {"status": "ok"}


@app.post("/audio/record", tags=["Audio"])
def record_audio(duration_ms: int = 3000):
    """Record audio from the microphone. Returns WAV bytes."""
    if not sd or not np:
        raise HTTPException(503, "Audio not available")
    if audio_input_device is None:
        raise HTTPException(503, "No input audio device found")
    import wave

    dev_info = sd.query_devices(audio_input_device)
    sample_rate = int(dev_info["default_samplerate"])
    channels = 1
    frames = int(sample_rate * duration_ms / 1000)
    recording = sd.rec(
        frames,
        samplerate=sample_rate,
        channels=channels,
        dtype="int16",
        device=audio_input_device,
    )
    sd.wait()

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(recording.tobytes())
    buf.seek(0)
    return Response(content=buf.read(), media_type="audio/wav")


# --- Emotion endpoint (orchestrates servo + LED + audio) ---


def _apply_emotion_led_display(emotion: str, intensity: float = 1.0) -> Optional[list]:
    """Apply LED effect + display expression for an emotion. Returns scaled LED color or None."""
    preset = EMOTION_PRESETS.get(emotion)
    if not preset:
        return None
    led_color = None
    # Idle LED (cyan breathing) is the ambient fallback — only apply when the user has not
    # explicitly set a scene/color/effect. If a user state exists, skip the LED change so
    # the user's environment lighting is preserved; the servo still plays normally.
    if emotion == "idle" and _user_led_state is not None:
        if display_service:
            try:
                display_service.set_expression(emotion)
            except Exception as e:
                logger.warning("Emotion display failed: %s", e)
        return None
    if rgb_service and preset.get("color"):
        scaled = [int(c * intensity) for c in preset["color"]]
        try:
            if preset.get("effect"):
                _stop_current_effect()
                global _effect_thread, _effect_name, _effect_base_color
                _effect_stop.clear()
                _effect_name = preset["effect"]
                _effect_base_color = tuple(
                    scaled
                )  # used by /led/color for stable color readback during animation
                _effect_thread = threading.Thread(
                    target=_run_effect,
                    args=(
                        preset["effect"],
                        tuple(scaled),
                        preset.get("speed", 1.0),
                        None,
                        _effect_stop,
                        rgb_service,
                    ),
                    daemon=True,
                    name=f"led-emotion-{emotion}",
                )
                _effect_thread.start()
            else:
                rgb_service.dispatch("solid", tuple(scaled))
            led_color = scaled
            if sensing_service:
                sensing_service.presence.set_last_color(tuple(scaled))
        except Exception as e:
            logger.warning("Emotion LED failed: %s", e)
    if display_service:
        try:
            display_service.set_expression(emotion)
        except Exception as e:
            logger.warning("Emotion display failed: %s", e)
    return led_color


@app.post("/emotion", response_model=EmotionResponse, tags=["Emotion"])
def express_emotion(req: EmotionRequest):
    """Express an emotion by coordinating servo animation + LED color simultaneously.

    This is the key differentiator — a single call produces a coordinated,
    expressive response instead of requiring separate servo + LED + audio calls.

    Intensity scales the LED brightness (0.0 = dim, 1.0 = full).
    """
    preset = EMOTION_PRESETS.get(req.emotion)
    if not preset:
        available = list(EMOTION_PRESETS.keys())
        raise HTTPException(
            400, f"Unknown emotion '{req.emotion}'. Available: {available}"
        )

    logger.info("POST /emotion: emotion=%s intensity=%s user_state=%s",
                req.emotion, req.intensity,
                _user_led_state.get("type") if _user_led_state else None)

    servo_played = None

    # Play servo animation
    if animation_service and preset.get("servo"):
        try:
            animation_service.dispatch("play", preset["servo"])
            servo_played = preset["servo"]
        except Exception as e:
            logger.warning(f"Emotion servo failed: {e}")

    led_color = _apply_emotion_led_display(req.emotion, req.intensity)

    # Schedule LED restore after the servo animation finishes.
    # Emotion LED is temporary (Lumi's reaction) — after the animation, restore
    # the user's environment lighting. If user never set anything, fade to idle breathing.
    #
    # Special cases:
    #   idle    — looping animation with no natural end; it IS the resting state,
    #             so no restore is scheduled (ambient will take over naturally).
    #   shock   — notification_flash auto-stops after ~1.5s (3 flashes); restore
    #             at 2.0s so LED doesn't linger in a blank post-flash state while
    #             the servo finishes its 4.8s recovery animation.
    if req.emotion == "idle":
        pass  # no restore — idle is ambient resting state
    elif req.emotion == "shock":
        _schedule_led_restore(2.0)
        logger.info("Emotion: shock — LED restore scheduled in 2.0s")
    else:
        servo_name = preset.get("servo", "")
        restore_delay = _get_recording_duration(servo_name) + 0.5 if servo_name else 3.5
        logger.info("Emotion: %s — LED restore scheduled in %.1fs (servo=%s)", req.emotion, restore_delay, servo_name)
        _schedule_led_restore(restore_delay)

    return {
        "status": "ok",
        "emotion": req.emotion,
        "servo": servo_played,
        "led": led_color,
    }


# --- Scene endpoints ---


@app.get("/scene", response_model=SceneListResponse, tags=["Scene"])
def list_scenes():
    """List all available lighting scene presets."""
    return {"scenes": list(SCENE_PRESETS.keys()), "active": _active_scene}


@app.post("/scene", response_model=SceneResponse, tags=["Scene"])
def activate_scene(req: SceneRequest):
    """Activate a lighting scene preset. Sets LED color + aims lamp head for the scene."""
    preset = SCENE_PRESETS.get(req.scene)
    if not preset:
        available = list(SCENE_PRESETS.keys())
        raise HTTPException(400, f"Unknown scene '{req.scene}'. Available: {available}")

    if not rgb_service:
        raise HTTPException(503, "LED not available")

    global _active_scene
    _stop_current_effect()  # stop any running effect before applying scene solid
    base = preset["color"]
    brightness = preset["brightness"]
    scaled = [int(c * brightness) for c in base]
    try:
        rgb_service.dispatch("solid", tuple(scaled))
    except Exception as e:
        raise HTTPException(500, f"Failed to set scene: {e}")

    _active_scene = req.scene
    # Track last color for presence restore
    if sensing_service:
        sensing_service.presence.set_last_color(tuple(scaled))
    # Save as user LED state so emotion calls can restore it afterward
    _save_user_led_state({"type": "scene", "scene": req.scene})

    # Aim lamp head for the scene (non-blocking — runs in background thread)
    aim_dir = preset.get("aim")
    if aim_dir and animation_service:
        threading.Thread(
            target=aim_servo,
            args=(ServoAimRequest(direction=aim_dir),),
            daemon=True,
            name=f"scene-aim-{aim_dir}",
        ).start()

    return {
        "status": "ok",
        "scene": req.scene,
        "brightness": brightness,
        "color": scaled,
        "aim": aim_dir,
    }


# --- Sensing endpoints ---


@app.get("/sensing", response_model=SensingResponse, tags=["Sensing"])
def get_sensing_state():
    """Get perception state: motion, face recognition, light level, presence, and event cooldowns."""
    if not sensing_service:
        raise HTTPException(503, "Sensing not available")
    return sensing_service.to_dict()


# --- Presence endpoints ---


@app.get("/presence", response_model=PresenceResponse, tags=["Presence"])
def get_presence():
    """Get current presence state (present/idle/away) and config."""
    if not sensing_service:
        return {
            "state": "unknown",
            "enabled": False,
            "seconds_since_motion": 0,
            "idle_timeout": 0,
            "away_timeout": 0,
        }
    return sensing_service.presence.to_dict()


@app.post("/presence/enable", response_model=StatusResponse, tags=["Presence"])
def enable_presence():
    """Enable automatic presence-based light control."""
    if not sensing_service:
        raise HTTPException(503, "Sensing not available")
    sensing_service.presence.enable()
    return {"status": "ok"}


@app.post("/presence/disable", response_model=StatusResponse, tags=["Presence"])
def disable_presence():
    """Disable automatic presence-based light control (manual mode)."""
    if not sensing_service:
        raise HTTPException(503, "Sensing not available")
    sensing_service.presence.disable()
    return {"status": "ok"}


def _require_face_recognizer():
    """Return FaceRecognizer or raise 503 if sensing/camera/InsightFace is unavailable."""
    if not sensing_service or FaceRecognizer is None:
        raise HTTPException(503, "Sensing not available")
    fr = getattr(sensing_service, "_face_recognizer", None)
    if fr is None:
        raise HTTPException(503, "Face recognition not available (no camera)")
    return fr


@app.post("/face/enroll", response_model=FaceEnrollResponse, tags=["Face"])
def face_enroll(req: FaceEnrollRequest):
    """Save a JPEG photo, train embeddings, and persist under users/{label}/."""
    fr = _require_face_recognizer()
    role = req.role if req.role in ("owner", "friend") else "owner"
    try:
        raw = base64.b64decode(req.image_base64)
    except Exception as exc:
        raise HTTPException(400, "invalid base64") from exc
    if not raw:
        raise HTTPException(400, "empty image")
    try:
        path = fr.enroll_from_bytes(raw, req.label, role=role)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    norm = FaceRecognizer.normalize_label(req.label)
    return FaceEnrollResponse(
        status="ok",
        label=norm,
        role=role,
        photo_path=path,
        enrolled_count=fr.owner_count(),
    )


@app.get("/face/status", response_model=FaceStatusResponse, tags=["Face"])
def face_status():
    """List enrolled owners (unique labels) and count."""
    fr = _require_face_recognizer()
    return FaceStatusResponse(
        owner_count=fr.owner_count(),
        owner_names=fr.owner_names(),
    )


@app.get("/face/owners", response_model=FaceOwnersDetailResponse, tags=["Face"])
def face_owners_detail():
    """List enrolled persons (owners and friends) with photo filenames."""
    fr = _require_face_recognizer()
    from lelamp.service.sensing.perceptions.facerecognizer import USERS_DIR, FaceRecognizer as FR

    persons: list[FacePersonDetail] = []
    if USERS_DIR.is_dir():
        img_exts = {".jpg", ".jpeg", ".png", ".bmp"}
        for d in sorted(USERS_DIR.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            photos = sorted(f.name for f in d.iterdir() if f.is_file() and f.suffix.lower() in img_exts)
            other_files = sorted(f.name for f in d.iterdir() if f.is_file() and f.suffix.lower() not in img_exts)
            mood_dir = d / "mood"
            mood_days = sorted(f.stem for f in mood_dir.iterdir() if f.suffix == ".jsonl") if mood_dir.is_dir() else []
            role = FR._read_role(d)
            persons.append(
                FacePersonDetail(
                    label=d.name,
                    role=role,
                    photo_count=len(photos),
                    photos=photos,
                    mood_days=mood_days,
                    files=other_files,
                )
            )
    return FaceOwnersDetailResponse(enrolled_count=len(persons), persons=persons)


@app.get("/face/photo/{label}/{filename}", tags=["Face"])
def face_photo(label: str, filename: str):
    """Serve an owner photo as JPEG."""
    from lelamp.service.sensing.perceptions.facerecognizer import USERS_DIR

    norm = FaceRecognizer.normalize_label(label)
    path = (USERS_DIR / norm / filename).resolve()
    # Prevent path traversal
    if not str(path).startswith(str(USERS_DIR.resolve())):
        raise HTTPException(400, "invalid path")
    if not path.is_file():
        raise HTTPException(404, "photo not found")
    return Response(content=path.read_bytes(), media_type="image/jpeg")


@app.get("/face/file/{label}/{filepath:path}", tags=["Face"])
def face_file(label: str, filepath: str):
    """Serve any text file from a user's directory (metadata, mood logs, etc.)."""
    from lelamp.service.sensing.perceptions.facerecognizer import USERS_DIR

    norm = FaceRecognizer.normalize_label(label)
    path = (USERS_DIR / norm / filepath).resolve()
    if not str(path).startswith(str(USERS_DIR.resolve())):
        raise HTTPException(400, "invalid path")
    if not path.is_file():
        raise HTTPException(404, "file not found")
    mime = "application/json" if path.suffix in (".json", ".jsonl") else "text/plain"
    return Response(content=path.read_bytes(), media_type=mime)


@app.post("/face/set-role", response_model=FaceSetRoleResponse, tags=["Face"])
def face_set_role(req: FaceSetRoleRequest):
    """Change a person's role without re-enrolling."""
    from lelamp.service.sensing.perceptions.facerecognizer import USERS_DIR, FaceRecognizer
    fr = _require_face_recognizer()
    norm = FaceRecognizer.normalize_label(req.label)
    person_dir = USERS_DIR / norm
    if not person_dir.is_dir():
        raise HTTPException(404, f"person '{norm}' not found")
    if req.role not in FaceRecognizer.KNOWN_ROLES:
        raise HTTPException(400, f"role must be one of {FaceRecognizer.KNOWN_ROLES}")
    FaceRecognizer._write_role(person_dir, req.role)
    return FaceSetRoleResponse(status="ok", label=norm, role=req.role)


@app.post("/face/remove", response_model=FaceRemoveResponse, tags=["Face"])
def face_remove(req: FaceRemoveRequest):
    """Remove one owner's saved photos and re-train from disk."""
    fr = _require_face_recognizer()
    norm = FaceRecognizer.normalize_label(req.label)
    if not fr.remove_owner(req.label):
        raise HTTPException(404, "owner not found")
    return FaceRemoveResponse(
        status="ok",
        label=norm,
        owner_count=fr.owner_count(),
    )


@app.post("/face/reset", response_model=FaceResetResponse, tags=["Face"])
def face_reset():
    """Clear all owner embeddings and delete all owner photos on disk."""
    fr = _require_face_recognizer()
    fr.reset_owners()
    return FaceResetResponse(status="ok", owner_count=0)


@app.get("/face/stranger-stats", tags=["Face"])
def face_stranger_stats():
    """Return visit counts for all tracked stranger IDs."""
    fr = _require_face_recognizer()
    return fr.stranger_stats()


# --- Display endpoints ---


class DisplayEyesRequest(BaseModel):
    expression: str = Field(
        ...,
        description="Expression: neutral, happy, sad, curious, thinking, excited, shy, shock, sleepy, angry, love",
    )
    pupil_x: float = Field(
        0.0, ge=-1.0, le=1.0, description="Pupil X: -1.0 (left) to 1.0 (right)"
    )
    pupil_y: float = Field(
        0.0, ge=-1.0, le=1.0, description="Pupil Y: -1.0 (up) to 1.0 (down)"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{"expression": "happy", "pupil_x": 0.0, "pupil_y": 0.0}]
        }
    }


class DisplayInfoRequest(BaseModel):
    text: str = Field(
        ..., min_length=1, max_length=20, description="Main text (short, e.g. '14:30')"
    )
    subtitle: str = Field(
        "", max_length=40, description="Subtitle (e.g. 'Good afternoon')"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{"text": "14:30", "subtitle": "Good afternoon"}]
        }
    }


@app.get("/display", response_model=DisplayStateResponse, tags=["Display"])
def get_display_state():
    """Get current display state (mode, expression, hardware availability)."""
    if not display_service:
        return {"mode": "unavailable", "hardware": False, "available_expressions": []}
    return display_service.get_state()


@app.post("/display/eyes", response_model=StatusResponse, tags=["Display"])
def set_display_eyes(req: DisplayEyesRequest):
    """Set eye expression on the round LCD display."""
    if not display_service:
        raise HTTPException(503, "Display not available")
    display_service.set_expression(req.expression, req.pupil_x, req.pupil_y)
    return {"status": "ok"}


@app.post("/display/info", response_model=StatusResponse, tags=["Display"])
def set_display_info(req: DisplayInfoRequest):
    """Switch display to info mode with text content (time, weather, etc.)."""
    if not display_service:
        raise HTTPException(503, "Display not available")
    display_service.set_info(req.text, req.subtitle)
    return {"status": "ok"}


@app.post("/display/eyes-mode", response_model=StatusResponse, tags=["Display"])
def switch_to_eyes_mode():
    """Switch display back to eyes mode (default)."""
    if not display_service:
        raise HTTPException(503, "Display not available")
    display_service.set_eyes_mode()
    return {"status": "ok"}


@app.get("/display/snapshot", tags=["Display"])
def display_snapshot():
    """Get current display frame as JPEG (for web preview / debugging)."""
    if not display_service:
        raise HTTPException(503, "Display not available")
    data = display_service.get_snapshot_bytes()
    if not data:
        raise HTTPException(404, "No frame rendered yet")
    return Response(content=data, media_type="image/jpeg")


# --- Voice endpoints ---


class VoiceStartRequest(BaseModel):
    llm_api_key: str = Field(
        ..., min_length=1, description="OpenAI-compatible API key for TTS and STT"
    )
    llm_base_url: str = Field(
        ..., min_length=1, description="OpenAI-compatible base URL for TTS and STT"
    )
    deepgram_api_key: str = Field(
        "", description="Deepgram API key (optional, falls back to Autonomous STT)"
    )


@app.post("/voice/start", response_model=StatusResponse, tags=["Voice"])
def start_voice(req: VoiceStartRequest):
    """Start the voice pipeline (always-on Deepgram STT + TTS). Called by Lumi on boot."""
    global voice_service, tts_service

    # Start TTS
    if TTSService and not (tts_service and tts_service.available):
        try:
            tts_service = TTSService(
                api_key=req.llm_api_key,
                base_url=req.llm_base_url,
                sound_device_module=sd,
                numpy_module=np,
                output_device=audio_output_device,
                speed=TTS_SPEED,
            )
            logger.info("TTSService started")
            # Wire TTS to MusicService so music pauses during speech
            if music_service:
                music_service._tts_service = tts_service
        except Exception as e:
            logger.warning(f"TTSService failed: {e}")

    # Start voice (always-on streaming STT)
    if voice_service and voice_service.available:
        return {"status": "already_running"}
    if not VoiceService:
        raise HTTPException(503, "Voice service not available (missing deps)")
    try:
        # Prefer AutonomousSTT (uses llm_api_key), fall back to Deepgram
        stt_provider = None
        if req.deepgram_api_key and DeepgramSTT:
            agent_name = _read_agent_name({})
            stt_provider = DeepgramSTT(api_key=req.deepgram_api_key, keywords=[f"{agent_name}:3"])
        elif AutonomousSTT:
            stt_provider = AutonomousSTT(
                api_key=req.llm_api_key, base_url=req.llm_base_url
            )
        if not stt_provider:
            raise HTTPException(503, "No STT provider available")
        wake_words = _build_wake_words(_read_agent_name({}))
        voice_service = VoiceService(
            stt_provider=stt_provider,
            input_device=audio_input_device,
            tts_service=tts_service,
            music_service=music_service,
            wake_words=wake_words,
            alsa_device=AUDIO_INPUT_ALSA,
        )
        voice_service.start()
        return {"status": "ok"}
    except Exception as e:
        voice_service = None
        raise HTTPException(500, f"Failed to start voice: {e}")


@app.post("/voice/stop", response_model=StatusResponse, tags=["Voice"])
def stop_voice():
    """Stop the voice pipeline."""
    global voice_service, tts_service
    if voice_service:
        voice_service.stop()
        voice_service = None
    tts_service = None
    return {"status": "ok"}


class VoiceConfigRequest(BaseModel):
    wake_words: list[str] = Field(..., min_length=1, description="Wake word list (lowercase matched)")


@app.post("/voice/config", response_model=StatusResponse, tags=["Voice"])
def update_voice_config(req: VoiceConfigRequest):
    """Update voice pipeline config at runtime. Called by Lumi when agent is renamed."""
    if not voice_service:
        return {"status": "ok"}  # Not running yet — no-op, will pick up on next start
    voice_service.set_wake_words(req.wake_words)
    return {"status": "ok"}


@app.post("/voice/speak", response_model=StatusResponse, tags=["Voice"])
def speak_text(req: SpeakRequest):
    """Synthesize text to speech and play through the speaker."""
    if not tts_service:
        logger.error("POST /voice/speak: tts_service is None (not initialized)")
        raise HTTPException(
            503,
            "TTS not initialized — call /voice/start first or check lumi config has llm_api_key + llm_base_url",
        )
    if not tts_service.available:
        logger.error(
            "POST /voice/speak: tts_service not available — client=%s, sd=%s",
            tts_service._client is not None,
            tts_service._sd is not None,
        )
        raise HTTPException(
            503, "TTS not available — missing openai SDK or sounddevice"
        )
    # Reject TTS while music is playing — shared speaker, TTS would kill the music
    if music_service and music_service.playing:
        logger.info(
            "POST /voice/speak: rejected — music is playing (text='%s')", req.text[:80]
        )
        raise HTTPException(409, "Speaker busy — music is playing")
    logger.info("POST /voice/speak: text='%s' (len=%d)", req.text[:80], len(req.text))
    started = tts_service.speak(req.text)
    if not started:
        raise HTTPException(409, "TTS is busy speaking")
    return {"status": "ok"}


@app.post("/tts/stop", response_model=StatusResponse, tags=["Voice"])
def stop_tts():
    """Interrupt active TTS playback immediately. No-op if not speaking."""
    if tts_service:
        tts_service.stop()
    return {"status": "ok"}


@app.get("/voice/status", response_model=VoiceStatusResponse, tags=["Voice"])
def voice_status():
    """Get voice pipeline status."""
    tts_detail = None
    if tts_service:
        tts_detail = {
            "has_client": tts_service._client is not None,
            "has_sd": tts_service._sd is not None,
            "base_url": getattr(tts_service, "_base_url", "unknown"),
        }
    return {
        "voice_available": voice_service is not None and voice_service.available
        if voice_service
        else False,
        "voice_listening": voice_service.listening if voice_service else False,
        "tts_available": tts_service is not None and tts_service.available
        if tts_service
        else False,
        "tts_speaking": tts_service.speaking if tts_service else False,
        "tts_detail": tts_detail,
    }


# --- Music ---

_MUSIC_STYLE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("music_jazz", ["jazz", "swing", "blues", "soul", "funk", "bossa nova"]),
    (
        "music_classical",
        [
            "classical",
            "orchestra",
            "symphony",
            "beethoven",
            "mozart",
            "chopin",
            "bach",
            "opera",
            "concerto",
            "sonata",
            "piano",
            "violin",
        ],
    ),
    ("music_hiphop", ["hip hop", "hiphop", "hip-hop", "rap", "trap", "rnb", "r&b"]),
    ("music_rock", ["rock", "metal", "punk", "grunge", "heavy", "guitar", "band"]),
    ("music_waltz", ["waltz", "tango", "ballroom", "foxtrot"]),
    ("music_chill", ["chill", "lofi", "lo-fi", "lo fi", "ambient", "relax", "mellow", "study", "calm", "sleep"]),
    ("music_hype", ["hype", "edm", "electronic", "dance", "rave", "party", "upbeat", "electro", "techno", "house", "festival"]),
]

_MUSIC_STYLE_EMOTION: dict[str, str] = {
    "music_groove": "happy",
    "music_jazz": "happy",
    "music_classical": "curious",
    "music_hiphop": "excited",
    "music_rock": "excited",
    "music_waltz": "happy",
    "music_chill": "sleepy",
    "music_hype": "excited",
}


def _detect_music_style(query: str) -> str:
    """Return recording name matching the genre keywords in query, else music_groove."""
    q = query.lower()
    for recording, keywords in _MUSIC_STYLE_KEYWORDS:
        if any(k in q for k in keywords):
            return recording
    return "music_groove"


@app.post("/audio/play", response_model=StatusResponse, tags=["Audio"])
def audio_play(req: MusicPlayRequest):
    """Search YouTube and play audio through the speaker."""
    if not music_service:
        raise HTTPException(503, "Music service not available")
    if not music_service.available:
        raise HTTPException(
            503, "Music service not available — missing sounddevice or numpy"
        )
    logger.info("POST /audio/play: query='%s'", req.query[:80])
    import os as _os
    if req.query.startswith("/") and _os.path.isfile(req.query):
        started = music_service.play_file(req.query)
    else:
        started = music_service.play(req.query)
    if not started:
        raise HTTPException(409, "Music is busy playing")
    # Detect genre → start matching groove servo + apply LED + display
    style = _detect_music_style(req.query)
    logger.info("music style detected: %s", style)
    if animation_service:
        animation_service.dispatch("music_start", style)
    emotion = _MUSIC_STYLE_EMOTION.get(style, "happy")
    _apply_emotion_led_display(emotion)
    return {"status": "ok"}


def _on_music_complete():
    """Restore state after music ends (servo, LED, display).

    If user had an active scene/color: restore it (LED + aim).
    Otherwise fall back to idle breathing so lamp doesn't go dark.
    """
    if animation_service:
        animation_service.dispatch("music_stop", None)

    state = _user_led_state
    logger.info("Music stop: restoring state type=%s", state.get("type") if state else None)
    if state is not None and state.get("type") != "off":
        _restore_user_led()
    elif rgb_service:
        logger.info("Music stop: no active user state — falling back to idle breathing")
        # No active user preference — gentle idle breathing
        idle_preset = EMOTION_PRESETS["idle"]
        try:
            _stop_current_effect()
            global _effect_thread, _effect_name
            _effect_stop.clear()
            _effect_name = idle_preset["effect"]
            _effect_thread = threading.Thread(
                target=_run_effect,
                args=(
                    idle_preset["effect"],
                    tuple(idle_preset["color"]),
                    idle_preset.get("speed", 0.3),
                    None,
                    _effect_stop,
                    rgb_service,
                ),
                daemon=True,
                name="led-music-idle",
            )
            _effect_thread.start()
        except Exception as e:
            logger.warning("Music stop LED failed: %s", e)

    if display_service:
        try:
            display_service.set_expression("neutral")
        except Exception as e:
            logger.warning("Music stop display failed: %s", e)


@app.post("/audio/stop", response_model=StatusResponse, tags=["Audio"])
def audio_stop():
    """Stop current music playback."""
    if music_service and music_service.playing:
        music_service.stop()
    _on_music_complete()
    return {"status": "ok"}


@app.get("/audio/status", response_model=MusicStatusResponse, tags=["Audio"])
def audio_status():
    """Get music playback status."""
    return {
        "available": music_service is not None and music_service.available,
        "playing": music_service.playing if music_service else False,
    }


@app.get("/audio/history", tags=["Audio"])
def audio_history(date: str | None = None, last: int = 50):
    """Return music playback history for AI to learn user preferences.

    Each entry: {ts, date, hour, query, title, duration_s, stopped_by}.
    stopped_by is one of: "user", "end", "tts", "error", "next".
    """
    from lelamp.service.voice.music_service import query_play_history

    entries = query_play_history(date_str=date, last=min(last, 500))
    return {"date": date or "today", "entries": entries, "count": len(entries)}


# --- Version ---


@app.get("/version", tags=["System"])
def version():
    """Return LeLamp runtime version."""
    return {"version": app.version}


# --- Health ---


@app.get("/health", response_model=HealthResponse, tags=["System"])
def health():
    """Check which hardware drivers are available."""
    return {
        "status": "ok",
        "servo": animation_service is not None,
        "led": rgb_service is not None,
        "camera": camera_capture is not None,
        "audio": audio_output_device is not None or audio_input_device is not None,
        "sensing": sensing_service is not None,
        "voice": voice_service is not None and voice_service.available
        if voice_service
        else False,
        "tts": tts_service is not None and tts_service.available
        if tts_service
        else False,
        "music": music_service is not None and music_service.available
        if music_service
        else False,
        "display": display_service is not None,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT)
