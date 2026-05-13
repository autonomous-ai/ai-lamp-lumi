"""HTTP integration tests for the Speech Emotion Recognition (SER) APIs.

Endpoints exercised (all mounted under ``/api/dl`` and gated by
``X-API-Key`` when the server is configured with one):

* ``GET  /api/dl/ser/labels``    -- active engine + ordered labels.
* ``POST /api/dl/ser/recognize`` -- multipart upload, base64 WAV, or
                                    http/https URL.

Requires:
    * ``DL_BACKEND_URL``  -- e.g. ``http://127.0.0.1:8000`` (set via .env).
    * ``DL_API_KEY``      -- optional; sent as ``X-API-Key`` if present.
    * Mock wavs under ``tests/mock_data/audio/ser/`` (only ``happy.wav``
      and ``sad.wav`` are used by this module).

The whole module is skipped if ``DL_BACKEND_URL`` is unset, and each
test is skipped at runtime if the labels endpoint isn't reachable (so
running this against a server that hasn't yet wired the SER router
produces a clear skip rather than a slew of 404s).
"""

from __future__ import annotations

import base64
import os
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
from dotenv import load_dotenv

_ = load_dotenv()

DL_BACKEND_URL = os.getenv("DL_BACKEND_URL", "").rstrip("/")
DL_API_KEY = os.getenv("DL_API_KEY", "")

DATA_DIR = Path(__file__).parent.parent / "mock_data" / "audio" / "ser"
HAPPY_WAV = DATA_DIR / "happy.wav"
SAD_WAV = DATA_DIR / "sad.wav"

pytestmark = pytest.mark.skipif(
    not DL_BACKEND_URL,
    reason="DL_BACKEND_URL not set - skipping SER API integration tests.",
)


# ---------------------------------------------------------------------------
# HTTP helpers (mirrors speaker_recognization_api/test_audio_recognizer_api.py)
# ---------------------------------------------------------------------------


def _headers() -> dict[str, str]:
    if DL_API_KEY:
        return {"X-API-Key": DL_API_KEY}
    return {}


def _url(path: str) -> str:
    return f"{DL_BACKEND_URL}{path}"


def _dump_response(label: str, resp: httpx.Response) -> None:
    print(
        f"[{label}] status={resp.status_code} "
        f"content-type={resp.headers.get('content-type', '')} "
        f"len={len(resp.text)}"
    )
    try:
        print(f"[{label}] body(json)={resp.json()}")
    except Exception:
        print(f"[{label}] body(text)={resp.text}")


def _timed_request(label: str, method: str, path: str, **kwargs) -> httpx.Response:
    start = time.perf_counter()
    resp = httpx.request(method, _url(path), **kwargs)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    print(f"[Timing] {label}: {elapsed_ms:.2f} ms")
    _dump_response(label, resp)
    return resp


def _ser_api_available() -> bool:
    """Preflight check: ``GET /ser/labels`` must answer (not 404)."""
    try:
        resp = _timed_request(
            "preflight /ser/labels",
            "GET",
            "/api/dl/ser/labels",
            headers=_headers(),
            timeout=10.0,
        )
    except Exception:
        return False
    return resp.status_code != 404


def _mock_files_ready() -> bool:
    return HAPPY_WAV.exists() and SAD_WAV.exists()


