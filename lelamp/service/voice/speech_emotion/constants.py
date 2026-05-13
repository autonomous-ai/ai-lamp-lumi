"""Defaults & label vocabulary for speech emotion recognition.

Bucketing mirrors the face emotion processor so downstream skills/dedup
share the same polarity language. emotion2vec_plus_large labels (from
dlbackend `/api/dl/ser/labels`):

    angry, disgusted, fearful, happy, neutral, other, sad, surprised, <unk>
"""

from __future__ import annotations

# --- API contract ---------------------------------------------------------

DEFAULT_DL_SER_ENDPOINT: str = "/lelamp/api/dl/ser/recognize"
DEFAULT_API_TIMEOUT_S: float = 15.0

# --- Input gating ---------------------------------------------------------

DEFAULT_MIN_AUDIO_S: float = 3.0
DEFAULT_CONFIDENCE_THRESHOLD: float = 0.5

# --- Buffering / dedup ---------------------------------------------------

DEFAULT_FLUSH_S: float = 10.0
DEFAULT_DEDUP_WINDOW_S: float = 300.0
DEFAULT_QUEUE_MAXSIZE: int = 32

# --- Polarity buckets -----------------------------------------------------
# Matches face emotion processor's EMOTION_BUCKETS shape so (user, bucket)
# dedup keys are interpretable across modalities.

LABEL_BUCKETS: dict[str, str] = {
    "happy": "positive",
    "surprised": "positive",
    "angry": "negative",
    "disgusted": "negative",
    "fearful": "negative",
    "sad": "negative",
    # Anything not in the map collapses to "other" via utils.bucket_for().
}

# Labels we treat as "no signal" — never flushed, never deduped. Mirrors
# the face-side `if emotion == "Neutral": continue` rule.
NEUTRAL_LABELS: frozenset[str] = frozenset(
    {"neutral", "other", "<unk>", "unk", ""}
)

HEDGE_BY_BUCKET: dict[str, str] = {
    "positive": "do not over-celebrate",
    "negative": "do not assume the user is distressed",
    "other": "do not over-react",
}

# --- Wire format ----------------------------------------------------------

SENSING_EVENT_TYPE: str = "speech_emotion.detected"
UNKNOWN_USER_LABEL: str = "unknown"
