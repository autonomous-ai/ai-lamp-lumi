"""In-process integration tests for the Speech Emotion Recognition (SER) core.

Calls :class:`core.ser.SpeechEmotionRecognizer` directly (no HTTP layer)
so we exercise the ONNX session, audio loader, resampler, and label
mapping without spinning up the FastAPI server.

Skip rules:
    * Required runtime libs (``onnxruntime``, ``soundfile``, ``scipy``,
      ``numpy``) must import.
    * Mock wavs under ``tests/mock_data/audio/ser/`` must exist.
    * Loading the engine itself may fail (e.g. the model file is not yet
      cached and FunASR is not installed); we surface that as a skip so
      the suite stays usable on lean CI runners.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from dotenv import load_dotenv

from core.ser.speech_emotion_recognizer import (
    DEFAULT_SER_ENGINE,
    SER_ENGINES,
    SpeechEmotionRecognizer,
    create_speech_emotion_recognizer,
)

_ = load_dotenv()

DATA_DIR = Path(__file__).parent.parent / "mock_data" / "audio" / "ser"
HAPPY_WAV = DATA_DIR / "happy.wav"
SAD_WAV = DATA_DIR / "sad.wav"


# Engine override for this test session. Falls back to the same env vars
# the server uses (``SER_ENGINE``) then to the package default.
TEST_SER_ENGINE = (
    os.getenv("TEST_SER_ENGINE")
    or os.getenv("SER_ENGINE")
    or DEFAULT_SER_ENGINE
).strip().lower()

print(
    f"[test_ser_local] using engine='{TEST_SER_ENGINE}' "
    f"(available: {sorted(SER_ENGINES)})",
    flush=True,
)


# ---------------------------------------------------------------------------
# Skip helpers
# ---------------------------------------------------------------------------


def _deps_ready() -> bool:
    try:
        import onnxruntime  # noqa: F401
        import scipy  # noqa: F401
        import soundfile  # noqa: F401
    except Exception:
        return False
    return True


def _files_ready() -> bool:
    return HAPPY_WAV.exists() and SAD_WAV.exists()


_REQUIREMENTS_MET = _deps_ready() and _files_ready()
_SKIP_REASON = "Missing runtime dependencies or required ser mock wav files."


# ---------------------------------------------------------------------------
# Shared fixtures + helpers
# ---------------------------------------------------------------------------


def _timed_call(label: str, fn, *args, **kwargs):
    start = time.perf_counter()
    out = fn(*args, **kwargs)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    print(f"[Timing] {label}: {elapsed_ms:.2f} ms")
    return out


def _load_waveform(path: Path) -> tuple[np.ndarray, int]:
    waveform, sr = sf.read(str(path), dtype="float32")
    arr = np.asarray(waveform, dtype=np.float32)
    if arr.ndim == 2:
        arr = arr.mean(axis=1)
    return arr, int(sr)


@pytest.fixture(scope="session")
def recognizer() -> SpeechEmotionRecognizer:
    """One engine instance shared across all tests in this module.

    Building the session is expensive (loads the ONNX file and warms the
    runtime) so we cache it. If construction fails we skip the whole
    session instead of erroring out, so contributors without the model
    cached locally can still run unrelated test suites.
    """
    try:
        eng = _timed_call(
            f"create_speech_emotion_recognizer({TEST_SER_ENGINE!r})",
            create_speech_emotion_recognizer,
            TEST_SER_ENGINE,
        )
    except Exception as exc:
        pytest.skip(f"Cannot create SER engine '{TEST_SER_ENGINE}': {exc}")
    return eng


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(not _REQUIREMENTS_MET, reason=_SKIP_REASON)
def test_labels_loaded(recognizer: SpeechEmotionRecognizer):
    """The engine must expose a non-empty ordered list of labels."""
    print(
        "==========================================test_labels_loaded=========================================="
    )
    print("[Action] recognizer.labels ->", recognizer.labels)
    assert isinstance(recognizer.labels, list)
    assert len(recognizer.labels) > 0
    assert recognizer.num_classes == len(recognizer.labels)
    # Sanity check: the well-known emotion classes should be in there.
    assert "happy" in recognizer.labels
    assert "sad" in recognizer.labels


@pytest.mark.integration
@pytest.mark.skipif(not _REQUIREMENTS_MET, reason=_SKIP_REASON)
def test_predict_happy_from_path(recognizer: SpeechEmotionRecognizer):
    """End-to-end happy path: file path → ``label == 'happy'``."""
    print(
        "==========================================test_predict_happy_from_path=========================================="
    )
    result = _timed_call("predict(happy.wav)", recognizer.predict, HAPPY_WAV)
    print("[Action] predict(happy.wav) ->", result)

    assert set(result.keys()) == {"label", "confidence", "scores"}
    assert result["label"] == "happy"
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["confidence"] > 0.4  # easy bar; model is very confident on this clip
    assert isinstance(result["scores"], dict)
    assert set(result["scores"].keys()) == set(recognizer.labels)
    # Top label in scores must agree with reported argmax.
    top_in_scores = max(result["scores"].items(), key=lambda kv: kv[1])[0]
    assert top_in_scores == result["label"]


@pytest.mark.integration
@pytest.mark.skipif(not _REQUIREMENTS_MET, reason=_SKIP_REASON)
def test_predict_sad_from_path(recognizer: SpeechEmotionRecognizer):
    """End-to-end sad path: file path → ``label == 'sad'``."""
    print(
        "==========================================test_predict_sad_from_path=========================================="
    )
    result = _timed_call("predict(sad.wav)", recognizer.predict, SAD_WAV)
    print("[Action] predict(sad.wav) ->", result)

    assert result["label"] == "sad"
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["confidence"] > 0.4


@pytest.mark.integration
@pytest.mark.skipif(not _REQUIREMENTS_MET, reason=_SKIP_REASON)
def test_predict_from_ndarray_at_engine_sr(recognizer: SpeechEmotionRecognizer):
    """Caller passes a pre-loaded numpy waveform that matches ``sample_rate``."""
    print(
        "==========================================test_predict_from_ndarray_at_engine_sr=========================================="
    )
    waveform, sr = _load_waveform(HAPPY_WAV)
    print(f"[Arrange] loaded waveform: shape={waveform.shape}, sr={sr}")

    result = _timed_call(
        "predict(ndarray, sample_rate=sr)",
        recognizer.predict,
        waveform,
        sample_rate=sr,
    )
    print("[Action] predict(ndarray happy) ->", result)
    assert result["label"] == "happy"


@pytest.mark.integration
@pytest.mark.skipif(not _REQUIREMENTS_MET, reason=_SKIP_REASON)
def test_predict_resamples_when_sr_mismatches(recognizer: SpeechEmotionRecognizer):
    """If the caller's waveform sample rate differs, the engine must resample.

    We crudely downsample the original to 8 kHz on the client side then
    feed it back with ``sample_rate=8000``. The engine should resample
    internally to ``self.sample_rate`` and still classify it correctly.
    """
    print(
        "==========================================test_predict_resamples_when_sr_mismatches=========================================="
    )
    waveform, sr = _load_waveform(HAPPY_WAV)
    assert sr in (16000, 8000), f"Unexpected source sample rate: {sr}"
    if sr != 16000:
        pytest.skip("happy.wav is not at 16 kHz; resample-from-8k case not meaningful.")

    # Decimate-by-2: cheap downsample to 8 kHz, deliberately *not* using
    # scipy so we don't accidentally test the same code path as the engine.
    half = waveform[::2].copy()
    print(f"[Arrange] decimated waveform: shape={half.shape}, sr=8000")

    result = _timed_call(
        "predict(ndarray, sample_rate=8000)",
        recognizer.predict,
        half,
        sample_rate=8000,
    )
    print("[Action] predict(8k happy) ->", result)
    # Aggressive decimation hurts accuracy, so we only assert the
    # response shape and reasonable confidence range -- not the label.
    assert set(result.keys()) == {"label", "confidence", "scores"}
    assert 0.0 <= result["confidence"] <= 1.0


@pytest.mark.integration
@pytest.mark.skipif(not _REQUIREMENTS_MET, reason=_SKIP_REASON)
def test_predict_from_waveform_direct(recognizer: SpeechEmotionRecognizer):
    """Bypass :meth:`predict` and call :meth:`predict_from_waveform` directly.

    This exercises the abstract API contract: subclasses must return a
    raw 1-D probability vector of length ``num_classes``.
    """
    print(
        "==========================================test_predict_from_waveform_direct=========================================="
    )
    waveform, sr = _load_waveform(SAD_WAV)
    # The engine's predict_from_waveform assumes input is already at engine SR;
    # since the file is already 16 kHz that's fine. Otherwise we'd resample
    # via the public predict() API.
    if sr != recognizer.sample_rate:
        pytest.skip(
            f"sad.wav is at {sr} Hz but engine expects {recognizer.sample_rate} Hz."
        )

    probs = _timed_call(
        "predict_from_waveform(sad)",
        recognizer.predict_from_waveform,
        waveform,
    )
    print(
        f"[Action] predict_from_waveform(sad.wav) shape={np.asarray(probs).shape} "
        f"top_idx={int(np.argmax(probs))}"
    )
    probs_arr = np.asarray(probs, dtype=np.float32)
    assert probs_arr.ndim == 1
    assert probs_arr.shape[0] == recognizer.num_classes
    # Soft check that the vector is a valid probability distribution.
    assert np.all(probs_arr >= 0.0)
    assert np.isclose(probs_arr.sum(), 1.0, atol=1e-2)
    # And the argmax matches the high-level predict() answer.
    assert recognizer.labels[int(np.argmax(probs_arr))] == "sad"