def _wav_file_to_b64(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def _require_mock_wav(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"Missing mock wav (add under tests/mock_data/audio/ser): {path}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def mock_http_server():
    """Serve ``tests/mock_data/audio/ser/`` over http://127.0.0.1:<port>/.

    Lets us exercise the ``wav_path`` (URL) input mode without needing a
    real CDN. The server lives only for the test session.
    """
    if not _mock_files_ready():
        pytest.skip("Missing ser mock wav files under tests/mock_data/audio/ser")

    handler = partial(SimpleHTTPRequestHandler, directory=str(DATA_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    try:
        yield base_url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.fixture(autouse=True)
def ensure_ser_api_ready():
    if not _ser_api_available():
        pytest.skip("SER API endpoints are not available at DL_BACKEND_URL.")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_get_labels():
    """``GET /api/dl/ser/labels`` returns the active engine + label list."""
    print(
        "==========================================test_get_labels=========================================="
    )
    resp = _timed_request(
        "list labels",
        "GET",
        "/api/dl/ser/labels",
        headers=_headers(),
        timeout=30.0,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "engine" in body
    assert "labels" in body
    assert isinstance(body["labels"], list)
    assert len(body["labels"]) > 0
    # Sanity: the engine must at least know what 'happy' and 'sad' look like
    # since this is the entire dataset we test against.
    assert "happy" in body["labels"]
    assert "sad" in body["labels"]


def test_recognize_with_wav_path_url_happy(mock_http_server):
    """JSON body with http URL: happy.wav → label = 'happy'."""
    print(
        "==========================================test_recognize_with_wav_path_url_happy=========================================="
    )
    _require_mock_wav(HAPPY_WAV)
    payload = {"wav_path": f"{mock_http_server}/happy.wav"}
    resp = _timed_request(
        "recognize wav_path URL happy",
        "POST",
        "/api/dl/ser/recognize",
        headers=_headers(),
        json=payload,
        timeout=120.0,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["label"] == "happy"
    assert 0.0 <= body["confidence"] <= 1.0
    assert body["confidence"] > 0.4
    assert "scores" in body and isinstance(body["scores"], dict)
    assert body["scores"]["happy"] == pytest.approx(body["confidence"], abs=1e-4)


def test_recognize_with_wav_path_url_sad(mock_http_server):
    """JSON body with http URL: sad.wav → label = 'sad'."""
    print(
        "==========================================test_recognize_with_wav_path_url_sad=========================================="
    )
    _require_mock_wav(SAD_WAV)
    payload = {"wav_path": f"{mock_http_server}/sad.wav"}
    resp = _timed_request(
        "recognize wav_path URL sad",
        "POST",
        "/api/dl/ser/recognize",
        headers=_headers(),
        json=payload,
        timeout=120.0,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["label"] == "sad"
    assert 0.0 <= body["confidence"] <= 1.0
    assert body["confidence"] > 0.4


def test_recognize_with_audio_b64_happy():
    """JSON body with base64-encoded WAV bytes."""
    print(
        "==========================================test_recognize_with_audio_b64_happy=========================================="
    )
    _require_mock_wav(HAPPY_WAV)
    payload = {
        "audio_b64": _wav_file_to_b64(HAPPY_WAV),
    }
    resp = _timed_request(
        "recognize audio_b64 happy",
        "POST",
        "/api/dl/ser/recognize",
        headers=_headers(),
        json=payload,
        timeout=120.0,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["label"] == "happy"
    assert 0.0 <= body["confidence"] <= 1.0


def test_recognize_with_audio_b64_sad():
    print(
        "==========================================test_recognize_with_audio_b64_sad=========================================="
    )
    _require_mock_wav(SAD_WAV)
    payload = {"audio_b64": _wav_file_to_b64(SAD_WAV)}
    resp = _timed_request(
        "recognize audio_b64 sad",
        "POST",
        "/api/dl/ser/recognize",
        headers=_headers(),
        json=payload,
        timeout=120.0,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["label"] == "sad"


def test_recognize_with_multipart_upload_happy():
    """multipart/form-data with a single ``wav`` file part."""
    print(
        "==========================================test_recognize_with_multipart_upload_happy=========================================="
    )
    _require_mock_wav(HAPPY_WAV)
    with open(HAPPY_WAV, "rb") as f:
        resp = _timed_request(
            "recognize multipart happy",
            "POST",
            "/api/dl/ser/recognize",
            headers=_headers(),
            files=[("wav", (HAPPY_WAV.name, f, "audio/wav"))],
            timeout=120.0,
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["label"] == "happy"
    assert 0.0 <= body["confidence"] <= 1.0
    assert "scores" in body and isinstance(body["scores"], dict)


def test_recognize_with_multipart_upload_sad():
    print(
        "==========================================test_recognize_with_multipart_upload_sad=========================================="
    )
    _require_mock_wav(SAD_WAV)
    with open(SAD_WAV, "rb") as f:
        resp = _timed_request(
            "recognize multipart sad",
            "POST",
            "/api/dl/ser/recognize",
            headers=_headers(),
            files=[("wav", (SAD_WAV.name, f, "audio/wav"))],
            timeout=120.0,
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["label"] == "sad"


def test_recognize_return_scores_false_drops_scores():
    """``return_scores=false`` collapses the response to label+confidence only."""
    print(
        "==========================================test_recognize_return_scores_false_drops_scores=========================================="
    )
    _require_mock_wav(HAPPY_WAV)
    payload = {
        "audio_b64": _wav_file_to_b64(HAPPY_WAV),
        "return_scores": False,
    }
    resp = _timed_request(
        "recognize return_scores=false",
        "POST",
        "/api/dl/ser/recognize",
        headers=_headers(),
        json=payload,
        timeout=120.0,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["label"] == "happy"
    assert body.get("scores") is None


def test_recognize_rejects_local_path():
    """``wav_path`` must be http/https; a local path is a validation error."""
    print(
        "==========================================test_recognize_rejects_local_path=========================================="
    )
    payload = {"wav_path": "/etc/passwd"}
    resp = _timed_request(
        "recognize local-path (expect 4xx)",
        "POST",
        "/api/dl/ser/recognize",
        headers=_headers(),
        json=payload,
        timeout=30.0,
    )
    # Pydantic validation surfaces as 400 (re-raised by the route handler)
    # or 422 depending on FastAPI's default behaviour; both are acceptable
    # "client error" responses for an invalid input.
    assert resp.status_code in (400, 422), resp.text


def test_recognize_empty_body_is_client_error():
    """An empty JSON body must not crash the server -- it's a 4xx."""
    print(
        "==========================================test_recognize_empty_body_is_client_error=========================================="
    )
    resp = _timed_request(
        "recognize empty body (expect 4xx)",
        "POST",
        "/api/dl/ser/recognize",
        headers=_headers(),
        json={},
        timeout=30.0,
    )
    assert resp.status_code in (400, 422), resp.text
