"""
LeLamp Hardware Runtime — FastAPI server on port 5001.

Only starts the drivers we need. LiveKit/OpenAI code stays untouched but never imported.
Lumi Server (Go, port 5000) bridges requests here.
"""

import io
import math
import os
import logging
import logging.handlers
import random
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, Union

# --- Logging: colored stdout + rotating file ---
LOG_DIR = Path(os.environ.get("LELAMP_LOG_DIR", "/var/log/lelamp"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

_LEVEL_COLORS = {
    logging.DEBUG:    "\033[37m",     # gray
    logging.INFO:     "\033[32m",     # green
    logging.WARNING:  "\033[33m",     # yellow
    logging.ERROR:    "\033[31m",     # red
    logging.CRITICAL: "\033[1;31m",   # bold red
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
_root.setLevel(logging.INFO)

# Console handler (colored)
_console = logging.StreamHandler()
_console.setFormatter(_ColorFormatter())
_root.addHandler(_console)

# File handler: 5 MB per file, keep 3 backups (~20 MB max) — no color codes
_file = logging.handlers.RotatingFileHandler(
    LOG_DIR / "server.log", maxBytes=5 * 1024 * 1024, backupCount=3,
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
    from lelamp.service.motors.animation_service import AnimationService, clamp_positions as clamp_servo_positions
except ImportError as e:
    logger.warning(f"Servo drivers not available: {e}")

try:
    from lelamp.service.rgb.rgb_service import RGBService
except ImportError as e:
    logger.warning(f"LED drivers not available: {e}")

try:
    import sounddevice as sd
    import numpy as np
except ImportError as e:
    logger.warning(f"Audio drivers not available: {e}")

cv2 = None
try:
    import cv2
except ImportError as e:
    logger.warning(f"Camera drivers (opencv) not available: {e}")

# --- Config ---

SERVO_PORT = os.environ.get("LELAMP_SERVO_PORT", "/dev/ttyACM0")
LAMP_ID = os.environ.get("LELAMP_LAMP_ID", "lelamp")
SERVO_FPS = int(os.environ.get("LELAMP_SERVO_FPS", "30"))
HTTP_PORT = int(os.environ.get("LELAMP_HTTP_PORT", "5001"))
CAMERA_INDEX = int(os.environ.get("LELAMP_CAMERA_INDEX", "0"))
CAMERA_WIDTH = int(os.environ.get("LELAMP_CAMERA_WIDTH", "640"))
CAMERA_HEIGHT = int(os.environ.get("LELAMP_CAMERA_HEIGHT", "480"))

# --- Lazy import for sensing ---

SensingService = None
try:
    from lelamp.service.sensing.sensing_service import SensingService
except ImportError as e:
    logger.warning(f"Sensing service not available: {e}")

# --- Lazy import for voice ---

VoiceService = None
DeepgramSTT = None
AutonomousSTT = None
TTSService = None
try:
    from lelamp.service.voice.voice_service import VoiceService
    from lelamp.service.voice.stt_deepgram import DeepgramSTT
    from lelamp.service.voice.stt_autonomous import AutonomousSTT
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


def _find_seeed_device(output: bool = True) -> Optional[int]:
    """Find Seeed audio device index."""
    if not sd:
        return None
    try:
        for i, d in enumerate(sd.query_devices()):
            if "seeed" not in d["name"].lower():
                continue
            if output and d["max_output_channels"] > 0:
                return i
            if not output and d["max_input_channels"] > 0:
                return i
    except Exception:
        pass
    return None


seeed_output_device: Optional[int] = None
seeed_input_device: Optional[int] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global animation_service, rgb_service, camera_capture, sensing_service
    global voice_service, tts_service, display_service
    global seeed_output_device, seeed_input_device

    # Start servo/animation service
    if AnimationService:
        try:
            animation_service = AnimationService(port=SERVO_PORT, lamp_id=LAMP_ID, fps=SERVO_FPS)
            animation_service.start()
            logger.info("AnimationService started")
        except Exception as e:
            logger.warning(f"AnimationService failed to start: {e}")
            animation_service = None

    # Start RGB LED service
    if RGBService:
        try:
            rgb_service = RGBService(led_count=64)
            rgb_service.start()
            logger.info("RGBService started")
        except Exception as e:
            logger.warning(f"RGBService failed to start: {e}")
            rgb_service = None

    # Open camera
    if cv2:
        try:
            cap = cv2.VideoCapture(CAMERA_INDEX)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
            if cap.isOpened():
                camera_capture = cap
                logger.info(f"Camera opened (index={CAMERA_INDEX}, {CAMERA_WIDTH}x{CAMERA_HEIGHT})")
            else:
                cap.release()
                logger.warning("Camera failed to open")
        except Exception as e:
            logger.warning(f"Camera failed to start: {e}")

    # Detect audio devices
    global music_service
    if sd:
        seeed_output_device = _find_seeed_device(output=True)
        seeed_input_device = _find_seeed_device(output=False)
        if seeed_output_device is not None:
            logger.info(f"Audio output device: {seeed_output_device}")
        if seeed_input_device is not None:
            logger.info(f"Audio input device: {seeed_input_device}")

    # Start music service (uses ffmpeg + ALSA directly, no sounddevice needed)
    if MusicService:
        try:
            music_service = MusicService()
            logger.info("MusicService started")
        except Exception as e:
            logger.warning(f"MusicService failed to start: {e}")

    # Start sensing loop (motion + sound detection → push events to Lumi → OpenClaw)
    sensing_enabled = os.environ.get("LELAMP_SENSING_ENABLED", "true").lower() in ("true", "1", "yes")
    if SensingService and sensing_enabled:
        try:
            sensing_service = SensingService(
                camera_capture=camera_capture,
                sound_device_module=sd,
                numpy_module=np,
                cv2_module=cv2,
                input_device=seeed_input_device,
                poll_interval=float(os.environ.get("LELAMP_SENSING_INTERVAL", "2.0")),
                rgb_service=rgb_service,
                tts_service=tts_service,
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
                output_device=seeed_output_device,
            )
            logger.info("TTSService auto-started from lumi config (base_url=%s, output_device=%s, available=%s)",
                        llm_url, seeed_output_device, tts_service.available)
            # Wire TTS to SensingService for echo suppression
            if sensing_service:
                sensing_service.set_tts_service(tts_service)
            # Wire TTS to MusicService so music pauses during speech
            if music_service:
                music_service._tts_service = tts_service
        if VoiceService and not voice_service:
            stt_provider = None
            logger.info("STT selection: deepgram_key=%s, DeepgramSTT=%s, AutonomousSTT=%s",
                        bool(dgk), DeepgramSTT is not None, AutonomousSTT is not None)
            if dgk and DeepgramSTT:
                stt_provider = DeepgramSTT(api_key=dgk, keywords=["lumi:3", "lu mi:2"])
            elif llm_key and llm_url and AutonomousSTT:
                stt_provider = AutonomousSTT(api_key=llm_key, base_url=llm_url)
            if stt_provider:
                voice_service = VoiceService(
                    stt_provider=stt_provider,
                    input_device=seeed_input_device,
                    tts_service=tts_service,
                )
                voice_service.start()
                logger.info("VoiceService auto-started (%s)", stt_provider.name)
    except FileNotFoundError:
        logger.info(f"Lumi config not found at {lumi_config_path}, voice will wait for /voice/start")
    except Exception as e:
        logger.warning(f"Auto-start voice from lumi config failed: {e}")

    yield

    # Shutdown
    _stop_current_effect()
    if display_service:
        display_service.stop()
    if music_service and music_service.playing:
        music_service.stop()
    if voice_service:
        voice_service.stop()
    if sensing_service:
        sensing_service.stop()
    # Release servo torque before stopping to protect motors
    if animation_service and animation_service.robot and animation_service.robot.bus:
        bus = animation_service.robot.bus
        for motor_name in bus.motors:
            try:
                bus.write("Torque_Enable", motor_name, 0)
            except Exception as e:
                logger.warning(f"Servo release on shutdown failed for {motor_name}: {e}")
        logger.info("Servos released on shutdown")
    if animation_service:
        animation_service.stop()
    if rgb_service:
        rgb_service.stop()
    if camera_capture:
        camera_capture.release()


app = FastAPI(
    title="LeLamp Hardware Runtime",
    description=(
        "Hardware driver API for Lumi AI Lamp. "
        "Controls servo motors (5-axis Feetech), RGB LEDs (64x WS2812), "
        "camera, audio (mic/speaker), display, and AI voice pipeline. "
        "Lumi Server (Go, port 5000) bridges requests here."
    ),
    version="0.2.0",
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


# --- Request/Response models ---

class ServoRequest(BaseModel):
    recording: str

    model_config = {
        "json_schema_extra": {
            "examples": [{"recording": "curious"}]
        }
    }


class ServoStateResponse(BaseModel):
    available_recordings: list[str]
    current: Optional[str]

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "available_recordings": ["nod", "curious", "happy_wiggle", "idle", "sad", "excited", "shy", "shock"],
                "current": "idle",
            }]
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
    color: list[int]  # [R, G, B]
    hex: str          # e.g. "#ff8800"


VALID_LED_EFFECTS = ["breathing", "candle", "rainbow", "notification_flash", "pulse"]


class LEDEffectRequest(BaseModel):
    effect: str = Field(..., description="Effect name: breathing, candle, rainbow, notification_flash, pulse")
    color: Optional[list[int]] = Field(None, description="Base RGB color for the effect (default: current color)")
    speed: float = Field(1.0, ge=0.1, le=5.0, description="Speed multiplier (0.1=slow, 1.0=normal, 5.0=fast)")
    duration_ms: Optional[int] = Field(None, ge=100, le=60000, description="Auto-stop after duration (null=indefinite)")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"effect": "breathing", "color": [255, 100, 0], "speed": 1.0},
                {"effect": "rainbow", "speed": 0.5},
                {"effect": "notification_flash", "color": [255, 0, 0], "duration_ms": 3000},
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

    model_config = {
        "json_schema_extra": {
            "examples": [{"volume": 75}]
        }
    }


class AudioDevicesResponse(BaseModel):
    output_device: Optional[int]
    input_device: Optional[int]
    available: bool


class CameraInfoResponse(BaseModel):
    available: bool
    width: Optional[int]
    height: Optional[int]


class EmotionRequest(BaseModel):
    emotion: str = Field(..., description="Emotion name: curious, happy, sad, thinking, idle, excited, shy, shock")
    intensity: float = Field(0.7, ge=0.0, le=1.0, description="Intensity 0.0-1.0")

    model_config = {
        "json_schema_extra": {
            "examples": [{"emotion": "curious", "intensity": 0.8}]
        }
    }


class EmotionResponse(BaseModel):
    status: str
    emotion: str
    servo: Optional[str]
    led: Optional[list[int]]


# Emotion presets: maps emotion name to servo recording + LED color + optional LED effect
# "effect" triggers a background LED animation; "color" is the base color for that effect.
# When no "effect" is set, LED is a simple solid fill.
EMOTION_PRESETS = {
    "curious":  {"servo": "curious",      "color": [255, 200, 80],  "effect": "pulse",              "speed": 1.2},
    "happy":    {"servo": "happy_wiggle",  "color": [255, 220, 0],   "effect": "pulse",              "speed": 1.5},
    "sad":      {"servo": "sad",           "color": [80, 80, 200],   "effect": "breathing",          "speed": 0.4},
    "thinking": {"servo": "nod",           "color": [180, 100, 255], "effect": "breathing",          "speed": 0.8},
    "idle":     {"servo": "idle",          "color": [100, 200, 220], "effect": "breathing",          "speed": 0.3},
    "excited":  {"servo": "excited",       "color": [255, 100, 0],   "effect": "pulse",              "speed": 2.5},
    "shy":      {"servo": "shy",           "color": [255, 150, 180], "effect": "breathing",          "speed": 0.5},
    "shock":    {"servo": "shock",         "color": [255, 255, 255], "effect": "notification_flash", "speed": 3.0},
}


# --- Lighting scene presets ---
# Simulated color temperature via RGB mixing
# 2200K = very warm amber, 2700K = warm white, 4000K = neutral, 5000K = cool, 6500K = daylight
SCENE_PRESETS = {
    "reading":  {"brightness": 0.80, "color": [255, 225, 180]},  # ~4000K neutral
    "focus":    {"brightness": 1.00, "color": [235, 240, 255]},  # ~5000K cool white
    "relax":    {"brightness": 0.40, "color": [255, 180, 100]},  # ~2700K warm
    "movie":    {"brightness": 0.15, "color": [255, 170, 80]},   # ~2700K dim amber
    "night":    {"brightness": 0.05, "color": [255, 140, 40]},   # ~2200K very warm
    "energize": {"brightness": 1.00, "color": [220, 235, 255]},  # ~6500K daylight
}



# --- Servo aim presets ---
# Named lamp-head directions mapped to joint positions (normalized -100..100)
# Neutral: base_yaw=3, base_pitch=-30, elbow_pitch=57, wrist_roll=0, wrist_pitch=18
AIM_PRESETS = {
    "center":  {"base_yaw.pos": 3.0,   "base_pitch.pos": -30.0, "elbow_pitch.pos": 57.0, "wrist_roll.pos": 0.0, "wrist_pitch.pos": 18.0},
    "desk":    {"base_yaw.pos": 3.0,   "base_pitch.pos": -25.0, "elbow_pitch.pos": 50.0, "wrist_roll.pos": 0.0, "wrist_pitch.pos": 40.0},
    "wall":    {"base_yaw.pos": 3.0,   "base_pitch.pos": -40.0, "elbow_pitch.pos": 65.0, "wrist_roll.pos": 0.0, "wrist_pitch.pos": -5.0},
    "left":    {"base_yaw.pos": -35.0, "base_pitch.pos": -30.0, "elbow_pitch.pos": 57.0, "wrist_roll.pos": 0.0, "wrist_pitch.pos": 18.0},
    "right":   {"base_yaw.pos": 40.0,  "base_pitch.pos": -30.0, "elbow_pitch.pos": 57.0, "wrist_roll.pos": 0.0, "wrist_pitch.pos": 18.0},
    "up":      {"base_yaw.pos": 3.0,   "base_pitch.pos": -45.0, "elbow_pitch.pos": 70.0, "wrist_roll.pos": 0.0, "wrist_pitch.pos": -10.0},
    "down":    {"base_yaw.pos": 3.0,   "base_pitch.pos": -22.0, "elbow_pitch.pos": 45.0, "wrist_roll.pos": 0.0, "wrist_pitch.pos": 50.0},
    "user":    {"base_yaw.pos": 3.0,   "base_pitch.pos": -28.0, "elbow_pitch.pos": 55.0, "wrist_roll.pos": 0.0, "wrist_pitch.pos": 22.0},
}


class SceneRequest(BaseModel):
    scene: str = Field(..., description="Scene name: reading, focus, relax, movie, night, energize")

    model_config = {
        "json_schema_extra": {
            "examples": [{"scene": "reading"}]
        }
    }


class SceneResponse(BaseModel):
    status: str
    scene: str
    brightness: float
    color: list[int]


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000, description="Text to speak via TTS")

    model_config = {
        "json_schema_extra": {
            "examples": [{"text": "Hi there! I am Lumi."}]
        }
    }


class MusicPlayRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="Song name or search query")

    model_config = {
        "json_schema_extra": {
            "examples": [{"query": "Bohemian Rhapsody Queen"}]
        }
    }


