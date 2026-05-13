"""Backend-agnostic audio I/O helpers for SER engines.

Pure functions that work on numpy arrays. Optional heavy dependencies
(``soundfile``, ``scipy``) are lazy-imported and raise a clear
``ImportError`` only when the function that needs them is actually called.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Tuple, Union

import numpy as np

try:
    import soundfile as sf
except ImportError:
    sf = None

try:
    from scipy.signal import resample_poly
except ImportError:
    resample_poly = None

AudioPath = Union[str, Path]


def load_waveform(path: AudioPath) -> Tuple[np.ndarray, int]:
    """Read an audio file from disk as float32, returning ``(waveform, sr)``.

    The waveform may be 1-D (mono) or 2-D (``[T, C]``). Use
    :func:`normalize_waveform` to enforce mono + target sample rate.
    """
    if sf is None:
        raise ImportError("soundfile is required to load audio files.")
    waveform, sample_rate = sf.read(str(path), dtype="float32")
    return np.asarray(waveform, dtype=np.float32), int(sample_rate)


def to_mono(waveform: np.ndarray) -> np.ndarray:
    """Collapse a stereo (``[T, C]``) waveform to mono by channel mean."""
    arr = np.asarray(waveform, dtype=np.float32)
    if arr.ndim == 2:
        return arr.mean(axis=1)
    if arr.ndim != 1:
        raise ValueError("Waveform must be 1D [T] or 2D [T, C].")
    return arr


def resample(waveform: np.ndarray, orig_sr: int, new_sr: int) -> np.ndarray:
    """Polyphase resample 1-D waveform from ``orig_sr`` to ``new_sr``."""
    if orig_sr == new_sr:
        return np.asarray(waveform, dtype=np.float32)
    if resample_poly is None:
        raise ImportError("scipy is required for resampling.")
    gcd = math.gcd(int(orig_sr), int(new_sr))
    up = int(new_sr // gcd)
    down = int(orig_sr // gcd)
    return resample_poly(waveform, up, down).astype(np.float32)


def normalize_waveform(
    waveform: np.ndarray, orig_sr: int, target_sr: int
) -> np.ndarray:
    """Force mono + ``target_sr`` + contiguous float32. The canonical
    pre-inference shape used by every SER engine in this package.
    """
    arr = to_mono(waveform)
    if int(orig_sr) != int(target_sr):
        arr = resample(arr, orig_sr=int(orig_sr), new_sr=int(target_sr))
    return np.ascontiguousarray(arr, dtype=np.float32)
