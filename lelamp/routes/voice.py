"""Voice route handlers -- /voice/*, /tts/* endpoints."""

from typing import Optional

from fastapi import APIRouter, HTTPException

import lelamp.app_state as state
from lelamp.config import AUDIO_INPUT_ALSA, TTS_SPEED, TTS_VOICE, TTS_INSTRUCTIONS
from lelamp.models import (
    SpeakRequest,
    StatusResponse,
    VoiceConfigRequest,
    VoiceStartRequest,
    VoiceStatusResponse,
)

router = APIRouter(tags=["Voice"])

# Lazy imports
sd = None
np = None
VoiceService = None
DeepgramSTT = None
AutonomousSTT = None
TTSService = None

try:
    import numpy as np
    import sounddevice as sd
except ImportError:
    pass

try:
    from lelamp.service.voice.stt_autonomous import AutonomousSTT
    from lelamp.service.voice.stt_deepgram import DeepgramSTT
    from lelamp.service.voice.voice_service import VoiceService
except ImportError:
    pass

try:
    from lelamp.service.voice.tts_service import TTSService
    from lelamp.service.voice.tts_backend import PROVIDER_OPENAI
except ImportError:
    PROVIDER_OPENAI = "openai"


@router.post("/voice/start", response_model=StatusResponse)
def start_voice(req: VoiceStartRequest):
    """Start the voice pipeline (always-on Deepgram STT + TTS)."""
    voice = req.tts_voice or TTS_VOICE
    instructions = req.tts_instructions or TTS_INSTRUCTIONS or None

    need_tts = TTSService and (
        not (state.tts_service and state.tts_service.available)
        or (state.tts_service and state.tts_service._voice != voice)
        or (state.tts_service and getattr(state.tts_service, "_instructions", None) != instructions)
        or (state.tts_service and getattr(state.tts_service, "_provider", None) != req.tts_provider)
    )
    if need_tts:
        if state.tts_service and state.tts_service.speaking:
            state.tts_service.stop()
        try:
            state.tts_service = TTSService(
                api_key=req.llm_api_key,
                base_url=req.llm_base_url,
                sound_device_module=sd,
                numpy_module=np,
                output_device=state.audio_output_device,
                voice=voice,
                speed=TTS_SPEED,
                instructions=instructions,
                on_speak_start=state._on_tts_speak_start,
                on_speak_end=state._on_tts_speak_end,
                provider=req.tts_provider,
            )
            state.logger.info("TTSService started (provider=%s, voice=%s)", req.tts_provider, voice)
            if state.music_service:
                state.music_service._tts_service = state.tts_service
        except Exception as e:
            state.logger.warning(f"TTSService failed: {e}")

    if state.voice_service and state.voice_service.available:
        if need_tts and state.tts_service:
            state.voice_service._tts = state.tts_service
            if hasattr(state.voice_service, '_backchannel') and state.voice_service._backchannel:
                state.voice_service._backchannel._tts = state.tts_service
            state.logger.info("Updated TTS in running voice service (voice=%s)", voice)
        return {"status": "already_running"}
    if not VoiceService:
        raise HTTPException(503, "Voice service not available (missing deps)")
    try:
        stt_provider = None
        if req.deepgram_api_key and DeepgramSTT:
            agent_name = state._read_agent_name({})
            stt_provider = DeepgramSTT(api_key=req.deepgram_api_key, keywords=[f"{agent_name}:3"])
        elif AutonomousSTT:
            stt_provider = AutonomousSTT(
                api_key=req.llm_api_key, base_url=req.llm_base_url
            )
        if not stt_provider:
            raise HTTPException(503, "No STT provider available")
        wake_words = state._build_wake_words(state._read_agent_name({}))
        state.voice_service = VoiceService(
            stt_provider=stt_provider,
            input_device=state.audio_input_device,
            tts_service=state.tts_service,
            music_service=state.music_service,
            wake_words=wake_words,
            alsa_device=AUDIO_INPUT_ALSA,
        )
        state.voice_service.start()
        return {"status": "ok"}
    except Exception as e:
        state.voice_service = None
        raise HTTPException(500, f"Failed to start voice: {e}")


@router.post("/voice/stop", response_model=StatusResponse)
def stop_voice():
    """Stop the voice pipeline."""
    if state.voice_service:
        state.voice_service.stop()
        state.voice_service = None
    state.tts_service = None
    return {"status": "ok"}


