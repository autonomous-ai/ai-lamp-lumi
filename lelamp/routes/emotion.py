"""Emotion route handler -- /emotion endpoint."""

from fastapi import APIRouter, HTTPException

import lelamp.app_state as state
from lelamp.models import EmotionRequest, EmotionResponse
from lelamp.presets import (
    EMOTION_PRESETS,
    EMO_CARING,
    EMO_CONFUSED,
    EMO_CURIOUS,
    EMO_EXCITED,
    EMO_GREETING,
    EMO_HAPPY,
    EMO_IDLE,
    EMO_LAUGH,
    EMO_SAD,
    EMO_SHOCK,
    EMO_SHY,
    EMO_SLEEPY,
    EMO_STRETCHING,
    LST_OFF,
    SERVO_CMD_PLAY,
)

# Emotions that can wake the lamp from sleep.
# greeting/stretching/sleepy = direct wake triggers.
# happy/excited/caring/laugh/curious/sad/shy/shock/confused = agent responding to user interaction.
# thinking/idle/acknowledge/nod/headshake/scan/music_* do NOT wake (background processing).
_WAKE_EMOTIONS = {
    EMO_GREETING, EMO_STRETCHING, EMO_SLEEPY,
    EMO_HAPPY, EMO_EXCITED, EMO_CARING, EMO_LAUGH, EMO_CURIOUS,
    EMO_SAD, EMO_SHY, EMO_SHOCK, EMO_CONFUSED,
}

router = APIRouter(tags=["Emotion"])


@router.get("/emotion/status")
def emotion_status():
    """Return current emotion state."""
    return {
        "current_emotion": state._current_emotion,
        "sleeping": state._sleeping,
        "active_scene": state._active_scene,
    }


@router.get("/emotion/presets")
def list_emotion_presets():
    """Return all available emotion presets with their LED color and effect."""
    result = {}
    for name, preset in EMOTION_PRESETS.items():
        result[name] = {
            "color": preset.get("color"),
            "effect": preset.get("effect"),
            "speed": preset.get("speed"),
        }
    return result


@router.post("/emotion", response_model=EmotionResponse)
def express_emotion(req: EmotionRequest):
    """Express an emotion by coordinating servo animation + LED color simultaneously."""
    preset = EMOTION_PRESETS.get(req.emotion)
    if not preset:
        available = list(EMOTION_PRESETS.keys())
        raise HTTPException(
            400, f"Unknown emotion '{req.emotion}'. Available: {available}"
        )

    state.logger.info("POST /emotion: emotion=%s intensity=%s user_state=%s sleeping=%s",
                       req.emotion, req.intensity,
                       state._user_led_state.get("type") if state._user_led_state else None,
                       state._sleeping)

    if state._sleeping and req.emotion not in _WAKE_EMOTIONS:
        state.logger.info("POST /emotion: ignored %s while sleeping", req.emotion)
        return {"status": "ignored", "emotion": req.emotion, "servo": None, "led": None}

    was_sleeping = state._sleeping
    state._sleeping = req.emotion == EMO_SLEEPY
    state._current_emotion = req.emotion

    # Auto-off scene when waking from sleep (e.g. Night mode → restore peripherals)
    if was_sleeping and not state._sleeping and state._active_scene:
        from lelamp.routes.scene import deactivate_scene
        state.logger.info("POST /emotion: waking from sleep, auto scene off (%s)", state._active_scene)
        deactivate_scene()

    # When servo is in hold mode (focus/reading scene), suppress emotion
    # animations to avoid distraction. Only scene-changing emotions pass through.
    servo_held = state.animation_service and getattr(state.animation_service, "_hold_mode", False)
    scene_change = req.emotion in {EMO_GREETING, EMO_SLEEPY, EMO_STRETCHING}

    servo_played = None

    if state.animation_service and preset.get("servo") and (not servo_held or scene_change):
        try:
            state.animation_service.dispatch(SERVO_CMD_PLAY, preset["servo"])
            servo_played = preset["servo"]
        except Exception as e:
            state.logger.warning(f"Emotion servo failed: {e}")
    elif servo_held:
        state.logger.info("POST /emotion: servo suppressed (%s) -- hold mode", req.emotion)

    led_color = state._apply_emotion_led_display(req.emotion, req.intensity) if not servo_held or scene_change else None

    if req.emotion == EMO_IDLE:
        pass
    elif req.emotion == EMO_SLEEPY:
        pass
    elif req.emotion == EMO_SHOCK:
        state._schedule_led_restore(2.0)
        state.logger.info("Emotion: shock -- LED restore scheduled in 2.0s")
    else:
        servo_name = preset.get("servo", "")
        restore_delay = state._get_recording_duration(servo_name) + 0.5 if servo_name else 3.5
        state.logger.info("Emotion: %s -- LED restore scheduled in %.1fs (servo=%s)", req.emotion, restore_delay, servo_name)
        state._schedule_led_restore(restore_delay)

    cam = preset.get("camera")
    if cam == LST_OFF:
        state._auto_camera_off(f"emotion:{req.emotion}")
    elif cam == "on" and state._camera_disabled:
        state._auto_camera_on(f"emotion:{req.emotion}")

    return {
        "status": "ok",
        "emotion": req.emotion,
        "servo": servo_played,
        "led": led_color,
    }
