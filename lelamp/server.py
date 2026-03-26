"""
LeLamp Hardware Runtime — FastAPI server on port 5001.

Only starts the drivers we need. LiveKit/OpenAI code stays untouched but never imported.
Lumi Server (Go, port 5000) bridges requests here.
"""

import io
import os
import logging
import subprocess
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, Union

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lelamp.server")

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
LAMP_ID = os.environ.get("LELAMP_LAMP_ID", "lumi")
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
TTSService = None
try:
    from lelamp.service.voice.voice_service import VoiceService
except ImportError as e:
    logger.warning(f"Voice service not available: {e}")

try:
    from lelamp.service.voice.tts_service import TTSService
except ImportError as e:
    logger.warning(f"TTS service not available: {e}")

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
    if sd:
        seeed_output_device = _find_seeed_device(output=True)
        seeed_input_device = _find_seeed_device(output=False)
        if seeed_output_device is not None:
            logger.info(f"Audio output device: {seeed_output_device}")
        if seeed_input_device is not None:
            logger.info(f"Audio input device: {seeed_input_device}")

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

    yield

    # Shutdown
    if display_service:
        display_service.stop()
    if voice_service:
        voice_service.stop()
    if sensing_service:
        sensing_service.stop()
    if animation_service:
        animation_service.stop()
    if rgb_service:
        rgb_service.stop()
    if camera_capture:
        camera_capture.release()


app = FastAPI(
    title="LeLamp Hardware Runtime",
    description="Hardware driver API for Lumi AI Lamp. "
    "Controls servo motors (5-axis Feetech), RGB LEDs (64x WS2812), "
    "camera, and audio (mic/speaker). "
    "Lumi Server (Go, port 5000) bridges requests here.",
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
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


# Emotion presets: maps emotion name to servo recording + LED color [R,G,B]
EMOTION_PRESETS = {
    "curious":  {"servo": "curious",      "color": [255, 200, 80]},   # warm yellow
    "happy":    {"servo": "happy_wiggle",  "color": [255, 220, 0]},    # bright yellow
    "sad":      {"servo": "sad",           "color": [80, 80, 200]},    # soft blue
    "thinking": {"servo": "nod",           "color": [180, 100, 255]},  # purple
    "idle":     {"servo": "idle",          "color": [100, 200, 220]},  # cyan
    "excited":  {"servo": "excited",       "color": [255, 100, 0]},    # orange
    "shy":      {"servo": "shy",           "color": [255, 150, 180]},  # pink
    "shock":    {"servo": "shock",         "color": [255, 255, 255]},  # white flash
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
            "examples": [{"text": "Xin chao! Toi la Lumi."}]
        }
    }


class HealthResponse(BaseModel):
    status: str
    servo: bool
    led: bool
    camera: bool
    audio: bool
    sensing: bool
    voice: bool
    tts: bool
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
        description="Joint positions: base_yaw, base_pitch, elbow_pitch, wrist_roll, wrist_pitch (degrees)",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{"positions": {"base_yaw.pos": 0.0, "base_pitch.pos": 10.0, "elbow_pitch.pos": -5.0, "wrist_roll.pos": 0.0, "wrist_pitch.pos": 0.0}}]
        }
    }


@app.post("/servo/move", response_model=StatusResponse, tags=["Servo"])
def move_servo(req: ServoMoveRequest):
    """Send direct joint positions to servo motors. Use to test hardware without recordings."""
    if not animation_service:
        raise HTTPException(503, "Servo not available")
    if not animation_service.robot:
        raise HTTPException(503, "Servo robot not connected")
    try:
        animation_service.robot.send_action(req.positions)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(500, f"Servo move failed: {e}")


@app.get("/servo/position", tags=["Servo"])
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


# --- LED endpoints ---

@app.get("/led", response_model=LEDStateResponse, tags=["LED"])
def get_led_state():
    """Get LED strip info."""
    if not rgb_service:
        raise HTTPException(503, "LED not available")
    return {"led_count": rgb_service.led_count}


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
    rgb_service.clear()
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


@app.post("/audio/volume", response_model=StatusResponse, tags=["Audio"])
def set_volume(req: VolumeRequest):
    """Set system speaker volume (0-100%). Uses amixer on the Pi."""
    controls = ["Line", "Line DAC", "HP"]
    for ctrl in controls:
        try:
            subprocess.run(
                ["amixer", "sset", ctrl, f"{req.volume}%"],
                capture_output=True, text=True, timeout=5,
            )
        except Exception:
            pass
    return {"status": "ok"}


@app.get("/audio/volume", tags=["Audio"])
def get_volume():
    """Get current speaker volume from amixer."""
    for ctrl in ["Line", "Line DAC", "HP"]:
        try:
            result = subprocess.run(
                ["amixer", "sget", ctrl],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                # Parse percentage from amixer output like [75%]
                import re
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

    # Set LED color scaled by intensity
    if rgb_service and preset.get("color"):
        base = preset["color"]
        scaled = [int(c * req.intensity) for c in base]
        try:
            rgb_service.dispatch("solid", tuple(scaled))
            led_color = scaled
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

@app.get("/scene", tags=["Scene"])
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

@app.get("/presence", tags=["Presence"])
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


@app.get("/display", tags=["Display"])
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
    deepgram_api_key: str = Field(..., min_length=1, description="Deepgram API key for STT")
    llm_api_key: str = Field(..., min_length=1, description="OpenAI-compatible API key for TTS")
    llm_base_url: str = Field(..., min_length=1, description="OpenAI-compatible base URL for TTS")


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
        except Exception as e:
            logger.warning(f"TTSService failed: {e}")

    # Start voice (always-on Deepgram streaming STT)
    if voice_service and voice_service.available:
        return {"status": "already_running"}
    if not VoiceService:
        raise HTTPException(503, "Voice service not available (missing deps)")
    try:
        voice_service = VoiceService(
            deepgram_api_key=req.deepgram_api_key,
            input_device=seeed_input_device,
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
    """Synthesize text to speech and play through the speaker (Edge TTS)."""
    if not tts_service or not tts_service.available:
        raise HTTPException(503, "TTS not available")
    started = tts_service.speak(req.text)
    if not started:
        raise HTTPException(409, "TTS is busy speaking")
    return {"status": "ok"}


@app.get("/voice/status", tags=["Voice"])
def voice_status():
    """Get voice pipeline status."""
    return {
        "voice_available": voice_service is not None and voice_service.available if voice_service else False,
        "voice_listening": voice_service.listening if voice_service else False,
        "tts_available": tts_service is not None and tts_service.available if tts_service else False,
        "tts_speaking": tts_service.speaking if tts_service else False,
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
        "display": display_service is not None,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT)
