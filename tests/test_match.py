"""Specs for facechain.face.match (pure functions) — written before the implementation."""

from __future__ import annotations

import numpy as np
import pytest

from facechain.face.match import band, best_similarity, cosine, pick_query_face, quality_ok
from facechain.face.types import Face


def _face(
    *,
    emb: np.ndarray | None = None,
    det: float = 0.9,
    ipd: float = 40.0,
    blur: float = 120.0,
    area: float = 10_000.0,
) -> Face:
    e = emb if emb is not None else np.array([1.0, 0.0, 0.0], dtype=np.float32)
    return Face(
        bbox=(0.0, 0.0, 100.0, 100.0),
        kps=[(30.0, 40.0), (70.0, 40.0), (50.0, 60.0), (35.0, 80.0), (65.0, 80.0)],
        det_score=det,
        embedding=e,
        ipd_px=ipd,
        blur_var=blur,
        area=area,
    )


def test_cosine_identical_orthogonal_and_opposite() -> None:
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([0.0, 1.0], dtype=np.float32)
    assert cosine(a, a) == pytest.approx(1.0)
    assert cosine(a, b) == pytest.approx(0.0)
    assert cosine(a, -a) == pytest.approx(-1.0)


def test_cosine_normalises_unnormalised_inputs() -> None:
    a = np.array([3.0, 0.0], dtype=np.float32)
    b = np.array([10.0, 0.0], dtype=np.float32)
    assert cosine(a, b) == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("sim", "expected"),
    [
        (0.9, "match"),
        (0.45, "match"),
        (0.4499, "review"),
        (0.35, "review"),
        (0.3499, "reject"),
        (-1.0, "reject"),
    ],
)
def test_band_thresholds_are_inclusive(sim: float, expected: str) -> None:
    assert band(sim, match_thr=0.45, review_thr=0.35) == expected


def test_best_similarity_picks_max_and_index() -> None:
    q = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    faces = [
        _face(emb=np.array([0.0, 1.0, 0.0], dtype=np.float32)),
        _face(emb=np.array([0.8, 0.6, 0.0], dtype=np.float32)),
        _face(emb=np.array([0.5, 0.5, 0.0], dtype=np.float32)),
    ]
    sim, idx = best_similarity(q, faces)
    assert idx == 1
    assert sim == pytest.approx(0.8)


def test_best_similarity_on_empty_list() -> None:
    q = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    assert best_similarity(q, []) == (-1.0, -1)


def test_quality_gate_reasons() -> None:
    assert quality_ok(_face()) == (True, "ok")
    assert quality_ok(_face(det=0.5)) == (False, "det_score 0.50 < 0.60")
    assert quality_ok(_face(ipd=10)) == (False, "ipd 10px < 25px")
    assert quality_ok(_face(blur=5)) == (False, "blur 5 < 60")


def test_pick_query_face_largest_by_default_or_by_index() -> None:
    small, big = _face(area=100), _face(area=5000)
    assert pick_query_face([small, big]) is big
    assert pick_query_face([small, big], index=0) is small
    with pytest.raises(ValueError):
        pick_query_face([])
    with pytest.raises(ValueError):
        pick_query_face([small], index=3)


def test_lenient_gate_accepts_thumbnail_faces_that_the_strict_gate_rejects() -> None:
    thumb_face = _face(det=0.55, ipd=14, blur=20)
    assert quality_ok(thumb_face)[0] is False
    assert quality_ok(thumb_face, strict=False) == (True, "ok")
    assert quality_ok(_face(det=0.3), strict=False)[0] is False
