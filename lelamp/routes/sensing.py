"""Sensing route handlers -- /sensing, /presence/*, /face/*, /user/* endpoints."""

import base64
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

import lelamp.app_state as state
from lelamp.models import (
    FaceEnrollRequest,
    FaceEnrollResponse,
    FaceOwnersDetailResponse,
    FacePersonDetail,
    FacePhotoRemoveRequest,
    FaceRemoveRequest,
    FaceRemoveResponse,
    FaceResetResponse,
    FaceStatusResponse,
    PresenceResponse,
    SensingResponse,
    StatusResponse,
    UserInfoResponse,
)

# Lazy import
FaceRecognizer = None
try:
    from lelamp.service.sensing.perceptions.facerecognizer import FaceRecognizer
except ImportError:
    pass

router = APIRouter()


def _require_face_recognizer():
    """Return FaceRecognizer or raise 503."""
    if not state.sensing_service or FaceRecognizer is None:
        raise HTTPException(503, "Sensing not available")
    fr = getattr(state.sensing_service, "_face_recognizer", None)
    if fr is None:
        raise HTTPException(503, "Face recognition not available (no camera)")
    return fr


# --- Sensing ---

@router.get("/sensing", response_model=SensingResponse, tags=["Sensing"])
def get_sensing_state():
    """Get perception state."""
    if not state.sensing_service:
        raise HTTPException(503, "Sensing not available")
    return state.sensing_service.to_dict()


# --- Presence ---

@router.get("/presence", response_model=PresenceResponse, tags=["Presence"])
def get_presence():
    """Get current presence state."""
    if not state.sensing_service:
        return {
            "state": "unknown",
            "enabled": False,
            "seconds_since_motion": 0,
            "idle_timeout": 0,
            "away_timeout": 0,
        }
    return state.sensing_service.presence.to_dict()


@router.post("/presence/enable", response_model=StatusResponse, tags=["Presence"])
def enable_presence():
    """Enable automatic presence-based light control."""
    if not state.sensing_service:
        raise HTTPException(503, "Sensing not available")
    state.sensing_service.presence.enable()
    return {"status": "ok"}


@router.post("/presence/disable", response_model=StatusResponse, tags=["Presence"])
def disable_presence():
    """Disable automatic presence-based light control."""
    if not state.sensing_service:
        raise HTTPException(503, "Sensing not available")
    state.sensing_service.presence.disable()
    return {"status": "ok"}


# --- Face ---

