"""Concrete Emotion2Vec+ Large ONNX engine.

Reference: https://huggingface.co/iic/emotion2vec_plus_large
"""

from __future__ import annotations

from pathlib import Path

from core.ser.speech_emotion_recognizer.onnx_base import OnnxSpeechEmotionRecognizer


SER_BASE_DIR = Path(__file__).resolve().parent.parent


class Emotion2VecPlusLargeRecognizer(OnnxSpeechEmotionRecognizer):
    """Emotion2Vec+ Large -- 9 emotion classes (incl. ``<unk>``).

    Inference is plain ONNX Runtime: raw 16 kHz mono waveform in,
    softmax probabilities out. No fbank, no VAD.
    """

    ENGINE_NAME = "emotion2vec_plus_large"
    MODEL_ID = "iic/emotion2vec_plus_large"
    DEFAULT_REMOTE_MODEL_PATH = ""
    DEFAULT_LOCAL_MODEL_PATH = SER_BASE_DIR / "models" / "emotion2vec_plus_large" / "emotion2vec.onnx"
    DEFAULT_LABELS_PATH = SER_BASE_DIR / "models" / "emotion2vec_plus_large" / "labels.txt"
