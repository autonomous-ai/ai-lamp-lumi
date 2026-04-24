"""Utility helpers for audio preprocessing before speaker embedding.

Thin, dependency-tolerant layers that ``BaseAudioRecognizer`` calls in the
embedding path. Each optional layer (``noisereduce``, ``silero-vad``,
``scipy``, ``torch``) degrades to a no-op when its dependency is missing so
the service never hard-fails.

Pipeline (applied in order by :func:`preprocess_for_embedding`):

1. High-pass filter (80 Hz)  -- opt-in (``use_hpf=False`` by default);
                                when enabled, removes DC / rumble before
                                the noise profile is estimated.
2. ``noisereduce``           -- attenuate stationary background noise.
3. Strip-VAD + gate          -- trim leading/trailing non-voice, keep the
                                internal silence; reject audio when the
                                remaining clip is too short or too noisy.
4. RMS loudness normalize    -- align enroll/query loudness.

After preprocessing the waveform is fed as a **single window** to the
embedding model. Long audio is cut into contiguous chunks with each piece
constrained to ``[min_sec, max_sec]`` (default 5-8 s) by
:func:`split_by_duration`; short audio is passed through as-is. This
matches the behavior of the WeSpeaker CLI instead of doing short-chunk
sliding-window aggregation.
"""

from __future__ import annotations

import logging
import math
from typing import List, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Layer 1 - noise reduction (``noisereduce`` non-stationary)
# ---------------------------------------------------------------------------

def reduce_noise(waveform: np.ndarray, sample_rate: int) -> np.ndarray:
    """Apply ``noisereduce`` (non-stationary) if the library is installed."""
    arr = np.asarray(waveform, dtype=np.float32)
    if arr.size == 0:
        return arr
    try:
        import noisereduce as nr
    except ImportError:
        return arr
    try:
        cleaned = nr.reduce_noise(y=arr, sr=int(sample_rate), stationary=False)
        return np.asarray(cleaned, dtype=np.float32)
    except Exception as exc:  # pragma: no cover - depends on runtime env
        logger.debug("noisereduce failed, falling back to raw waveform: %s", exc)
        return arr


# ---------------------------------------------------------------------------
# Silero-VAD loader (shared lazy cache)
# ---------------------------------------------------------------------------

_SILERO_STATE: dict = {"tried": False, "model": None, "utils": None}


def _load_silero_vad():
    """Lazy-load silero-vad. Prefer the pip package, fall back to torch.hub."""
    if _SILERO_STATE["tried"]:
        return _SILERO_STATE["model"], _SILERO_STATE["utils"]
    _SILERO_STATE["tried"] = True
    try:
        from silero_vad import load_silero_vad, get_speech_timestamps  # type: ignore

        _SILERO_STATE["model"] = load_silero_vad()
        _SILERO_STATE["utils"] = {"get_speech_timestamps": get_speech_timestamps}
        return _SILERO_STATE["model"], _SILERO_STATE["utils"]
    except Exception as exc:
        logger.debug("silero-vad pip package not usable: %s", exc)
    try:
        import torch  # noqa: F401

        model, utils = torch.hub.load(  # type: ignore[attr-defined]
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
            onnx=False,
        )
        get_speech_timestamps = utils[0]
        _SILERO_STATE["model"] = model
        _SILERO_STATE["utils"] = {"get_speech_timestamps": get_speech_timestamps}
    except Exception as exc:  # pragma: no cover - requires network / torch
        logger.info("silero-vad unavailable, skipping VAD: %s", exc)
    return _SILERO_STATE["model"], _SILERO_STATE["utils"]


