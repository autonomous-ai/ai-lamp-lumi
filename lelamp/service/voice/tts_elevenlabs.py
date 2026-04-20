"""ElevenLabs TTS backend with streaming support."""

import logging
from typing import Iterator, Optional

from lelamp.service.voice.tts_backend import TTSBackend, STREAM_CHUNK_SIZE

logger = logging.getLogger("lelamp.voice.tts_backend")


class ElevenLabsTTSBackend(TTSBackend):
    """ElevenLabs TTS backend with streaming support."""

    DEFAULT_MODEL = "eleven_v3"
    API_BASE = "https://api.elevenlabs.io"

    # Premade voice name -> voice_id mapping
    # Top picks for companion/conversational AI marked with (*)
    VOICE_IDS = {
        # Female — warm, expressive
        "Rachel": "21m00Tcm4TlvDq8ikWAM",   # (*) warm, natural
        "Sarah": "EXAVITQu4vr4xnSDxMaL",    # (*) friendly, clear
        "Grace": "oWAxZDx7w5VEj9dCyTzz",    # (*) sincere, feels like a friend
        "Charlotte": "XB0fDUnXU5powFXDhCwa",
        "Alice": "Xb7hH8MSUJpSbSDYk0k2",
        "Lily": "pFZP5JQG7iQjIQuC4Bku",
        "Matilda": "XrExE9yKIg1WjnnlVkGX",
        "Freya": "jsCqWAovK2LkecY7zXl4",    # (*) expressive
        "Nicole": "piTKgcLEGmPE4e6mEKli",
        "Glinda": "z9fAnlkpzviPz146aGWa",
        "Serena": "pMsXgVXv3BLzUgSXRplE",   # calm, soothing
        "Emily": "LcfcDJNUP1GQjkzn1xUU",
        "Dorothy": "ThT5KcBeYPX3keUQqHPh",
        "Jessie": "t0jbNlBVZ17f02VDIeMI",
        # Male — conversational, warm
        "Brian": "nPczCjzI2devNBz1zQrb",     # (*) cheerful, relatable
        "Adam": "pNInz6obpgDQGcFmaJgB",      # (*) warm, emotional depth
        "Daniel": "onwK4e9ZLuTAKqWW03F9",    # (*) well-paced
        "George": "JBFqnCBsd6RMkjVDRZzb",
        "James": "ZQe5CZNOzWyzPSCn5a3c",     # calm British
        "Liam": "TX3LPaxmHKxFdv7VOQHJ",
        "Callum": "N2lVS1w4EtoT3dr4eOWO",    # gentle, confident
        "Harry": "SOYHLrjzK2X1ezoPC6cr",     # versatile, balanced
        "Charlie": "IKne3meq5aSn9XLyUdCD",
        "Chris": "iP95p4xoKVk53GoZ742B",
        "Drew": "29vD33N1CtxCmqQRPOHJ",
        "Clyde": "2EiwWnXFnvU5JabPnv8n",
        "Arnold": "VR6AewLTigWG4xSOukaG",
        "Bill": "pqHfZKP75CvOlQylNhV4",
        "Sam": "yoZ06aMxZJJ28mfd3POQ",
        "Patrick": "ODq5zmih8GrVes37Dizd",
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
