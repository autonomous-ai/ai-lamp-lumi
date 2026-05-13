"""Shared button/touch actions.

Reused by any input device that maps to the same three gestures:
- single_click_action(): stop speaker / unmute mic + announce listening
- triple_click_action(): reboot OS
- long_press_action():  shutdown OS

Callers (GPIO button, touchpad, future remotes) only need to detect the
gesture and invoke the matching function — the destructive sequencing
(TTS announce → servo park → shutdown/reboot) lives here so every input
path gets the same safe behavior.
"""

import logging
import subprocess
import threading
import time

import lelamp.app_state as state

logger = logging.getLogger(__name__)

DOUBLE_CLICK_WINDOW = 0.4  # seconds to wait for second click
LONG_PRESS_DURATION = 5.0  # seconds to hold for shutdown

# Localized action announcements. reboot/shutdown phrases stay literal
# in every language ("rebooting", "shutting down") because the user just
# triggered a destructive gesture and needs explicit confirmation of
# which action fired — this is a safety announcement, not a persona
# moment. Empty/unknown stt_language → English.
_PHRASES_BY_LANG = {
    "listening": {
        "en": "I'm listening!",
        "vi": "Mình nghe đây!",
        "zh-CN": "我在听！",
        "zh-TW": "我在聽！",
    },
    "reboot": {
        "en": "Rebooting now.",
        "vi": "Đang khởi động lại.",
        "zh-CN": "正在重启。",
        "zh-TW": "正在重啟。",
    },
    "shutdown": {
        "en": "Shutting down now.",
        "vi": "Đang tắt máy.",
        "zh-CN": "正在关机。",
        "zh-TW": "正在關機。",
    },
}


def _phrase(key: str) -> str:
    """Return the localized phrase for `key` based on Lumi's stt_language.
    Falls back to English when the config can't be read or the language
    is empty/unknown."""
    try:
        from lelamp.config import _lumi_cfg_get
        lang = (_lumi_cfg_get("stt_language") or "").strip()
    except Exception:
        lang = ""
    pool = _PHRASES_BY_LANG.get(key, {})
    return pool.get(lang) or pool.get("en", "")


def _announce_listening():
    """Speak the localized listening cue, preempting any in-flight TTS.
    speak_cached() uses a non-blocking acquire — if the service is busy
    and the current speech wasn't marked interruptible, the cue is
    silently dropped. stop() flips stop_event but only the playback loop
    checks it; if the previous speech is in the render phase (live TTS
    round-trip, 2-5s), the lock won't free until render + short play
    break finish. Retry with backoff so the cue lands as soon as the
    lock releases. ~6s total cap covers a worst-case fresh render before
    giving up silently."""
    text = _phrase("listening")
    state.tts_service.stop()
    for delay in (0.15, 0.4, 0.8, 1.6, 3.0):
        time.sleep(delay)
        if state.tts_service.speak_cached(text):
            return
    logger.warning("listening cue dropped: TTS busy after retries")


def _tts_available() -> bool:
    return bool(
        state.tts_service
        and state.tts_service.available
        and not state._speaker_muted
    )


def single_click_action(source: str = "button"):
    """Stop in-flight speech / unmute mic, then announce listening cue."""
    from lelamp.routes.music import audio_stop
    from lelamp.routes.voice import stop_tts, unmute_mic

    if state._mic_muted:
        logger.info("%s single click -- unmuting mic", source)
        unmute_mic()
    else:
        logger.info("%s single click -- stopping speaker", source)
        stop_tts()
        audio_stop()
    # Always announce the listening cue so the user hears confirmation
    # of the click — both for unmute (mic just opened) and for
    # stop-speaker (Lumi was talking, user wants the floor). The cue
    # itself preempts in-flight TTS via stop() + speak_cached retry,
    # so calling stop_tts() above is fine — _announce_listening handles
    # the lock handoff.
    if _tts_available():
        threading.Thread(
            target=_announce_listening,
            daemon=True,
            name=f"{source}-single-click-tts",
        ).start()


def triple_click_action(source: str = "button"):
    """Announce + reboot OS."""
    logger.info("%s triple click -- rebooting OS", source)
    if _tts_available():
        state.tts_service.speak_cached(_phrase("reboot"))
        # speak_cached is async; reboot kicks the OS before audio plays
        # without this. ~5s covers the cached "Rebooting now" clip
        # (matches long_press_action shutdown delay).
        time.sleep(5)
    subprocess.Popen(
        ["sudo", "reboot"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def long_press_action(source: str = "button"):
    """Announce, park servos, then shutdown OS."""
    logger.info("%s long press -- shutting down OS", source)

    # Step 1: TTS announce.
    if _tts_available():
        state.tts_service.speak_cached(_phrase("shutdown"))
        time.sleep(5)

    # Step 2: park servo in safe pose then cut torque, otherwise the
    # body slams down when systemd kills the process mid-pose.
    try:
        from lelamp.routes.servo import release_servos

        logger.info("%s long press -- releasing servo before shutdown", source)
        release_servos()
    except Exception as e:
        logger.warning(f"Servo release before shutdown failed: {e}")

    # Step 3: shutdown OS.
    subprocess.Popen(
        ["sudo", "shutdown", "-h", "now"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
