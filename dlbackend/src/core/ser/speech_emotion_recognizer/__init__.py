"""Speech Emotion Recognition (SER) engine package.

Layout:

* :mod:`.base`          -- ABC :class:`SpeechEmotionRecognizer`.
* :mod:`.audio_io`      -- backend-agnostic audio loading helpers.
* :mod:`.onnx_base`     -- :class:`OnnxSpeechEmotionRecognizer` mid-layer.
* :mod:`.emotion2vec`   -- concrete :class:`Emotion2VecPlusLargeRecognizer`.
* :mod:`.factory`       -- registry + ``create_speech_emotion_recognizer``.

Public names are re-exported below so callers can keep using the flat
``from core.ser.speech_emotion_recognizer import ...`` style.
"""

from .audio_utils import load_waveform, normalize_waveform, resample, to_mono
from .base import SpeechEmotionRecognizer
from .emotion2vec import Emotion2VecPlusLargeRecognizer
from .factory import (
    DEFAULT_SER_ENGINE,
    ENV_SER_ENGINE,
    ENV_SER_LABELS_PATH,
    ENV_SER_MODEL_PATH,
    SER_ENGINES,
    create_speech_emotion_recognizer,
    resolve_engine_name,
)
from .onnx_base import OnnxSpeechEmotionRecognizer

BaseSpeechEmotionRecognizer = SpeechEmotionRecognizer

__all__ = [
    "BaseSpeechEmotionRecognizer",
    "DEFAULT_SER_ENGINE",
    "Emotion2VecPlusLargeRecognizer",
    "ENV_SER_ENGINE",
    "ENV_SER_LABELS_PATH",
    "ENV_SER_MODEL_PATH",
    "OnnxSpeechEmotionRecognizer",
    "SER_ENGINES",
    "SpeechEmotionRecognizer",
    "create_speech_emotion_recognizer",
    "load_waveform",
    "normalize_waveform",
    "resample",
    "resolve_engine_name",
    "to_mono",
]
