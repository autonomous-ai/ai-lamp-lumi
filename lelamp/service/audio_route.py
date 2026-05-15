"""Runtime audio routing — hot-swap TTS output + VoiceService input between
the lamp's built-in speaker/mic and a connected Bluetooth headset.

Kept fully decoupled from app_state:
  * lamp defaults are captured the first time a swap is requested
  * all reconfiguration happens through public attributes of the existing
    TTSService / VoiceService instances — no constructor changes
  * sensing (SoundPerception) keeps its own device pointer; it's never
    touched by this module
"""

import logging
import threading
from typing import Optional

import lelamp.app_state as state

logger = logging.getLogger("lelamp.audio_route")

_lock = threading.Lock()

_LAMP_OUT_IDX: Optional[int] = None
_LAMP_IN_IDX: Optional[int] = None
_LAMP_ALSA_IN: Optional[str] = None
_defaults_captured: bool = False

_current_label: str = "lamp"


def _capture_lamp_defaults() -> None:
    """Latch the lamp-default device indices on first call. Re-running is a
    no-op so we never overwrite the originals with a Bluetooth index."""
    global _LAMP_OUT_IDX, _LAMP_IN_IDX, _LAMP_ALSA_IN, _defaults_captured
    if _defaults_captured:
        return
    _LAMP_OUT_IDX = state.audio_output_device
    _LAMP_IN_IDX = state.audio_input_device
    try:
        from lelamp.config import AUDIO_INPUT_ALSA
        _LAMP_ALSA_IN = AUDIO_INPUT_ALSA
    except Exception:
        _LAMP_ALSA_IN = None
    _defaults_captured = True
    logger.info(
        "Lamp audio defaults captured: out=%s in=%s alsa_in=%s",
        _LAMP_OUT_IDX, _LAMP_IN_IDX, _LAMP_ALSA_IN,
    )


def current_label() -> str:
    return _current_label


def _swap_tts(output_idx: Optional[int]) -> None:
    tts = state.tts_service
    if tts is None:
        return
    try:
        if tts.speaking:
            tts.stop()
    except Exception:
        logger.exception("tts.stop failed")
    try:
        tts.release_stream()
    except Exception:
        logger.exception("tts.release_stream failed")
    try:
        tts._output_device = output_idx
        tts._device_rate = None
        tts._stream = None
        tts._stream_rate = None
        if tts._sd is not None:
            tts._probe_device_rate(force=True)
            if tts._device_rate:
                tts._ensure_stream(tts._device_rate)
    except Exception:
        logger.exception("tts device swap failed")


def _swap_voice(input_idx: Optional[int], alsa_device: Optional[str]) -> None:
    vs = state.voice_service
    if vs is None:
        return
    try:
        vs.stop()
    except Exception:
        logger.exception("voice_service.stop failed")
    try:
        vs._input_device = input_idx
        # BT sinks/sources don't have a plughw: equivalent — clear alsa override
        # so VoiceService falls back to sd.InputStream(device=index).
        vs._alsa_device = alsa_device
        vs._device_rate = None
        vs.start()
    except Exception:
        logger.exception("voice_service restart failed")


def route_to_lamp() -> None:
    """Switch TTS + voice back to the lamp's built-in speaker/mic."""
    global _current_label
    _capture_lamp_defaults()
    with _lock:
        logger.info("Route → lamp (out=%s in=%s)", _LAMP_OUT_IDX, _LAMP_IN_IDX)
        _swap_tts(_LAMP_OUT_IDX)
        _swap_voice(_LAMP_IN_IDX, _LAMP_ALSA_IN)
        _current_label = "lamp"


def route_to_bluetooth(output_idx: int, input_idx: Optional[int], mac: str) -> None:
    """Switch TTS + voice to a connected BT headset.

    If the device exposes no input (rare for a true headset; happens for some
    speakers), voice mic falls back to the lamp's built-in mic so STT keeps
    working.
    """
    global _current_label
    _capture_lamp_defaults()
    actual_in = input_idx if input_idx is not None else _LAMP_IN_IDX
    actual_alsa = None if input_idx is not None else _LAMP_ALSA_IN
    with _lock:
        logger.info(
            "Route → bt:%s (out=%s in=%s alsa_in=%s)",
            mac, output_idx, actual_in, actual_alsa,
        )
        _swap_tts(output_idx)
        _swap_voice(actual_in, actual_alsa)
        _current_label = f"bt:{mac}"


def maybe_restore_bt_route() -> None:
    """Called once at server startup after voice_service exists. If the user
    had a BT headset active before reboot, try to reconnect + re-route. Best
    effort — failures fall back silently to the lamp route already in place."""
    try:
        from lelamp.service.bluetooth_manager import BluetoothManager
    except Exception:
        return
    mgr = BluetoothManager()
    mac = mgr.active_mac
    if not mac:
        return
    if not mgr.available():
        logger.info("BT restore skipped — bluetoothctl unavailable")
        return
    logger.info("Restoring BT route to %s on boot", mac)
    try:
        import sounddevice as sd
    except Exception:
        logger.info("BT restore skipped — sounddevice unavailable")
        return
    try:
        if not mgr.info(mac)["connected"]:
            mgr.connect(mac)
        out_idx, in_idx = mgr.find_sd_indices(mac, sd)
        if out_idx is None:
            logger.warning("BT restore: %s did not enumerate in PortAudio", mac)
            return
        route_to_bluetooth(out_idx, in_idx, mac)
    except Exception:
        logger.exception("BT route restore failed")
