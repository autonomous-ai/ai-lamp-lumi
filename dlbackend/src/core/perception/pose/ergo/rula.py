"""RULA (Rapid Upper Limb Assessment) ergonomic scoring from H36M keypoints.

Computes joint angles from H36M keypoints and applies the standard RULA
scoring methodology to produce a risk score (1-7+).

All angles are computed in 3D. 2D input is padded to 3D (x=0) before
processing. The skeleton is rotated so that the spine-to-thorax vector
aligns with the vertical before computing angles. Joints with confidence
below a threshold are skipped and given neutral default scores.

Both sides are assessed independently; the overall score is the worse of
the two.

Reference: McAtamney & Corlett (1993), "RULA: a survey method for the
investigation of work-related upper limb disorders."

H36M joint indices:
    0: Pelvis, 1: Left Hip, 4: Right Hip,
    7: Spine, 8: Thorax, 9: Neck/Nose, 10: Head,
    11: Left Shoulder, 12: Left Elbow, 13: Left Wrist,
    14: Right Shoulder, 15: Right Elbow, 16: Right Wrist
"""
# TODO: This is written by Claude based on https://ergo-plus.com/wp-content/uploads/RULA-A-Step-by-Step-Guide1.pdf
# Refactor and logic checking needed.
# This serves mainly as the PoC now.

import logging

import numpy as np
import numpy.typing as npt

from .base import ErgoAssessment, ErgoAssessor, RiskLevel, SideAssessment

# ---------------------------------------------------------------------------
# H36M joint indices
# ---------------------------------------------------------------------------
_PELVIS: int = 0
_SPINE: int = 7
_THORAX: int = 8
_NECK: int = 9
_HEAD: int = 10
_L_SHOULDER: int = 11
_L_ELBOW: int = 12
_L_WRIST: int = 13
_R_SHOULDER: int = 14
_R_ELBOW: int = 15
_R_WRIST: int = 16

_JOINT_NAMES: dict[int, str] = {
    _PELVIS: "pelvis", _SPINE: "spine", _THORAX: "thorax",
    _NECK: "neck", _HEAD: "head",
    _L_SHOULDER: "left_shoulder", _L_ELBOW: "left_elbow", _L_WRIST: "left_wrist",
    _R_SHOULDER: "right_shoulder", _R_ELBOW: "right_elbow", _R_WRIST: "right_wrist",
}

# ---------------------------------------------------------------------------
# 3D geometry helpers
# ---------------------------------------------------------------------------


