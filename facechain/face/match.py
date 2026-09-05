"""Pure matching helpers: cosine similarity, decision bands, quality gate, query-face choice."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from .types import Face

MIN_DET_SCORE = 0.60
MIN_IPD_PX = 25.0
MIN_BLUR_VAR = 60.0
# candidate media are often 100-300 px thumbnails; calibration showed same-person similarity
# stays far above impostors there, so the gate for candidates only rejects hopeless faces
LENIENT_DET_SCORE = 0.50
LENIENT_IPD_PX = 12.0
LENIENT_BLUR_VAR = 15.0

Band = str  # "match" | "review" | "reject"


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity in [-1, 1]; safe for un-normalised or zero vectors."""
    va = np.asarray(a, dtype=np.float32).ravel()
    vb = np.asarray(b, dtype=np.float32).ravel()
    na = float(np.linalg.norm(va))
    nb = float(np.linalg.norm(vb))
    if na == 0.0 or nb == 0.0:
        return -1.0
    return float(np.dot(va, vb) / (na * nb))


def band(sim: float, *, match_thr: float, review_thr: float) -> Band:
    if sim >= match_thr:
        return "match"
    if sim >= review_thr:
        return "review"
    return "reject"


def best_similarity(query: np.ndarray, faces: Sequence[Face]) -> tuple[float, int]:
    """Highest cosine between the query embedding and any face; (-1.0, -1) when no faces."""
    best, best_idx = -1.0, -1
    for idx, face in enumerate(faces):
        sim = cosine(query, face.embedding)
        if sim > best:
            best, best_idx = sim, idx
    return best, best_idx


def quality_ok(face: Face, *, strict: bool = True) -> tuple[bool, str]:
    """Gate faces that are too uncertain, too small or too blurry to trust an embedding.

    strict=True is for the query photo; strict=False is the thumbnail-tolerant gate for candidates.
    """
    det, ipd, blur = (
        (MIN_DET_SCORE, MIN_IPD_PX, MIN_BLUR_VAR)
        if strict
        else (LENIENT_DET_SCORE, LENIENT_IPD_PX, LENIENT_BLUR_VAR)
    )
    if face.det_score < det:
        return False, f"det_score {face.det_score:.2f} < {det:.2f}"
    if face.ipd_px < ipd:
        return False, f"ipd {face.ipd_px:.0f}px < {ipd:.0f}px"
    if face.blur_var < blur:
        return False, f"blur {face.blur_var:.0f} < {blur:.0f}"
    return True, "ok"


def pick_query_face(faces: Sequence[Face], index: int | None = None) -> Face:
    """The face that represents the query: an explicit index, else the largest."""
    if not faces:
        raise ValueError("no faces to choose from")
    if index is not None:
        if index < 0 or index >= len(faces):
            raise ValueError(f"face index {index} out of range 0..{len(faces) - 1}")
        return faces[index]
    good = [f for f in faces if quality_ok(f)[0]]
    return max(good or faces, key=lambda f: f.area)
