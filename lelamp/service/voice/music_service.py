"""
Music Service — search YouTube and stream audio through the speaker.

Uses yt-dlp to search and resolve YouTube audio URLs, ffmpeg to decode
and output directly to ALSA device (bypassing sounddevice/PortAudio).
"""

import json
import logging
import re
import subprocess
import sys
import threading
import time
from typing import Optional

logger = logging.getLogger("lelamp.voice.music")
logger.setLevel(logging.DEBUG)


def _detect_alsa_output_device() -> str:
    """Detect ALSA output device from aplay -l.

    Priority: CD002 > Seeed ReSpeaker > any USB audio device.
    Returns plughw:CARD,0 for direct hardware access (handles sample rate
    conversion), or "default" as fallback.
    """
    try:
        result = subprocess.run(["aplay", "-l"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return "default"
        speaker_keywords = ["cd002", "seeed", "usb audio"]
        for keyword in speaker_keywords:
            for line in result.stdout.splitlines():
                if not line.startswith("card "):
                    continue
                if keyword not in line.lower():
                    continue
                m = re.search(r"card \d+: (\S+)", line)
                if m:
                    card = m.group(1)
                    logger.info("Detected ALSA output: plughw:%s,0 (matched '%s')", card, keyword)
                    return f"plughw:{card},0"
    except Exception as e:
        logger.warning("ALSA device detection failed: %s", e)
    logger.info("ALSA output: using default")
    return "default"


# Detect at import time so it's logged during service startup.
# plughw:CARD,0 handles sample rate conversion natively; music and TTS
# use the device exclusively but the service serialises them (music pauses
# while TTS speaks, so no simultaneous access).
ALSA_DEVICE = _detect_alsa_output_device()


class MusicService:
    """YouTube music search + streaming playback via yt-dlp + ffmpeg + ALSA."""

    def __init__(
        self,
        tts_service=None,
        alsa_device: str = ALSA_DEVICE,
    ):
        self._tts_service = tts_service
        self._alsa_device = alsa_device

        self._lock = threading.Lock()
        self._playing = False
        self._stop_event = threading.Event()
        self._ytdlp_proc: Optional[subprocess.Popen] = None
        self._ffmpeg_proc: Optional[subprocess.Popen] = None
        self._current_title: Optional[str] = None

    @property
    def available(self) -> bool:
        return True

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def current_title(self) -> Optional[str]:
        return self._current_title

    def play(self, query: str) -> bool:
        """Search YouTube and play first result. Returns True if started."""
        # Stop current playback if any
        if self._playing:
            self.stop()
            time.sleep(0.3)

        if not self._lock.acquire(blocking=False):
            logger.info("Music busy, skipping: %s", query[:80])
            return False

        self._stop_event.clear()
        thread = threading.Thread(
            target=self._play_sync,
            args=(query,),
            daemon=True,
            name="music-play",
        )
        thread.start()
        return True

    def stop(self):
        """Stop current playback."""
        self._stop_event.set()
        for proc in [self._ffmpeg_proc, self._ytdlp_proc]:
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass

    def _play_sync(self, query: str):
        """Search, resolve audio URL, play via ffmpeg directly to ALSA."""
        try:
            self._playing = True

            # Resolve audio URL via yt-dlp
            logger.info("Searching YouTube: '%s'", query[:80])
            audio_url, title = self._resolve_audio_url(query)
            if not audio_url:
                logger.error("No audio URL found for: '%s'", query[:80])
                return

            self._current_title = title

            # Wait if TTS is speaking (TTS has priority, shares ALSA device)
            if self._tts_service and self._tts_service.speaking:
                logger.info("Waiting for TTS to finish before playing music")
                for _ in range(100):  # max 10s
                    if not self._tts_service.speaking or self._stop_event.is_set():
                        break
                    time.sleep(0.1)
                # Extra wait for ALSA device to be fully released
                time.sleep(0.5)

            if self._stop_event.is_set():
                return

            # Stream: yt-dlp stdout -> ffmpeg stdin -> ALSA (no temp file)
            logger.info("Starting playback: '%s'", title[:80] if title else query[:80])
            self._ytdlp_proc = subprocess.Popen(
                [
                    sys.executable, "-m", "yt_dlp",
                    "--js-runtimes", "node:/usr/bin/node",
                    "--remote-components", "ejs:github",
                    "-f", "bestaudio",
                    "-o", "-",
                    audio_url,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            self._ffmpeg_proc = subprocess.Popen(
                [
                    "ffmpeg",
                    "-i", "pipe:0",
                    "-ar", "44100",
                    "-f", "alsa",
                    self._alsa_device,
                ],
                stdin=self._ytdlp_proc.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            self._ytdlp_proc.stdout.close()

            # Wait for ffmpeg to finish or stop signal
            while not self._stop_event.is_set():
                ret = self._ffmpeg_proc.poll()
                if ret is not None:
                    if ret != 0:
                        stderr = self._ffmpeg_proc.stderr.read().decode(errors="replace")
                        logger.error("ffmpeg exited with code %d: %s", ret, stderr[-500:])
                    break
                # Pause playback while TTS is speaking
                if self._tts_service and self._tts_service.speaking:
                    logger.debug("Pausing music for TTS")
                    self._ffmpeg_proc.terminate()
                    break
                time.sleep(0.2)

            logger.info("Music playback ended")

        except Exception as e:
            logger.error("Music play failed: %s (type=%s)", e, type(e).__name__)
        finally:
            for proc in [self._ffmpeg_proc, self._ytdlp_proc]:
                if proc and proc.poll() is None:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
            self._ffmpeg_proc = None
            self._ytdlp_proc = None
            self._playing = False
            self._current_title = None
            self._lock.release()

    def _resolve_audio_url(self, query: str) -> tuple[Optional[str], Optional[str]]:
        """Use yt-dlp to search YouTube and return (watch_url, title)."""
        try:
            result = subprocess.run(
                [
                    sys.executable, "-m", "yt_dlp",
                    "--js-runtimes", "node:/usr/bin/node",
                    "--remote-components", "ejs:github",
                    "--dump-json",
                    "--no-download",
                    f"ytsearch1:{query}",
                ],
                capture_output=True,
                text=True,
                timeout=90,
            )

            if result.returncode != 0:
                logger.error("yt-dlp failed: %s", result.stderr[:200])
                return None, None

            info = json.loads(result.stdout)
            title = info.get("title", query)
            watch_url = info.get("webpage_url")

            if not watch_url:
                logger.warning("yt-dlp returned no URL for: '%s'", query[:80])
                return None, None

            logger.info("Found: '%s' (%s)", title, watch_url)
            return watch_url, title

        except subprocess.TimeoutExpired:
            logger.error("yt-dlp timed out for: '%s'", query[:80])
            return None, None
        except Exception as e:
            logger.error("yt-dlp resolve failed: %s (type=%s)", e, type(e).__name__)
            return None, None
