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

from lelamp.service.motors.animation_service import AnimationService
from lelamp.service.rgb.rgb_service import RGBService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lelamp.server")

# --- Config ---

SERVO_PORT = os.environ.get("LELAMP_SERVO_PORT", "/dev/ttyACM0")
LAMP_ID = os.environ.get("LELAMP_LAMP_ID", "lumi")
SERVO_FPS = int(os.environ.get("LELAMP_SERVO_FPS", "30"))
HTTP_PORT = int(os.environ.get("LELAMP_HTTP_PORT", "5001"))

# --- Services (initialized on startup) ---

animation_service: Optional[AnimationService] = None
rgb_service: Optional[RGBService] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global animation_service, rgb_service

    # Start servo/animation service
    try:
        animation_service = AnimationService(port=SERVO_PORT, lamp_id=LAMP_ID, fps=SERVO_FPS)
        animation_service.start()
        logger.info("AnimationService started")
    except Exception as e:
        logger.warning(f"AnimationService not available: {e}")
        animation_service = None

    # Start RGB LED service
    try:
        rgb_service = RGBService(led_count=64)
        rgb_service.start()
        logger.info("RGBService started")
    except Exception as e:
        logger.warning(f"RGBService not available: {e}")
        rgb_service = None

    yield

    # Shutdown
    if animation_service:
        animation_service.stop()
    if rgb_service:
        rgb_service.stop()


app = FastAPI(title="LeLamp Hardware Runtime", lifespan=lifespan)


# --- Request models ---

class ServoRequest(BaseModel):
    recording: str  # e.g. "nod", "curious", "happy_wiggle"


class LEDSolidRequest(BaseModel):
    color: Union[list[int], int]  # [R, G, B] or packed int


class LEDPaintRequest(BaseModel):
    colors: list[Union[list[int], int]]  # per-pixel colors


# --- Servo endpoints ---

@app.get("/servo")
def get_servo_state():
    if not animation_service:
        raise HTTPException(503, "Servo not available")
    return {
        "available_recordings": animation_service.get_available_recordings(),
        "current": animation_service._current_recording,
    }


@app.post("/servo/play")
def play_recording(req: ServoRequest):
    if not animation_service:
        raise HTTPException(503, "Servo not available")
    animation_service.dispatch("play", req.recording)
    return {"status": "ok", "recording": req.recording}


# --- LED endpoints ---

@app.get("/led")
def get_led_state():
    if not rgb_service:
        raise HTTPException(503, "LED not available")
    return {"led_count": rgb_service.led_count}


@app.post("/led/solid")
def set_led_solid(req: LEDSolidRequest):
    if not rgb_service:
        raise HTTPException(503, "LED not available")
    color = tuple(req.color) if isinstance(req.color, list) else req.color
    rgb_service.dispatch("solid", color)
    return {"status": "ok"}


@app.post("/led/paint")
def set_led_paint(req: LEDPaintRequest):
    if not rgb_service:
        raise HTTPException(503, "LED not available")
    colors = [tuple(c) if isinstance(c, list) else c for c in req.colors]
    rgb_service.dispatch("paint", colors)
    return {"status": "ok"}


@app.post("/led/off")
def turn_off_leds():
    if not rgb_service:
        raise HTTPException(503, "LED not available")
    rgb_service.clear()
    return {"status": "ok"}


# --- Health ---

@app.get("/health")
def health():
    return {
        "status": "ok",
        "servo": animation_service is not None,
        "led": rgb_service is not None,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT)
