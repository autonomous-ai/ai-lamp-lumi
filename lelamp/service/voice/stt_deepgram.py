"""
Deepgram STT provider — streaming speech-to-text via Deepgram WebSocket API.
"""

import logging
import threading
from typing import Callable, List, Optional

from lelamp.service.voice.stt_provider import STTProvider, STTSession

logger = logging.getLogger("lelamp.voice.stt")

# Default Deepgram streaming config
DEFAULT_MODEL = "nova-2"
DEFAULT_LANGUAGE = "vi"
DEFAULT_ENDPOINTING_MS = 1500


class DeepgramSession(STTSession):
    """A single Deepgram streaming session."""

    def __init__(self, client, keywords: List[str], sample_rate: int, channels: int,
                 language: str = DEFAULT_LANGUAGE, model: str = DEFAULT_MODEL):
        self._client = client
        self._keywords = keywords
        self._sample_rate = sample_rate
        self._channels = channels
        self._language = language
        self._model = model
        self._connection = None
        self._listener_thread: Optional[threading.Thread] = None
        self._closed = threading.Event()
        self._listener_ready = threading.Event()

    def start(self, on_transcript: Callable[[str, bool], None]) -> bool:
        from deepgram.core.events import EventType
        from deepgram.listen.v1.types import ListenV1Results

        try:
            self._connection = self._client.listen.v1.connect(
                model=self._model,
                language=self._language,
                smart_format="true",
                encoding="linear16",
                channels=self._channels,
                sample_rate=self._sample_rate,
                interim_results="false",
                endpointing=DEFAULT_ENDPOINTING_MS,
                vad_events="true",
                keywords=self._keywords,
            )
            self._connection.__enter__()
        except Exception as e:
            logger.error("Deepgram connect failed: %s", e)
            self._closed.set()
            return False

        def on_message(message):
            if not isinstance(message, ListenV1Results):
                return
            transcript = message.channel.alternatives[0].transcript
            if not transcript or not transcript.strip():
                return
            on_transcript(transcript.strip(), message.is_final)

        def on_error(error):
            logger.error("Deepgram error: %s", error)
            self._closed.set()

        def on_open(_):
            logger.info("Deepgram WebSocket opened")
            self._listener_ready.set()

        def on_close(_):
            logger.info("Deepgram connection closed")
            self._closed.set()

        conn = self._connection
        conn.on(EventType.OPEN, on_open)
        conn.on(EventType.MESSAGE, on_message)
        conn.on(EventType.ERROR, on_error)
        conn.on(EventType.CLOSE, on_close)

        self._listener_thread = threading.Thread(
            target=conn.start_listening, daemon=True, name="dg-listener",
        )
        self._listener_thread.start()

        if not self._listener_ready.wait(timeout=5):
            logger.error("Deepgram listener did not become ready in 5s")
            self.close()
            return False

        logger.info("Deepgram connected — streaming speech...")
        return True

    def send_audio(self, data: bytes):
        if self._connection and not self._closed.is_set():
            self._connection.send_media(data)

    def close(self):
        if self._closed.is_set():
            return
        self._closed.set()
        if self._connection:
            try:
                self._connection.send_close_stream()
            except Exception:
                pass
            try:
                self._connection.__exit__(None, None, None)
            except Exception:
                pass
        if self._listener_thread:
            self._listener_thread.join(timeout=5)
            if self._listener_thread.is_alive():
                logger.warning("Deepgram listener thread did not exit in 5s — will be orphaned")

    def is_closed(self) -> bool:
        return self._closed.is_set()


class DeepgramSTT(STTProvider):
    """Deepgram streaming STT provider."""

    def __init__(self, api_key: str, sample_rate: int = 16000, channels: int = 1,
                 language: str = DEFAULT_LANGUAGE, keywords: Optional[List[str]] = None):
        self._api_key = api_key
        self._sample_rate = sample_rate
        self._channels = channels
        self._language = language
        self._keywords = keywords or []
        self._client = None
        self._available = False

        try:
            from deepgram import DeepgramClient
            self._client = DeepgramClient(api_key=api_key)
            self._available = True
            logger.info("DeepgramSTT ready (model=%s, lang=%s)", DEFAULT_MODEL, language)
        except ImportError:
            logger.warning("deepgram-sdk not available — DeepgramSTT disabled")

    def create_session(self) -> STTSession:
        return DeepgramSession(
            client=self._client,
            keywords=self._keywords,
            sample_rate=self._sample_rate,
            channels=self._channels,
            language=self._language,
        )

    @property
    def available(self) -> bool:
        return self._available and self._api_key != ""
