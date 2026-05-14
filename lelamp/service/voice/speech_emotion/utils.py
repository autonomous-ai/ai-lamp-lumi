"""Pure helpers for the speech emotion pipeline.

Kept free of I/O and threading so they can be unit-tested without spinning
up the service or hitting dlbackend.
"""

from __future__ import annotations

from lelamp.service.voice.speech_emotion.constants import (
    HEDGE_BY_BUCKET,
    LABEL_BUCKETS,
    NEUTRAL_LABELS,
)


def normalize_label(label: str) -> str:
    return (label or "").strip().lower()


def is_neutral(label: str) -> bool:
    return normalize_label(label) in NEUTRAL_LABELS


def bucket_for(label: str) -> str:
    return LABEL_BUCKETS.get(normalize_label(label), "other")


def hedge_for(bucket: str) -> str:
    return HEDGE_BY_BUCKET.get(bucket, "do not over-react")


def format_message(label: str, confidence: float, bucket: str) -> str:
    """Hedged sensing message — symmetric with face emotion processor.

    Skill parsers on Lumi extract the raw label via regex on the
    "Speech emotion detected: <Label>." prefix; everything inside the
    parentheses is human-readable hint for the agent.
    """
    nice = normalize_label(label).capitalize() or "Unknown"
    return (
        f"Speech emotion detected: {nice}. "
        f"(weak voice cue; confidence={confidence:.2f}; "
        f"bucket={bucket}; treat as uncertain, {hedge_for(bucket)}.)"
    )
