"""
Voice Service — local VAD + pluggable STT for autonomous sensing.

Pipeline:
  1. Mic always on, local RMS energy check (free, zero cost)
  2. Speech detected → create STT session, stream audio
  3. Silence for SILENCE_TIMEOUT → close session (stop billing)
  4. Transcripts → POST to Lumi Server /api/sensing/event
  5. Lumi Go → local intent match or OpenClaw → AI responds → POST /voice/speak

STT provider is pluggable (default: Deepgram).
"""

import logging
import threading
import time
from typing import Optional

import requests

from lelamp.service.voice.stt_provider import STTProvider

logger = logging.getLogger("lelamp.voice")

LUMI_SENSING_URL = "http://127.0.0.1:5000/api/sensing/event"

SAMPLE_RATE = 16000
CHANNELS = 1
FRAME_SIZE = 1024  # 64ms at 16kHz

# Local VAD config
RMS_THRESHOLD = 500       # Audio energy above this = speech (tune on device)
RMS_THRESHOLD_MUSIC = 3000  # Higher threshold when music is playing (filter out music from mic)
SILENCE_TIMEOUT_S = 2.5   # Disconnect STT after this much silence
SPEECH_HOLDOFF_S = 0.2    # Minimum speech duration before connecting STT
SESSION_COOLDOWN_S = 0.3  # Cooldown between STT sessions for cleanup

# Echo cancellation config
ECHO_RMS_FLOOR = 200          # RMS must drop below this before re-enabling VAD
ECHO_GATE_MAX_WAIT_S = 1.5   # Max time to wait for reverb decay after TTS
ECHO_GATE_WINDOW_S = 0.05    # RMS check window (50ms)
ECHO_SIMILARITY_THRESHOLD = 0.55  # Transcript similarity above this = echo, drop it
ECHO_RELEVANCE_WINDOW_S = 15.0   # Only filter transcripts within this window after TTS
MAX_SESSION_DURATION_S = 120      # Force-close STT session after this (prevent zombie sessions)

# Wake word patterns (lowercase match)
WAKE_WORDS = ["hey lumi", "hey lu mi", "này lumi", "ê lumi", "lumi ơi"]