class MusicStatusResponse(BaseModel):
    available: bool
    playing: bool


class VolumeResponse(BaseModel):
    control: str
    volume: int


class ServoPositionResponse(BaseModel):
    positions: dict[str, float]


class ServoAimRequest(BaseModel):
    direction: str = Field(..., description="Named direction: desk, wall, left, right, up, down, center, user")
    duration: float = Field(2.0, ge=0.0, le=10.0, description="Move duration in seconds (default: 2.0)")

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


class PresenceResponse(BaseModel):
    state: str
    enabled: bool
    seconds_since_motion: int
    idle_timeout: int
    away_timeout: int


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


@app.post("/servo/play", response_model=StatusResponse, tags=["Servo"])
def play_recording(req: ServoRequest):
    """Play a pre-recorded servo animation by name."""
    if not animation_service:
        raise HTTPException(503, "Servo not available")
    animation_service.dispatch("play", req.recording)
    return {"status": "ok"}


class ServoMoveRequest(BaseModel):
    positions: dict[str, float] = Field(
        ...,
        description=(
            "Joint positions (degrees). Ordered by servo ID: "
            "base_yaw.pos (ID 1, min -78 max 78), "
            "base_pitch.pos (ID 2, min -78 max 80), "
            "elbow_pitch.pos (ID 3, min -25 max 97), "
            "wrist_roll.pos (ID 4, min -68 max 68), "
            "wrist_pitch.pos (ID 5, min -25 max 72). "
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
                        "base_yaw.pos":     0.0,
                        "base_pitch.pos":   10.0,
                        "elbow_pitch.pos":  -5.0,
                        "wrist_roll.pos":   0.0,
                        "wrist_pitch.pos":  0.0,
                    },
                    "_comment": "ID1 base_yaw [-78,78] | ID2 base_pitch [-78,80] | ID3 elbow_pitch [-25,97] | ID4 wrist_roll [-68,68] | ID5 wrist_pitch [-25,72]",
                },
                {"positions": {"base_pitch.pos": 5.0, "elbow_pitch.pos": 5.0}, "duration": 3.0},
            ]
        }
    }


