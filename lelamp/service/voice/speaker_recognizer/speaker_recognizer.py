"""Speaker voice recognition service.

Stores per-user voice embeddings under ``/root/local/users/<name>/voice/`` and
recognizes speakers via cosine similarity. Embeddings are computed by a
configurable external API (see ``SPEAKER_EMBEDDING_API_URL``).

External API contract:
    POST {SPEAKER_EMBEDDING_API_URL}
    Headers: X-API-Key: {SPEAKER_EMBEDDING_API_KEY} (optional)
    Body:    {"audios_b64": ["<base64 WAV>", ...]}
    Response: {"embedding": [float, float, ...]}  (single 1-D vector
              aggregated from all inputs, any dimension)

Storage layout per user::

    /root/local/users/<norm>/
        metadata.json           — SHARED identity (telegram_username, telegram_id,
                                   display_name). Same file face-enroll writes —
                                   merged on write, never overwritten blindly.
        voice/
            embedding.npy       — L2-normalized aggregated embedding
            metadata.json       — voice-specific (enrolled_at, updated_at,
                                   num_samples, sample_files, embedding_dim)
            sample_<ts>_<uuid>.wav  — source WAV files (16kHz mono)

Label normalization matches :class:`FaceRecognizer.normalize_label` so face /
voice / mood / wellbeing all share the same per-user folder for a person.

Registry of users with registered voices::

    /root/local/users/.voice_registry.json
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
import wave
from math import gcd
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import requests

logger = logging.getLogger("lelamp.voice.speaker")

# --- Storage layout ---
_USERS_DIR = Path(os.environ.get("LELAMP_USERS_DIR", "/root/local/users"))
_VOICE_SUBDIR = "voice"
_EMBEDDING_FILE = "embedding.npy"
_METADATA_FILE = "metadata.json"
_REGISTRY_FILE = _USERS_DIR / ".voice_registry.json"
_UNKNOWN_AUDIO_DIR = Path(
    os.environ.get("LELAMP_UNKNOWN_AUDIO_DIR", "/tmp/lumi-unknown-voice")
)

# --- External embedding API ---
# Default endpoint is dlbackend's /api/dl/audio-recognizer/embed, which is
# stateless (no DB write) and returns one aggregated L2-normalized vector.
# Override with SPEAKER_EMBEDDING_API_URL to point at a different service.
_DL_BACKEND_URL = os.environ.get("DL_BACKEND_URL", "").rstrip("/")
_DEFAULT_EMBED_URL = (
    f"{_DL_BACKEND_URL}/api/dl/audio-recognizer/embed" if _DL_BACKEND_URL else ""
)
_API_URL = os.environ.get("SPEAKER_EMBEDDING_API_URL", _DEFAULT_EMBED_URL)
_API_KEY = os.environ.get(
    "SPEAKER_EMBEDDING_API_KEY", os.environ.get("DL_API_KEY", "")
)
_API_TIMEOUT_S = float(os.environ.get("SPEAKER_EMBEDDING_API_TIMEOUT_S", "15"))
_EMBED_MAX_SECONDS = float(os.environ.get("SPEAKER_EMBED_MAX_SECONDS", "6.0"))

# Cosine similarity above which a speaker is considered a match.
_MATCH_THRESHOLD = float(os.environ.get("SPEAKER_MATCH_THRESHOLD", "0.7"))

# Target sample rate for stored/enrolled audio (matches STT pipeline).
_TARGET_SR = 16000


class SpeakerRecognizerError(Exception):
    """Raised on invalid input or external API failure."""


def _normalize_label(name: str) -> str:
    """Folder-safe lowercase label — matches FaceRecognizer.normalize_label.

    Keeping this rule identical to the face recognizer ensures that a person
    enrolled via face and via voice lands in the SAME per-user folder, and
    that mood/wellbeing/music-suggestion logs all refer to the same identity.
    """
    s = (name or "").strip().lower()
    s = re.sub(r"[^a-z0-9_-]+", "_", s)
    s = s.strip("_")
    return s[:64] if s else "person"


def _cosine_similarity(e1: np.ndarray, e2: np.ndarray) -> float:
    """Compute raw cosine similarity in range [-1, 1].

    Tolerates non-normalized inputs (unlike plain ``np.dot`` which requires
    pre-normalized vectors). The ``+ 1e-12`` guards against zero-norm inputs.
    Returns the confidence in range [0, 1].
    """
    raw_cos = float(np.dot(e1, e2) / (np.linalg.norm(e1) * np.linalg.norm(e2) + 1e-12))
    return (raw_cos + 1.0) / 2.0

def _sample_origin(filename: str) -> str:
    """Parse the origin tag encoded in ``sample_<origin>_<ts>_<uuid>.wav``.

    Legacy files ``sample_<ts>_<uuid>.wav`` (no origin) → ``"unknown"``.
    """
    parts = filename.split("_", 2)
    if len(parts) >= 2 and parts[0] == "sample":
        candidate = parts[1]
        if candidate in ("mic", "telegram", "other"):
            return candidate
    return "unknown"


def _merge_shared_metadata(
    user_dir: Path,
    *,
    display_name: str | None = None,
    telegram_username: str | None = None,
    telegram_id: str | None = None,
) -> dict[str, Any]:
    """Merge identity fields into ``/root/local/users/<norm>/metadata.json``.

    This is the SAME file that :class:`FaceRecognizer` writes — we read,
    update only the provided fields, and write back. Empty/``None`` values
    never overwrite existing entries.
    """
    path = user_dir / "metadata.json"
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text()) or {}
        except (json.JSONDecodeError, OSError):
            data = {}
    if display_name:
        data.setdefault("display_name", display_name)
    if telegram_username:
        data["telegram_username"] = telegram_username
    if telegram_id:
        data["telegram_id"] = telegram_id
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    except OSError as e:
        logger.warning("failed to write shared metadata %s: %s", path, e)
    return data


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _wav_bytes_to_float32_16k_mono(raw: bytes) -> np.ndarray:
    """Decode WAV bytes into float32 mono waveform at 16kHz."""
    try:
        import soundfile as sf  # type: ignore
    except ImportError as e:
        raise SpeakerRecognizerError(
            "soundfile is required for WAV processing"
        ) from e

    try:
        data, sr = sf.read(io.BytesIO(raw), dtype="float32")
    except Exception as e:
        raise SpeakerRecognizerError(f"cannot decode WAV: {e}") from e

    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim == 2:
        arr = arr.mean(axis=1)
    elif arr.ndim != 1:
        raise SpeakerRecognizerError(f"unsupported WAV shape {arr.shape}")

    if sr != _TARGET_SR:
        try:
            from scipy.signal import resample_poly  # type: ignore
        except ImportError as e:
            raise SpeakerRecognizerError(
                "scipy is required for resampling"
            ) from e
        g = gcd(_TARGET_SR, int(sr))
        arr = resample_poly(arr, _TARGET_SR // g, int(sr) // g).astype(np.float32)
    return arr


def _float32_waveform_to_wav_bytes(waveform: np.ndarray) -> bytes:
    """Encode a float32 mono waveform into 16kHz PCM_16 WAV bytes."""
    try:
        import soundfile as sf  # type: ignore
    except ImportError as e:
        raise SpeakerRecognizerError(
            "soundfile is required for WAV processing"
        ) from e
    buf = io.BytesIO()
    sf.write(buf, np.asarray(waveform, dtype=np.float32), _TARGET_SR, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def _ensure_wav_16k_mono(raw: bytes) -> bytes:
    """Normalize WAV bytes to 16kHz mono PCM_16 WAV bytes."""
    return _float32_waveform_to_wav_bytes(_wav_bytes_to_float32_16k_mono(raw))


def pcm16_bytes_to_wav(pcm_bytes: bytes, sample_rate: int = _TARGET_SR) -> bytes:
    """Wrap raw int16 mono PCM bytes in a WAV header."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm_bytes)
    return buf.getvalue()


