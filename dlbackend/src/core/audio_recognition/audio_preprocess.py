"""Utility helpers for audio preprocessing before speaker embedding.

Organized as thin, dependency-tolerant layers that ``BaseAudioRecognizer``
calls in the embedding extraction path. Each layer degrades to a no-op when
its optional dependency is missing so the service never hard-fails just
because ``noisereduce`` / ``silero-vad`` / ``scipy`` / ``torch`` is absent.

Layers
------
- Layer 0 : stationary / non-stationary noise reduction (``noisereduce``).
- Layer 1 : 80 Hz high-pass, silero-VAD, RMS loudness normalization.
- Chunk   : short-chunk + fine-stride windowing for robust aggregation.
- Agg     : self-consistency weighted aggregation (robust to 1-2 interferer
            words chen vào that only poison a minority of chunks).
- Anchor  : percentile / margin based chunk filter when an enrolled centroid
            is available (kept here as a pure helper; not wired into the
            recognize flow to avoid touching matching logic).
"""

from __future__ import annotations

import logging
from typing import List, Optional, Sequence

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Layer 0 - noise reduction
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
# Layer 1a - silero VAD
# ---------------------------------------------------------------------------

_SILERO_STATE: dict = {"tried": False, "model": None, "utils": None}


def _load_silero_vad():
    """Lazy-load silero-vad. Prefer the pip package, fall back to torch.hub."""
    if _SILERO_STATE["tried"]:
        return _SILERO_STATE["model"], _SILERO_STATE["utils"]
    _SILERO_STATE["tried"] = True
    # Preferred path: pip install silero-vad
    try:
        from silero_vad import load_silero_vad, get_speech_timestamps  # type: ignore

        _SILERO_STATE["model"] = load_silero_vad()
        _SILERO_STATE["utils"] = {"get_speech_timestamps": get_speech_timestamps}
        return _SILERO_STATE["model"], _SILERO_STATE["utils"]
    except Exception as exc:
        logger.debug("silero-vad pip package not usable: %s", exc)
    # Fallback: torch.hub
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


