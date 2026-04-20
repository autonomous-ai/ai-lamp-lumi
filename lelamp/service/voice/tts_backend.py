"""
TTS Backend abstraction — pluggable providers for text-to-speech streaming.

Supported providers:
  - openai (default): OpenAI-compatible API (works with any OpenAI-compatible server)
  - elevenlabs: ElevenLabs TTS API with streaming support
"""

import logging
from abc import ABC, abstractmethod
from typing import Iterator, Optional

logger = logging.getLogger("lelamp.voice.tts_backend")

# Provider constants
PROVIDER_OPENAI = "openai"
PROVIDER_ELEVENLABS = "elevenlabs"

# OpenAI TTS returns 24kHz 16-bit mono PCM
TTS_SAMPLE_RATE = 24000
STREAM_CHUNK_SIZE = 4096


class TTSBackend(ABC):
    """Abstract TTS backend — streams raw PCM int16 bytes from text."""

    @abstractmethod
    def stream_pcm(
        self,
        text: str,
        voice: str,
        model: str,
        speed: float,
        instructions: Optional[str] = None,
    ) -> Iterator[bytes]:
        """Yield raw PCM int16 byte chunks (24kHz mono) for the given text."""
        ...

    @property
    def sample_rate(self) -> int:
        return TTS_SAMPLE_RATE

    @property
    @abstractmethod
    def available(self) -> bool:
        ...


class OpenAITTSBackend(TTSBackend):
    """OpenAI-compatible TTS backend (default)."""

    def __init__(self, api_key: str, base_url: str):
        self._client = None
        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=api_key, base_url=base_url)
            logger.info("OpenAI TTS backend ready (base_url=%s)", base_url)
        except ImportError as e:
            logger.warning("openai SDK not available: %s", e)

    @property
    def available(self) -> bool:
        return self._client is not None

    def stream_pcm(
        self,
        text: str,
        voice: str,
        model: str,
        speed: float,
        instructions: Optional[str] = None,
    ) -> Iterator[bytes]:
        kwargs = dict(
            model=model,
            voice=voice,
            input=text,
            response_format="pcm",
            speed=speed,
        )
        if instructions:
            kwargs["instructions"] = instructions
        with self._client.audio.speech.with_streaming_response.create(**kwargs) as response:
            for chunk in response.iter_bytes(STREAM_CHUNK_SIZE):
                yield chunk


class ElevenLabsTTSBackend(TTSBackend):
    """ElevenLabs TTS backend with streaming support."""

    DEFAULT_MODEL = "eleven_flash_v2_5"
    API_BASE = "https://api.elevenlabs.io"

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        self._api_key = api_key
        self._base_url = (base_url or self.API_BASE).rstrip("/")
        self._httpx = None
        try:
            import httpx
            self._httpx = httpx
            logger.info("ElevenLabs TTS backend ready (base_url=%s)", self._base_url)
        except ImportError as e:
            logger.warning("httpx not available for ElevenLabs backend: %s", e)

    @property
    def available(self) -> bool:
        return self._httpx is not None and bool(self._api_key)

    def stream_pcm(
        self,
        text: str,
        voice: str,
        model: str,
        speed: float,
        instructions: Optional[str] = None,
    ) -> Iterator[bytes]:
        el_model = model if model.startswith("eleven_") else self.DEFAULT_MODEL
        # Use pcm_24000 to match OpenAI TTS sample rate (24kHz 16-bit mono)
        url = f"{self._base_url}/v1/text-to-speech/{voice}/stream"
        headers = {
            "xi-api-key": self._api_key,
            "Content-Type": "application/json",
        }
        body = {
            "text": text,
            "model_id": el_model,
            "output_format": "pcm_24000",
        }
        if speed != 1.0:
            body["voice_settings"] = {"speed": max(0.7, min(1.2, speed))}

        with self._httpx.stream(
            "POST", url, headers=headers, json=body, timeout=30.0
        ) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes(STREAM_CHUNK_SIZE):
                yield chunk


def create_backend(
    provider: str,
    api_key: str,
    base_url: str = "",
) -> TTSBackend:
    """Factory: create a TTS backend by provider name."""
    provider = (provider or PROVIDER_OPENAI).lower().strip()
    if provider == PROVIDER_ELEVENLABS:
        return ElevenLabsTTSBackend(api_key=api_key, base_url=base_url or None)
    # Default: openai-compatible
    return OpenAITTSBackend(api_key=api_key, base_url=base_url)