class ServoMoveResponse(BaseModel):
    status: str
    requested: dict[str, float]
    clamped: dict[str, float]
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
    from lelamp.service.motors.animation_service import JOINT_LIMITS
    unknown = [j for j in req.positions if j not in JOINT_LIMITS]
    if unknown:
        raise HTTPException(400, f"Unknown joints: {unknown}. Valid: {list(JOINT_LIMITS.keys())}")

    safe_positions = clamp_servo_positions(req.positions)
    errors = {}

    try:
        if req.duration > 0:
            animation_service.move_to(safe_positions, duration=req.duration)
        else:
            animation_service.robot.send_action(safe_positions)
    except Exception as e:
        errors["move"] = str(e)

    # Read back actual positions to check errors
    try:
        obs = animation_service.robot.get_observation()
        for joint, target in safe_positions.items():
            actual = obs.get(joint)
            if actual is not None:
                error = abs(actual - target)
                if error > 5.0:
                    errors[joint] = f"position error {error:.1f} deg (target={target:.1f}, actual={actual:.1f})"
    except Exception as e:
        errors["read_position"] = str(e)

    return {
        "status": "error" if "move" in errors else "ok",
        "requested": req.positions,
        "clamped": safe_positions,
        "duration": req.duration,
        "errors": errors if errors else None,
    }


