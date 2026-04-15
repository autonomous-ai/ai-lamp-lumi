"""Tests for the action-analysis WebSocket endpoint."""

import base64
import json
import os
import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

TEST_API_KEY = "test-secret-key"
os.environ["DL_API_KEY"] = TEST_API_KEY


def _make_frame_b64(width: int = 320, height: int = 240) -> str:
    """Create a base64-encoded JPEG of a random BGR image."""
    frame = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
    _, buf = cv2.imencode(".jpg", frame)
    return base64.b64encode(buf.tobytes()).decode()


@pytest.fixture(scope="session")
def recognizer():
    """Load the real X3DActionRecognizer once for the entire test session."""
    from core.actionanalysis.x3d import X3DActionRecognizer

    return X3DActionRecognizer(frame_interval=0.0)


@pytest.fixture()
def client(recognizer):
    """Create a TestClient with the real recognizer."""
    import server

    server.DL_API_KEY = TEST_API_KEY
    server.action_recognizer = recognizer
    # Reset frame buffer between tests
    recognizer._frame_buffer.clear()
    recognizer._last_ts = 0
    return TestClient(server.app)


AUTH_HEADERS = {"X-API-Key": TEST_API_KEY}


class TestApiKeyAuth:
    def test_health_without_key_returns_401(self, client):
        resp = client.get("/api/dl/health")
        assert resp.status_code == 401

    def test_health_with_wrong_key_returns_401(self, client):
        resp = client.get("/api/dl/health", headers={"X-API-Key": "wrong"})
        assert resp.status_code == 401

    def test_health_with_valid_key(self, client):
        resp = client.get("/api/dl/health", headers=AUTH_HEADERS)
        assert resp.status_code == 200


class TestHealthEndpoint:
    def test_health_ok(self, client):
        resp = client.get("/api/dl/health", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["action_recognizer"] is True

    def test_health_not_loaded(self, client):
        import server

        saved = server.action_recognizer
        server.action_recognizer = None
        resp = client.get("/api/dl/health", headers=AUTH_HEADERS)
        assert resp.json()["action_recognizer"] is False
        server.action_recognizer = saved


class TestActionAnalysisWebSocket:
    def test_frame_returns_detected_classes(self, client):
        frame_b64 = _make_frame_b64()
        with client.websocket_connect(
            "/api/dl/action-analysis/ws", headers=AUTH_HEADERS
        ) as ws:
            ws.send_text(json.dumps({"type": "frame", "frame_b64": frame_b64}))
            resp = ws.receive_json()
            assert "detected_classes" in resp
            assert isinstance(resp["detected_classes"], list)

    def test_multiple_frames(self, client):
        """Sending multiple frames should each produce a response."""
        with client.websocket_connect(
            "/api/dl/action-analysis/ws", headers=AUTH_HEADERS
        ) as ws:
            for _ in range(3):
                ws.send_text(json.dumps({"type": "frame", "frame_b64": _make_frame_b64()}))
                resp = ws.receive_json()
                assert "detected_classes" in resp

    def test_whitelist_update(self, client):
        with client.websocket_connect(
            "/api/dl/action-analysis/ws", headers=AUTH_HEADERS
        ) as ws:
            ws.send_text(json.dumps({"type": "whitelist", "whitelist": ["walking", "running"]}))
            resp = ws.receive_json()
            assert resp["status"] == "whitelist_updated"

    def test_whitelist_reset(self, client):
        with client.websocket_connect(
            "/api/dl/action-analysis/ws", headers=AUTH_HEADERS
        ) as ws:
            ws.send_text(json.dumps({"type": "whitelist", "whitelist": None}))
            resp = ws.receive_json()
            assert resp["status"] == "whitelist_updated"

    def test_whitelist_then_frame(self, client):
        """Set a whitelist, then send a frame — response classes should be from whitelist."""
        allowed = {"applauding", "clapping"}
        with client.websocket_connect(
            "/api/dl/action-analysis/ws", headers=AUTH_HEADERS
        ) as ws:
            ws.send_text(json.dumps({"type": "whitelist", "whitelist": list(allowed)}))
            resp = ws.receive_json()
            assert resp["status"] == "whitelist_updated"

            ws.send_text(json.dumps({"type": "frame", "frame_b64": _make_frame_b64()}))
            resp = ws.receive_json()
            assert "detected_classes" in resp
            for class_name, _ in resp["detected_classes"]:
                assert class_name in allowed

            # Reset whitelist for other tests
            ws.send_text(json.dumps({"type": "whitelist", "whitelist": None}))
            ws.receive_json()

    def test_invalid_json(self, client):
        with client.websocket_connect(
            "/api/dl/action-analysis/ws", headers=AUTH_HEADERS
        ) as ws:
            ws.send_text("not json at all")
            resp = ws.receive_json()
            assert "error" in resp

    def test_missing_type_field(self, client):
        with client.websocket_connect(
            "/api/dl/action-analysis/ws", headers=AUTH_HEADERS
        ) as ws:
            ws.send_text(json.dumps({"frame_b64": "abc"}))
            resp = ws.receive_json()
            assert "error" in resp

    def test_unknown_type(self, client):
        with client.websocket_connect(
            "/api/dl/action-analysis/ws", headers=AUTH_HEADERS
        ) as ws:
            ws.send_text(json.dumps({"type": "bogus"}))
            resp = ws.receive_json()
            assert "error" in resp

    def test_frame_missing_frame_b64(self, client):
        with client.websocket_connect(
            "/api/dl/action-analysis/ws", headers=AUTH_HEADERS
        ) as ws:
            ws.send_text(json.dumps({"type": "frame"}))
            resp = ws.receive_json()
            assert "error" in resp

    def test_recognizer_not_loaded_closes_ws(self, client):
        import server

        saved = server.action_recognizer
        server.action_recognizer = None
        with pytest.raises(Exception):
            with client.websocket_connect(
                "/api/dl/action-analysis/ws", headers=AUTH_HEADERS
            ) as ws:
                ws.send_text(json.dumps({"type": "frame", "frame_b64": "abc"}))
                ws.receive_json()
        server.action_recognizer = saved

    def test_ws_without_api_key_rejected(self, client):
        with pytest.raises(Exception):
            with client.websocket_connect("/api/dl/action-analysis/ws") as ws:
                ws.send_text(json.dumps({"type": "whitelist", "whitelist": None}))
                ws.receive_json()
