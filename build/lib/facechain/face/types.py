"""Face value object shared by the engine, the matcher and the ranker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class Face:
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 in source-image pixels
    kps: list[tuple[float, float]]  # 5 landmarks: left eye, right eye, nose, mouth L, mouth R
    det_score: float
    embedding: np.ndarray  # 512-d, L2-normalised (dot product == cosine)
    ipd_px: float  # inter-pupil distance in source-image pixels
    blur_var: float  # Laplacian variance of the grey face crop (higher = sharper)
    area: float  # bbox area in source-image pixels

    def to_dict(self) -> dict[str, Any]:
        return {
            "bbox": [round(v, 1) for v in self.bbox],
            "det_score": round(self.det_score, 4),
            "ipd_px": round(self.ipd_px, 1),
            "blur_var": round(self.blur_var, 1),
            "area": round(self.area, 1),
        }