@app.post("/servo/release", response_model=StatusResponse, tags=["Servo"])
def release_servos():
    """Disable torque on all 5 servos (release / go limp).

    Sends Torque_Enable=0 to every servo. If a servo is temporarily
    offline it will fail silently for that servo but still release the rest.
    """
    if not animation_service:
        raise HTTPException(503, "Servo not available")
    if not animation_service.robot:
        raise HTTPException(503, "Servo robot not connected")
    bus = animation_service.robot.bus
    errors = {}
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
        obs = animation_service.robot.get_observation()
        positions = {k: v for k, v in obs.items() if k.endswith(".pos")}
        return {"positions": positions}
    except Exception as e:
        raise HTTPException(500, f"Failed to read position: {e}")


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

    positions = AIM_PRESETS.get(req.direction)
    if positions is None:
        available = list(AIM_PRESETS.keys())
        raise HTTPException(400, f"Unknown direction '{req.direction}'. Available: {available}")

    try:
        if req.duration > 0:
            animation_service.move_to(positions, duration=req.duration)
        else:
            animation_service.robot.send_action(positions)
        return {"status": "ok", "direction": req.direction, "positions": positions}
    except Exception as e:
        raise HTTPException(500, f"Servo aim failed: {e}")


# --- LED endpoints ---