def apply_vad(
    waveform: np.ndarray,
    sample_rate: int,
    *,
    min_speech_sec: float = 0.2,
    min_silence_sec: float = 0.3,
    speech_pad_sec: float = 0.1,
) -> np.ndarray:
    """Keep only speech regions detected by silero-vad.

    Falls back to the original waveform when VAD is unavailable or detects
    nothing (we prefer "keep everything" over "return empty audio").
    """
    arr = np.asarray(waveform, dtype=np.float32)
    if arr.size == 0:
        return arr
    model, utils = _load_silero_vad()
    if model is None or utils is None:
        return arr
    try:
        import torch
    except ImportError:
        return arr

    wav_tensor = torch.from_numpy(arr)
    try:
        timestamps = utils["get_speech_timestamps"](
            wav_tensor,
            model,
            sampling_rate=int(sample_rate),
            min_speech_duration_ms=int(min_speech_sec * 1000),
            min_silence_duration_ms=int(min_silence_sec * 1000),
            speech_pad_ms=int(speech_pad_sec * 1000),
            return_seconds=False,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("silero-vad inference failed: %s", exc)
        return arr

    if not timestamps:
        return arr

    pieces: List[np.ndarray] = []
    for ts in timestamps:
        start = int(ts.get("start", 0))
        end = int(ts.get("end", 0))
        if end > start:
            pieces.append(arr[start:end])
    if not pieces:
        return arr
    return np.concatenate(pieces).astype(np.float32)


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
# Full preprocessing pipeline (Layer 0 + Layer 1)
# ---------------------------------------------------------------------------

def preprocess_waveform(
    waveform: np.ndarray,
    sample_rate: int,
    *,
    use_noisereduce: bool = True,
    use_vad: bool = True,
    use_hpf: bool = True,
    use_rms: bool = True,
    hpf_cutoff_hz: float = 80.0,
    rms_target: float = 0.1,
) -> np.ndarray:
    """Run the full preprocessing chain. Order chosen intentionally:

    1. HPF: kill DC / rumble first so later stages work on clean bands.
    2. Noise reduce: attenuate stationary background.
    3. VAD: drop silence / breath / non-speech (most-aggressive last so that
       any denoise artifacts are removed rather than embedded).
    4. RMS normalize: finally match loudness between enroll and query.
    """
    out = np.asarray(waveform, dtype=np.float32)
    if out.size == 0:
        return out
    if use_hpf:
        out = high_pass_filter(out, sample_rate, cutoff_hz=hpf_cutoff_hz)
    if use_noisereduce:
        out = reduce_noise(out, sample_rate)
    if use_vad:
        out = apply_vad(out, sample_rate)
    if use_rms:
        out = rms_normalize(out, target_rms=rms_target)
    return out


# ---------------------------------------------------------------------------
# Short-chunk + fine-stride windowing
# ---------------------------------------------------------------------------

def chunk_with_stride(
    waveform: np.ndarray,
    sample_rate: int,
    chunk_sec: float = 1.0,
    stride_sec: float = 0.25,
    min_chunk_sec: float = 0.4,
) -> List[np.ndarray]:
    """Split a 1-D waveform into overlapping chunks.

    Short chunks (~1s) with fine stride (~0.25s) concentrate any 0.3-1s
    interferer into a minority of chunks, which outlier / self-consistency
    rejection can then drop.
    """
    arr = np.asarray(waveform, dtype=np.float32)
    if arr.ndim != 1:
        raise ValueError("waveform must be 1D [time].")
    if arr.size == 0:
        return []
    chunk_samples = max(1, int(round(chunk_sec * sample_rate)))
    stride_samples = max(1, int(round(stride_sec * sample_rate)))
    min_samples = max(1, int(round(min_chunk_sec * sample_rate)))

    # Short input: return as a single chunk (better than dropping).
    if arr.size <= chunk_samples:
        if arr.size < min_samples:
            return [arr.copy()]
        return [arr.copy()]

    chunks: List[np.ndarray] = []
    for start in range(0, arr.size, stride_samples):
        end = start + chunk_samples
        seg = arr[start:end]
        if seg.size < min_samples:
            break
        chunks.append(seg.astype(np.float32, copy=True))
        if end >= arr.size:
            break
    if not chunks:
        chunks.append(arr.copy())
    return chunks


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def _l2(x: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    arr = np.asarray(x, dtype=np.float32)
    n = float(np.linalg.norm(arr))
    if n < eps:
        return arr
    return (arr / n).astype(np.float32)


def self_consistency_weights(
    embeddings: Sequence[np.ndarray],
    power: float = 4.0,
    eps: float = 1e-9,
) -> np.ndarray:
    """Weight each embedding by its cosine sim to the provisional centroid.

    Uses the L2-normalized median as a noise-robust centroid, maps sims
    from ``[-1, 1]`` to ``[0, 1]``, then raises to ``power`` to sharpen.
    Outlier chunks (interferer / heavy noise) get near-zero weight.
    """
    if not embeddings:
        return np.zeros(0, dtype=np.float32)
    stack = np.stack([_l2(e) for e in embeddings], axis=0)
    centroid = _l2(np.median(stack, axis=0))
    sims = stack @ centroid
    sims01 = np.clip((sims + 1.0) / 2.0, 0.0, 1.0)
    weights = sims01 ** float(power)
    total = float(weights.sum())
    if total < eps:
        return np.full(stack.shape[0], 1.0 / stack.shape[0], dtype=np.float32)
    return (weights / total).astype(np.float32)


def weighted_aggregate(
    embeddings: Sequence[np.ndarray],
    weights: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Aggregate embeddings via weighted mean + L2 normalize.

    When ``weights`` is ``None`` we derive them with
    :func:`self_consistency_weights`, which is the attentive aggregation
    described in Layer 3.
    """
    if not embeddings:
        raise ValueError("No embeddings to aggregate.")
    stack = np.stack([_l2(e) for e in embeddings], axis=0)
    if weights is None:
        weights = self_consistency_weights(embeddings)
    w = np.asarray(weights, dtype=np.float32).reshape(-1)
    if w.size != stack.shape[0]:
        raise ValueError("weights length must equal number of embeddings.")
    agg = (stack * w[:, None]).sum(axis=0)
    return _l2(agg)


# ---------------------------------------------------------------------------
# Anchor-based filtering (pure helper, not wired into recognize)
# ---------------------------------------------------------------------------

def anchor_filter_indices(
    embeddings: Sequence[np.ndarray],
    anchor: np.ndarray,
    percentile: float = 70.0,
    min_delta: float = 0.05,
) -> np.ndarray:
    """Indices of chunks with cos(chunk, anchor) in the top-tail.

    Keeps a chunk when its similarity is at least the looser of two cutoffs:
    the ``percentile`` quantile, or ``max(sims) - min_delta``. That matches
    the "p70 OR max-δ" rule from the design doc, keeping more chunks when
    the per-query spread is narrow.
    """
    if not embeddings:
        return np.zeros(0, dtype=np.int64)
    stack = np.stack([_l2(e) for e in embeddings], axis=0)
    a = _l2(anchor)
    sims = stack @ a
    pct_threshold = float(np.percentile(sims, percentile))
    delta_threshold = float(sims.max()) - float(min_delta)
    threshold = min(pct_threshold, delta_threshold)
    return np.where(sims >= threshold)[0]
