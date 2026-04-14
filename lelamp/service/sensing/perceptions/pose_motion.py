import io
import logging
import time
import zipfile
from pathlib import Path
from typing import Callable, Optional, override

import lelamp.config as config
import numpy as np
import numpy.typing as npt
import onnxruntime as ort
import requests

from .base import Perception
from .motion import MoveEnum

logger = logging.getLogger(__name__)

_MODEL_ZIP_URL = (
    "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/"
    "rtmpose-m_simcc-body7_pt-body7_420e-256x192-e48f03d0_20230504.zip"
)
# Path inside the zip to the ONNX file
_MODEL_ZIP_INNER = (
    "20230831/rtmpose_onnx/"
    "rtmpose-m_simcc-body7_pt-body7_420e-256x192-e48f03d0_20230504/"
    "end2end.onnx"
)


def _ensure_model(dest: Path) -> None:
    """Download and extract the RTMPose model if not already present."""
    if dest.exists():
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("[pose_motion] downloading RTMPose model from %s", _MODEL_ZIP_URL)

    response = requests.get(_MODEL_ZIP_URL, stream=True, timeout=120)
    response.raise_for_status()

    data = io.BytesIO()
    for chunk in response.iter_content(chunk_size=1024 * 1024):
        data.write(chunk)
    data.seek(0)

    with zipfile.ZipFile(data) as zf:
        with zf.open(_MODEL_ZIP_INNER) as src, dest.open("wb") as dst:
            dst.write(src.read())

    logger.info("[pose_motion] model saved to %s", dest)


class PoseEstimator:
    """RTMPose-based skeleton keypoint estimator (SimCC head, ONNX)."""

    INPUT_W: int = 192
    INPUT_H: int = 256

    INPUT_MEAN: npt.NDArray[np.float32] = np.array([123.675, 116.28, 103.53])
    INPUT_STD: npt.NDArray[np.float32] = np.array([58.395, 57.12, 57.375])

    def __init__(self, cv2, model_path: Path | None = None):
        self._cv2 = cv2
        if model_path is None:
            model_path = config.POSE_MOTION_MODEL_PATH
        _ensure_model(model_path)
        self._session: ort.InferenceSession = self._prepare_session(model_path)

    def update(
        self, frame: npt.NDArray[np.uint8]
    ) -> tuple[npt.NDArray[np.float32], npt.NDArray[np.float32]]:
        """Return (keypoints, scores) where keypoints shape is [1, K, 2]."""
        H, W = frame.shape[:2]
        p_frame = self._preprocess(frame)
        simcc_x, simcc_y = self._session.run(["simcc_x", "simcc_y"], {"input": p_frame})
        simcc_x = np.array(simcc_x)
        simcc_y = np.array(simcc_y)

        loc_x = simcc_x.argmax(-1) * W / self.INPUT_W
        loc_y = simcc_y.argmax(-1) * H / self.INPUT_H
        keypoints = np.stack([loc_x, loc_y], axis=-1) * 0.5
        scores = np.minimum(simcc_x.max(-1), simcc_y.max(-1))

        return keypoints, scores

    def _preprocess(self, frame: npt.NDArray[np.uint8]) -> npt.NDArray[np.float32]:
        cv2 = self._cv2
        frame = frame.copy()
        frame = cv2.resize(frame, (self.INPUT_W, self.INPUT_H))
        frame = ((frame - self.INPUT_MEAN) / self.INPUT_STD).astype(np.float32)
        return np.expand_dims(frame.transpose(2, 0, 1), axis=0)

    def _prepare_session(self, model_path: Path) -> ort.InferenceSession:
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.add_session_config_entry("session.dynamic_block_base", "4")
        return ort.InferenceSession(
            str(model_path), sess_options=opts, providers=["CPUExecutionProvider"]
        )