@app.get("/led", response_model=LEDStateResponse, tags=["LED"])
def get_led_state():
    """Get LED strip info."""
    if not rgb_service:
        raise HTTPException(503, "LED not available")
    return {"led_count": rgb_service.led_count}


@app.get("/led/color", response_model=LEDColorResponse, tags=["LED"])
def get_led_color():
    """Get the current LED color (last color set on the strip)."""
    if not rgb_service:
        raise HTTPException(503, "LED not available")
    # Use last_color tracked by presence service when available,
    # otherwise fall back to reading the first pixel from the strip directly.
    if sensing_service:
        r, g, b = sensing_service.presence._last_color
    else:
        raw = rgb_service.strip.getPixelColor(0)
        r = (raw >> 16) & 0xFF
        g = (raw >> 8) & 0xFF
        b = raw & 0xFF
    return {
        "led_count": rgb_service.led_count,
        "color": [r, g, b],
        "hex": f"#{r:02x}{g:02x}{b:02x}",
    }


@app.post("/led/solid", response_model=StatusResponse, tags=["LED"])
def set_led_solid(req: LEDSolidRequest):
    """Fill entire LED strip with a single color. Color as [R,G,B] or packed int."""
    if not rgb_service:
        raise HTTPException(503, "LED not available")
    color = tuple(req.color) if isinstance(req.color, list) else req.color
    rgb_service.dispatch("solid", color)
    # Track for presence restore
    if sensing_service and isinstance(color, tuple):
        sensing_service.presence.set_last_color(color)
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
    _stop_current_effect()
    rgb_service.clear()
    return {"status": "ok"}


# --- LED effects helpers ---

_effect_thread: Optional[threading.Thread] = None
_effect_stop: threading.Event = threading.Event()
_effect_name: Optional[str] = None


