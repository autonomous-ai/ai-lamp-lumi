"""
LeLamp Hardware Runtime — FastAPI server on port 5001.

Only starts the drivers we need. LiveKit/OpenAI code stays untouched but never imported.
Lumi Server (Go, port 5000) bridges requests here.
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Union

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lelamp.server")

# --- Lazy imports for hardware drivers (may not be available on dev machines) ---

AnimationService = None
RGBService = None

try:
    from lelamp.service.motors.animation_service import AnimationService
except ImportError as e:
    logger.warning(f"Servo drivers not available: {e}")

try:
    from lelamp.service.rgb.rgb_service import RGBService
except ImportError as e:
    logger.warning(f"LED drivers not available: {e}")

# --- Config ---

SERVO_PORT = os.environ.get("LELAMP_SERVO_PORT", "/dev/ttyACM0")
LAMP_ID = os.environ.get("LELAMP_LAMP_ID", "lumi")
SERVO_FPS = int(os.environ.get("LELAMP_SERVO_FPS", "30"))
HTTP_PORT = int(os.environ.get("LELAMP_HTTP_PORT", "5001"))

# --- Services (initialized on startup) ---

animation_service = None
rgb_service = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global animation_service, rgb_service

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

    yield

    # Shutdown
    if animation_service:
        animation_service.stop()
    if rgb_service:
        rgb_service.stop()


app = FastAPI(
    title="LeLamp Hardware Runtime",
    description="Hardware driver API for Lumi AI Lamp. "
    "Controls servo motors (5-axis Feetech) and RGB LEDs (64x WS2812). "
    "Lumi Server (Go, port 5000) bridges requests here.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


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


class HealthResponse(BaseModel):
    status: str
    servo: bool
    led: bool


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
    return {"status": "ok", "recording": req.recording}


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


# --- Health ---

@app.get("/health", response_model=HealthResponse, tags=["System"])
def health():
    """Check which hardware drivers are available."""
    return {
        "status": "ok",
        "servo": animation_service is not None,
        "led": rgb_service is not None,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT)