class SpeakerRecognizer:
    """Per-user voice embedding store with external-API embedding computation."""

    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        users_dir: Optional[Path] = None,
        match_threshold: Optional[float] = None,
    ) -> None:
        self._api_url = api_url or _API_URL
        self._api_key = api_key or _API_KEY
        self._users_dir = Path(users_dir) if users_dir else _USERS_DIR
        self._match_threshold = (
            match_threshold if match_threshold is not None else _MATCH_THRESHOLD
        )
        self._mu = threading.Lock()

        self._users_dir.mkdir(parents=True, exist_ok=True)
        _UNKNOWN_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(
            "SpeakerRecognizer ready (api=%s, threshold=%.2f, users_dir=%s)",
            self._api_url or "<unset>",
            self._match_threshold,
            self._users_dir,
        )

    @property
    def available(self) -> bool:
        return bool(self._api_url)

    # ------------------------------------------------------------------ paths

    def _voice_dir(self, norm: str) -> Path:
        return self._users_dir / norm / _VOICE_SUBDIR

    def _embedding_path(self, norm: str) -> Path:
        return self._voice_dir(norm) / _EMBEDDING_FILE

    def _metadata_path(self, norm: str) -> Path:
        return self._voice_dir(norm) / _METADATA_FILE

    # ------------------------------------------------------------- registry

    def _load_registry(self) -> dict[str, Any]:
        if _REGISTRY_FILE.is_file():
            try:
                return json.loads(_REGISTRY_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save_registry(self, registry: dict[str, Any]) -> None:
        try:
            _REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
            _REGISTRY_FILE.write_text(json.dumps(registry, indent=2))
        except OSError as e:
            logger.warning("failed to save voice registry: %s", e)

    def _update_registry(self, norm: str, meta: dict[str, Any]) -> None:
        with self._mu:
            reg = self._load_registry()
            reg[norm] = {
                "display_name": meta.get("display_name", norm),
                "telegram_username": meta.get("telegram_username", ""),
                "telegram_id": meta.get("telegram_id", ""),
                "has_telegram_identity": meta.get("has_telegram_identity", False),
                "enrollment_sources": meta.get("enrollment_sources", []),
                "last_enrollment_source": meta.get("last_enrollment_source", ""),
                "enrolled_at": meta.get("enrolled_at"),
                "updated_at": meta.get("updated_at"),
                "num_samples": meta.get("num_samples", 0),
                "embedding_dim": meta.get("embedding_dim", 0),
            }
            self._save_registry(reg)

    def _remove_from_registry(self, norm: str) -> None:
        with self._mu:
            reg = self._load_registry()
            if norm in reg:
                del reg[norm]
                self._save_registry(reg)

    # -------------------------------------------------------------- external

    def _call_embedding_api(self, audios_b64: list[str]) -> np.ndarray:
        """POST audios to the embedding API and return one L2-normalized vector."""
        if not self._api_url:
            raise SpeakerRecognizerError(
                "SPEAKER_EMBEDDING_API_URL not configured"
            )
        if not audios_b64:
            raise SpeakerRecognizerError("no audio to embed")

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["X-API-Key"] = self._api_key

        try:
            resp = requests.post(
                self._api_url,
                json={"audios_b64": audios_b64},
                headers=headers,
                timeout=_API_TIMEOUT_S,
            )
        except requests.RequestException as e:
            raise SpeakerRecognizerError(
                f"embedding API unreachable: {e}"
            ) from e

        if resp.status_code != 200:
            raise SpeakerRecognizerError(
                f"embedding API error {resp.status_code}: {resp.text[:200]}"
            )

        try:
            payload = resp.json()
        except ValueError as e:
            raise SpeakerRecognizerError(f"embedding API returned non-JSON: {e}") from e

        emb = payload.get("embedding")
        if emb is None:
            raise SpeakerRecognizerError("embedding API response missing 'embedding'")

        vec = np.asarray(emb, dtype=np.float32)
        if vec.ndim != 1 or vec.size == 0:
            raise SpeakerRecognizerError(
                f"embedding must be a non-empty 1-D array, got shape {vec.shape}"
            )

        norm = float(np.linalg.norm(vec))
        if norm == 0.0:
            raise SpeakerRecognizerError("embedding has zero norm")
        return vec / norm

    def _split_waveform_by_max_seconds(self, waveform: np.ndarray) -> list[np.ndarray]:
        """Split waveform into max-duration chunks for robust embedding."""
        wav = np.asarray(waveform, dtype=np.float32)
        if wav.ndim != 1:
            raise SpeakerRecognizerError("waveform must be 1-D")
        if wav.size == 0:
            return []

        max_seconds = max(float(_EMBED_MAX_SECONDS), 0.1)
        max_samples = max(1, int(max_seconds * _TARGET_SR))
        if wav.shape[0] <= max_samples:
            return [wav]

        chunks: list[np.ndarray] = []
        for start in range(0, wav.shape[0], max_samples):
            seg = wav[start : start + max_samples]
            if seg.size > 0:
                chunks.append(seg.astype(np.float32))
        return chunks

    def _expand_wav_for_embedding(self, wav_bytes: bytes, *, stem: str) -> list[str]:
        """Return base64 WAV inputs; long audios are split in-memory (no disk I/O)."""
        waveform = _wav_bytes_to_float32_16k_mono(wav_bytes)
        chunks = self._split_waveform_by_max_seconds(waveform)
        if not chunks:
            raise SpeakerRecognizerError("empty audio after decoding")

        if len(chunks) == 1:
            return [base64.b64encode(_float32_waveform_to_wav_bytes(chunks[0])).decode("ascii")]

        logger.info(
            "split long audio for embedding: stem=%s chunks=%d max_seconds=%.2f",
            stem,
            len(chunks),
            _EMBED_MAX_SECONDS,
        )
        return [
            base64.b64encode(_float32_waveform_to_wav_bytes(chunk)).decode("ascii")
            for chunk in chunks
        ]

    def _compute_representative_embedding(self, audios_b64: list[str]) -> np.ndarray:
        """Compute representative embedding by averaging per-sample embeddings."""
        if not audios_b64:
            raise SpeakerRecognizerError("no audio to embed")

        emb_list: list[np.ndarray] = []
        for audio_b64 in audios_b64:
            emb_list.append(self._call_embedding_api([audio_b64]))

        stacked = np.stack(emb_list, axis=0).astype(np.float32)
        mean_vec = np.mean(stacked, axis=0).astype(np.float32)
        norm = float(np.linalg.norm(mean_vec))
        if norm == 0.0:
            raise SpeakerRecognizerError("mean embedding has zero norm")
        return mean_vec / norm

    # ------------------------------------------------------------- metadata

    def _read_metadata(self, norm: str) -> dict[str, Any]:
        p = self._metadata_path(norm)
        if p.is_file():
            try:
                return json.loads(p.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _read_shared_metadata(self, norm: str) -> dict[str, Any]:
        """Read the top-level ``/root/local/users/<norm>/metadata.json``.

        Shared with FaceRecognizer — source of truth for telegram_* fields.
        """
        p = self._users_dir / norm / "metadata.json"
        if p.is_file():
            try:
                return json.loads(p.read_text()) or {}
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _write_metadata(self, norm: str, meta: dict[str, Any]) -> None:
        self._metadata_path(norm).write_text(json.dumps(meta, indent=2))

    def _load_all_embeddings(self) -> dict[str, np.ndarray]:
        """Load every stored embedding from disk — source of truth for recognize()."""
        out: dict[str, np.ndarray] = {}
        if not self._users_dir.is_dir():
            return out
        for entry in sorted(self._users_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            emb_path = self._voice_dir(entry.name) / _EMBEDDING_FILE
            if not emb_path.is_file():
                continue
            try:
                emb = np.load(emb_path).astype(np.float32)
                if emb.ndim == 1 and emb.size > 0:
                    # Defensive re-normalize in case file was edited.
                    n = float(np.linalg.norm(emb))
                    if n > 0.0:
                        out[entry.name] = emb / n
            except Exception as e:
                logger.warning("failed to load embedding for %s: %s", entry.name, e)
        return out

    # --------------------------------------------------------- public: enroll

    def enroll(
        self,
        name: str,
        wav_sources: Iterable[str],
        source_type: str = "base64",
        telegram_username: str = "",
        telegram_id: str = "",
        origin: str = "",
    ) -> dict[str, Any]:
        """Enroll or re-enroll a speaker.

        New sample WAVs are appended to the user's ``voice/`` folder and the
        embedding is (re)computed from ALL samples in the folder, producing a
        single aggregated representative vector.

        Identity (``telegram_username`` / ``telegram_id`` / display name) is
        merged into the SHARED ``/root/local/users/<norm>/metadata.json`` —
        the same file face-enroll writes to — so one person's identity is
        consistent across face, voice, mood, and wellbeing skills.

        Each sample is tagged with its origin (``"mic"`` or ``"telegram"``)
        so a user enrolled only via mic (no Telegram identity yet) can later
        be re-enrolled via Telegram without losing their earlier samples.

        Args:
            name: Display name (normalized to folder-safe lowercase).
            wav_sources: List of base64-encoded WAV data or filepaths.
            source_type: ``"base64"`` or ``"filepath"``.
            telegram_username: Optional Telegram @handle (e.g. ``chloe_92``).
            telegram_id: Optional numeric Telegram user ID.
            origin: ``"mic"`` / ``"telegram"`` / ``"other"``. Auto-derived
                (from presence of telegram_id/username) if empty.

        Returns:
            Metadata dict for the enrolled speaker (voice-specific + merged
            identity fields).
        """
        sources = list(wav_sources or [])
        if not sources:
            raise SpeakerRecognizerError("no audio provided")
        if source_type not in ("base64", "filepath"):
            raise SpeakerRecognizerError(
                f"invalid source_type {source_type!r}"
            )
        if not self.available:
            raise SpeakerRecognizerError(
                "embedding API not configured — set SPEAKER_EMBEDDING_API_URL"
            )

        # Infer origin from whether Telegram identity was supplied.
        if not origin:
            origin = (
                "telegram" if (telegram_username or telegram_id) else "mic"
            )
        origin = origin if origin in ("mic", "telegram", "other") else "other"

        norm = _normalize_label(name)
        user_dir = self._users_dir / norm
        user_dir.mkdir(parents=True, exist_ok=True)
        voice_dir = self._voice_dir(norm)
        voice_dir.mkdir(parents=True, exist_ok=True)

        # Persist shared identity early, even if embedding fails later.
        shared_identity = _merge_shared_metadata(
            user_dir,
            display_name=name.strip() or None,
            telegram_username=telegram_username or None,
            telegram_id=telegram_id or None,
        )

        # Decode + normalize incoming audios.
        new_wavs: list[bytes] = []
        for src in sources:
            if source_type == "filepath":
                raw = _read_bytes(src)
            else:
                try:
                    raw = base64.b64decode(src)
                except Exception as e:
                    raise SpeakerRecognizerError(f"invalid base64: {e}") from e
            if not raw:
                raise SpeakerRecognizerError("empty audio")
            new_wavs.append(_ensure_wav_16k_mono(raw))

        # Persist original audios; origin is encoded in filename.
        for wb in new_wavs:
            fname = (
                f"sample_{origin}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}.wav"
            )
            (voice_dir / fname).write_bytes(wb)

        # Build representative embedding from all saved samples.
        all_samples = sorted(voice_dir.glob("sample_*.wav"))
        audios_b64: list[str] = []
        for p in all_samples:
            audios_b64.extend(
                self._expand_wav_for_embedding(
                    p.read_bytes(),
                    stem=f"{norm}_{p.stem}",
                )
            )
        embedding = self._compute_representative_embedding(audios_b64)
        np.save(self._embedding_path(norm), embedding)

        # Update voice metadata + registry.
        existing = self._read_metadata(norm)
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z") or time.strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        enrollment_sources = sorted(
            {_sample_origin(p.name) for p in all_samples} | {origin}
        )
        meta: dict[str, Any] = {
            "name": norm,
            "display_name": shared_identity.get("display_name")
                or existing.get("display_name")
                or name.strip()
                or norm,
            "telegram_username": shared_identity.get("telegram_username", ""),
            "telegram_id": shared_identity.get("telegram_id", ""),
            "has_telegram_identity": bool(
                shared_identity.get("telegram_id")
                or shared_identity.get("telegram_username")
            ),
            "enrollment_sources": enrollment_sources,
            "last_enrollment_source": origin,
            "enrolled_at": existing.get("enrolled_at", now_iso),
            "updated_at": now_iso,
            "num_samples": len(all_samples),
            "sample_files": [p.name for p in all_samples],
            "sample_origins": {p.name: _sample_origin(p.name) for p in all_samples},
            "embedding_dim": int(embedding.shape[0]),
        }
        self._write_metadata(norm, meta)
        self._update_registry(norm, meta)
        logger.info(
            "Enrolled speaker '%s' — %d total samples, dim=%d",
            norm,
            meta["num_samples"],
            meta["embedding_dim"],
        )
        return meta

    # --------------------------------------------------------- public: remove

    def remove(self, name: str) -> bool:
        """Delete the user's voice folder (embedding + samples + voice metadata).

        Other per-user data (face photos, mood, wellbeing, ...) is preserved —
        we only touch the ``voice/`` subdir. The SHARED identity file
        ``/root/local/users/<norm>/metadata.json`` (telegram_username,
        telegram_id) is left untouched because face-enroll and other skills
        may still depend on it.
        """
        norm = _normalize_label(name)
        voice_dir = self._voice_dir(norm)
        if not voice_dir.is_dir():
            self._remove_from_registry(norm)
            return False
        try:
            shutil.rmtree(voice_dir)
        except OSError as e:
            logger.warning("failed to remove voice dir for %s: %s", norm, e)
            return False
        self._remove_from_registry(norm)
        logger.info("Removed speaker '%s'", norm)
        return True

    # ------------------------------------------------------ public: recognize

    def recognize(
        self,
        wav_source: str,
        source_type: str = "base64",
    ) -> dict[str, Any]:
        """Recognize a speaker from a single WAV audio.

        Returns a dict with:

        ``name``
            matched user's normalized label, or ``"unknown"``
        ``confidence``
            best match confidence in ``[0, 1]``
        ``match``
            whether the best confidence exceeds ``match_threshold``
        ``unknown_audio_path``
            path to the audio saved under the unknown-audio dir (always set —
            so the skill can reuse the path for later enrollment)
        ``candidates``
            top-3 ``(name, confidence)`` pairs for debugging
        """
        if source_type not in ("base64", "filepath"):
            raise SpeakerRecognizerError(
                f"invalid source_type {source_type!r}"
            )

        if source_type == "filepath":
            raw = _read_bytes(wav_source)
        else:
            try:
                raw = base64.b64decode(wav_source)
            except Exception as e:
                raise SpeakerRecognizerError(f"invalid base64: {e}") from e
        if not raw:
            raise SpeakerRecognizerError("empty audio")

        wav_bytes = _ensure_wav_16k_mono(raw)

        saved_path = self._save_incoming_audio(wav_bytes)

        if not self.available:
            return {
                "name": "unknown",
                "confidence": 0.0,
                "match": False,
                "unknown_audio_path": saved_path,
                "candidates": [],
                "error": "embedding API not configured",
            }

        try:
            input_audios = self._expand_wav_for_embedding(
                wav_bytes,
                stem="incoming",
            )
            embedding = self._compute_representative_embedding(input_audios)
        except SpeakerRecognizerError as e:
            return {
                "name": "unknown",
                "confidence": 0.0,
                "match": False,
                "unknown_audio_path": saved_path,
                "candidates": [],
                "error": str(e),
            }

        known = self._load_all_embeddings()
        if not known:
            return {
                "name": "unknown",
                "confidence": 0.0,
                "match": False,
                "unknown_audio_path": saved_path,
                "candidates": [],
            }

        scores: list[tuple[str, float]] = []
        for n, emb in known.items():
            conf = _cosine_similarity(embedding, emb)
            scores.append((n, conf))
        scores.sort(key=lambda t: t[1], reverse=True)
        best_name, best_conf = scores[0]

        is_match = best_conf >= self._match_threshold
        resolved_name = best_name if is_match else "unknown"
        result: dict[str, Any] = {
            "name": resolved_name,
            "confidence": round(best_conf, 4),
            "match": is_match,
            "unknown_audio_path": saved_path,
            "candidates": [
                {"name": n, "confidence": round(c, 4)}
                for n, c in scores[:3]
            ],
        }
        # Surface identity fields on match.
        if is_match:
            shared = self._read_shared_metadata(best_name)
            result["display_name"] = shared.get("display_name", best_name)
            result["telegram_username"] = shared.get("telegram_username", "")
            result["telegram_id"] = shared.get("telegram_id", "")
            result["has_telegram_identity"] = bool(
                shared.get("telegram_id") or shared.get("telegram_username")
            )
        return result

    # ----------------------------------------------------------- public: list

    def list_registered(self) -> list[dict[str, Any]]:
        """Return users who have a registered voice (embedding file exists).

        Backed by the registry file but cross-verified with on-disk state so
        stale registry rows are skipped. Telegram identity is read fresh from
        the shared ``metadata.json`` on every call so renames propagate.

        Each entry includes ``enrollment_sources`` (e.g. ``["mic"]``,
        ``["telegram"]`` or ``["mic", "telegram"]``) and
        ``has_telegram_identity`` — so the skill can tell whether a mic-only
        user still needs to be linked to a Telegram account for DM targeting.
        """
        reg = self._load_registry()
        out: list[dict[str, Any]] = []
        for norm in sorted(reg.keys()):
            if not self._embedding_path(norm).is_file():
                continue
            voice_meta = self._read_metadata(norm)
            shared_meta = self._read_shared_metadata(norm)
            tg_username = shared_meta.get(
                "telegram_username", voice_meta.get("telegram_username", "")
            )
            tg_id = shared_meta.get(
                "telegram_id", voice_meta.get("telegram_id", "")
            )
            out.append(
                {
                    "name": norm,
                    "display_name": shared_meta.get("display_name")
                    or voice_meta.get("display_name", norm),
                    "telegram_username": tg_username,
                    "telegram_id": tg_id,
                    "has_telegram_identity": bool(tg_username or tg_id),
                    "enrollment_sources": voice_meta.get(
                        "enrollment_sources", []
                    ),
                    "last_enrollment_source": voice_meta.get(
                        "last_enrollment_source", ""
                    ),
                    "num_samples": voice_meta.get("num_samples", 0),
                    "embedding_dim": voice_meta.get("embedding_dim", 0),
                    "enrolled_at": voice_meta.get("enrolled_at"),
                    "updated_at": voice_meta.get("updated_at"),
                    "sample_files": voice_meta.get("sample_files", []),
                    "sample_origins": voice_meta.get("sample_origins", {}),
                }
            )
        return out

    # ------------------------------------ public: identity-focused methods

    def get_telegram_id(self, name: str) -> str | None:
        """Return ``telegram_id`` for a user, or ``None`` if not set.

        Mirrors :meth:`FaceRecognizer.get_telegram_id` so any skill wanting
        to DM a person after voice recognition can use a single lookup.
        """
        norm = _normalize_label(name)
        meta = self._read_shared_metadata(norm)
        val = meta.get("telegram_id") or ""
        return val or None

    def get_telegram_username(self, name: str) -> str | None:
        norm = _normalize_label(name)
        meta = self._read_shared_metadata(norm)
        val = meta.get("telegram_username") or ""
        return val or None

    def lookup_by_telegram_id(self, telegram_id: str) -> str | None:
        """Reverse-lookup: given a Telegram user ID, return the norm label.

        Useful when a Telegram turn arrives and the skill wants to decide
        whether the sender already has a voice profile before enrolling.
        """
        if not telegram_id:
            return None
        reg = self._load_registry()
        for norm, entry in reg.items():
            if entry.get("telegram_id") == telegram_id:
                return norm
        return None

    def update_identity(
        self,
        name: str,
        telegram_username: str = "",
        telegram_id: str = "",
    ) -> dict[str, Any]:
        """Attach / update Telegram identity on an existing voice profile.

        Use this when a user enrolled by mic first (no Telegram info) later
        introduces themselves from Telegram — we can link the two without
        re-uploading audio or recomputing the embedding.
        """
        norm = _normalize_label(name)
        user_dir = self._users_dir / norm
        if not self._embedding_path(norm).is_file():
            raise SpeakerRecognizerError(
                f"no voice profile for '{norm}' — call enroll first"
            )
        shared = _merge_shared_metadata(
            user_dir,
            display_name=name.strip() or None,
            telegram_username=telegram_username or None,
            telegram_id=telegram_id or None,
        )
        # Refresh mirrored fields in voice metadata + registry.
        voice_meta = self._read_metadata(norm)
        voice_meta["telegram_username"] = shared.get("telegram_username", "")
        voice_meta["telegram_id"] = shared.get("telegram_id", "")
        voice_meta["has_telegram_identity"] = bool(
            shared.get("telegram_id") or shared.get("telegram_username")
        )
        voice_meta["display_name"] = shared.get(
            "display_name", voice_meta.get("display_name", norm)
        )
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z") or time.strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        voice_meta["updated_at"] = now_iso
        self._write_metadata(norm, voice_meta)
        self._update_registry(norm, voice_meta)
        logger.info(
            "Linked Telegram identity to '%s' (username=%s, id=%s)",
            norm, telegram_username, telegram_id,
        )
        return voice_meta

    def reset_all(self) -> int:
        """Delete every registered voice profile.

        Mirrors :meth:`FaceRecognizer.reset_enrolled`. Only the ``voice/``
        subdir of each user is removed — the shared ``metadata.json``
        (telegram identity) is preserved because face / mood / wellbeing
        still depend on it.
        """
        count = 0
        reg = self._load_registry()
        for norm in list(reg.keys()):
            if self.remove(norm):
                count += 1
        # Best-effort: walk disk too in case registry was stale.
        if self._users_dir.is_dir():
            for entry in self._users_dir.iterdir():
                if not entry.is_dir() or entry.name.startswith("."):
                    continue
                voice_dir = self._voice_dir(entry.name)
                if voice_dir.is_dir():
                    try:
                        shutil.rmtree(voice_dir)
                        count += 1
                    except OSError as e:
                        logger.warning("reset_all: failed to drop %s: %s", voice_dir, e)
        # Clear registry file.
        with self._mu:
            self._save_registry({})
        logger.info("reset_all: cleared %d voice profiles", count)
        return count

    # --------------------------------------------------------------- helpers

    def _save_incoming_audio(self, wav_bytes: bytes) -> str:
        """Save the incoming recognize() WAV to the unknown-audio dir.

        We always save — even on a match — so that skills have a stable path
        to reuse for follow-up enrollment flows.
        """
        _UNKNOWN_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        fname = (
            f"incoming_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}.wav"
        )
        fpath = _UNKNOWN_AUDIO_DIR / fname
        try:
            fpath.write_bytes(wav_bytes)
        except OSError as e:
            logger.warning("failed to save incoming audio: %s", e)
            return ""
        return str(fpath)