def _stop_current_effect():
    """Signal the running effect thread to stop and wait for it."""
    global _effect_thread, _effect_name
    if _effect_thread and _effect_thread.is_alive():
        _effect_stop.set()
        _effect_thread.join(timeout=2.0)
    _effect_thread = None
    _effect_name = None


def _run_effect(effect: str, color: tuple, speed: float, duration_ms: Optional[int],
                stop_event: threading.Event, svc):
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


def _effect_breathing(color: tuple, speed: float, deadline: Optional[float],
                      stop_event: threading.Event, svc):
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


def _effect_candle(color: tuple, speed: float, deadline: Optional[float],
                   stop_event: threading.Event, svc):
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


def _effect_rainbow(speed: float, deadline: Optional[float],
                    stop_event: threading.Event, svc):
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


def _effect_notification_flash(color: tuple, speed: float,
                               stop_event: threading.Event, svc):
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


def _effect_pulse(color: tuple, speed: float, deadline: Optional[float],
                  stop_event: threading.Event, svc):
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
                    falloff = max(0.0, 1.0 - abs(dist - radius) / max(max_radius * 0.3, 1))
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
    global _effect_thread, _effect_name
    if not rgb_service:
        raise HTTPException(503, "LED not available")
    if req.effect not in VALID_LED_EFFECTS:
        raise HTTPException(400, f"Unknown effect '{req.effect}'. Available: {VALID_LED_EFFECTS}")

    # Stop any running effect
    _stop_current_effect()

    # Default color: warm white if none provided
    base_color = tuple(req.color) if req.color else (255, 180, 100)

    _effect_stop.clear()
    _effect_name = req.effect
    _effect_thread = threading.Thread(
        target=_run_effect,
        args=(req.effect, base_color, req.speed, req.duration_ms, _effect_stop, rgb_service),
        daemon=True,
        name=f"led-effect-{req.effect}",
    )
    _effect_thread.start()
    logger.info("LED effect started: %s (speed=%.1f, duration=%s)", req.effect, req.speed, req.duration_ms)

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
    if not camera_capture:
        return {"available": False, "width": None, "height": None}
    return {
        "available": True,
        "width": int(camera_capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(camera_capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    }


@app.get("/camera/snapshot", tags=["Camera"])
def camera_snapshot():
    """Capture a single JPEG frame from the camera."""
    if not camera_capture:
        raise HTTPException(503, "Camera not available")
    ret, frame = camera_capture.read()
    if not ret:
        raise HTTPException(500, "Failed to capture frame")
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return Response(content=buf.tobytes(), media_type="image/jpeg")


@app.get("/camera/stream", tags=["Camera"])
def camera_stream():
    """MJPEG stream from the camera (multipart/x-mixed-replace)."""
    if not camera_capture:
        raise HTTPException(503, "Camera not available")

    def generate():
        while True:
            ret, frame = camera_capture.read()
            if not ret:
                break
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
            )

    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")


# --- Audio endpoints ---

@app.get("/audio", response_model=AudioDevicesResponse, tags=["Audio"])
def get_audio_info():
    """Get audio device availability."""
    return {
        "output_device": seeed_output_device,
        "input_device": seeed_input_device,
        "available": seeed_output_device is not None or seeed_input_device is not None,
    }


def _detect_playback_controls() -> list[str]:
    """Auto-detect available playback mixer controls from amixer."""
    try:
        result = subprocess.run(
            ["amixer", "scontrols"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            import re
            # Parse lines like: Simple mixer control 'Speaker',0
            return re.findall(r"Simple mixer control '([^']+)'", result.stdout)
    except Exception:
        pass
    return []


@app.post("/audio/volume", response_model=StatusResponse, tags=["Audio"])
def set_volume(req: VolumeRequest):
    """Set system speaker volume (0-100%). Uses amixer on the Pi."""
    controls = _detect_playback_controls()
    if not controls:
        raise HTTPException(503, "No audio mixer controls found")
    for ctrl in controls:
        try:
            subprocess.run(
                ["amixer", "sset", ctrl, f"{req.volume}%"],
                capture_output=True, text=True, timeout=5,
            )
        except Exception:
            pass
    return {"status": "ok"}


@app.get("/audio/volume", response_model=VolumeResponse, tags=["Audio"])
def get_volume():
    """Get current speaker volume from amixer."""
    import re
    for ctrl in _detect_playback_controls():
        try:
            result = subprocess.run(
                ["amixer", "sget", ctrl],
                capture_output=True, text=True, timeout=5,
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
    if seeed_output_device is None:
        raise HTTPException(503, "No output audio device found")
    sample_rate = 44100
    t = np.linspace(0, duration_ms / 1000, int(sample_rate * duration_ms / 1000), endpoint=False)
    tone = 0.5 * np.sin(2 * np.pi * frequency * t).astype(np.float32)
    sd.play(tone, samplerate=sample_rate, device=seeed_output_device)
    return {"status": "ok"}


@app.post("/audio/record", tags=["Audio"])
def record_audio(duration_ms: int = 3000):
    """Record audio from the microphone. Returns WAV bytes."""
    if not sd or not np:
        raise HTTPException(503, "Audio not available")
    if seeed_input_device is None:
        raise HTTPException(503, "No input audio device found")
    import wave
    sample_rate = 44100
    channels = 1
    frames = int(sample_rate * duration_ms / 1000)
    recording = sd.rec(frames, samplerate=sample_rate, channels=channels,
                       dtype="int16", device=seeed_input_device)
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
        raise HTTPException(400, f"Unknown emotion '{req.emotion}'. Available: {available}")

    servo_played = None
    led_color = None

    # Play servo animation
    if animation_service and preset.get("servo"):
        try:
            animation_service.dispatch("play", preset["servo"])
            servo_played = preset["servo"]
        except Exception as e:
            logger.warning(f"Emotion servo failed: {e}")

    # Set LED color + effect (coordinated with servo)
    if rgb_service and preset.get("color"):
        base = preset["color"]
        scaled = [int(c * req.intensity) for c in base]
        try:
            if preset.get("effect"):
                # Stop any running effect, then start emotion effect
                _stop_current_effect()
                global _effect_thread, _effect_name
                _effect_stop.clear()
                _effect_name = preset["effect"]
                _effect_thread = threading.Thread(
                    target=_run_effect,
                    args=(preset["effect"], tuple(scaled), preset.get("speed", 1.0), None, _effect_stop, rgb_service),
                    daemon=True,
                    name=f"led-emotion-{req.emotion}",
                )
                _effect_thread.start()
            else:
                rgb_service.dispatch("solid", tuple(scaled))
            led_color = scaled
            # Track so GET /led/color returns the correct current color
            if sensing_service:
                sensing_service.presence.set_last_color(tuple(scaled))
        except Exception as e:
            logger.warning(f"Emotion LED failed: {e}")

    # Set matching eye expression on display (if available)
    if display_service:
        try:
            display_service.set_expression(req.emotion)
        except Exception as e:
            logger.warning(f"Emotion display failed: {e}")

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
    return {"scenes": list(SCENE_PRESETS.keys())}


@app.post("/scene", response_model=SceneResponse, tags=["Scene"])
def activate_scene(req: SceneRequest):
    """Activate a lighting scene preset. Sets LED color scaled by scene brightness."""
    preset = SCENE_PRESETS.get(req.scene)
    if not preset:
        available = list(SCENE_PRESETS.keys())
        raise HTTPException(400, f"Unknown scene '{req.scene}'. Available: {available}")

    if not rgb_service:
        raise HTTPException(503, "LED not available")

    base = preset["color"]
    brightness = preset["brightness"]
    scaled = [int(c * brightness) for c in base]
    try:
        rgb_service.dispatch("solid", tuple(scaled))
    except Exception as e:
        raise HTTPException(500, f"Failed to set scene: {e}")

    # Track last color for presence restore
    if sensing_service:
        sensing_service.presence.set_last_color(tuple(scaled))

    return {
        "status": "ok",
        "scene": req.scene,
        "brightness": brightness,
        "color": scaled,
    }


# --- Presence endpoints ---

@app.get("/presence", response_model=PresenceResponse, tags=["Presence"])
def get_presence():
    """Get current presence state (present/idle/away) and config."""
    if not sensing_service:
        return {"state": "unknown", "enabled": False, "seconds_since_motion": 0,
                "idle_timeout": 0, "away_timeout": 0}
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


# --- Display endpoints ---

class DisplayEyesRequest(BaseModel):
    expression: str = Field(..., description="Expression: neutral, happy, sad, curious, thinking, excited, shy, shock, sleepy, angry, love")
    pupil_x: float = Field(0.0, ge=-1.0, le=1.0, description="Pupil X: -1.0 (left) to 1.0 (right)")
    pupil_y: float = Field(0.0, ge=-1.0, le=1.0, description="Pupil Y: -1.0 (up) to 1.0 (down)")

    model_config = {
        "json_schema_extra": {
            "examples": [{"expression": "happy", "pupil_x": 0.0, "pupil_y": 0.0}]
        }
    }


class DisplayInfoRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=20, description="Main text (short, e.g. '14:30')")
    subtitle: str = Field("", max_length=40, description="Subtitle (e.g. 'Good afternoon')")

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
    llm_api_key: str = Field(..., min_length=1, description="OpenAI-compatible API key for TTS and STT")
    llm_base_url: str = Field(..., min_length=1, description="OpenAI-compatible base URL for TTS and STT")
    deepgram_api_key: str = Field("", description="Deepgram API key (optional, falls back to Autonomous STT)")


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
                output_device=seeed_output_device,
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
            stt_provider = DeepgramSTT(api_key=req.deepgram_api_key, keywords=["lumi:3", "lu mi:2"])
        elif AutonomousSTT:
            stt_provider = AutonomousSTT(api_key=req.llm_api_key, base_url=req.llm_base_url)
        if not stt_provider:
            raise HTTPException(503, "No STT provider available")
        voice_service = VoiceService(
            stt_provider=stt_provider,
            input_device=seeed_input_device,
            tts_service=tts_service,
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


@app.post("/voice/speak", response_model=StatusResponse, tags=["Voice"])
def speak_text(req: SpeakRequest):
    """Synthesize text to speech and play through the speaker."""
    if not tts_service:
        logger.error("POST /voice/speak: tts_service is None (not initialized)")
        raise HTTPException(503, "TTS not initialized — call /voice/start first or check lumi config has llm_api_key + llm_base_url")
    if not tts_service.available:
        logger.error("POST /voice/speak: tts_service not available — client=%s, sd=%s",
                      tts_service._client is not None, tts_service._sd is not None)
        raise HTTPException(503, "TTS not available — missing openai SDK or sounddevice")
    # Reject TTS while music is playing — shared speaker, TTS would kill the music
    if music_service and music_service.playing:
        logger.info("POST /voice/speak: rejected — music is playing (text='%s')", req.text[:80])
        raise HTTPException(409, "Speaker busy — music is playing")
    logger.info("POST /voice/speak: text='%s' (len=%d)", req.text[:80], len(req.text))
    started = tts_service.speak(req.text)
    if not started:
        raise HTTPException(409, "TTS is busy speaking")
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
        "voice_available": voice_service is not None and voice_service.available if voice_service else False,
        "voice_listening": voice_service.listening if voice_service else False,
        "tts_available": tts_service is not None and tts_service.available if tts_service else False,
        "tts_speaking": tts_service.speaking if tts_service else False,
        "tts_detail": tts_detail,
    }


# --- Music ---

@app.post("/audio/play", response_model=StatusResponse, tags=["Audio"])
def audio_play(req: MusicPlayRequest):
    """Search YouTube and play audio through the speaker."""
    if not music_service:
        raise HTTPException(503, "Music service not available")
    if not music_service.available:
        raise HTTPException(503, "Music service not available — missing sounddevice or numpy")
    logger.info("POST /audio/play: query='%s'", req.query[:80])
    started = music_service.play(req.query)
    if not started:
        raise HTTPException(409, "Music is busy playing")
    # Groove servo while music plays
    if animation_service:
        animation_service.dispatch("music_start", None)
    return {"status": "ok"}


@app.post("/audio/stop", response_model=StatusResponse, tags=["Audio"])
def audio_stop():
    """Stop current music playback."""
    if music_service and music_service.playing:
        music_service.stop()
    # Stop groove servo
    if animation_service:
        animation_service.dispatch("music_stop", None)
    return {"status": "ok"}


@app.get("/audio/status", response_model=MusicStatusResponse, tags=["Audio"])
def audio_status():
    """Get music playback status."""
    return {
        "available": music_service is not None and music_service.available,
        "playing": music_service.playing if music_service else False,
    }


# --- Health ---

@app.get("/health", response_model=HealthResponse, tags=["System"])
def health():
    """Check which hardware drivers are available."""
    return {
        "status": "ok",
        "servo": animation_service is not None,
        "led": rgb_service is not None,
        "camera": camera_capture is not None,
        "audio": seeed_output_device is not None or seeed_input_device is not None,
        "sensing": sensing_service is not None,
        "voice": voice_service is not None and voice_service.available if voice_service else False,
        "tts": tts_service is not None and tts_service.available if tts_service else False,
        "music": music_service is not None and music_service.available if music_service else False,
        "display": display_service is not None,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT)
