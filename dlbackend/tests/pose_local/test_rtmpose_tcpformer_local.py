"""Tests for pose estimation with 2D RTMPose + 3D TCPFormer lifting."""

import base64
import json
import os
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from protocols.utils.state import get_pose_model, set_pose_model
from core.perception.pose.pose import PoseAnalysis
from core.perception.pose.utils import create_estimator_2d, create_lifter_3d

TEST_API_KEY = "test-secret-key"
os.environ["DL_API_KEY"] = TEST_API_KEY

RTMPOSE_MODEL_PATH = Path.cwd() / "local" / "rtmpose-m.onnx"
TCPFORMER_MODEL_PATH = Path.cwd() / "local" / "tcpformer_h36m_243.onnx"

pytestmark = pytest.mark.skipif(
    not RTMPOSE_MODEL_PATH.exists() or not TCPFORMER_MODEL_PATH.exists(),
    reason=f"Local models not found (rtmpose={RTMPOSE_MODEL_PATH.exists()}, tcpformer={TCPFORMER_MODEL_PATH.exists()})",
)


def _make_frame_b64(width: int = 320, height: int = 240) -> str:
    frame = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
    _, buf = cv2.imencode(".jpg", frame)
    return base64.b64encode(buf.tobytes()).decode()


@pytest.fixture(scope="session")
def model():
    """Load RTMPose 2D + TCPFormer 3D once for the entire test session."""
    from core.enums.pose import PoseEstimator2DEnum, PoseLifter3DEnum

    estimator_2d = create_estimator_2d(
        model_name=PoseEstimator2DEnum.RTMPOSE, model_path=RTMPOSE_MODEL_PATH
    )
    lifter_3d = create_lifter_3d(
        model_name=PoseLifter3DEnum.TCPFORMER,
        model_path=TCPFORMER_MODEL_PATH,
        frame_size=(320, 240),
    )
    pose_model = PoseAnalysis(estimator_2d=estimator_2d, lifter_3d=lifter_3d)
    pose_model.start()
    return pose_model


@pytest.fixture()
def client(model):
    import config
    import server

    config.settings.dl_api_key = TEST_API_KEY
    set_pose_model(model)
    return TestClient(server.app)


AUTH_HEADERS = {"X-API-Key": TEST_API_KEY}


class TestPoseWith3DLifting:
    def test_frame_returns_pose_2d_and_pose_3d(self, client):
        """With 3D lifter configured, response should include both pose_2d and pose_3d."""
        with client.websocket_connect("/api/dl/pose-estimation/ws", headers=AUTH_HEADERS) as ws:
            ws.send_text(json.dumps({"type": "frame", "task": "pose", "frame_b64": _make_frame_b64()}))
            resp = ws.receive_json()
            assert "pose_2d" in resp
            assert "pose_3d" in resp

    def test_pose_3d_has_xyz_joints(self, client):
        """Each 3D joint should have x, y, z coordinates."""
        with client.websocket_connect("/api/dl/pose-estimation/ws", headers=AUTH_HEADERS) as ws:
            ws.send_text(json.dumps({"type": "frame", "task": "pose", "frame_b64": _make_frame_b64()}))
            resp = ws.receive_json()
            assert "pose_3d" in resp
            for joint in resp["pose_3d"]["joints"]:
                assert len(joint) == 3
                assert all(isinstance(v, float) for v in joint)

    def test_pose_3d_graph_type_is_h36m(self, client):
        with client.websocket_connect("/api/dl/pose-estimation/ws", headers=AUTH_HEADERS) as ws:
            ws.send_text(json.dumps({"type": "frame", "task": "pose", "frame_b64": _make_frame_b64()}))
            resp = ws.receive_json()
            assert resp["pose_3d"]["graph_type"] == "h36m"

    def test_pose_2d_graph_type_is_coco(self, client):
        with client.websocket_connect("/api/dl/pose-estimation/ws", headers=AUTH_HEADERS) as ws:
            ws.send_text(json.dumps({"type": "frame", "task": "pose", "frame_b64": _make_frame_b64()}))
            resp = ws.receive_json()
            assert resp["pose_2d"]["graph_type"] == "coco"

    def test_http_returns_both_poses(self, client):
        resp = client.post(
            "/api/dl/pose-estimate",
            json={"image_b64": _make_frame_b64()},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "pose_2d" in body
        assert "pose_3d" in body
        assert body["pose_2d"]["graph_type"] == "coco"
        assert body["pose_3d"]["graph_type"] == "h36m"

    def test_pose_3d_has_17_joints(self, client):
        """H36M format should have 17 joints."""
        with client.websocket_connect("/api/dl/pose-estimation/ws", headers=AUTH_HEADERS) as ws:
            ws.send_text(json.dumps({"type": "frame", "task": "pose", "frame_b64": _make_frame_b64()}))
            resp = ws.receive_json()
            assert len(resp["pose_3d"]["joints"]) == 17
            assert len(resp["pose_3d"]["confs"]) == 17

    def test_multiple_frames_with_3d(self, client):
        with client.websocket_connect("/api/dl/pose-estimation/ws", headers=AUTH_HEADERS) as ws:
            for _ in range(3):
                ws.send_text(json.dumps({"type": "frame", "task": "pose", "frame_b64": _make_frame_b64()}))
                resp = ws.receive_json()
                assert "pose_2d" in resp
                assert "pose_3d" in resp
