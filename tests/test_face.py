"""Model-backed specs for facechain.face.engine. Skipped when the model pack is absent."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from facechain.face.match import cosine, quality_ok
from tests.conftest import requires_model

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
KOHLI = SAMPLES / "kohli" / "subject.jpg"
KOHLI_ALT = SAMPLES / "kohli" / "alt-3-virat-kohli-in-new-delhi-in-december-2018.jpg"
MESSI = SAMPLES / "neg" / "lionel-messi-argentina-2022-fifa-world-cup-cropped-upscale.jpg"

pytestmark = [pytest.mark.model, requires_model]


def _thumb(path: Path, width: int) -> bytes:
    img = Image.open(path).convert("RGB")
    h = round(img.height * width / img.width)
    buf = io.BytesIO()
    img.resize((width, h), Image.Resampling.LANCZOS).save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def test_embed_bytes_finds_one_good_face_with_unit_embedding() -> None:
    from facechain.face.engine import get_engine

    faces = get_engine().embed_bytes(KOHLI.read_bytes())
    assert len(faces) == 1
    face = faces[0]
    assert face.det_score >= 0.8
    assert face.embedding.shape == (512,)
    assert float(np.linalg.norm(face.embedding)) == pytest.approx(1.0, abs=1e-3)
    assert face.ipd_px > 25
    assert quality_ok(face) == (True, "ok")


def test_same_person_scores_higher_than_impostor() -> None:
    from facechain.face.engine import get_engine

    eng = get_engine()
    q = eng.embed_bytes(KOHLI.read_bytes())[0].embedding
    same = eng.embed_bytes(KOHLI_ALT.read_bytes())
    other = eng.embed_bytes(MESSI.read_bytes())
    assert same and other
    s_same = max(cosine(q, f.embedding) for f in same)
    s_other = max(cosine(q, f.embedding) for f in other)
    assert s_same > s_other
    assert s_same > 0.3


def test_thumbnail_sized_image_still_yields_a_face() -> None:
    from facechain.face.engine import get_engine

    faces = get_engine().embed_bytes(_thumb(KOHLI, 160))
    assert len(faces) >= 1
    # inter-pupil distance is reported in original thumbnail pixels even after upscale retry
    assert 5 < faces[0].ipd_px < 80


def test_garbage_bytes_return_no_faces_without_raising() -> None:
    from facechain.face.engine import get_engine

    assert get_engine().embed_bytes(b"not an image") == []
