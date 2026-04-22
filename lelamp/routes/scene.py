"""Scene route handlers -- /scene endpoints."""

import threading

from fastapi import APIRouter, HTTPException

import lelamp.app_state as state
from lelamp.models import (
    SceneListResponse,
    SceneRequest,
    SceneResponse,
    ServoAimRequest,
    StatusResponse,
)
from lelamp.presets import LST_OFF, LST_SCENE, RGB_CMD_SOLID, SCENE_PRESETS

router = APIRouter(tags=["Scene"])


@router.get("/scene", response_model=SceneListResponse)
def list_scenes():
    """List all available lighting scene presets."""
    return {"scenes": list(SCENE_PRESETS.keys()), "active": state._active_scene}


@router.post("/scene", response_model=SceneResponse)
def activate_scene(req: SceneRequest):
    """Activate a lighting scene preset."""
    preset = SCENE_PRESETS.get(req.scene)
    if not preset:
        available = list(SCENE_PRESETS.keys())
        raise HTTPException(400, f"Unknown scene '{req.scene}'. Available: {available}")

    if not state.rgb_service:
        raise HTTPException(503, "LED not available")

    state._stop_current_effect()
    base = preset["color"]
    brightness = preset["brightness"]
    scaled = [int(c * brightness) for c in base]
    try:
        state.rgb_service.dispatch(RGB_CMD_SOLID, tuple(scaled))
    except Exception as e:
        raise HTTPException(500, f"Failed to set scene: {e}")

    state._active_scene = req.scene
    if state.sensing_service:
        state.sensing_service.presence.set_last_color(tuple(scaled))
    state._save_user_led_state({"type": LST_SCENE, "scene": req.scene})

    aim_dir = preset.get("aim")
    if aim_dir and state.animation_service:
        from lelamp.routes.servo import aim_servo

        threading.Thread(
            target=aim_servo,
            args=(ServoAimRequest(direction=aim_dir),),
            daemon=True,
            name=f"scene-aim-{aim_dir}",
        ).start()

    cam = preset.get("camera")
    if cam == LST_OFF:
        state._auto_camera_off(f"scene:{req.scene}")
    elif cam == "on":
        state._auto_camera_on(f"scene:{req.scene}")

    # Mic control
    mic = preset.get("mic")
    if mic == "off" and not state._mic_muted:
        state._mic_muted = True
        if state.voice_service and state.voice_service.available:
            state.voice_service.stop()
        state.logger.info("Scene %s: mic muted", req.scene)
    elif mic == "on" and state._mic_muted:
        state._mic_muted = False
        state._mic_manual_override = False
        if state.voice_service:
            state.voice_service.start()
        state.logger.info("Scene %s: mic unmuted", req.scene)

    # Speaker control
    spk = preset.get("speaker")
    if spk == "off" and not state._speaker_muted:
        state._speaker_muted = True
        if state.tts_service and state.tts_service.speaking:
            state.tts_service.stop()
        if state.music_service and state.music_service.playing:
            state.music_service.stop()
        state.logger.info("Scene %s: speaker muted", req.scene)
    elif spk == "on" and state._speaker_muted:
        state._speaker_muted = False
        state.logger.info("Scene %s: speaker unmuted", req.scene)

    # Servo hold/release
    servo = preset.get("servo")
    if servo == "hold" and state.animation_service:
        state.animation_service._hold_mode = True
        state.logger.info("Scene %s: servo hold", req.scene)
    elif servo != "hold" and state.animation_service and state.animation_service._hold_mode:
        state.animation_service._hold_mode = False
        state.logger.info("Scene %s: servo released", req.scene)

    return {
        "status": "ok",
        "scene": req.scene,
        "brightness": brightness,
        "color": scaled,
        "aim": aim_dir,
    }
