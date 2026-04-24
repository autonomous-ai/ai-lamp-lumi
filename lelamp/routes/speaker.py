"""FastAPI router for speaker (voice-identity) recognition.

Routes accept local WAV filepaths only (no base64 — keeps the HTTP surface
minimal; internally the service handles both). Mounted by
:mod:`lelamp.server` on application startup.

Enrolled users live under ``/speaker/*``; unknown-voice-cluster browsing
lives under ``/voice/*`` (input side — avoids semantic clash with the
loudspeaker hardware). Both sets live in this file since they're two
halves of the same speaker recognition surface.

Routes:
    POST   /speaker/enroll                       — enroll / re-enroll a user from WAV paths
    POST   /speaker/identity                     — attach Telegram identity to existing profile
    POST   /speaker/reset                        — wipe all voice profiles
    POST   /speaker/remove                       — delete a user's voice folder
    POST   /speaker/recognize                    — identify the speaker of a WAV file
    GET    /speaker/list                         — list users with registered voice
    GET    /voice/strangers                      — list unknown-voice clusters + samples
    GET    /voice/strangers/audio/{hash}/{file}  — stream a cluster sample WAV
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from lelamp import config
from lelamp.service.voice.speaker_recognizer import (
    EmbeddingAPIUnavailableError,
    SpeakerRecognizer,
    SpeakerRecognizerError,
)

_STRANGER_HASH_RE = re.compile(r"^voice_\d+$")
_STRANGER_SAMPLE_RE = re.compile(r"^[A-Za-z0-9_.-]+\.wav$")

logger = logging.getLogger("lelamp.speaker_router")

router = APIRouter(tags=["Speaker"])

# Module-level singleton. Built lazily so import of this module never fails
# (e.g. when SPEAKER_EMBEDDING_API_URL is unset at import time).
_recognizer: Optional[SpeakerRecognizer] = None


def get_speaker_recognizer() -> SpeakerRecognizer:
    """Lazy accessor — raises 503 if unusable.

    Exposed so other routers / services can share the same instance.
    """
    global _recognizer
    if _recognizer is None:
        try:
            _recognizer = SpeakerRecognizer()
        except Exception as exc:
            logger.warning("SpeakerRecognizer unavailable: %s", exc)
            raise HTTPException(
                status_code=503,
                detail=f"Speaker recognizer unavailable: {exc}",
            ) from exc
    return _recognizer


# ----------------------------------------------------------------- Pydantic


class EnrollSpeakerRequest(BaseModel):
    """Enroll one speaker from 1+ local WAV filepaths."""

    name: str = Field(min_length=1, description="Display name to enroll as.")
    wav_paths: list[str] = Field(
        min_length=1,
        description="Local filepaths of WAV files (any sample rate — will be "
        "normalized to 16kHz mono).",
    )
    telegram_username: Optional[str] = Field(
        default=None,
        description="Optional Telegram @handle (e.g. 'chloe_92'). Merged into "
        "/root/local/users/<name>/metadata.json — same file face-enroll writes.",
    )
    telegram_id: Optional[str] = Field(
        default=None,
        description="Optional numeric Telegram user ID (for DM targeting).",
    )
    origin: Optional[str] = Field(
        default=None,
        description="Channel the audio came from: 'mic' | 'telegram' | "
        "'other'. Auto-inferred from presence of telegram_* fields if "
        "omitted. Encoded in the stored sample filename so list_registered "
        "can show which channels contributed.",
    )


class UpdateIdentityRequest(BaseModel):
    """Attach / update Telegram identity on an existing voice profile."""

    name: str = Field(min_length=1)
    telegram_username: Optional[str] = None
    telegram_id: Optional[str] = None


class RemoveSpeakerRequest(BaseModel):
    name: str = Field(min_length=1)


class RecognizeSpeakerRequest(BaseModel):
    wav_path: str = Field(min_length=1, description="Local filepath of WAV file.")


class SpeakerMeta(BaseModel):
    """Full metadata — used for enroll / identity confirmation responses."""

    name: str
    display_name: str
    telegram_username: Optional[str] = None
    telegram_id: Optional[str] = None
    has_telegram_identity: bool = False
    enrollment_sources: list[str] = []
    last_enrollment_source: Optional[str] = None
    num_samples: int
    embedding_dim: int
    enrolled_at: Optional[str] = None
    updated_at: Optional[str] = None
    sample_files: list[str] = []
    sample_origins: dict[str, str] = {}


class SpeakerListItem(BaseModel):
    """Trimmed public view for /speaker/list — identity-focused, no internals.

    Drops internal bookkeeping fields (embedding_dim, sample_files,
    sample_origins, enrolled_at, updated_at, last_enrollment_source) — those
    belong in log/debug output, not the public API response.
    """

    name: str
    display_name: str
    telegram_username: Optional[str] = None
    telegram_id: Optional[str] = None
    has_telegram_identity: bool = False
    enrollment_sources: list[str] = []
    num_samples: int


class EnrollResponse(BaseModel):
    status: str
    meta: SpeakerMeta


class RemoveResponse(BaseModel):
    status: str
    name: str
    removed: bool


class RecognizeResponse(BaseModel):
    name: str
    confidence: float
    match: bool
    display_name: Optional[str] = None
    telegram_username: Optional[str] = None
    telegram_id: Optional[str] = None
    has_telegram_identity: bool = False
    unknown_audio_path: Optional[str] = None
    # Stable cluster label for unknown voices (e.g. "voice_7"). Null when the
    # speaker matched a known user — their name already serves as identity.
    voiceprint_hash: Optional[str] = None
    candidates: list[dict[str, Any]] = []
    error: Optional[str] = None


class ListResponse(BaseModel):
    total: int
    enrolled_names: list[str]
    speakers: list[SpeakerListItem]


class StrangerSample(BaseModel):
    filename: str
    size_bytes: int
    mtime: float


class StrangerCluster(BaseModel):
    hash: str
    sample_count: int
    latest_mtime: float
    samples: list[StrangerSample]


class StrangersResponse(BaseModel):
    total: int
    clusters: list[StrangerCluster]


# ------------------------------------------------------------------ helpers


def _validate_paths(paths: list[str]) -> None:
    for p in paths:
        if not p or not Path(p).is_file():
            raise HTTPException(status_code=400, detail=f"wav file not found: {p}")


# ------------------------------------------------------------------- routes


@router.post("/speaker/enroll", response_model=EnrollResponse)
def speaker_enroll(req: EnrollSpeakerRequest) -> EnrollResponse:
    """Enroll or re-enroll a speaker from 1+ local WAV filepaths.

    New samples are appended to the user's voice folder and the embedding is
    recomputed from all samples in the folder (old + new).
    """
    logger.info(
        "POST /speaker/enroll name=%r wav_paths=%d tg_user=%r tg_id=%r origin=%r",
        req.name, len(req.wav_paths),
        req.telegram_username or "", req.telegram_id or "", req.origin or "",
    )
    _validate_paths(req.wav_paths)
    sr = get_speaker_recognizer()
    try:
        meta = sr.enroll(
            req.name,
            req.wav_paths,
            source_type="filepath",
            telegram_username=req.telegram_username or "",
            telegram_id=req.telegram_id or "",
            origin=req.origin or "",
        )
    except EmbeddingAPIUnavailableError as e:
        logger.warning("POST /speaker/enroll API unavailable for %r: %s", req.name, e)
        raise HTTPException(
            status_code=503,
            detail=f"embedding service unavailable — please try again: {e}",
        ) from e
    except SpeakerRecognizerError as e:
        logger.warning("POST /speaker/enroll failed for %r: %s", req.name, e)
        raise HTTPException(status_code=400, detail=str(e)) from e
    return EnrollResponse(status="ok", meta=SpeakerMeta(**meta))


@router.post("/speaker/identity", response_model=EnrollResponse)
def speaker_update_identity(req: UpdateIdentityRequest) -> EnrollResponse:
    """Attach / update Telegram identity on an existing voice profile.

    Use when a user was first enrolled via mic (no Telegram info) and later
    introduces themselves via Telegram — we can link the two without
    re-uploading audio.
    """
    logger.info(
        "POST /speaker/identity name=%r tg_user=%r tg_id=%r",
        req.name, req.telegram_username or "", req.telegram_id or "",
    )
    sr = get_speaker_recognizer()
    try:
        meta = sr.update_identity(
            req.name,
            telegram_username=req.telegram_username or "",
            telegram_id=req.telegram_id or "",
        )
    except SpeakerRecognizerError as e:
        logger.warning("POST /speaker/identity failed for %r: %s", req.name, e)
        raise HTTPException(status_code=404, detail=str(e)) from e
    return EnrollResponse(status="ok", meta=SpeakerMeta(**meta))


@router.post("/speaker/reset", response_model=RemoveResponse)
def speaker_reset() -> RemoveResponse:
    """Delete every voice profile (mirrors /face/reset).

    Shared identity (``metadata.json``) is preserved — face / mood /
    wellbeing still depend on it.
    """
    logger.info("POST /speaker/reset — wiping all voice profiles")
    sr = get_speaker_recognizer()
    n = sr.reset_all()
    return RemoveResponse(status="ok", name="*", removed=n > 0)


@router.post("/speaker/remove", response_model=RemoveResponse)
def speaker_remove(req: RemoveSpeakerRequest) -> RemoveResponse:
    """Delete the user's voice folder (embedding + samples + metadata).

    Returns 404 if the user has no voice profile — mirrors ``/face/remove``
    behaviour so callers don't silently no-op on a typo. Other per-user data
    (face photos, mood, wellbeing, ...) is preserved regardless.
    """
    logger.info("POST /speaker/remove name=%r", req.name)
    sr = get_speaker_recognizer()
    removed = sr.remove(req.name)
    if not removed:
        logger.warning("POST /speaker/remove: voice profile not found for %r", req.name)
        raise HTTPException(
            status_code=404,
            detail=f"voice profile not found: {req.name}",
        )
    return RemoveResponse(status="ok", name=req.name, removed=removed)


@router.post("/speaker/recognize", response_model=RecognizeResponse)
def speaker_recognize(req: RecognizeSpeakerRequest) -> RecognizeResponse:
    """Recognize the speaker of a single WAV file.

    Returns ``{name: "unknown"}`` when no registered speaker exceeds the match
    threshold, along with ``unknown_audio_path`` so the skill can reuse that
    path for a later enrollment call.
    """
    _validate_paths([req.wav_path])
    sr = get_speaker_recognizer()
    try:
        result = sr.recognize(req.wav_path, source_type="filepath")
    except SpeakerRecognizerError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return RecognizeResponse(**result)


@router.get("/speaker/list", response_model=ListResponse)
def speaker_list() -> ListResponse:
    """List users with a registered voice — public identity-focused view.

    Internal bookkeeping (sample filenames, embedding dim, timestamps) is
    computed by the service but intentionally not exposed here — see
    :class:`SpeakerListItem` for the trimmed schema.
    """
    sr = get_speaker_recognizer()
    speakers = sr.list_registered()
    public_items = [
        SpeakerListItem(
            name=s["name"],
            display_name=s.get("display_name") or s["name"],
            telegram_username=s.get("telegram_username") or None,
            telegram_id=s.get("telegram_id") or None,
            has_telegram_identity=bool(s.get("has_telegram_identity", False)),
            enrollment_sources=list(s.get("enrollment_sources", [])),
            num_samples=int(s.get("num_samples", 0)),
        )
        for s in speakers
    ]
    return ListResponse(
        total=len(public_items),
        enrolled_names=[item.name for item in public_items],
        speakers=public_items,
    )


# ----------------------------------------- unknown-voice cluster browsing


@router.get("/voice/strangers", response_model=StrangersResponse)
def voice_strangers() -> StrangersResponse:
    """List unknown-voice clusters with their saved WAV samples.

    Scans the per-cluster sub-dirs the speaker service writes under
    ``SPEAKER_UNKNOWN_AUDIO_DIR/voice_<N>/`` so the web UI can play back
    clips the lamp has grouped as "same unknown voice" before deciding to
    enroll them as a known speaker.
    """
    root = Path(config.SPEAKER_UNKNOWN_AUDIO_DIR)
    if not root.is_dir():
        return StrangersResponse(total=0, clusters=[])

    clusters: list[StrangerCluster] = []
    for sub in sorted(root.iterdir()):
        if not sub.is_dir() or not _STRANGER_HASH_RE.match(sub.name):
            continue
        samples: list[StrangerSample] = []
        for wav in sub.glob("*.wav"):
            try:
                st = wav.stat()
            except OSError:
                continue
            samples.append(StrangerSample(
                filename=wav.name,
                size_bytes=int(st.st_size),
                mtime=float(st.st_mtime),
            ))
        if not samples:
            continue
        samples.sort(key=lambda s: s.mtime, reverse=True)
        clusters.append(StrangerCluster(
            hash=sub.name,
            sample_count=len(samples),
            latest_mtime=samples[0].mtime,
            samples=samples,
        ))
    clusters.sort(key=lambda c: c.latest_mtime, reverse=True)
    return StrangersResponse(total=len(clusters), clusters=clusters)


class StrangerDeleteResponse(BaseModel):
    status: str
    hash: str
    filename: Optional[str] = None
    cluster_removed: bool = False


@router.delete("/voice/strangers/{hash}", response_model=StrangerDeleteResponse)
def voice_stranger_delete_cluster(hash: str) -> StrangerDeleteResponse:
    """Delete a whole unknown-voice cluster — centroid row + on-disk dir.

    Used from the web card when the operator decides a cluster is noise or
    belongs to someone they don't want tracked any further.
    """
    if not _STRANGER_HASH_RE.match(hash):
        raise HTTPException(status_code=400, detail="invalid cluster hash")
    sr = get_speaker_recognizer()
    removed = sr.drop_stranger_cluster(hash)
    if not removed:
        raise HTTPException(status_code=404, detail=f"cluster not found: {hash}")
    logger.info("DELETE /voice/strangers/%s — removed", hash)
    return StrangerDeleteResponse(status="ok", hash=hash, cluster_removed=True)


@router.delete(
    "/voice/strangers/{hash}/{filename}", response_model=StrangerDeleteResponse,
)
def voice_stranger_delete_sample(hash: str, filename: str) -> StrangerDeleteResponse:
    """Delete a single WAV from a cluster.

    If the cluster becomes empty after deletion, auto-drop the centroid so
    the .npy state stays in sync with what the web list can show (an empty
    cluster dir is filtered out of ``GET /voice/strangers``, which would
    otherwise orphan the centroid forever).
    """
    if not _STRANGER_HASH_RE.match(hash) or not _STRANGER_SAMPLE_RE.match(filename):
        raise HTTPException(status_code=400, detail="invalid path")
    root = Path(config.SPEAKER_UNKNOWN_AUDIO_DIR).resolve()
    cluster_dir = (root / hash).resolve()
    try:
        cluster_dir.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid path") from exc
    target = cluster_dir / filename
    if not target.is_file():
        raise HTTPException(status_code=404, detail="sample not found")
    try:
        target.unlink()
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"delete failed: {exc}",
        ) from exc
    cluster_emptied = not any(cluster_dir.glob("*.wav"))
    if cluster_emptied:
        sr = get_speaker_recognizer()
        sr.drop_stranger_cluster(hash)
    logger.info(
        "DELETE /voice/strangers/%s/%s (cluster_emptied=%s)",
        hash, filename, cluster_emptied,
    )
    return StrangerDeleteResponse(
        status="ok",
        hash=hash,
        filename=filename,
        cluster_removed=cluster_emptied,
    )


@router.get("/voice/strangers/audio/{hash}/{filename}")
def voice_stranger_audio(hash: str, filename: str) -> FileResponse:
    """Stream a stranger-cluster WAV by cluster hash + filename.

    Path components are whitelisted (``voice_<digits>`` / ``<safe>.wav``) and
    the resolved file must sit inside ``SPEAKER_UNKNOWN_AUDIO_DIR`` — blocks
    path-traversal attempts like ``../../etc/passwd``.
    """
    if not _STRANGER_HASH_RE.match(hash) or not _STRANGER_SAMPLE_RE.match(filename):
        raise HTTPException(status_code=400, detail="invalid path")
    root = Path(config.SPEAKER_UNKNOWN_AUDIO_DIR).resolve()
    target = (root / hash / filename).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid path") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="sample not found")
    return FileResponse(str(target), media_type="audio/wav", filename=filename)
