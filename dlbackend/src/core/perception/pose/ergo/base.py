"""Abstract base class for ergonomic assessment from pose keypoints."""

from abc import ABC, abstractmethod
from enum import IntEnum

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel


class RiskLevel(IntEnum):
    NEGLIGIBLE = 1   # Score 1-2: acceptable posture
    LOW = 2          # Score 3-4: further investigation, may need changes
    MEDIUM = 3       # Score 5-6: investigation and changes needed soon
    HIGH = 4         # Score 7+: investigation and changes needed immediately


class SideAssessment(BaseModel):
    """RULA assessment result for one side of the body."""

    score: int
    risk_level: RiskLevel
    body_scores: dict[str, int]
    skipped_joints: list[str]


class ErgoAssessment(BaseModel):
    """Result of an ergonomic assessment for both sides."""

    left: SideAssessment
    right: SideAssessment
    score: int
    risk_level: RiskLevel


class ErgoAssessor(ABC):
    """Base interface for ergonomic assessors that operate on pose keypoints."""

    @abstractmethod
    def assess(
        self,
        keypoints: npt.NDArray[np.float32],
        scores: npt.NDArray[np.float32],
    ) -> ErgoAssessment | None:
        """Run ergonomic assessment on a single frame of keypoints.

        Args:
            keypoints: (17, 2) or (17, 3) joint positions.
            scores:    (17,) confidence scores.

        Returns:
            ErgoAssessment with both-side results, or None if not enough
            confident keypoints to assess.
        """