class VoiceService:
    """Local VAD + pluggable STT provider for autonomous sensing."""

    def __init__(
            self,
            stt_provider: STTProvider,
            input_device: Optional[int] = None,
            tts_service=None,
            music_service=None,
    ):
        self._stt = stt_provider
        self._input_device = input_device
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._listening = False
        self._tts = tts_service
        self._music = music_service

        # Lazy imports
        self._sd = None
        self._np = None

        try:
            import numpy as np
            self._np = np
        except ImportError:
            logger.warning("numpy not available for voice")

        try:
            import sounddevice as sd
            self._sd = sd
        except ImportError:
            logger.warning("sounddevice not available")

    @property
    def available(self) -> bool:
        return (
                self._sd is not None
                and self._np is not None
                and self._stt.available
        )

    @property
    def listening(self) -> bool:
        return self._listening

    def start(self):
        if self._running:
            return
        if not self.available:
            logger.warning(
                "VoiceService not starting — sd=%s np=%s stt=%s",
                self._sd is not None,
                self._np is not None,
                self._stt.available,
            )
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="voice")
        self._thread.start()
        logger.info("VoiceService started (local VAD + %s)", self._stt.name)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("VoiceService stopped")

    def _rms(self, audio_data) -> float:
        """Calculate RMS energy of audio frame."""
        np = self._np
        samples = audio_data.flatten().astype(np.float32)
        return float(np.sqrt(np.mean(samples ** 2)))

    def _tts_is_speaking(self) -> bool:
        """Check if TTS is currently using the audio device."""
        return self._tts is not None and self._tts.speaking

    def _music_is_playing(self) -> bool:
        """Check if music is currently playing through ALSA."""
        return self._music is not None and self._music.playing

    def _wait_for_tts(self):
        """Block until TTS finishes speaking, then wait for reverb to decay (adaptive RMS gate)."""
        if not self._tts_is_speaking():
            return
        logger.info("TTS is speaking, pausing mic until done...")
        while self._running and self._tts_is_speaking():
            time.sleep(0.2)
        if not self._running:
            return

        # Adaptive RMS gate: wait for reverb/echo to decay instead of fixed sleep
        logger.info("TTS done, waiting for reverb decay (RMS < %d)...", ECHO_RMS_FLOOR)
        sd = self._sd
        np = self._np
        try:
            window_frames = int(SAMPLE_RATE * ECHO_GATE_WINDOW_S)
            elapsed = 0.0
            with sd.InputStream(
                samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16",
                blocksize=window_frames, device=self._input_device,
            ) as tmp_mic:
                while elapsed < ECHO_GATE_MAX_WAIT_S and self._running:
                    data, overflowed = tmp_mic.read(window_frames)
                    if overflowed:
                        continue
                    rms = float(np.sqrt(np.mean(data.astype(np.float32) ** 2)))
                    elapsed += ECHO_GATE_WINDOW_S
                    if rms < ECHO_RMS_FLOOR:
                        logger.info("Reverb decayed (RMS=%.0f < %d) after %.2fs", rms, ECHO_RMS_FLOOR, elapsed)
                        return
            logger.info("Reverb gate timeout after %.1fs, resuming anyway", ECHO_GATE_MAX_WAIT_S)
        except Exception as e:
            logger.warning("RMS gate failed, falling back to fixed delay: %s", e)
            time.sleep(1.0)

    def _loop(self):
        """Main loop: local VAD → STT on speech → disconnect on silence."""
        time.sleep(3)  # Wait for hardware init
        sd = self._sd

        while self._running:
            # Wait for TTS to finish before opening mic
            self._wait_for_tts()

            try:
                with sd.InputStream(
                        samplerate=SAMPLE_RATE,
                        channels=CHANNELS,
                        dtype="int16",
                        blocksize=FRAME_SIZE,
                        device=self._input_device,
                ) as mic:
                    logger.info("Listening locally for speech (RMS threshold=%d)...", RMS_THRESHOLD)
                    self._vad_loop(mic)
            except Exception as e:
                logger.error("Voice loop error: %s", e)
                if self._running:
                    time.sleep(3)

    def _vad_loop(self, mic):
        """Monitor mic with local VAD, connect STT when speech detected.
        Breaks out when TTS starts speaking so _loop can close mic and reopen after."""
        speech_start = None

        while self._running:
            # Yield mic to TTS — break so _loop closes InputStream first
            if self._tts_is_speaking():
                logger.info("TTS started, releasing mic...")
                return

            data, overflowed = mic.read(FRAME_SIZE)
            if overflowed:
                continue

            rms = self._rms(data)

            # Use higher threshold when music is playing to filter out music from mic
            music_on = self._music_is_playing()
            threshold = RMS_THRESHOLD_MUSIC if music_on else RMS_THRESHOLD

            if rms >= threshold:
                if speech_start is None:
                    speech_start = time.time()
                # Wait for holdoff before connecting STT (avoid short noises)
                elif (time.time() - speech_start) >= SPEECH_HOLDOFF_S:
                    logger.info("Speech detected (RMS=%.0f, threshold=%d, music=%s), connecting STT...", rms, threshold, music_on)
                    self._stream_session(mic)
                    speech_start = None
                    # Cooldown after session to let resources clean up
                    time.sleep(SESSION_COOLDOWN_S)
            else:
                speech_start = None

    def _stream_session(self, mic):
        """Stream audio to STT provider until silence or TTS interrupts."""
        session = self._stt.create_session()

        def on_transcript(text: str, is_final: bool):
            if not is_final:
                return
            lower = text.lower()
            # Check for wake word
            is_command = any(w in lower for w in WAKE_WORDS)

            # When music is playing, only accept wake word commands — ignore
            # ambient transcripts which are likely music lyrics picked up by mic
            if self._music_is_playing() and not is_command:
                logger.info("STT ignored during music: '%s'", text[:80])
                return

            if is_command:
                cmd = lower
                for w in WAKE_WORDS:
                    if cmd.startswith(w):
                        cmd = text[len(w):].strip().lstrip(",").strip()
                        break
                logger.info("STT COMMAND: '%s' (wake word detected)", cmd or text)
                self._send_to_lumi(cmd or text, event_type="voice_command")
            else:
                logger.info("STT ambient: '%s'", text)
                self._send_to_lumi(text, event_type="voice")

        try:
            if not session.start(on_transcript):
                return

            self._listening = True
            last_speech_time = time.time()
            session_start = time.time()

            while self._running and not session.is_closed():
                # If TTS starts speaking mid-session, stop streaming immediately
                if self._tts_is_speaking():
                    logger.info("TTS started mid-session, closing STT to avoid echo")
                    break

                # Guard against zombie sessions
                if (time.time() - session_start) > MAX_SESSION_DURATION_S:
                    logger.warning("STT session exceeded %ds, force-closing", MAX_SESSION_DURATION_S)
                    break

                data, overflowed = mic.read(FRAME_SIZE)
                if overflowed:
                    continue

                try:
                    session.send_audio(data.tobytes())
                except Exception as e:
                    logger.warning("send_audio failed (connection dead?): %s", e)
                    break

                rms = self._rms(data)
                if rms >= RMS_THRESHOLD:
                    last_speech_time = time.time()
                elif (time.time() - last_speech_time) > SILENCE_TIMEOUT_S:
                    logger.info("Silence detected, disconnecting STT")
                    break
        except Exception as e:
            logger.error("STT stream error: %s", e)
        finally:
            self._listening = False
            session.close()

    def _is_echo(self, transcript: str) -> bool:
        """Check if transcript is echo of last TTS output (Layer 3: transcript self-filter)."""
        if not self._tts or not self._tts.last_spoken_text:
            return False
        # Only relevant within a time window after TTS finished
        elapsed = time.time() - self._tts.last_spoken_time
        if elapsed > ECHO_RELEVANCE_WINDOW_S:
            return False
        from difflib import SequenceMatcher
        similarity = SequenceMatcher(
            None, transcript.lower(), self._tts.last_spoken_text.lower()
        ).ratio()
        if similarity >= ECHO_SIMILARITY_THRESHOLD:
            logger.info(
                "Echo detected (similarity=%.2f): '%s' ≈ TTS:'%s' — dropping",
                similarity, transcript[:60], self._tts.last_spoken_text[:60],
            )
            return True
        return False

    def _send_to_lumi(self, transcript: str, event_type: str = "voice"):
        """Send voice transcript to Lumi Server as a sensing event (with retry)."""
        # Layer 3: transcript self-filter — drop if it's echo of our own TTS
        if self._is_echo(transcript):
            return

        import json as _json
        payload = {"type": event_type, "message": transcript}
        logger.info("curl -s -X POST %s -H 'Content-Type: application/json' -d '%s'",
                    LUMI_SENSING_URL, _json.dumps(payload))
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(
                    LUMI_SENSING_URL,
                    json=payload,
                    timeout=5,
                )
                if resp.status_code == 503 and attempt < max_retries:
                    logger.warning("Lumi agent not ready (503), retrying in 2s... (attempt %d/%d)", attempt, max_retries)
                    time.sleep(2)
                    continue
                elif resp.status_code != 200:
                    logger.warning("Lumi returned %d: %s", resp.status_code, resp.text)
                else:
                    logger.info("Sent to Lumi: '%s'", transcript[:80])
                return
            except requests.ConnectionError as e:
                if attempt < max_retries:
                    logger.warning("Lumi not reachable (attempt %d/%d), retrying in 2s...", attempt, max_retries)
                    time.sleep(2)
                else:
                    logger.warning("Failed to send voice event to Lumi after %d attempts: %s", max_retries, e)
            except requests.RequestException as e:
                logger.warning("Failed to send voice event to Lumi: %s", e)
                return
