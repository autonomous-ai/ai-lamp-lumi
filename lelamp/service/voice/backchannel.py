"""
Backchannel — active listening cues during STT sessions.

Plays short filler words ("Uhm", "Ok", etc.) via TTS when the user pauses
mid-speech, signaling that Lumi is still listening.

Usage:
    bc = Backchannel(tts_service)
    bc.on_partial("hello I want to")   # call on every STT partial
    bc.reset()                          # call when STT session ends

Feature is disabled when LELAMP_BACKCHANNEL_FILLERS env var is empty.

Does NOT use tts_service.speak() — that would set the speaking flag and
kill the active STT session. Instead calls TTS API directly and plays
audio without touching the speaking flag.

Config (env vars):
    LELAMP_BACKCHANNEL_FILLERS     comma-separated filler words (empty = disabled)
    LELAMP_BACKCHANNEL_STALL_S     partial unchanged for N seconds → play cue (0 = every partial)
    LELAMP_BACKCHANNEL_INTERVAL_S  min seconds between cues
    LELAMP_BACKCHANNEL_VOLUME      volume multiplier 0.0–1.0
"""

import logging
import math
import os
import random
import threading
import time
from typing import Optional

logger = logging.getLogger("lelamp.voice.backchannel")

# Config from env
# Comma-separated filler words to play as listening cues. Empty string = feature disabled.
_fillers_env = os.environ.get("LELAMP_BACKCHANNEL_FILLERS", "Uhm,Ok,Hmm,Yeah,Uh huh,Right,Sure,Mm,Ah,Oh ok,Yep,I see")
FILLERS = [w.strip() for w in _fillers_env.split(",") if w.strip()]
# How long (seconds) the partial transcript must stay unchanged before playing a cue.
# 0 = play on every new partial (still throttled by MIN_INTERVAL_S).
STALL_TIMEOUT_S = float(os.environ.get("LELAMP_BACKCHANNEL_STALL_S", "0.1"))
# Minimum seconds between two consecutive cues (prevents spamming).
MIN_INTERVAL_S = float(os.environ.get("LELAMP_BACKCHANNEL_INTERVAL_S", "3.0"))
# Volume multiplier for cue audio relative to normal TTS (0.0 = silent, 1.0 = full).
VOLUME = float(os.environ.get("LELAMP_BACKCHANNEL_VOLUME", "0.5"))


class Backchannel:
    """Monitor STT partials and play filler words when user pauses mid-speech."""

    def __init__(self, tts_service):
        self._tts = tts_service
        self._last_partial: str = ""
        self._last_cue_time: float = 0.0
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None

        if FILLERS:
            logger.info("Backchannel enabled: fillers=%s, stall=%.1fs, interval=%.1fs",
                        FILLERS, STALL_TIMEOUT_S, MIN_INTERVAL_S)

    @property
    def enabled(self) -> bool:
        return len(FILLERS) > 0

    def on_partial(self, text: str) -> None:
        """Called on each STT partial. Schedules a cue if partial stalls."""
        if not FILLERS:
            return
        with self._lock:
            if text == self._last_partial:
                return
            self._last_partial = text
            self._cancel_timer()
            if STALL_TIMEOUT_S <= 0:
                self._fire_cue()
            else:
                self._timer = threading.Timer(STALL_TIMEOUT_S, self._fire_cue)
                self._timer.daemon = True
                self._timer.start()

    def reset(self) -> None:
        """Reset state when STT session ends."""
        with self._lock:
            self._cancel_timer()
            self._last_partial = ""

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _fire_cue(self) -> None:
        """Check interval, then play a random filler in background thread."""
        now = time.time()
        if (now - self._last_cue_time) < MIN_INTERVAL_S:
            logger.info("Backchannel skipped: interval cooldown (%.1fs < %.1fs)",
                        now - self._last_cue_time, MIN_INTERVAL_S)
            return
        if not self._last_partial.strip():
            return
        if self._tts is not None and self._tts.speaking:
            logger.info("Backchannel skipped: TTS is speaking")
            return
        self._last_cue_time = now
        filler = random.choice(FILLERS)
        logger.info("Backchannel: '%s'", filler)
        threading.Thread(target=self._play, args=(filler,), daemon=True, name="bc-cue").start()

    def _play(self, text: str) -> None:
        """Play a short TTS cue directly, bypassing tts_service.speak()."""
        tts = self._tts
        if tts is None or tts._client is None or tts._sd is None:
            return
        try:
            import numpy as np
            dst_rate = tts._device_rate or 24000
            with tts._client.audio.speech.with_streaming_response.create(
                model=tts._model,
                voice=tts._voice,
                input=text,
                response_format="pcm",
                speed=tts._speed,
            ) as response:
                raw = response.read()
            if len(raw) < 2:
                return
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            samples *= max(0.0, min(1.0, VOLUME))
            src_rate = 24000
            if dst_rate != src_rate:
                ratio = dst_rate / src_rate
                n_out = math.ceil(len(samples) * ratio)
                x_old = np.linspace(0, 1, len(samples))
                x_new = np.linspace(0, 1, n_out)
                samples = np.interp(x_new, x_old, samples).astype(np.float32)
            with tts._sd.OutputStream(
                samplerate=dst_rate, channels=1, dtype="float32",
                device=tts._output_device,
            ) as stream:
                stream.write(samples.reshape(-1, 1))
            logger.info("Backchannel played: '%s'", text)
        except Exception as e:
            logger.warning("Backchannel play failed: %s", e)
