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
"""
# TODO: This is written by Claude based on https://ergo-plus.com/wp-content/uploads/RULA-A-Step-by-Step-Guide1.pdf
# Refactor and logic checking needed.
# This serves mainly as the PoC now.

import numpy as np
import numpy.typing as npt
from typing_extensions import override

from core.enums.pose import GraphEnum
from core.models.pose import ErgoAssessment, RiskLevel, SideAssessment
from core.perception.pose.graph.h36m import H36MJoint
from core.utils.common import get_or_default
from core.utils.compute import angle_between_3d, ensure_3d, rotate_to

from .base import ErgoAssessor, ErgoInput

# ---------------------------------------------------------------------------
# Joint name lookup (for skipped-joints reporting)
# ---------------------------------------------------------------------------
_JOINT_NAMES: dict[int, str] = {j.value: j.name.lower() for j in H36MJoint}


# ---------------------------------------------------------------------------
# 3D geometry helpers (RULA-specific)
# ---------------------------------------------------------------------------


def _signed_flexion_angle(
    v: npt.NDArray[np.float32],
    trunk_up: npt.NDArray[np.float32],
) -> float:
    """Signed flexion angle (degrees) of *v* relative to *trunk_up*.

    Positive = forward flexion, negative = extension.
    Computed fully in 3D using the cross product to determine sign.
    """
    angle: float = angle_between_3d(v, trunk_up)
    cross: npt.NDArray[np.float32] = np.cross(trunk_up, v)
    if cross[0] > 0:
        return angle
    else:
        return -angle


def _align_to_vertical(
    keypoints: npt.NDArray[np.float32],
) -> npt.NDArray[np.float32]:
    """Rotate 3D keypoints so that spine-to-thorax aligns with +Z (up)."""
    spine: npt.NDArray[np.float32] = keypoints[H36MJoint.SPINE]
    thorax: npt.NDArray[np.float32] = keypoints[H36MJoint.THORAX]
    trunk_vec: npt.NDArray[np.float32] = thorax - spine

    return rotate_to(
        keypoints,
        src_vec=trunk_vec,
        dst_vec=np.array([0.0, 0.0, 1.0], dtype=np.float32),
        center=spine,
    )


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
    [
        [[1, 2], [2, 2], [2, 3], [3, 3]],
        [[2, 2], [2, 2], [3, 3], [3, 3]],
        [[2, 3], [3, 3], [3, 3], [4, 4]],
    ],
    [
        [[2, 3], [3, 3], [3, 4], [4, 4]],
        [[3, 3], [3, 3], [3, 4], [4, 4]],
        [[3, 4], [4, 4], [4, 4], [5, 5]],
    ],
    [
        [[3, 3], [4, 4], [4, 4], [5, 5]],
        [[3, 4], [4, 4], [4, 4], [5, 5]],
        [[4, 4], [4, 4], [4, 5], [5, 5]],
    ],
    [
        [[4, 4], [4, 4], [4, 5], [5, 5]],
        [[4, 4], [4, 4], [4, 5], [5, 5]],
        [[4, 4], [4, 5], [5, 5], [6, 6]],
    ],
    [
        [[5, 5], [5, 5], [5, 6], [6, 7]],
        [[5, 6], [6, 6], [6, 7], [7, 7]],
        [[6, 6], [6, 7], [7, 7], [7, 8]],
    ],
    [
        [[7, 7], [7, 7], [7, 8], [8, 9]],
        [[8, 8], [8, 8], [8, 9], [9, 9]],
        [[9, 9], [9, 9], [9, 9], [9, 9]],
    ],
]

# Table B: [neck-1][trunk-1][legs-1]
TABLE_B: list[list[list[int]]] = [
    [[1, 3], [2, 3], [3, 4], [5, 5], [6, 6], [7, 7]],
    [[2, 3], [2, 3], [4, 5], [5, 5], [6, 7], [7, 7]],
    [[3, 3], [3, 4], [4, 5], [5, 6], [6, 7], [7, 7]],
    [[5, 5], [5, 6], [6, 7], [7, 7], [7, 7], [8, 8]],
    [[7, 7], [7, 7], [7, 8], [8, 8], [8, 8], [8, 8]],
    [[8, 8], [8, 8], [8, 8], [8, 9], [9, 9], [9, 9]],
]

# Table C: [score_a-1][score_b-1]
TABLE_C: list[list[int]] = [
    [1, 2, 3, 3, 4, 5, 5],
    [2, 2, 3, 4, 4, 5, 5],
    [3, 3, 3, 4, 4, 5, 6],
    [3, 3, 3, 4, 5, 6, 6],
    [4, 4, 4, 5, 6, 7, 7],
    [4, 4, 5, 6, 6, 7, 7],
    [5, 5, 6, 6, 7, 7, 7],
    [5, 5, 6, 7, 7, 7, 7],
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
        shoulder_idx = H36MJoint.R_SHOULDER
        elbow_idx = H36MJoint.R_ELBOW
        wrist_idx = H36MJoint.R_WRIST
    else:
        shoulder_idx = H36MJoint.L_SHOULDER
        elbow_idx = H36MJoint.L_ELBOW
        wrist_idx = H36MJoint.L_WRIST

    skipped_set: set[str] = set()

    def _ok(idx: int) -> bool:
        if confs[idx] < conf_threshold:
            skipped_set.add(_JOINT_NAMES.get(idx, str(idx)))
            return False
        return True

    # Trunk direction (spine -> thorax) = up after alignment
    trunk_up: npt.NDArray[np.float32] = kps[H36MJoint.THORAX] - kps[H36MJoint.SPINE]

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
        lower_arm_angle: float = angle_between_3d(forearm_vec, upper_arm_neg)
        lower_arm_score: int = _score_lower_arm(lower_arm_angle)
    else:
        lower_arm_angle = 80.0
        lower_arm_score = 1

    # Wrist — H36M has no hand keypoints, always neutral
    wrist_score: int = 1
    wrist_twist_score: int = 1

    # --- Neck angle (3D angle of head-neck vec relative to trunk) ---
    if _ok(H36MJoint.NECK) and _ok(H36MJoint.HEAD):
        neck_vec: npt.NDArray[np.float32] = kps[H36MJoint.HEAD] - kps[H36MJoint.NECK]
        neck_angle: float = _signed_flexion_angle(neck_vec, trunk_up)
        neck_score: int = _score_neck(neck_angle)
    else:
        neck_angle = 0.0
        neck_score = 1

    # --- Trunk angle (3D angle of trunk from true vertical [0,0,1]) ---
    true_vertical: npt.NDArray[np.float32] = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    trunk_angle: float = _signed_flexion_angle(trunk_up, true_vertical)
    trunk_score: int = _score_trunk(trunk_angle)

    leg_score: int = 1

    # --- Lookup tables ---
    table_a_score: int = _lookup_table_a(
        upper_arm_score, lower_arm_score, wrist_score, wrist_twist_score
    )
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

    GRAPH_TYPE: GraphEnum = GraphEnum.H36M

    DEFAULT_CONFIDENCE_THRESHOLD: float = 0.3
    DEFAULT_MUSCLE_USE_SCORE: int = 0
    DEFAULT_FORCE_LOAD_SCORE: int = 0

    def __init__(
        self,
        confidence_threshold: float | None = None,
        muscle_use_score: int | None = None,
        force_load_score: int | None = None,
    ) -> None:
        super().__init__()
        self._confidence_threshold: float = get_or_default(
            confidence_threshold, self.DEFAULT_CONFIDENCE_THRESHOLD
        )
        self._muscle_use_score: int = get_or_default(
            muscle_use_score, self.DEFAULT_MUSCLE_USE_SCORE
        )
        self._force_load_score: int = get_or_default(
            force_load_score, self.DEFAULT_FORCE_LOAD_SCORE
        )

    def _assess_single(
        self,
        keypoints: npt.NDArray[np.float32],
        scores: npt.NDArray[np.float32],
    ) -> ErgoAssessment | None:
        """Run RULA on both sides of the body for a single frame.

        Args:
            keypoints: (17, 2) or (17, 3) H36M joint positions.
            scores:    (17,) confidence scores.

        Returns:
            ErgoAssessment with left/right results, or None if spine/thorax
            are not confident enough to define the trunk.
        """
        if (
            scores[H36MJoint.SPINE] < self._confidence_threshold
            or scores[H36MJoint.THORAX] < self._confidence_threshold
        ):
            return None

        kps_3d: npt.NDArray[np.float32] = ensure_3d(keypoints)
        aligned: npt.NDArray[np.float32] = _align_to_vertical(kps_3d)

        left: SideAssessment = _assess_side(
            aligned,
            scores,
            self._confidence_threshold,
            "left",
            self._muscle_use_score,
            self._force_load_score,
        )
        right: SideAssessment = _assess_side(
            aligned,
            scores,
            self._confidence_threshold,
            "right",
            self._muscle_use_score,
            self._force_load_score,
        )

        overall_score: int = max(left.score, right.score)

        return ErgoAssessment(
            left=left,
            right=right,
            score=overall_score,
            risk_level=_risk_level_from_score(overall_score),
        )

    @override
    def predict(
        self,
        input: list[ErgoInput],
        *,
        preprocess: bool = True,
    ) -> list[ErgoAssessment | None]:
        """Run RULA assessment on a batch of (keypoints, scores) pairs."""
        return [self._assess_single(kps, scores) for kps, scores in input]
