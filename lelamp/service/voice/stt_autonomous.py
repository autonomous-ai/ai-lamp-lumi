"""
Autonomous STT provider — streaming speech-to-text via Autonomous AI WebSocket API.

Wraps Deepgram behind campaign-api.autonomous.ai, authenticated with the same
LLM API key used for TTS. No separate Deepgram key needed.

Protocol (Deepgram-compatible):
  → send raw linear16 audio bytes
  ← receive JSON {"type": "Results", "channel": {"alternatives": [{"transcript": "..."}]}, "is_final": true}
"""

import json
import logging
import threading
from typing import Callable, Optional
from urllib.parse import urlencode

from lelamp.service.voice.stt_provider import STTProvider, STTSession

logger = logging.getLogger("lelamp.voice.stt")
logger.setLevel(logging.INFO)

DEFAULT_MODEL = "flux-general-en"
DEFAULT_ENCODING = "linear16"


class AutonomousSTTSession(STTSession):
    """A single Autonomous AI streaming STT session over WebSocket."""

    def __init__(self, ws_url: str, api_key: str, sample_rate: int):
        self._ws_url = ws_url
        self._api_key = api_key
        self._sample_rate = sample_rate
        self._ws = None
        self._recv_thread: Optional[threading.Thread] = None
        self._closed = threading.Event()
        self._ready = threading.Event()

    def start(self, on_transcript: Callable[[str, bool], None]) -> bool:
        try:
            from websockets.sync.client import connect
        except ImportError:
            logger.error("websockets package not available")
            self._closed.set()
            return False

        try:
            self._ws = connect(
                self._ws_url,
                additional_headers={"Authorization": f"Token {self._api_key}"},
                open_timeout=10,
                close_timeout=5,
            )
        except Exception as e:
            logger.error("Autonomous STT connect failed: %s", e)
            self._closed.set()
            return False

        logger.info("Autonomous STT WebSocket opened")
        self._ready.set()

        def recv_loop():
            try:
                for raw in self._ws:
                    if self._closed.is_set():
                        break
                    logger.debug("STT recv: %s", str(raw)[:200])
                    try:
                        msg = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        logger.warning("STT recv non-JSON: %s", str(raw)[:200])
                        continue
                    msg_type = msg.get("type", "")

                    # Deepgram format: {"type": "Results", "channel": {"alternatives": [...]}, "is_final": true}
                    if msg_type == "Results":
                        alts = msg.get("channel", {}).get("alternatives", [])
                        if not alts:
                            continue
                        transcript = alts[0].get("transcript", "").strip()
                        if not transcript:
                            continue
                        on_transcript(transcript, msg.get("is_final", False))

                    # Autonomous format: {"type": "TurnInfo", "event": "Update"/"EndOfTurn", "transcript": "..."}
                    elif msg_type == "TurnInfo":
                        transcript = msg.get("transcript", "").strip()
                        if not transcript:
                            continue
                        on_transcript(transcript, msg.get("event", "") == "EndOfTurn")
            except Exception as e:
                if not self._closed.is_set():
                    logger.error("Autonomous STT recv error: %s", e)
            finally:
                self._closed.set()

        self._recv_thread = threading.Thread(target=recv_loop, daemon=True, name="auto-stt-recv")
        self._recv_thread.start()

        logger.info("Autonomous STT connected — streaming speech (recv thread alive=%s)",
                    self._recv_thread.is_alive())
        return True

    def send_audio(self, data: bytes):
        if self._ws and not self._closed.is_set():
            self._ws.send(data)

    def close(self):
        if self._closed.is_set():
            return
        self._closed.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        if self._recv_thread:
            self._recv_thread.join(timeout=5)
            if self._recv_thread.is_alive():
                logger.warning("Autonomous STT recv thread did not exit in 5s")
        logger.info("Autonomous STT connection closed")

    def is_closed(self) -> bool:
        return self._closed.is_set()


class AutonomousSTT(STTProvider):
    """Autonomous AI streaming STT provider (Deepgram wrapper behind campaign-api)."""

    def __init__(self, api_key: str, base_url: str, sample_rate: int = 16000,
                 model: str = DEFAULT_MODEL, language: Optional[str] = None):
        self._api_key = api_key
        self._sample_rate = sample_rate
        self._model = model
        self._language = language

        # Convert HTTP base_url to WebSocket URL
        # base_url: https://campaign-api.autonomous.ai/api/v1/ai/v1
        # ws_url:   wss://campaign-api.autonomous.ai/api/v1/ai/v1/ws/audio/transcriptions
        ws_base = base_url.replace("https://", "wss://").replace("http://", "ws://").rstrip("/")
        params = {
            "model": model,
            "encoding": DEFAULT_ENCODING,
            "sample_rate": str(sample_rate),
        }
        if language:
            params["language"] = language
        self._ws_url = f"{ws_base}/ws/audio/transcriptions?{urlencode(params)}"
        logger.info("AutonomousSTT ready (url=%s, model=%s)", self._ws_url, model)

    def create_session(self) -> STTSession:
        return AutonomousSTTSession(
            ws_url=self._ws_url,
            api_key=self._api_key,
            sample_rate=self._sample_rate,
        )

    @property
    def available(self) -> bool:
        return self._api_key != ""

    @property
    def name(self) -> str:
        return f"AutonomousSTT({self._model})"