@router.post("/voice/config", response_model=StatusResponse)
def update_voice_config(req: VoiceConfigRequest):
    """Update voice pipeline config at runtime."""
    if not state.voice_service:
        return {"status": "ok"}
    state.voice_service.set_wake_words(req.wake_words)
    return {"status": "ok"}


@router.get("/voice/voices")
def get_voices(provider: Optional[str] = None):
    """Return available TTS voices for the requested (or current) provider."""
    from lelamp.service.voice.tts_elevenlabs import ElevenLabsTTSBackend
    from lelamp.service.voice.tts_backend import PROVIDER_ELEVENLABS, PROVIDER_OPENAI as _PO
    if provider is None:
        provider = getattr(state.tts_service, "_provider", _PO) if state.tts_service else _PO
    if provider == PROVIDER_ELEVENLABS:
        return {"provider": provider, "voices": list(ElevenLabsTTSBackend.VOICE_IDS.keys())}
    return {"provider": provider, "voices": ["alloy", "ash", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer"]}


@router.post("/voice/speak", response_model=StatusResponse)
def speak_text(req: SpeakRequest):
    """Synthesize text to speech and play through the speaker."""
    if not state.tts_service:
        state.logger.error("POST /voice/speak: tts_service is None (not initialized)")
        raise HTTPException(
            503,
            "TTS not initialized -- call /voice/start first or check lumi config has llm_api_key + llm_base_url",
        )
    if not state.tts_service.available:
        state.logger.error(
            "POST /voice/speak: tts_service not available -- backend=%s, sd=%s",
            state.tts_service._backend is not None and state.tts_service._backend.available,
            state.tts_service._sd is not None,
        )
        raise HTTPException(
            503, "TTS not available -- missing openai SDK or sounddevice"
        )
    if state._speaker_muted:
        state.logger.info("POST /voice/speak: suppressed -- speaker muted (text='%s')", req.text[:80])
        return {"status": "suppressed"}
    if state.music_service and state.music_service.playing:
        state.logger.info(
            "POST /voice/speak: rejected -- music is playing (text='%s')", req.text[:80]
        )
        raise HTTPException(409, "Speaker busy -- music is playing")
    if req.voice:
        state.tts_service._voice = req.voice
    state.logger.info("POST /voice/speak: req=%s", req.model_dump_json())
    started = state.tts_service.speak(req.text, interruptible=req.interruptible)
    if not started:
        raise HTTPException(409, "TTS is busy speaking")
    return {"status": "ok"}


@router.post("/tts/stop", response_model=StatusResponse)
def stop_tts():
    """Interrupt active TTS playback immediately."""
    if state.tts_service:
        state.tts_service.stop()
    return {"status": "ok"}


@router.post("/voice/mute", response_model=StatusResponse)
def mute_mic():
    """Mute mic -- stop voice pipeline and sound perception."""
    if state._mic_muted:
        return {"status": "already_muted"}
    state._mic_muted = True
    state._mic_manual_override = True
    if state.voice_service and state.voice_service.available:
        state.voice_service.stop()
    state.logger.info("Mic muted by user")
    return {"status": "ok"}


@router.post("/voice/unmute", response_model=StatusResponse)
def unmute_mic():
    """Unmute mic -- restart voice pipeline."""
    if not state._mic_muted:
        return {"status": "already_unmuted"}
    state._mic_muted = False
    state._mic_manual_override = False
    if state.voice_service:
        state.voice_service.start()
    state.logger.info("Mic unmuted")
    return {"status": "ok"}


@router.get("/voice/status", response_model=VoiceStatusResponse)
def voice_status():
    """Get voice pipeline status."""
    tts_detail = None
    if state.tts_service:
        tts_detail = {
            "has_backend": state.tts_service._backend is not None and state.tts_service._backend.available,
            "has_sd": state.tts_service._sd is not None,
            "provider": getattr(state.tts_service, "_provider", "unknown"),
        }
    return {
        "voice_available": state.voice_service is not None and state.voice_service.available
        if state.voice_service
        else False,
        "voice_listening": state.voice_service.listening if state.voice_service else False,
        "tts_available": state.tts_service is not None and state.tts_service.available
        if state.tts_service
        else False,
        "tts_speaking": state.tts_service.speaking if state.tts_service else False,
        "tts_detail": tts_detail,
        "mic_muted": state._mic_muted,
    }
