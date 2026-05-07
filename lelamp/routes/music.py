"""Music route handlers -- /audio/play, /audio/stop, /audio/status, /audio/history, /speaker/mute|unmute."""

import os
import random
import threading

from fastapi import APIRouter, HTTPException

import lelamp.app_state as state
from lelamp.models import (
    MusicPlayRequest,
    MusicStatusResponse,
    StatusResponse,
)
from lelamp.presets import (
    EMO_CURIOUS,
    EMO_EXCITED,
    EMO_HAPPY,
    EMO_IDLE,
    EMO_SLEEPY,
    EMOTION_PRESETS,
    SERVO_CMD_MUSIC_START,
    SERVO_CMD_MUSIC_STOP,
    SERVO_MUSIC_CHILL,
    SERVO_MUSIC_CLASSICAL,
    SERVO_MUSIC_GROOVE,
    SERVO_MUSIC_HIPHOP,
    SERVO_MUSIC_HYPE,
    SERVO_MUSIC_JAZZ,
    SERVO_MUSIC_ROCK,
    SERVO_MUSIC_WALTZ,
)
from lelamp.service.rgb.effects import run_effect as _run_effect

router = APIRouter()

# --- Music style detection ---

_MUSIC_STYLE_KEYWORDS: list[tuple[str, list[str]]] = [
    (SERVO_MUSIC_JAZZ, ["jazz", "swing", "blues", "soul", "funk", "bossa nova"]),
    (
        SERVO_MUSIC_CLASSICAL,
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
    (SERVO_MUSIC_HIPHOP, ["hip hop", "hiphop", "hip-hop", "rap", "trap", "rnb", "r&b"]),
    (SERVO_MUSIC_ROCK, ["rock", "metal", "punk", "grunge", "heavy", "guitar", "band"]),
    (SERVO_MUSIC_WALTZ, ["waltz", "tango", "ballroom", "foxtrot"]),
    (SERVO_MUSIC_CHILL, ["chill", "lofi", "lo-fi", "lo fi", "ambient", "relax", "mellow", "study", "calm", "sleep"]),
    (SERVO_MUSIC_HYPE, ["hype", "edm", "electronic", "dance", "rave", "party", "upbeat", "electro", "techno", "house", "festival"]),
]

_MUSIC_STYLE_EMOTION: dict[str, str] = {
    SERVO_MUSIC_GROOVE: EMO_HAPPY,
    SERVO_MUSIC_JAZZ: EMO_HAPPY,
    SERVO_MUSIC_CLASSICAL: EMO_CURIOUS,
    SERVO_MUSIC_HIPHOP: EMO_EXCITED,
    SERVO_MUSIC_ROCK: EMO_EXCITED,
    SERVO_MUSIC_WALTZ: EMO_HAPPY,
    SERVO_MUSIC_CHILL: EMO_SLEEPY,
    SERVO_MUSIC_HYPE: EMO_EXCITED,
}


# --- Pre-play backchannel ---
#
# yt-dlp resolve + ffmpeg startup takes 1-3s before audio actually plays.
# A short cached TTS line fills that gap so the lamp sounds responsive.
# Phrases are intentionally generic and short so one cache pool covers
# every style/query. Cache is keyed by provider/voice/model in TTSService.
MUSIC_BACKCHANNEL_PHRASES: list[str] = [
    "On it.",
    "Coming up.",
    "Got it.",
    "Sure thing.",
    "One sec.",
]


def _fire_music_backchannel() -> None:
    """Speak a random short cue if all gates pass.

    Skip when:
      - speaker is muted
      - TTS is already speaking (would queue or be skipped by the lock)
      - music is currently playing (replacing track — backchannel feels redundant)
      - voice_service is mid-STT-session (firing TTS would cut the user off)
    """
    if state._speaker_muted:
        return
    tts = state.tts_service
    if tts is None or not getattr(tts, "available", False):
        return
    if tts.speaking:
        return
    if state.music_service and state.music_service.playing:
        return
    if state.voice_service and state.voice_service.listening:
        state.logger.info("Music backchannel suppressed: STT session active")
        return
    phrase = random.choice(MUSIC_BACKCHANNEL_PHRASES)
    try:
        tts.speak_cached(phrase)
    except Exception as e:
        state.logger.warning("Music backchannel speak failed: %s", e)


def _detect_music_style(query: str) -> str:
    """Return recording name matching the genre keywords in query, else music_groove."""
    q = query.lower()
    for recording, keywords in _MUSIC_STYLE_KEYWORDS:
        if any(k in q for k in keywords):
            return recording
    return SERVO_MUSIC_GROOVE


def _on_music_complete():
    """Restore state after music ends (servo, LED, display)."""
    if state.animation_service:
        state.animation_service.dispatch(SERVO_CMD_MUSIC_STOP, None)

    user_state = state._user_led_state
    state.logger.info("Music stop: restoring state type=%s", user_state.get("type") if user_state else None)
    if user_state is not None and user_state.get("type") != "off":
        state._restore_user_led()
    elif state.rgb_service:
        state.logger.info("Music stop: no active user state -- falling back to idle breathing")
        idle_preset = EMOTION_PRESETS[EMO_IDLE]
        try:
            state._stop_current_effect()
            state._effect_stop.clear()
            state._effect_name = idle_preset["effect"]
            state._effect_thread = threading.Thread(
                target=_run_effect,
                args=(
                    idle_preset["effect"],
                    tuple(idle_preset["color"]),
                    idle_preset.get("speed", 0.3),
                    None,
                    state._effect_stop,
                    state.rgb_service,
                ),
                daemon=True,
                name="led-music-idle",
            )
            state._effect_thread.start()
        except Exception as e:
            state.logger.warning("Music stop LED failed: %s", e)

    if state.display_service:
        try:
            state.display_service.set_expression("neutral")
        except Exception as e:
            state.logger.warning("Music stop display failed: %s", e)


@router.post("/audio/play", response_model=StatusResponse, tags=["Audio"])
def audio_play(req: MusicPlayRequest):
    """Search YouTube and play audio through the speaker."""
    if state._speaker_muted:
        state.logger.info("POST /audio/play: suppressed -- speaker muted (query='%s')", req.query[:80])
        return {"status": "suppressed"}
    if not state.music_service:
        raise HTTPException(503, "Music service not available")
    if not state.music_service.available:
        raise HTTPException(
            503, "Music service not available -- missing sounddevice or numpy"
        )

    # Pre-play backchannel — fires async; music's _play_sync waits for TTS
    # to finish before grabbing ALSA, so the cue plays in series ahead of
    # ffmpeg with no extra serialization here.
    _fire_music_backchannel()

    from lelamp.service.voice.music_service import canonicalize_person

    raw_person = req.person.strip()
    person = canonicalize_person(raw_person) if raw_person else ""
    if raw_person and person != raw_person.lower():
        state.logger.info("POST /audio/play: canonicalized person '%s' -> '%s'", raw_person, person)
    state.logger.info("POST /audio/play: query='%s' person='%s'", req.query[:80], person)
    style = _detect_music_style(req.query)
    state.logger.info("music style detected: %s", style)
    emotion = _MUSIC_STYLE_EMOTION.get(style, EMO_HAPPY)

    def _on_audio_started():
        if state.animation_service:
            state.animation_service.dispatch(SERVO_CMD_MUSIC_START, style)

    if req.query.startswith("/") and os.path.isfile(req.query):
        started = state.music_service.play_file(req.query, person=person)
        if started and state.animation_service:
            state.animation_service.dispatch(SERVO_CMD_MUSIC_START, style)
    else:
        started = state.music_service.play(req.query, on_started=_on_audio_started, person=person)
    if not started:
        raise HTTPException(409, "Music is busy playing")
    state._apply_emotion_led_display(emotion)
    return {"status": "ok"}


@router.post("/audio/stop", response_model=StatusResponse, tags=["Audio"])
def audio_stop():
    """Stop current music playback."""
    if state.music_service and state.music_service.playing:
        state.music_service.stop()
    _on_music_complete()
    return {"status": "ok"}


@router.post("/speaker/mute", response_model=StatusResponse, tags=["Audio"])
def mute_speaker():
    """Mute all audio output -- TTS, music, backchannel suppressed."""
    if state._speaker_muted:
        return {"status": "already_muted"}
    state._speaker_muted = True
    if state.tts_service and state.tts_service.speaking:
        state.tts_service.stop()
    if state.music_service and state.music_service.playing:
        state.music_service.stop()
    state.logger.info("Speaker muted")
    return {"status": "ok"}


@router.post("/speaker/unmute", response_model=StatusResponse, tags=["Audio"])
def unmute_speaker():
    """Unmute audio output."""
    if not state._speaker_muted:
        return {"status": "already_unmuted"}
    state._speaker_muted = False
    state.logger.info("Speaker unmuted")
    return {"status": "ok"}


@router.get("/audio/status", response_model=MusicStatusResponse, tags=["Audio"])
def audio_status():
    """Get music playback status."""
    return {
        "available": state.music_service is not None and state.music_service.available,
        "playing": state.music_service.playing if state.music_service else False,
        "title": state.music_service.current_title if state.music_service else None,
        "speaker_muted": state._speaker_muted,
    }


@router.get("/audio/history", tags=["Audio"])
def audio_history(date: str | None = None, person: str = "", last: int = 50):
    """Return music playback history for AI to learn user preferences."""
    from lelamp.service.voice.music_service import canonicalize_person, query_play_history

    raw_person = person.strip()
    norm_person = canonicalize_person(raw_person) if raw_person else state.DEFAULT_USER
    entries = query_play_history(person=norm_person, date_str=date, last=min(last, 500))
    return {"date": date or "today", "person": norm_person, "entries": entries, "count": len(entries)}