def _ensure_3d(keypoints: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    """Pad 2D (N,2) to 3D (N,3) by inserting x=0 as the first axis.

    Convention: (x, y, z) where x=lateral, y=depth, z=vertical.
    2D input (col, row) is mapped to (0, col, row).
    """
    if keypoints.shape[1] >= 3:
        return keypoints.copy()
    zeros: npt.NDArray[np.float32] = np.zeros((keypoints.shape[0], 1), dtype=np.float32)
    return np.concatenate([zeros, keypoints], axis=1).astype(np.float32)


def _angle_between_3d(
    v1: npt.NDArray[np.float32],
    v2: npt.NDArray[np.float32],
) -> float:
    """Unsigned angle in degrees between two 3D vectors."""
    denom: float = float(np.linalg.norm(v1) * np.linalg.norm(v2))
    if denom < 1e-8:
        return 0.0
    cos: float = float(np.clip(np.dot(v1, v2) / denom, -1.0, 1.0))
    return float(np.degrees(np.arccos(cos)))


def _signed_flexion_angle(
    v: npt.NDArray[np.float32],
    trunk_up: npt.NDArray[np.float32],
) -> float:
    """Signed flexion angle (degrees) of *v* relative to *trunk_up*.

    Positive = forward flexion, negative = extension.
    Computed fully in 3D using the cross product to determine sign.
    """
    angle: float = _angle_between_3d(v, trunk_up)
    # Use cross product with lateral axis (x) to determine flexion direction
    cross: npt.NDArray[np.float32] = np.cross(trunk_up, v)
    # If the x-component of cross is positive, it is flexion
    if cross[0] > 0:
        return angle
    else:
        return -angle


def _align_to_vertical(
    keypoints: npt.NDArray[np.float32],
) -> npt.NDArray[np.float32]:
    """Rotate 3D keypoints so that spine-to-thorax aligns with +Z (up).

    Uses Rodrigues' rotation formula: find a single rotation that maps
    the trunk vector to [0, 0, 1]. Input must be (N, 3). Returns a copy.
    """
    spine: npt.NDArray[np.float32] = keypoints[_SPINE]
    thorax: npt.NDArray[np.float32] = keypoints[_THORAX]
    trunk_vec: npt.NDArray[np.float32] = thorax - spine
    trunk_norm: float = float(np.linalg.norm(trunk_vec))
    if trunk_norm < 1e-8:
        return keypoints.copy()

    src: npt.NDArray[np.float32] = (trunk_vec / trunk_norm).astype(np.float32)
    dst: npt.NDArray[np.float32] = np.array([0.0, 0.0, 1.0], dtype=np.float32)

    cross: npt.NDArray[np.float32] = np.cross(src, dst).astype(np.float32)
    sin_a: float = float(np.linalg.norm(cross))
    cos_a: float = float(np.dot(src, dst))

    aligned: npt.NDArray[np.float32] = keypoints.copy()
    centered: npt.NDArray[np.float32] = aligned - spine

    if sin_a < 1e-8:
        # Already aligned (or opposite — opposite would need 180° flip but is degenerate)
        return aligned

    # Skew-symmetric matrix of cross product axis
    k: npt.NDArray[np.float32] = (cross / sin_a).astype(np.float32)
    K: npt.NDArray[np.float32] = np.array([
        [0, -k[2], k[1]],
        [k[2], 0, -k[0]],
        [-k[1], k[0], 0],
    ], dtype=np.float32)

    # Rodrigues' rotation matrix: R = I + sin(a)*K + (1 - cos(a))*K^2
    R: npt.NDArray[np.float32] = (
        np.eye(3, dtype=np.float32) + sin_a * K + (1 - cos_a) * (K @ K)
    )

    rotated: npt.NDArray[np.float32] = (centered @ R.T).astype(np.float32)
    return rotated + spine


# ---------------------------------------------------------------------------
# RULA scoring functions
# ---------------------------------------------------------------------------


def _score_upper_arm(angle: float) -> int:
    """+1: [-20,20], +2: <-20 or (20,45], +3: (45,90], +4: >90."""
    if -20 <= angle <= 20:
        return 1
    elif angle < -20 or 20 < angle <= 45:
        return 2
    elif 45 < angle <= 90:
        return 3
    else:
        return 4


def _score_lower_arm(angle: float) -> int:
    """+1: [60,100], +2: <60 or >100."""
    if 60 <= angle <= 100:
        return 1
    else:
        return 2


def _score_wrist(angle: float) -> int:
    """+1: neutral, +2: <=15, +3: >15."""
    abs_angle: float = abs(angle)
    if abs_angle <= 1:
        return 1
    elif abs_angle <= 15:
        return 2
    else:
        return 3


def _score_neck(angle: float) -> int:
    """+1: [0,10], +2: (10,20], +3: >20, +4: extension (<0)."""
    if angle < 0:
        return 4
    elif angle <= 10:
        return 1
    elif angle <= 20:
        return 2
    else:
        return 3


def _score_trunk(angle: float) -> int:
    """+1: ~0, +2: (0,20], +3: (20,60], +4: >60."""
    abs_angle: float = abs(angle)
    if abs_angle <= 1:
        return 1
    elif abs_angle <= 20:
        return 2
    elif abs_angle <= 60:
        return 3
    else:
        return 4


# ---------------------------------------------------------------------------
# RULA lookup tables (McAtamney & Corlett 1993)
# ---------------------------------------------------------------------------

# Table A: [upper_arm-1][lower_arm-1][wrist-1][wrist_twist-1]
TABLE_A: list[list[list[list[int]]]] = [
    [[[1,2],[2,2],[2,3],[3,3]],[[2,2],[2,2],[3,3],[3,3]],[[2,3],[3,3],[3,3],[4,4]]],
    [[[2,3],[3,3],[3,4],[4,4]],[[3,3],[3,3],[3,4],[4,4]],[[3,4],[4,4],[4,4],[5,5]]],
    [[[3,3],[4,4],[4,4],[5,5]],[[3,4],[4,4],[4,4],[5,5]],[[4,4],[4,4],[4,5],[5,5]]],
    [[[4,4],[4,4],[4,5],[5,5]],[[4,4],[4,4],[4,5],[5,5]],[[4,4],[4,5],[5,5],[6,6]]],
    [[[5,5],[5,5],[5,6],[6,7]],[[5,6],[6,6],[6,7],[7,7]],[[6,6],[6,7],[7,7],[7,8]]],
    [[[7,7],[7,7],[7,8],[8,9]],[[8,8],[8,8],[8,9],[9,9]],[[9,9],[9,9],[9,9],[9,9]]],
]

# Table B: [neck-1][trunk-1][legs-1]
TABLE_B: list[list[list[int]]] = [
    [[1,3],[2,3],[3,4],[5,5],[6,6],[7,7]],
    [[2,3],[2,3],[4,5],[5,5],[6,7],[7,7]],
    [[3,3],[3,4],[4,5],[5,6],[6,7],[7,7]],
    [[5,5],[5,6],[6,7],[7,7],[7,7],[8,8]],
    [[7,7],[7,7],[7,8],[8,8],[8,8],[8,8]],
    [[8,8],[8,8],[8,8],[8,9],[9,9],[9,9]],
]

# Table C: [score_a-1][score_b-1]
TABLE_C: list[list[int]] = [
    [1,2,3,3,4,5,5],
    [2,2,3,4,4,5,5],
    [3,3,3,4,4,5,6],
    [3,3,3,4,5,6,6],
    [4,4,4,5,6,7,7],
    [4,4,5,6,6,7,7],
    [5,5,6,6,7,7,7],
    [5,5,6,7,7,7,7],
]


def _lookup_table_a(upper_arm: int, lower_arm: int, wrist: int, wrist_twist: int) -> int:
    ua: int = min(max(upper_arm, 1), 6) - 1
    la: int = min(max(lower_arm, 1), 3) - 1
    w: int = min(max(wrist, 1), 4) - 1
    wt: int = min(max(wrist_twist, 1), 2) - 1
    return TABLE_A[ua][la][w][wt]


def _lookup_table_b(neck: int, trunk: int, legs: int) -> int:
    n: int = min(max(neck, 1), 6) - 1
    t: int = min(max(trunk, 1), 6) - 1
    lg: int = min(max(legs, 1), 2) - 1
    return TABLE_B[n][t][lg]


def _lookup_table_c(score_a: int, score_b: int) -> int:
    sa: int = min(max(score_a, 1), 8) - 1
    sb: int = min(max(score_b, 1), 7) - 1
    return TABLE_C[sa][sb]


def _risk_level_from_score(score: int) -> RiskLevel:
    if score <= 2:
        return RiskLevel.NEGLIGIBLE
    elif score <= 4:
        return RiskLevel.LOW
    elif score <= 6:
        return RiskLevel.MEDIUM
    else:
        return RiskLevel.HIGH


# ---------------------------------------------------------------------------
# Single-side assessment
# ---------------------------------------------------------------------------


def _assess_side(
    kps: npt.NDArray[np.float32],
    confs: npt.NDArray[np.float32],
    conf_threshold: float,
    side: str,
    muscle_use_score: int,
    force_load_score: int,
) -> SideAssessment:
    """Assess one side. All keypoints must be 3D and already aligned."""
    if side == "right":
        shoulder_idx, elbow_idx, wrist_idx = _R_SHOULDER, _R_ELBOW, _R_WRIST
    else:
        shoulder_idx, elbow_idx, wrist_idx = _L_SHOULDER, _L_ELBOW, _L_WRIST

    skipped_set: set[str] = set()

    def _ok(idx: int) -> bool:
        if confs[idx] < conf_threshold:
            skipped_set.add(_JOINT_NAMES.get(idx, str(idx)))
            return False
        return True

    # Trunk direction (spine -> thorax) = up after alignment
    trunk_up: npt.NDArray[np.float32] = kps[_THORAX] - kps[_SPINE]

    # Mark all low-confidence joints upfront
    shoulder_ok: bool = _ok(shoulder_idx)
    elbow_ok: bool = _ok(elbow_idx)
    wrist_ok: bool = _ok(wrist_idx)

    # --- Upper arm angle (3D angle between upper-arm vec and trunk) ---
    if shoulder_ok and elbow_ok:
        upper_arm_vec: npt.NDArray[np.float32] = kps[elbow_idx] - kps[shoulder_idx]
        upper_arm_angle: float = _signed_flexion_angle(upper_arm_vec, trunk_up)
        upper_arm_score: int = _score_upper_arm(upper_arm_angle)
    else:
        upper_arm_angle = 0.0
        upper_arm_score = 1

    # --- Lower arm angle (3D elbow flexion) ---
    if shoulder_ok and elbow_ok and wrist_ok:
        forearm_vec: npt.NDArray[np.float32] = kps[wrist_idx] - kps[elbow_idx]
        upper_arm_neg: npt.NDArray[np.float32] = kps[shoulder_idx] - kps[elbow_idx]
        lower_arm_angle: float = _angle_between_3d(forearm_vec, upper_arm_neg)
        lower_arm_score: int = _score_lower_arm(lower_arm_angle)
    else:
        lower_arm_angle = 80.0
        lower_arm_score = 1

    # Wrist — H36M has no hand keypoints, always neutral
    wrist_score: int = 1
    wrist_twist_score: int = 1

    # --- Neck angle (3D angle of head-neck vec relative to trunk) ---
    if _ok(_NECK) and _ok(_HEAD):
        neck_vec: npt.NDArray[np.float32] = kps[_HEAD] - kps[_NECK]
        neck_angle: float = _signed_flexion_angle(neck_vec, trunk_up)
        neck_score: int = _score_neck(neck_angle)
    else:
        neck_angle = 0.0
        neck_score = 1

    # --- Trunk angle (3D angle of trunk from true vertical [0,0,1]) ---
    # After alignment trunk_up should be near [0,0,1], but compute anyway
    # for non-perfect alignment or when used without alignment
    true_vertical: npt.NDArray[np.float32] = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    trunk_angle: float = _signed_flexion_angle(trunk_up, true_vertical)
    trunk_score: int = _score_trunk(trunk_angle)

    leg_score: int = 1

    # --- Lookup tables ---
    table_a_score: int = _lookup_table_a(upper_arm_score, lower_arm_score, wrist_score, wrist_twist_score)
    score_a: int = table_a_score + muscle_use_score + force_load_score

    table_b_score: int = _lookup_table_b(neck_score, trunk_score, leg_score)
    score_b: int = table_b_score + muscle_use_score + force_load_score

    final_score: int = _lookup_table_c(score_a, score_b)

    return SideAssessment(
        score=final_score,
        risk_level=_risk_level_from_score(final_score),
        body_scores={
            "upper_arm": upper_arm_score,
            "lower_arm": lower_arm_score,
            "wrist": wrist_score,
            "wrist_twist": wrist_twist_score,
            "neck": neck_score,
            "trunk": trunk_score,
            "legs": leg_score,
            "table_a": table_a_score,
            "table_b": table_b_score,
            "score_a": score_a,
            "score_b": score_b,
            "upper_arm_angle": int(upper_arm_angle),
            "lower_arm_angle": int(lower_arm_angle),
            "neck_angle": int(neck_angle),
            "trunk_angle": int(trunk_angle),
        },
        skipped_joints=sorted(skipped_set),
    )


# ---------------------------------------------------------------------------
# RULA assessor
# ---------------------------------------------------------------------------


class RULAAssessor(ErgoAssessor):
    """RULA ergonomic assessment from H36M keypoints.

    Assesses both sides independently. The skeleton is first converted to 3D
    (if 2D), then rotated so that the spine-to-thorax vector aligns with the
    vertical. Joints with confidence below the threshold are skipped.

    The overall score is the worse (higher) of the two sides.
    """

    DEFAULT_CONFIDENCE_THRESHOLD: float = 0.3
    DEFAULT_MUSCLE_USE_SCORE: int = 0
    DEFAULT_FORCE_LOAD_SCORE: int = 0

    def __init__(
        self,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        muscle_use_score: int = DEFAULT_MUSCLE_USE_SCORE,
        force_load_score: int = DEFAULT_FORCE_LOAD_SCORE,
    ):
        self._confidence_threshold: float = confidence_threshold
        self._muscle_use_score: int = muscle_use_score
        self._force_load_score: int = force_load_score
        self._logger: logging.Logger = logging.getLogger(self.__class__.__name__)

    def assess(
        self,
        keypoints: npt.NDArray[np.float32],
        scores: npt.NDArray[np.float32],
    ) -> ErgoAssessment | None:
        """Run RULA on both sides of the body.

        Args:
            keypoints: (17, 2) or (17, 3) H36M joint positions.
            scores:    (17,) confidence scores.

        Returns:
            ErgoAssessment with left/right results, or None if spine/thorax
            are not confident enough to define the trunk.
        """
        if scores[_SPINE] < self._confidence_threshold or scores[_THORAX] < self._confidence_threshold:
            return None

        # Convert to 3D if needed, then align trunk to vertical
        kps_3d: npt.NDArray[np.float32] = _ensure_3d(keypoints)
        aligned: npt.NDArray[np.float32] = _align_to_vertical(kps_3d)

        left: SideAssessment = _assess_side(
            aligned, scores, self._confidence_threshold, "left",
            self._muscle_use_score, self._force_load_score,
        )
        right: SideAssessment = _assess_side(
            aligned, scores, self._confidence_threshold, "right",
            self._muscle_use_score, self._force_load_score,
        )

        overall_score: int = max(left.score, right.score)

        return ErgoAssessment(
            left=left,
            right=right,
            score=overall_score,
            risk_level=_risk_level_from_score(overall_score),
        )
