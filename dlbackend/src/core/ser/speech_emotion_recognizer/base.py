"""Abstract base class for Speech Emotion Recognition engines.

Defines *only* the contract every SER engine must satisfy, plus the
backend-agnostic plumbing every engine ends up needing:

* keep a list of labels in stable order;
* dispatch :meth:`predict` so callers can pass a file path / URL / raw
  numpy waveform interchangeably;
* turn a raw probability vector into the canonical response dict.

Anything model-specific (ONNX session, framework imports, model file
download / build, ...) lives in subclasses such as
:class:`OnnxSpeechEmotionRecognizer`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Sequence, Union

import numpy as np

from core.ser.speech_emotion_recognizer.audio_utils import load_waveform, normalize_waveform

AudioInput = Union[str, Path]
WaveformLike = Union[np.ndarray, Sequence[float]]


def _load_labels_file(path: Union[str, Path]) -> List[str]:
    """Read a one-label-per-line text file in stable order."""
    labels_path = Path(path)
    if not labels_path.exists():
        raise FileNotFoundError(f"Labels file not found: {labels_path}")
    labels: List[str] = []
    for line in labels_path.read_text(encoding="utf-8").splitlines():
        token = line.strip()
        if token:
            labels.append(token)
    if not labels:
        raise ValueError(f"Labels file is empty: {labels_path}")
    return labels


class SpeechEmotionRecognizer(ABC):
    """Abstract Speech Emotion Recognizer.

    Subclasses MUST provide:

    * :attr:`sample_rate` -- model's native input sample rate (Hz).
    * :meth:`predict_from_waveform` -- run inference on a mono float32
      waveform that is **already** at :attr:`sample_rate` and return a
      raw probability vector (length ``num_classes``).

    Subclasses MAY override:

    * :meth:`predict` if they need to bypass the default dispatch
      (e.g. a streaming model that wants to ingest chunks differently).
    """

    ENGINE_NAME: str = "base"
    DEFAULT_LABELS_PATH: Path = Path("")

    def __init__(self, labels_path: Union[str, Path, None] = None) -> None:
        labels_src = labels_path or self.DEFAULT_LABELS_PATH
        if not labels_src:
            raise ValueError(
                f"Engine '{self.ENGINE_NAME}' must provide labels_path or "
                "DEFAULT_LABELS_PATH."
            )
        self.labels: List[str] = _load_labels_file(labels_src)
        self.num_classes: int = len(self.labels)

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Native input sample rate of the underlying model (Hz)."""

    @abstractmethod
    def predict_from_waveform(self, waveform: np.ndarray) -> np.ndarray:
        """Run inference on a mono float32 waveform at ``self.sample_rate``.

        Args:
            waveform: 1-D float32 array, shape ``[T]``.

        Returns:
            1-D float32 probability vector, shape ``[num_classes]``.
            The vector is expected to be a proper softmax (sums to ~1).
        """

    def predict(
        self,
        audio: Union[AudioInput, WaveformLike],
        sample_rate: int | None = None,
    ) -> Dict[str, Any]:
        """Classify one utterance.

        Args:
            audio: Either a file path / URL string (loaded via
                ``soundfile``) or a raw 1-D numpy / sequence waveform.
            sample_rate: Required when ``audio`` is a raw waveform whose
                sample rate differs from :attr:`sample_rate`.

        Returns:
            Dict with keys:

            * ``label`` -- argmax label (top-1).
            * ``confidence`` -- probability of the top label, ``[0, 1]``.
            * ``scores`` -- ordered ``{label: probability}`` mapping.
        """
        if isinstance(audio, (str, Path)):
            waveform, orig_sr = load_waveform(audio)
            waveform = normalize_waveform(
                waveform, orig_sr, target_sr=self.sample_rate
            )
        else:
            arr = np.asarray(audio, dtype=np.float32)
            sr = int(sample_rate) if sample_rate is not None else self.sample_rate
            waveform = normalize_waveform(arr, sr, target_sr=self.sample_rate)

        probs = self.predict_from_waveform(waveform)
        return self._format_response(probs)

    def _format_response(self, probs: np.ndarray) -> Dict[str, Any]:
        """Convert a probability vector into the canonical response dict."""
        probs = np.asarray(probs, dtype=np.float32).reshape(-1)
        if probs.shape[0] != self.num_classes:
            raise RuntimeError(
                f"Model produced {probs.shape[0]} classes but labels file has "
                f"{self.num_classes}; check labels.txt vs model export."
            )
        top_idx = int(np.argmax(probs))
        return {
            "label": self.labels[top_idx],
            "confidence": float(probs[top_idx]),
            "scores": {label: float(probs[i]) for i, label in enumerate(self.labels)},
        }
