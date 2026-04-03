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
import os
import threading
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlencode

from lelamp.service.voice.stt_provider import STTProvider, STTSession

logger = logging.getLogger("lelamp.voice.stt")
logger.setLevel(logging.INFO)

_FALLBACK_MODEL = "flux-general-en"
_FALLBACK_LANGUAGE = None

_NOVA_MODEL = "nova-3"
_NOVA_LANGUAGE = "vi"


def _load_lumi_stt_defaults() -> tuple[str, Optional[str]]:
    """Read stt_model / stt_language from Lumi's config.json.

    Config path: env var LUMI_CONFIG_PATH, otherwise /opt/lumi/config/config.json.
    Falls back to flux-general-en / None when the file is absent or fields are empty.
    """
    path = os.environ.get("LUMI_CONFIG_PATH", "/opt/lumi/config/config.json")
    try:
        with open(path, "r") as f:
            cfg = json.load(f)
        model = (cfg.get("stt_model") or "").strip()
        language = (cfg.get("stt_language") or "").strip() or None
        if model:
            logger.info("STT config from %s: model=%s language=%s", path, model, language)
            return model, language
    except FileNotFoundError:
        logger.debug("Lumi config not found at %s, using STT defaults", path)
    except Exception as e:
        logger.warning("Failed to read Lumi config at %s: %s", path, e)
    return _FALLBACK_MODEL, _FALLBACK_LANGUAGE


DEFAULT_MODEL, DEFAULT_LANGUAGE = _load_lumi_stt_defaults()

DEFAULT_ENCODING = "linear16"
DEFAULT_ENDPOINTING_MS = 1500  # ms of silence before Deepgram fires is_final (same as stt_deepgram.py)
DEFAULT_INTERIM_RESULTS = "true"


def _is_flux(model: str) -> bool:
    return model.startswith("flux")


def _is_nova3(model: str) -> bool:
    return model.startswith("nova-3")


def _keyword_boost_to_terms(keywords: List[str]) -> List[str]:
    """Strip 'word:int' → 'word' for keyterm (nova-3 rejects keywords on upstream Deepgram)."""
    out: List[str] = []
    for k in keywords:
        k = k.strip()
        if not k:
            continue
        out.append(k.split(":", 1)[0].strip())
    return out


def _build_flux_query_params(
    *,
    model: str,
    encoding: str,
    sample_rate: int,
) -> Dict[str, Any]:
    """Flux (`flux-*`): model + PCM + channels only (Listen v2 style)."""
    return dict(
        model=model,
        encoding=encoding,
        sample_rate=sample_rate,
    )


def _build_nova_query_params(
    *,
    model: str,
    sample_rate: int,
    channels: int,
    language: str,
    keywords: List[str],
) -> Dict[str, Any]:
    """Nova (`nova-*`): v1-style options; nova-3 uses keyterm, not keywords."""
    params: Dict[str, Any] = dict(
        model=model,
        encoding=DEFAULT_ENCODING,
        sample_rate=sample_rate,
        channels=channels,
        language=language,
        smart_format="true",
        interim_results=DEFAULT_INTERIM_RESULTS,
        endpointing=DEFAULT_ENDPOINTING_MS,
        vad_events="true",
    )
    if not keywords:
        return params
    if _is_nova3(model):
        terms = _keyword_boost_to_terms(keywords)
        if terms:
            params["keyterm"] = terms
            logger.info(
                "Autonomous STT: nova-3 — keyterm=%s (do not use keywords on query)",
                terms,
            )
    else:
        params["keywords"] = ",".join(keywords)
    return params


def _transcriptions_ws_url(ws_base: str, params: Dict[str, Any]) -> str:
    q = urlencode(params, doseq=True)
    return f"{ws_base}/ws/audio/transcriptions?{q}"


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
        self._bytes_sent = 0
        self._logged_first_send = False

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
            logger.error("Autonomous STT: WebSocket connect failed: %s", e)
            self._closed.set()
            return False

        logger.info(
            "Autonomous STT: WebSocket OPEN — ready to receive audio (url=%s)",
            self._ws_url[:160] + ("…" if len(self._ws_url) > 160 else ""),
        )
        self._ready.set()

        def recv_loop():
            try:
                for raw in self._ws:
                    if self._closed.is_set():
                        break
                    try:
                        msg = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        r = str(raw)[:200]
                        logger.warning(
                            "Autonomous STT: recv non-JSON (truncated): %s",
                            r + ("…" if len(str(raw)) > 200 else ""),
                        )
                        continue
                    msg_type = msg.get("type", "")

                    if msg_type == "Results":
                        alts = msg.get("channel", {}).get("alternatives", [])
                        if not alts:
                            continue
                        transcript = alts[0].get("transcript", "").strip()
                        if not transcript:
                            continue
                        on_transcript(transcript, msg.get("is_final", False))

                    elif msg_type == "TurnInfo":
                        transcript = msg.get("transcript", "").strip()
                        if not transcript:
                            continue
                        ev = msg.get("event", "")
                        on_transcript(transcript, ev == "EndOfTurn")
            except Exception as e:
                if not self._closed.is_set():
                    code = getattr(e, "code", None)
                    reason = getattr(e, "reason", None)
                    if code is not None or reason is not None:
                        logger.error(
                            "Autonomous STT: WebSocket closed in recv loop (code=%s reason=%s)",
                            code,
                            reason,
                        )
                    else:
                        logger.error("Autonomous STT: recv loop error: %s", e)
                    if code == 1011 or "1011" in str(e):
                        logger.error(
                            "Autonomous STT: 1011 = server-side failure (often upstream STT). "
                        )
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
            self._bytes_sent += len(data)
            if not self._logged_first_send:
                self._logged_first_send = True
                logger.info(
                    "Autonomous STT: first audio chunk sent to WebSocket (%d bytes, linear16)",
                    len(data),
                )

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
                 channels: int = 1, model: str = DEFAULT_MODEL, language: Optional[str] = None,
                 keywords: Optional[List[str]] = None):
        self._api_key = api_key
        self._sample_rate = sample_rate
        self._channels = channels
        self._model = model
        self._language = language or DEFAULT_LANGUAGE
        self._keywords = keywords or []

        ws_base = base_url.replace("https://", "wss://").replace("http://", "ws://").rstrip("/")
        if _is_flux(model):
            params = _build_flux_query_params(
                model=model,
                sample_rate=sample_rate,
                encoding=DEFAULT_ENCODING,
            )
        else:
            params = _build_nova_query_params(
                model=model,
                sample_rate=sample_rate,
                channels=channels,
                language=self._language,
                keywords=self._keywords,
            )
        self._ws_url = _transcriptions_ws_url(ws_base, params)
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