class PoseMotionChecker:
    """Detects body movement by tracking joint angle changes in the arm chain."""

    # Keypoint indices along the arm chain: left/right wrist → elbow → shoulder → shoulder → elbow → wrist
    HAND_CHAINS: list[int] = [9, 7, 5, 6, 8, 10]

    def __init__(self, conf_threshold: float = 0.4, threshold: float = 30):
        self._last_angles: npt.NDArray[np.float32] | None = None
        self._last_mask: npt.NDArray[np.bool_] | None = None
        self._conf_threshold: float = conf_threshold
        self._threshold: float = threshold

    def update(
        self,
        keypoints_list: npt.NDArray[np.float32],
        scores_list: npt.NDArray[np.float32],
    ):
        max_score = -1
        move_type = MoveEnum.NONE
        for keypoints, scores in zip(keypoints_list, scores_list):
            if scores.max() <= max_score:
                continue

            angles = np.zeros(4, dtype=np.float32)
            mask = np.zeros(4, dtype=np.bool_)
            for i in range(1, len(self.HAND_CHAINS) - 1):
                last_score = scores[self.HAND_CHAINS[i - 1]]
                cur_score = scores[self.HAND_CHAINS[i]]
                next_score = scores[self.HAND_CHAINS[i + 1]]
                if min(last_score, cur_score, next_score) < self._conf_threshold:
                    continue
                last = keypoints[self.HAND_CHAINS[i - 1]]
                cur = keypoints[self.HAND_CHAINS[i]]
                next = keypoints[self.HAND_CHAINS[i + 1]]

                v1 = last - cur
                v2 = next - cur

                cos = np.dot(v1 / np.linalg.norm(v1), v2 / np.linalg.norm(v2))
                angles[i - 1] = np.rad2deg(np.arccos(cos))
                mask[i - 1] = True

            if self._last_angles is not None and self._last_mask is not None:
                joint_mask = mask * self._last_mask
                if joint_mask.sum() > 0:
                    max_movement = np.abs(self._last_angles - angles)[joint_mask].max()
                    if max_movement > self._threshold:
                        move_type = MoveEnum.FOREGROUND

            self._last_angles = angles
            self._last_mask = mask
            max_score = scores.max()

        return move_type


class PoseMotionPerception(Perception):
    """Detects body movement via skeleton keypoint angle changes (RTMPose ONNX)."""

    def __init__(
        self,
        cv2,
        send_event: Callable,
        on_motion: Callable,
        capture_stable_frame: Callable,
        presence_service,
        model_path: Path | None = None,
        motion_update_ts: float = config.MOTION_EVENT_COOLDOWN_S,
    ):
        super().__init__(send_event)
        self._on_motion = on_motion
        self._capture_stable_frame = capture_stable_frame
        self._presence = presence_service
        self._motion_update_ts = motion_update_ts
        self._last_motion_time: Optional[float] = None
        self._last_motion_event_ts: float = 0.0
        self._estimator = PoseEstimator(cv2, model_path)
        self._checker = PoseMotionChecker()

    @override
    def _check_impl(self, frame: npt.NDArray[np.uint8]) -> None:
        if frame is None:
            return

        try:
            keypoints, scores = self._estimator.update(frame)
        except Exception:
            logger.exception("[pose_motion] estimator error")
            return

        result = self._checker.update(keypoints, scores)

        if result != MoveEnum.FOREGROUND:
            return

        cur_ts = time.time()
        self._last_motion_time = cur_ts
        self._on_motion()

        if (cur_ts - self._last_motion_event_ts) < self._motion_update_ts:
            return
        self._last_motion_event_ts = cur_ts

        stable = self._capture_stable_frame()
        image = stable if stable is not None else frame

        from ..presence_service import PresenceState

        if self._presence.state == PresenceState.PRESENT:
            logger.info("[pose_motion] activity analysis while PRESENT")
            self._send_event(
                "motion.activity",
                "Body movement detected via pose estimation while user is present. "
                "Look at the attached image — describe what the user appears to be doing "
                "(e.g. stretching, reaching, fidgeting, getting up). "
                "If nothing noteworthy, reply NO_REPLY.",
                image=image,
            )
        else:
            self._send_event(
                "motion",
                "Body movement detected via pose estimation — someone may have entered or left the room",
                image=image,
            )

    def to_dict(self) -> dict:
        seconds_since = (
            int(time.time() - self._last_motion_time)
            if self._last_motion_time is not None
            else None
        )
        return {
            "type": "pose_motion",
            "has_baseline": self._checker._last_angles is not None,
            "motion_detected": self._last_motion_time is not None,
            "seconds_since_motion": seconds_since,
        }
