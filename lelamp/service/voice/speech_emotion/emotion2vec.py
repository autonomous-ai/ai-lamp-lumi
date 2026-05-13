"""emotion2vec recognizer — POSTs WAV to dlbackend /api/dl/ser/recognize.

Mirrors `RemoteEmotionRecognizer` in the face emotion processor: stateless
HTTP wrapper, returns `None` on any transport/parse failure so the caller
can simply skip the sample.
"""

from __future__ import annotations

import base64
import logging
from typing import Optional

import requests

from lelamp.service.voice.speech_emotion.base import (
    BaseSpeechEmotionRecognizer,
    SpeechEmotionResult,
)
from lelamp.service.voice.speech_emotion.constants import DEFAULT_API_TIMEOUT_S

logger = logging.getLogger("lelamp.voice.speech_emotion.engine")


class Emotion2VecRecognizer(BaseSpeechEmotionRecognizer):
    """HTTP wrapper around dlbackend `/api/dl/ser/recognize`.

    Request body (per dlbackend README):
        {"audio_b64": "<base64 WAV>", "return_scores": false}
    Response body:
        {"label": "happy", "confidence": 0.9981, "scores": null}
    """

    def __init__(
        self,
        url: str,
        api_key: str = "",
        timeout_s: float = DEFAULT_API_TIMEOUT_S,
    ):
        self._url: str = url or ""
        self._api_key: str = api_key or ""
        self._timeout: float = timeout_s

    @property
    def available(self) -> bool:
        return bool(self._url)

    def recognize(self, wav_bytes: bytes) -> Optional[SpeechEmotionResult]:
        if not self._url:
            return None
        if not wav_bytes:
            return None
        try:
            payload = {
                "audio_b64": base64.b64encode(wav_bytes).decode("ascii"),
                "return_scores": False,
            }
            headers = {"X-API-Key": self._api_key} if self._api_key else {}
            resp = requests.post(
                self._url, json=payload, headers=headers, timeout=self._timeout,
            )
        except requests.RequestException as e:
            logger.warning("[speech_emotion] request failed: %s", e)
            return None

        if resp.status_code != 200:
            logger.warning(
                "[speech_emotion] HTTP %d: %s", resp.status_code, resp.text[:200],
            )
            return None

        try:
            data = resp.json()
        except ValueError:
            logger.warning("[speech_emotion] non-JSON response: %s", resp.text[:200])
            return None

        label = data.get("label")
        if not label:
            return None
        confidence = float(data.get("confidence", 0.0))
        return SpeechEmotionResult(label=label, confidence=confidence)
