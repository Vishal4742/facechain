"""InsightFace wrapper: decode -> detect (SCRFD) -> align + embed (ArcFace) -> quality metrics.

Only the detection and recognition models are loaded (no landmarks/gender-age), which keeps
CPU inference fast. Small images that yield no face are retried once at 2x with a lower
detection threshold; reported coordinates are always in source-image pixels.
"""

from __future__ import annotations

import contextlib
import io
import threading
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps

from .types import Face

MODEL_NAME = "buffalo_l"
DEFAULT_DET_THRESH = 0.5
RETRY_DET_THRESH = 0.3
UPSCALE_BELOW_PX = 640
UPSCALE_FACTOR = 2.0

_lock = threading.Lock()
_engine: FaceEngine | None = None


def decode_image(data: bytes) -> np.ndarray | None:
    """Bytes -> BGR array with EXIF orientation applied; None if not an image."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            rgb = np.asarray(ImageOps.exif_transpose(im).convert("RGB"))
    except Exception:  # noqa: BLE001 - any decode failure means "not an image"
        return None
    if rgb.ndim != 3 or rgb.shape[0] < 8 or rgb.shape[1] < 8:
        return None
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def blur_variance(gray_crop: np.ndarray) -> float:
    if gray_crop.size == 0:
        return 0.0
    return float(cv2.Laplacian(gray_crop, cv2.CV_64F).var())


def _ipd(kps: list[tuple[float, float]]) -> float:
    (lx, ly), (rx, ry) = kps[0], kps[1]
    return float(np.hypot(lx - rx, ly - ry))


class FaceEngine:
    def __init__(self, name: str = MODEL_NAME, det_thresh: float = DEFAULT_DET_THRESH) -> None:
        from insightface.app import FaceAnalysis

        chatter = io.StringIO()  # model-loading chatter is noise for users; errors still raise
        with contextlib.redirect_stdout(chatter), contextlib.redirect_stderr(chatter):
            self.app = FaceAnalysis(
                name=name,
                allowed_modules=["detection", "recognition"],
                providers=["CPUExecutionProvider"],
            )
            self.app.prepare(ctx_id=-1, det_thresh=det_thresh)
        self.det_thresh = det_thresh

    def _detect(self, img: np.ndarray, det_thresh: float) -> list[Any]:
        det = self.app.det_model
        previous = det.det_thresh
        det.det_thresh = det_thresh
        try:
            return list(self.app.get(img))
        finally:
            det.det_thresh = previous

    def embed_image(self, img: np.ndarray) -> list[Face]:
        with _lock:
            raw = self._detect(img, self.det_thresh)
        scale = 1.0
        if not raw and min(img.shape[:2]) < UPSCALE_BELOW_PX:
            up = cv2.resize(
                img, None, fx=UPSCALE_FACTOR, fy=UPSCALE_FACTOR, interpolation=cv2.INTER_LANCZOS4
            )
            with _lock:
                raw = self._detect(up, RETRY_DET_THRESH)
            scale = UPSCALE_FACTOR

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        height, width = gray.shape[:2]
        faces: list[Face] = []
        for f in raw:
            x1, y1, x2, y2 = (float(v) / scale for v in f.bbox)
            bbox = (x1, y1, x2, y2)
            crop = gray[
                max(0, int(y1)) : min(height, int(y2)), max(0, int(x1)) : min(width, int(x2))
            ]
            kps = [(float(x) / scale, float(y) / scale) for x, y in f.kps]
            faces.append(
                Face(
                    bbox=bbox,
                    kps=kps,
                    det_score=float(f.det_score),
                    embedding=np.asarray(f.normed_embedding, dtype=np.float32),
                    ipd_px=_ipd(kps),
                    blur_var=blur_variance(crop),
                    area=max(0.0, x2 - x1) * max(0.0, y2 - y1),
                )
            )
        faces.sort(key=lambda face: face.area, reverse=True)
        return faces

    def embed_bytes(self, data: bytes) -> list[Face]:
        img = decode_image(data)
        return [] if img is None else self.embed_image(img)


def get_engine() -> FaceEngine:
    """Process-wide singleton; the first call pays the model load (~5 s on CPU)."""
    global _engine
    with _lock:
        if _engine is None:
            _engine = FaceEngine()
    return _engine
