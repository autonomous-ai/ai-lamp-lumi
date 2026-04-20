"""ElevenLabs TTS backend with streaming support."""

import logging
from typing import Iterator, Optional

from lelamp.service.voice.tts_backend import TTSBackend, STREAM_CHUNK_SIZE

logger = logging.getLogger("lelamp.voice.tts_backend")


class ElevenLabsTTSBackend(TTSBackend):
    """ElevenLabs TTS backend with streaming support."""

    DEFAULT_MODEL = "eleven_v3"
    API_BASE = "https://api.elevenlabs.io"

    # Voice name -> voice_id mapping
    # Curated for companion AI — warm, friendly, expressive
    # Top picks marked with (*)
    VOICE_IDS = {
        # Female — premade
        "Rachel": "21m00Tcm4TlvDq8ikWAM",       # (*) warm, natural American
        "Sarah": "EXAVITQu4vr4xnSDxMaL",        # (*) friendly, clear American
        "Nicole": "piTKgcLEGmPE4e6mEKli",       # soft, inspirational
        # Female — community (conversational, young, American)
        "Terra": "aFueGIISJUmscc05ZNfD",         # (*) bubbly, friendly — 14k clones
        "Maria": "vZzlAds9NzvLsFSWp0qk",        # (*) soft, calm, expressive — 48k clones
        "Sophie": "AEW6JTgnyoPaoB9zlK3S",       # (*) sparky, energetic, young
        "Piper": "rzgrf9VyEb0LLa824k8Q",        # spirited, upbeat, dynamic
        "Mia": "052jzHJceQiZr7ltnY0C",          # lively, warm, expressive
        "Kimmy": "TmK7x2BFDD7TOVlR69J2",        # youthful, sweet, natural charm
        "Brianna": "2NzqTfQARqdn4tcBKTSh",      # soft, sincere, intimate
        "Ally": "qmm0vRXCIew16ilYAeiI",         # bubbly, fun, caring
        "Tori": "lAxf5ma5HGtzxC434SWT",         # confident, warm, encouraging
        # Male — premade
        "Brian": "nPczCjzI2devNBz1zQrb",        # (*) cheerful, relatable American
        "Adam": "pNInz6obpgDQGcFmaJgB",         # (*) warm, emotional depth
        "Daniel": "onwK4e9ZLuTAKqWW03F9",       # (*) well-paced, clear
        "George": "JBFqnCBsd6RMkjVDRZzb",
        "James": "ZQe5CZNOzWyzPSCn5a3c",        # calm British
        "Liam": "TX3LPaxmHKxFdv7VOQHJ",        # energetic American
        "Charlie": "IKne3meq5aSn9XLyUdCD",
        "Sam": "yoZ06aMxZJJ28mfd3POQ",
        # Male — community (conversational, young, American)
        "Sean": "FgARTjeugpFkVodK0Ovq",         # (*) casual, optimized for conversation — 1.9k clones
        "Kael": "RxsTyZQJnPygpas5IyzL",         # (*) energetic, trendy, youthful — 1.8k clones
        "Brooks": "sUzXYdokj3o9QQ91yPRF",       # (*) bright, affable, friendly smile — 1.5k clones
        "Erion": "BSgaLWMIhbNhOCIH1apf",        # unique, friendly, casual — 1.3k clones
    }

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        self._api_key = "sk_ad049bfc2b626d950d9f2f969e14a1f19df93fbb7c494268"  # api_key — hardcoded for testing
        self._base_url = self.API_BASE #(base_url or self.API_BASE).rstrip("/")
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

    @property
    def volume_boost(self) -> float:
        return 1.0

    def stream_pcm(
        self,
        text: str,
        voice: str,
        model: str,
        speed: float,
        instructions: Optional[str] = None,
    ) -> Iterator[bytes]:
        el_model = model if model.startswith("eleven_") else self.DEFAULT_MODEL
        # Resolve voice name to voice_id (pass through if already an ID)
        voice_id = self.VOICE_IDS.get(voice, voice)
        # output_format is a query param, not body — pcm_24000 = 24kHz 16-bit mono
        url = f"{self._base_url}/v1/text-to-speech/{voice_id}/stream?output_format=pcm_24000"
        headers = {
            "xi-api-key": self._api_key,
            "Content-Type": "application/json",
        }
        body = {
            "text": text,
            "model_id": el_model,
        }
        if speed != 1.0:
            body["voice_settings"] = {"speed": max(0.7, min(1.2, speed))}

        with self._httpx.stream(
            "POST", url, headers=headers, json=body, timeout=30.0
        ) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes(STREAM_CHUNK_SIZE):
                yield chunk
