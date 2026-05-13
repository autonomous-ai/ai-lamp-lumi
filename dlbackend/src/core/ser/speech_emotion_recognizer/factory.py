"""SER engine factory + registry.

Selection precedence:

1. Explicit ``engine`` argument.
2. ``SER_ENGINE`` env var.
3. :data:`DEFAULT_SER_ENGINE`.

Model-path precedence (forwarded to the engine constructor):

1. Explicit ``model_path`` argument.
2. ``SER_MODEL_PATH`` env var.
3. Engine class defaults (cached local → remote URL → FunASR export).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Type, Union

from core.ser.speech_emotion_recognizer.base import SpeechEmotionRecognizer
from core.ser.speech_emotion_recognizer.emotion2vec import Emotion2VecPlusLargeRecognizer

logger = logging.getLogger(__name__)


ENV_SER_ENGINE = "SER_ENGINE"
ENV_SER_MODEL_PATH = "SER_MODEL_PATH"


SER_ENGINES: Dict[str, Type[SpeechEmotionRecognizer]] = {
    Emotion2VecPlusLargeRecognizer.ENGINE_NAME: Emotion2VecPlusLargeRecognizer,
}


DEFAULT_SER_ENGINE = Emotion2VecPlusLargeRecognizer.ENGINE_NAME


def resolve_engine_name(engine: str | None = None) -> str:
    """Pick engine name from explicit arg, env var, or default."""
    if engine:
        return engine.strip().lower()
    env_value = os.getenv(ENV_SER_ENGINE, "").strip().lower()
    return env_value or DEFAULT_SER_ENGINE


def create_speech_emotion_recognizer(
    engine: str | None = None,
    model_path: Union[str, Path, None] = None,
    **kwargs: Any,
) -> SpeechEmotionRecognizer:
    """Instantiate the configured SER engine.

    Args:
        engine: Engine identifier. See :data:`SER_ENGINES` keys. ``None``
            falls back to env var / default.
        model_path: Local path or http(s) URL to the ONNX file. ``None``
            falls back to ``SER_MODEL_PATH`` env, then engine defaults.
        **kwargs: Forwarded to the engine constructor (e.g.
            ``labels_path``, ``sample_rate``, ``intra_op_threads``).

    Raises:
        ValueError: Unknown engine name.
    """
    name = resolve_engine_name(engine)
    cls = SER_ENGINES.get(name)
    if cls is None:
        available = ", ".join(sorted(SER_ENGINES.keys()))
        raise ValueError(f"Unknown SER engine '{name}'. Available: {available}")

    resolved_model_path = model_path
    if resolved_model_path is None:
        env_path = os.getenv(ENV_SER_MODEL_PATH, "").strip()
        if env_path:
            resolved_model_path = env_path

    source = (
        "arg" if engine
        else ("env" if os.getenv(ENV_SER_ENGINE) else "default")
    )
    msg = (
        f"[SER] create_speech_emotion_recognizer engine='{name}' "
        f"source={source} class={cls.__name__} "
        f"model_path={resolved_model_path!r}"
    )
    logger.info(msg)
    print(msg, flush=True)

    return cls(model_path=resolved_model_path, **kwargs)
