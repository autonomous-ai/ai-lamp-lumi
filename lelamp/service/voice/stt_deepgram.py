"""
Deepgram STT provider — streaming speech-to-text via Deepgram WebSocket API.

Supports both v1 (nova-2) and v2 (flux) endpoints, auto-detected by model name.
"""

import logging
import threading
from typing import Callable, List, Optional

from lelamp.service.voice.stt_provider import STTProvider, STTSession

logger = logging.getLogger("lelamp.voice.stt")

# Default Deepgram streaming config
DEFAULT_MODEL = "flux-general-en"
DEFAULT_ENDPOINTING_MS = 1500


def _is_flux(model: str) -> bool:
    return model.startswith("flux")


class DeepgramSession(STTSession):
    """A single Deepgram streaming session (v1 or v2 auto-detected)."""

    def __init__(self, client, keywords: List[str], sample_rate: int, channels: int,
                 language: Optional[str] = None, model: str = DEFAULT_MODEL):
        self._client = client
        self._keywords = keywords
        self._sample_rate = sample_rate
        self._channels = channels
        self._language = language
        self._model = model
        self._ctx = None
        self._connection = None
        self._listener_thread: Optional[threading.Thread] = None
        self._closed = threading.Event()
        self._listener_ready = threading.Event()

    def start(self, on_transcript: Callable[[str, bool], None]) -> bool:
        from deepgram.core.events import EventType

        use_flux = _is_flux(self._model)
        api_version = "v2" if use_flux else "v1"

        # Build connect params
        params = dict(
            model=self._model,
            encoding="linear16",
            channels=self._channels,
            sample_rate=self._sample_rate,
        )
        if not use_flux:
            # v1-only params
            params.update(
                language=self._language or "vi",
                smart_format="true",
                interim_results="false",
                endpointing=DEFAULT_ENDPOINTING_MS,
                vad_events="true",
                keywords=self._keywords,
            )

        try:
            listener = self._client.listen.v2 if use_flux else self._client.listen.v1
            self._ctx = listener.connect(**params)
            self._connection = self._ctx.__enter__()
        except Exception as e:
            logger.error("Deepgram connect failed (%s): %s", api_version, e)
            self._closed.set()
            return False

        # Message handler — v1 and v2 have different result types
        if use_flux:
            def on_message(message):
                logger.debug("Deepgram v2 recv: type=%s", type(message).__name__)
                # Flux v2: check for transcript attr
                transcript = getattr(message, "transcript", None)
                if not transcript or not transcript.strip():
                    return
                is_final = getattr(message, "is_final", False)
                # Flux uses event field for turn detection
                event = getattr(message, "event", "")
                if event == "EndOfTurn":
                    is_final = True
                on_transcript(transcript.strip(), is_final)
        else:
            from deepgram.listen.v1.types import ListenV1Results

            def on_message(message):
                logger.debug("Deepgram v1 recv: type=%s", type(message).__name__)
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
            logger.info("Deepgram WebSocket opened (%s, model=%s)", api_version, self._model)
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

        logger.info("Deepgram connected — streaming speech (%s)...", api_version)
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
        if self._ctx:
            try:
                self._ctx.__exit__(None, None, None)
            except Exception:
                pass
        if self._listener_thread:
            self._listener_thread.join(timeout=5)
            if self._listener_thread.is_alive():
                logger.warning("Deepgram listener thread did not exit in 5s — will be orphaned")

    def is_closed(self) -> bool:
        return self._closed.is_set()


class DeepgramSTT(STTProvider):
    """Deepgram streaming STT provider. Supports nova-2 (v1) and flux (v2)."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, sample_rate: int = 16000,
                 channels: int = 1, language: Optional[str] = None,
                 keywords: Optional[List[str]] = None):
        self._api_key = api_key
        self._model = model
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
            api_version = "v2" if _is_flux(model) else "v1"
            logger.info("DeepgramSTT ready (model=%s, %s, lang=%s)", model, api_version, language)
        except ImportError:
            logger.warning("deepgram-sdk not available — DeepgramSTT disabled")

    def create_session(self) -> STTSession:
        return DeepgramSession(
            client=self._client,
            keywords=self._keywords,
            sample_rate=self._sample_rate,
            channels=self._channels,
            language=self._language,
            model=self._model,
        )

    @property
    def available(self) -> bool:
        return self._available and self._api_key != ""
