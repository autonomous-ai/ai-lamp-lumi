"""
Music Service — search YouTube and stream audio through the speaker.

Uses yt-dlp to search and resolve YouTube audio URLs, ffmpeg to decode
and output directly to ALSA device (bypassing sounddevice/PortAudio).
"""

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("lelamp.voice.music")
logger.setLevel(logging.DEBUG)

# Per-user audio history — JSONL logs under /root/local/users/{person}/audio_history/
_USERS_DIR = Path(os.environ.get("LELAMP_USERS_DIR", "/root/local/users"))
_HISTORY_MAX_DAYS = 30


def _history_dir(person: str = "") -> Path:
    """Return history directory for a person, or 'unknown' fallback."""
    if not person:
        person = "unknown"
    return _USERS_DIR / person / "audio_history"


def _history_path(person: str = "", date_str: str | None = None) -> Path:
    """Return path to daily history JSONL file."""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    return _history_dir(person) / f"music_{date_str}.jsonl"


def _log_play_event(
    query: str,
    title: str | None,
    started_at: float,
    ended_at: float,
    stopped_by: str,
    person: str = "",
) -> None:
    """Append a play event to today's history file (per-user if person is set)."""
    try:
        hist_dir = _history_dir(person)
        hist_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": started_at,
            "date": datetime.fromtimestamp(started_at).strftime("%Y-%m-%d"),
            "hour": datetime.fromtimestamp(started_at).hour,
            "query": query,
            "title": title or "",
            "duration_s": round(ended_at - started_at, 1),
            "stopped_by": stopped_by,  # "user" | "end" | "tts" | "error" | "next"
            "person": person,
        }
        path = _history_path(person, entry["date"])
        with open(path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.debug("Audio history logged: %s (%s) person=%s", title, stopped_by, person or "shared")
    except Exception as e:
        logger.warning("Failed to log audio history: %s", e)


def _cleanup_old_history() -> None:
    """Remove history files older than _HISTORY_MAX_DAYS across all users."""
    try:
        if not _USERS_DIR.exists():
            return
        cutoff = time.time() - (_HISTORY_MAX_DAYS * 86400)
        for f in _USERS_DIR.rglob("audio_history/music_*.jsonl"):
            if f.stat().st_mtime < cutoff:
                f.unlink()
                logger.debug("Cleaned up old history: %s", f)
    except Exception as e:
        logger.warning("History cleanup failed: %s", e)


def query_play_history(person: str = "", date_str: str | None = None, last: int = 50) -> list[dict]:
    """Read play history for a person on a given date. Returns most recent `last` entries."""
    path = _history_path(person, date_str)
    if not path.exists():
        return []
    entries = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except Exception as e:
        logger.warning("Failed to read history %s: %s", path, e)
    return entries[-last:]


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
        on_complete=None,
    ):
        self._tts_service = tts_service
        self._alsa_device = alsa_device
        self._on_complete = on_complete

        self._lock = threading.Lock()
        self._playing = False
        self._stop_event = threading.Event()
        self._ytdlp_proc: Optional[subprocess.Popen] = None
        self._ffmpeg_proc: Optional[subprocess.Popen] = None
        self._current_title: Optional[str] = None
        # Per-play callback fired when ffmpeg actually starts (after yt-dlp resolves URL).
        # Set by play() each call; cleared after firing.
        self._on_started = None
        _cleanup_old_history()

    @property
    def available(self) -> bool:
        return True

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def current_title(self) -> Optional[str]:
        return self._current_title

    def play(self, query: str, on_started=None, person: str = "") -> bool:
        """Search YouTube and play first result. Returns True if started.

        on_started: optional callable fired once ffmpeg begins streaming
        (i.e. after yt-dlp resolves the URL). Use this to synchronize
        visual effects (e.g. groove animation) with actual audio start.
        person: who requested the music (for per-user history).
        """
        # Stop current playback if any
        if self._playing:
            self.stop()
            time.sleep(0.3)

        if not self._lock.acquire(blocking=False):
            logger.info("Music busy, skipping: %s", query[:80])
            return False

        self._on_started = on_started
        self._stop_event.clear()
        thread = threading.Thread(
            target=self._play_sync,
            args=(query, person),
            daemon=True,
            name="music-play",
        )
        thread.start()
        return True

    def play_file(self, path: str, title: Optional[str] = None, person: str = "") -> bool:
        """Play a local audio file directly via ffmpeg. Returns True if started."""
        if self._playing:
            self.stop()
            time.sleep(0.3)

        if not self._lock.acquire(blocking=False):
            logger.info("Music busy, skipping file: %s", path)
            return False

        self._stop_event.clear()
        thread = threading.Thread(
            target=self._play_file_sync,
            args=(path, title, person),
            daemon=True,
            name="music-play-file",
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

    def _play_file_sync(self, path: str, title: Optional[str] = None, person: str = ""):
        """Play a local audio file via ffmpeg directly to ALSA."""
        try:
            self._playing = True
            self._current_title = title or path.split("/")[-1]
            _started_at = time.time()
            _stopped_by = "end"

            # Wait if TTS is speaking
            if self._tts_service and self._tts_service.speaking:
                logger.info("Waiting for TTS to finish before playing file")
                for _ in range(100):  # max 10s
                    if not self._tts_service.speaking or self._stop_event.is_set():
                        break
                    time.sleep(0.1)
                time.sleep(0.5)

            if self._stop_event.is_set():
                return

            logger.info("Playing local file: '%s'", path)
            self._ffmpeg_proc = subprocess.Popen(
                [
                    "ffmpeg",
                    "-i", path,
                    "-ar", "44100",
                    "-f", "alsa",
                    self._alsa_device,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )

            while not self._stop_event.is_set():
                ret = self._ffmpeg_proc.poll()
                if ret is not None:
                    if ret != 0:
                        stderr = self._ffmpeg_proc.stderr.read().decode(errors="replace")
                        logger.error("ffmpeg exited with code %d: %s", ret, stderr[-500:])
                        _stopped_by = "error"
                    break
                if self._tts_service and self._tts_service.speaking:
                    logger.debug("Pausing file playback for TTS")
                    self._ffmpeg_proc.terminate()
                    _stopped_by = "tts"
                    break
                time.sleep(0.2)

            if self._stop_event.is_set():
                _stopped_by = "user"

            logger.info("File playback ended")

        except Exception as e:
            logger.error("File play failed: %s (type=%s)", e, type(e).__name__)
            _stopped_by = "error"
        finally:
            if self._ffmpeg_proc and self._ffmpeg_proc.poll() is None:
                try:
                    self._ffmpeg_proc.terminate()
                except Exception:
                    pass
            _log_play_event(path, self._current_title, _started_at, time.time(), _stopped_by, person)
            self._ffmpeg_proc = None
            self._playing = False
            self._current_title = None
            self._lock.release()
            if self._on_complete:
                try:
                    self._on_complete()
                except Exception as e:
                    logger.warning("on_complete callback failed: %s", e)

    def _play_sync(self, query: str, person: str = ""):
        """Search, resolve audio URL, play via ffmpeg directly to ALSA."""
        _started_at = time.time()
        _stopped_by = "end"
        try:
            self._playing = True

            # Resolve audio URL via yt-dlp
            logger.info("Searching YouTube: '%s'", query[:80])
            audio_url, title = self._resolve_audio_url(query)
            if not audio_url:
                logger.error("No audio URL found for: '%s'", query[:80])
                _stopped_by = "error"
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
                    "-threads", "1",
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

            # Notify caller that audio is actually starting (yt-dlp resolved, ffmpeg running).
            if self._on_started:
                try:
                    self._on_started()
                except Exception as e:
                    logger.warning("on_started callback failed: %s", e)
                self._on_started = None

            # Wait for ffmpeg to finish or stop signal
            while not self._stop_event.is_set():
                ret = self._ffmpeg_proc.poll()
                if ret is not None:
                    if ret != 0:
                        stderr = self._ffmpeg_proc.stderr.read().decode(errors="replace")
                        logger.error("ffmpeg exited with code %d: %s", ret, stderr[-500:])
                        _stopped_by = "error"
                    break
                # Pause playback while TTS is speaking
                if self._tts_service and self._tts_service.speaking:
                    logger.debug("Pausing music for TTS")
                    self._ffmpeg_proc.terminate()
                    _stopped_by = "tts"
                    break
                time.sleep(0.2)

            if self._stop_event.is_set():
                _stopped_by = "user"

            logger.info("Music playback ended")

        except Exception as e:
            logger.error("Music play failed: %s (type=%s)", e, type(e).__name__)
            _stopped_by = "error"
        finally:
            for proc in [self._ffmpeg_proc, self._ytdlp_proc]:
                if proc and proc.poll() is None:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
            _log_play_event(query, self._current_title, _started_at, time.time(), _stopped_by, person)
            self._ffmpeg_proc = None
            self._ytdlp_proc = None
            self._playing = False
            self._current_title = None
            self._lock.release()
            if self._on_complete:
                try:
                    self._on_complete()
                except Exception as e:
                    logger.warning("on_complete callback failed: %s", e)

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
