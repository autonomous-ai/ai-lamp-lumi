"""
Music Service — search YouTube and stream audio through the speaker.

Uses yt-dlp to search and resolve YouTube audio URLs, ffmpeg to decode to PCM,
and sounddevice to play through the Seeed 2-mic HAT speaker.
"""

import json
import logging
import subprocess
import threading
import time
from typing import Optional

logger = logging.getLogger("lelamp.voice.music")
logger.setLevel(logging.DEBUG)

# ffmpeg output format
SAMPLE_RATE = 48000
CHANNELS = 1
CHUNK_SIZE = 8192  # bytes per read from ffmpeg stdout


class MusicService:
    """YouTube music search + streaming playback via yt-dlp + ffmpeg + sounddevice."""

    def __init__(
        self,
        sound_device_module=None,
        numpy_module=None,
        output_device: Optional[int] = None,
        tts_service=None,
    ):
        self._sd = sound_device_module
        self._np = numpy_module
        self._output_device = output_device
        self._tts_service = tts_service

        self._lock = threading.Lock()
        self._playing = False
        self._stop_event = threading.Event()
        self._ffmpeg_proc: Optional[subprocess.Popen] = None
        self._current_title: Optional[str] = None

    @property
    def available(self) -> bool:
        return self._sd is not None and self._np is not None

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def current_title(self) -> Optional[str]:
        return self._current_title

    def play(self, query: str) -> bool:
        """Search YouTube and play first result. Returns True if started."""
        if not self.available:
            logger.warning("MusicService not available (missing sounddevice or numpy)")
            return False

        # Stop current playback if any
        if self._playing:
            self.stop()
            # Wait briefly for cleanup
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
        if self._ffmpeg_proc and self._ffmpeg_proc.poll() is None:
            try:
                self._ffmpeg_proc.terminate()
            except Exception:
                pass

    def _play_sync(self, query: str):
        """Search, resolve audio URL, pipe through ffmpeg, play via sounddevice."""
        sd = self._sd
        np = self._np

        try:
            self._playing = True

            # Resolve audio URL via yt-dlp
            logger.info("Searching YouTube: '%s'", query[:80])
            audio_url, title = self._resolve_audio_url(query)
            if not audio_url:
                logger.error("No audio URL found for: '%s'", query[:80])
                return

            self._current_title = title

            # Wait if TTS is speaking (TTS has priority)
            if self._tts_service and self._tts_service.speaking:
                logger.info("Waiting for TTS to finish before playing music")
                for _ in range(100):  # max 10s
                    if not self._tts_service.speaking or self._stop_event.is_set():
                        break
                    time.sleep(0.1)

            if self._stop_event.is_set():
                return

            # Pipe through ffmpeg to get raw PCM
            logger.info("Starting ffmpeg stream for: '%s'", title[:80] if title else query[:80])
            self._ffmpeg_proc = subprocess.Popen(
                [
                    "ffmpeg",
                    "-reconnect", "1",
                    "-reconnect_streamed", "1",
                    "-i", audio_url,
                    "-f", "s16le",
                    "-ar", str(SAMPLE_RATE),
                    "-ac", str(CHANNELS),
                    "pipe:1",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )

            total_samples = 0
            with sd.OutputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
                device=self._output_device,
            ) as stream:
                while not self._stop_event.is_set():
                    chunk = self._ffmpeg_proc.stdout.read(CHUNK_SIZE)
                    if not chunk:
                        break

                    # Pause playback while TTS is speaking
                    if self._tts_service and self._tts_service.speaking:
                        logger.debug("Pausing music for TTS")
                        while self._tts_service.speaking and not self._stop_event.is_set():
                            time.sleep(0.1)
                        if self._stop_event.is_set():
                            break

                    # Ensure 2-byte alignment for int16
                    usable = len(chunk) - (len(chunk) % 2)
                    if usable == 0:
                        continue

                    samples = (
                        np.frombuffer(chunk[:usable], dtype=np.int16).astype(np.float32)
                        / 32768.0
                    )
                    stream.write(samples.reshape(-1, 1))
                    total_samples += len(samples)

            logger.info("Music playback complete (%d samples)", total_samples)

        except Exception as e:
            logger.error("Music play failed: %s (type=%s)", e, type(e).__name__)
        finally:
            if self._ffmpeg_proc and self._ffmpeg_proc.poll() is None:
                self._ffmpeg_proc.terminate()
            self._ffmpeg_proc = None
            self._playing = False
            self._current_title = None
            self._lock.release()

    def _resolve_audio_url(self, query: str) -> tuple[Optional[str], Optional[str]]:
        """Use yt-dlp to search YouTube and return (audio_url, title)."""
        try:
            import sys
            result = subprocess.run(
                [
                    sys.executable, "-m", "yt_dlp",
                    "--dump-json",
                    "--no-download",
                    "-f", "bestaudio",
                    f"ytsearch1:{query}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                logger.error("yt-dlp failed: %s", result.stderr[:200])
                return None, None

            info = json.loads(result.stdout)
            title = info.get("title", query)
            url = info.get("url")

            if not url:
                logger.warning("yt-dlp returned no URL for: '%s'", query[:80])
                return None, None

            logger.info("Found: '%s' (%s)", title, info.get("webpage_url", ""))
            return url, title

        except subprocess.TimeoutExpired:
            logger.error("yt-dlp timed out for: '%s'", query[:80])
            return None, None
        except Exception as e:
            logger.error("yt-dlp resolve failed: %s (type=%s)", e, type(e).__name__)
            return None, None