def _silero_timestamps(
    waveform: np.ndarray,
    sample_rate: int,
    *,
    min_speech_sec: float,
    min_silence_sec: float,
    speech_pad_sec: float,
) -> List[dict]:
    """Run silero-vad and return raw ``[{start, end}]`` in sample indices.

    Returns an empty list when the model or ``torch`` is unavailable, or when
    inference fails.
    """
    arr = np.asarray(waveform, dtype=np.float32)
    if arr.size == 0:
        return []
    model, utils = _load_silero_vad()
    if model is None or utils is None:
        return []
    try:
        import torch
    except ImportError:
        return []
    try:
        ts = utils["get_speech_timestamps"](
            torch.from_numpy(arr),
            model,
            sampling_rate=int(sample_rate),
            min_speech_duration_ms=int(min_speech_sec * 1000),
            min_silence_duration_ms=int(min_silence_sec * 1000),
            speech_pad_ms=int(speech_pad_sec * 1000),
            return_seconds=False,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("silero-vad inference failed: %s", exc)
        return []
    return list(ts) if ts else []


def strip_nonvoice(
    waveform: np.ndarray,
    sample_rate: int,
    *,
    min_speech_sec: float = 0.2,
    min_silence_sec: float = 0.3,
    speech_pad_sec: float = 0.1,
) -> Tuple[np.ndarray, float]:
    """Trim only leading and trailing non-voice regions.

    Internal silence between speech regions is **kept**, matching WeSpeaker's
    assumption of only head/tail silence. Returns ``(stripped, voice_ratio)``
    where ``voice_ratio`` is the fraction of speech samples over the length
    of ``stripped``.

    Fallback behavior:

    * Empty input: ``(empty, 0.0)``.
    * VAD unavailable (``silero-vad``/``torch`` missing): ``(waveform, 1.0)``
      so the embedding gate does not reject on a missing dependency.
    * VAD ran but detected no speech: ``(empty, 0.0)``.
    """
    arr = np.asarray(waveform, dtype=np.float32)
    if arr.size == 0:
        return np.zeros(0, dtype=np.float32), 0.0

    model, utils = _load_silero_vad()
    if model is None or utils is None:
        return arr, 1.0

    segs = _silero_timestamps(
        arr,
        sample_rate,
        min_speech_sec=min_speech_sec,
        min_silence_sec=min_silence_sec,
        speech_pad_sec=speech_pad_sec,
    )
    if not segs:
        return np.zeros(0, dtype=np.float32), 0.0

    first_start = max(0, int(segs[0].get("start", 0)))
    last_end = min(int(arr.size), int(segs[-1].get("end", arr.size)))
    if last_end <= first_start:
        return np.zeros(0, dtype=np.float32), 0.0

    stripped = arr[first_start:last_end]
    # Merge overlapping intervals before counting: silero-vad's
    # ``speech_pad_ms`` pads each segment on both sides, so two segments
    # separated by a silence shorter than ``2 * speech_pad_ms`` overlap in
    # the returned list. Summing ``e - s`` directly would double-count the
    # overlap and inflate ``voice_ratio`` past the gate.
    intervals = []
    for ts in segs:
        s = max(first_start, int(ts.get("start", 0)))
        e = min(last_end, int(ts.get("end", 0)))
        if e > s:
            intervals.append((s, e))
    intervals.sort()
    speech_samples = 0
    prev_end = first_start
    for s, e in intervals:
        s = max(s, prev_end)
        if e > s:
            speech_samples += e - s
            prev_end = e
    ratio = float(speech_samples) / float(max(1, stripped.size))
    return stripped.astype(np.float32, copy=False), float(min(1.0, max(0.0, ratio)))


# ---------------------------------------------------------------------------
# Layer 1b - high-pass filter
# ---------------------------------------------------------------------------

def high_pass_filter(
    waveform: np.ndarray,
    sample_rate: int,
    cutoff_hz: float = 80.0,
    order: int = 4,
) -> np.ndarray:
    """4th-order Butterworth HPF at ``cutoff_hz`` (zero-phase)."""
    arr = np.asarray(waveform, dtype=np.float32)
    if arr.size == 0:
        return arr
    try:
        from scipy.signal import butter, sosfiltfilt
    except ImportError:
        return arr
    nyq = 0.5 * float(sample_rate)
    if cutoff_hz <= 0.0 or cutoff_hz >= nyq:
        return arr
    try:
        sos = butter(order, cutoff_hz / nyq, btype="highpass", output="sos")
        filtered = sosfiltfilt(sos, arr)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("high_pass_filter failed: %s", exc)
        return arr
    return np.asarray(filtered, dtype=np.float32)


# ---------------------------------------------------------------------------
# Layer 1c - RMS loudness normalization
# ---------------------------------------------------------------------------

def rms_normalize(
    waveform: np.ndarray,
    target_rms: float = 0.1,
    max_gain: float = 20.0,
    eps: float = 1e-6,
) -> np.ndarray:
    """Scale waveform to a fixed RMS so enroll/query share the same loudness."""
    arr = np.asarray(waveform, dtype=np.float32)
    if arr.size == 0:
        return arr
    rms = float(np.sqrt(np.mean(arr ** 2)))
    if rms < eps:
        return arr
    gain = min(target_rms / rms, max_gain)
    return (arr * gain).astype(np.float32)


# ---------------------------------------------------------------------------
# Full preprocessing pipeline with gate
# ---------------------------------------------------------------------------

def preprocess_for_embedding(
    waveform: np.ndarray,
    sample_rate: int,
    *,
    use_hpf: bool = False,
    use_noisereduce: bool = True,
    use_vad: bool = True,
    use_rms: bool = True,
    hpf_cutoff_hz: float = 80.0,
    rms_target: float = 0.1,
    min_duration_sec: float = 0.5,
    min_voice_ratio: float = 0.7,
) -> np.ndarray:
    """Run (optional HPF) -> noisereduce -> strip-VAD + gate -> RMS.

    HPF is opt-in (``use_hpf=False`` default) because the WeSpeaker /
    ECAPA-TDNN fbank front-end already attenuates sub-80 Hz bands; enable
    it only for domains with heavy DC / rumble.

    Order rationale:

    * HPF (when enabled) first so DC/rumble doesn't pollute
      ``noisereduce``'s noise profile.
    * ``noisereduce`` before VAD so the voice/silence boundary is sharper.
    * Strip-VAD before RMS so loudness is measured on the speech portion.
    * RMS last so embedding input has a consistent energy scale.

    Returns an **empty** ``float32`` array when the speech gate rejects the
    clip (VAD removed everything, stripped clip shorter than
    ``min_duration_sec``, or voice/total ratio below ``min_voice_ratio``).
    Callers should treat the empty return as "no embedding" and surface that
    back to the client.
    """
    out = np.asarray(waveform, dtype=np.float32)
    if out.size == 0:
        return out

    if use_hpf:
        out = high_pass_filter(out, sample_rate, cutoff_hz=hpf_cutoff_hz)
    if use_noisereduce:
        out = reduce_noise(out, sample_rate)

    if use_vad:
        stripped, voice_ratio = strip_nonvoice(out, sample_rate)
        if stripped.size == 0:
            logger.debug("preprocess gate: VAD removed all audio")
            return np.zeros(0, dtype=np.float32)
        duration = stripped.size / max(1, int(sample_rate))
        if duration < float(min_duration_sec):
            logger.debug(
                "preprocess gate: stripped=%.3fs < min=%.3fs",
                duration,
                float(min_duration_sec),
            )
            return np.zeros(0, dtype=np.float32)
        if voice_ratio < float(min_voice_ratio):
            logger.debug(
                "preprocess gate: voice_ratio=%.3f < min=%.3f (dur=%.2fs)",
                voice_ratio,
                float(min_voice_ratio),
                duration,
            )
            return np.zeros(0, dtype=np.float32)
        out = stripped

    if use_rms:
        out = rms_normalize(out, target_rms=rms_target)
    return out


# ---------------------------------------------------------------------------
# Length-cap split (only used for long audio)
# ---------------------------------------------------------------------------

def split_by_duration(
    waveform: np.ndarray,
    sample_rate: int,
    min_sec: float = 5.0,
    max_sec: float = 8.0,
) -> List[np.ndarray]:
    """Split into contiguous chunks so every chunk is in ``[min_sec, max_sec]``.

    Given the stripped + preprocessed waveform of length ``T`` seconds:

    * ``T <= max_sec``                 -> single window ``[T]`` (no split).
    * ``max_sec < T <= 2 * min_sec``   -> **still a single window** (``T`` up
      to roughly ``2 * min_sec`` seconds). Splitting into two pieces here
      would produce chunks shorter than ``min_sec``, so we prefer one
      slightly-long window over two under-sized ones. Matches WeSpeaker's
      "one utterance, one embedding" behavior for mid-length audio.
    * ``T > 2 * min_sec``              -> ``n = ceil(T / max_sec)`` equal
      pieces of length ``T / n``. By construction
      ``min_sec <= T/n <= max_sec`` in this branch.

    With defaults ``min_sec=5``, ``max_sec=8`` this means:

    * <= 8 s  -> 1 window
    * 8-10 s  -> 1 window (length 8-10 s)
    * > 10 s  -> 2+ windows, each in [5, 8] s (last one also in range)

    Args:
        waveform: 1D float array (any sample rate).
        sample_rate: samples per second.
        min_sec: minimum desired chunk length when splitting (seconds).
        max_sec: maximum desired chunk length when splitting (seconds).

    Returns:
        List of float32 waveform chunks; empty if input is empty.
    """
    arr = np.asarray(waveform, dtype=np.float32)
    if arr.size == 0:
        return []
    if min_sec <= 0 or max_sec <= 0 or max_sec < min_sec:
        raise ValueError(
            f"Invalid split range: min_sec={min_sec}, max_sec={max_sec}"
        )

    duration_sec = arr.size / float(max(1, sample_rate))

    # Short / mid-length audio: single window. The 2*min_sec cap is the
    # longest T for which equal-splitting into 2 pieces would still drop
    # each piece below min_sec; keeping it as one window avoids that.
    if duration_sec <= max(max_sec, 2.0 * min_sec):
        return [arr.astype(np.float32, copy=True)]

    # Long audio: equal split, piece length in [min_sec, max_sec].
    n_chunks = max(2, math.ceil(duration_sec / max_sec))
    # Sample-accurate boundaries using linspace so the final chunk covers
    # the exact tail and all chunks differ by <= 1 sample.
    boundaries = np.linspace(0, arr.size, n_chunks + 1, dtype=np.int64)
    chunks: List[np.ndarray] = []
    for i in range(n_chunks):
        start = int(boundaries[i])
        end = int(boundaries[i + 1])
        if end > start:
            chunks.append(arr[start:end].astype(np.float32, copy=True))
    return chunks


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _l2(x: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    arr = np.asarray(x, dtype=np.float32)
    n = float(np.linalg.norm(arr))
    if n < eps:
        return arr
    return (arr / n).astype(np.float32)


def mean_aggregate(embeddings: Sequence[np.ndarray]) -> np.ndarray:
    """Simple L2-normalize -> mean -> L2-normalize.

    Used whenever multiple embeddings must collapse into one vector:

    * multi-utterance enroll (several wav files per speaker in ``register``),
    * single long utterance split by :func:`split_by_duration` into 5-8 s
      windows,
    * both combined.

    When the input fits in a single window this function is not called --
    the lone embedding is returned as-is (matches WeSpeaker's "one
    embedding per utterance" behavior). The per-input L2 step is kept as
    a safety net in case callers pass un-normalized embeddings.
    """
    if not embeddings:
        raise ValueError("No embeddings to aggregate.")
    stack = np.stack([_l2(e) for e in embeddings], axis=0)
    return _l2(stack.mean(axis=0))
