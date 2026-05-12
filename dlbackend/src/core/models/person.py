from pydantic import BaseModel


class PersonDetection(BaseModel):
    """Single person detection bounding box."""

    bbox_xyxy: tuple[int, int, int, int]
    confidence: float
    area: int