@router.post("/face/enroll", response_model=FaceEnrollResponse, tags=["Face"])
def face_enroll(req: FaceEnrollRequest):
    """Save a JPEG photo, train embeddings, and persist under users/{label}/."""
    fr = _require_face_recognizer()
    try:
        raw = base64.b64decode(req.image_base64)
    except Exception as exc:
        raise HTTPException(400, "invalid base64") from exc
    if not raw:
        raise HTTPException(400, "empty image")
    tg_username = req.telegram_username or ""
    tg_id = req.telegram_id or ""
    try:
        path = fr.enroll_from_bytes(raw, req.label, tg_username, tg_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    norm = FaceRecognizer.normalize_label(req.label)
    return FaceEnrollResponse(
        status="ok",
        label=norm,
        telegram_username=tg_username or None,
        telegram_id=tg_id or None,
        photo_path=path,
        enrolled_count=fr.enrolled_count(),
    )


@router.get("/face/status", response_model=FaceStatusResponse, tags=["Face"])
def face_status():
    """List enrolled persons and count."""
    fr = _require_face_recognizer()
    return FaceStatusResponse(
        enrolled_count=fr.enrolled_count(),
        enrolled_names=fr.enrolled_names(),
    )


@router.get("/face/owners", response_model=FaceOwnersDetailResponse, tags=["Face"])
def face_owners_detail():
    """List enrolled persons with photo filenames."""
    fr = _require_face_recognizer()
    from lelamp.service.sensing.perceptions.facerecognizer import USERS_DIR

    persons: list[FacePersonDetail] = []
    if USERS_DIR.is_dir():
        img_exts = {".jpg", ".jpeg", ".png", ".bmp"}
        for d in sorted(USERS_DIR.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            photos = sorted(f.name for f in d.iterdir() if f.is_file() and f.suffix.lower() in img_exts)
            other_files = sorted(f.name for f in d.iterdir() if f.is_file() and f.suffix.lower() not in img_exts)
            mood_dir = d / "mood"
            mood_days = sorted(f.stem for f in mood_dir.iterdir() if f.suffix == ".jsonl") if mood_dir.is_dir() else []
            wb_dir = d / "wellbeing"
            wellbeing_days = sorted(f.stem for f in wb_dir.iterdir() if f.suffix == ".jsonl") if wb_dir.is_dir() else []
            music_sugg_dir = d / "music-suggestions"
            music_suggestion_days = sorted(f.stem for f in music_sugg_dir.iterdir() if f.suffix == ".jsonl") if music_sugg_dir.is_dir() else []
            audio_hist_dir = d / "audio_history"
            audio_history_days = sorted(f.stem for f in audio_hist_dir.iterdir() if f.suffix == ".jsonl") if audio_hist_dir.is_dir() else []
            voice_dir = d / "voice"
            voice_samples = sorted(f.name for f in voice_dir.iterdir() if f.is_file() and f.suffix.lower() in {".wav", ".mp3", ".ogg"}) if voice_dir.is_dir() else []
            habit_patterns = (d / "habit" / "patterns.json").is_file()
            meta = FaceRecognizer._read_metadata(d)
            persons.append(
                FacePersonDetail(
                    label=d.name,
                    telegram_username=meta.get("telegram_username"),
                    telegram_id=meta.get("telegram_id"),
                    photo_count=len(photos),
                    photos=photos,
                    mood_days=mood_days,
                    wellbeing_days=wellbeing_days,
                    music_suggestion_days=music_suggestion_days,
                    audio_history_days=audio_history_days,
                    voice_samples=voice_samples,
                    habit_patterns=habit_patterns,
                    files=other_files,
                )
            )
    return FaceOwnersDetailResponse(enrolled_count=len(persons), persons=persons)


@router.get("/face/photo/{label}/{filename}", tags=["Face"])
def face_photo(label: str, filename: str):
    """Serve an owner photo as JPEG."""
    from lelamp.service.sensing.perceptions.facerecognizer import USERS_DIR

    norm = FaceRecognizer.normalize_label(label)
    path = (USERS_DIR / norm / filename).resolve()
    if not str(path).startswith(str(USERS_DIR.resolve())):
        raise HTTPException(400, "invalid path")
    if not path.is_file():
        raise HTTPException(404, "photo not found")
    return Response(content=path.read_bytes(), media_type="image/jpeg")


@router.get("/face/file/{label}/{filepath:path}", tags=["Face"])
def face_file(label: str, filepath: str):
    """Serve any text file from a user's directory."""
    from lelamp.service.sensing.perceptions.facerecognizer import USERS_DIR

    norm = FaceRecognizer.normalize_label(label)
    path = (USERS_DIR / norm / filepath).resolve()
    if not str(path).startswith(str(USERS_DIR.resolve())):
        raise HTTPException(400, "invalid path")
    if not path.is_file():
        raise HTTPException(404, "file not found")
    mime = "application/json" if path.suffix in (".json", ".jsonl") else "text/plain"
    return Response(content=path.read_bytes(), media_type=mime)


@router.post("/face/remove", response_model=FaceRemoveResponse, tags=["Face"])
def face_remove(req: FaceRemoveRequest):
    """Remove one person's saved photos and re-train from disk."""
    fr = _require_face_recognizer()
    norm = FaceRecognizer.normalize_label(req.label)
    if not fr.remove_person(req.label):
        raise HTTPException(404, "person not found")
    return FaceRemoveResponse(
        status="ok",
        label=norm,
        enrolled_count=fr.enrolled_count(),
    )


@router.post("/face/photo/remove", response_model=StatusResponse, tags=["Face"])
def face_photo_remove(req: FacePhotoRemoveRequest):
    """Remove a single photo from a person and re-train."""
    fr = _require_face_recognizer()
    if not fr.remove_photo(req.label, req.filename):
        raise HTTPException(404, "photo not found")
    return {"status": "ok"}


@router.post("/face/reset", response_model=FaceResetResponse, tags=["Face"])
def face_reset():
    """Clear all enrolled embeddings and delete all photos on disk."""
    fr = _require_face_recognizer()
    fr.reset_enrolled()
    return FaceResetResponse(status="ok", enrolled_count=0)


@router.get("/face/stranger-stats", tags=["Face"])
def face_stranger_stats():
    """Return visit counts for all tracked stranger IDs."""
    fr = _require_face_recognizer()
    return fr.stranger_stats()


@router.get("/face/cooldowns", tags=["Face"])
def face_cooldowns():
    """Return current cooldown state for all tracked persons."""
    fr = _require_face_recognizer()
    return fr.cooldown_state()


@router.post("/face/cooldowns/reset", tags=["Face"])
def face_cooldowns_reset():
    """Reset all face recognition cooldown timers."""
    fr = _require_face_recognizer()
    fr.reset_cooldowns()
    return {"status": "ok"}


# --- User ---

def _resolve_user_dir(name: str) -> tuple[str, Path]:
    """Resolve user name and directory."""
    from lelamp.service.sensing.perceptions.facerecognizer import USERS_DIR, FaceRecognizer as FR

    norm = FR.normalize_label(name) if name else state.DEFAULT_USER
    user_dir = USERS_DIR / norm
    user_dir.mkdir(parents=True, exist_ok=True)
    return norm, user_dir


@router.get("/user/info", response_model=UserInfoResponse, tags=["User"])
def user_info(name: str = ""):
    """Get basic user info: name, is_friend, telegram identity."""
    from lelamp.service.sensing.perceptions.facerecognizer import FaceRecognizer as FR

    actual_name = name or state.DEFAULT_USER
    norm, user_dir = _resolve_user_dir(actual_name)
    meta = FR._read_metadata(user_dir)
    img_exts = {".jpg", ".jpeg", ".png", ".bmp"}
    is_friend = any(f.suffix.lower() in img_exts for f in user_dir.iterdir() if f.is_file())

    return UserInfoResponse(
        name=norm,
        is_friend=is_friend,
        telegram_id=meta.get("telegram_id"),
        telegram_username=meta.get("telegram_username"),
    )
