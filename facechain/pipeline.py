"""Orchestration shared by the `search` and `run` commands."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .cache import Cache
from .config import Settings
from .face.engine import get_engine
from .face.match import pick_query_face
from .face.types import Face
from .search.base import Candidate, Hint
from .search.filters import dedupe
from .search.lens import SearchMeta, search_lens
from .search.rank import Decision, accept, corroborate, verify_candidates

CORROBORATE_THRESHOLD = 0.40
FIXTURES_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "cache"

EventHandler = Callable[[str, str], None]


@dataclass(frozen=True)
class SearchOutcome:
    face_id: str
    query_face: Face
    faces_in_query: int
    candidates: list[Candidate]
    decision: Decision
    hints: list[Hint] = field(default_factory=list)
    meta: list[SearchMeta] = field(default_factory=list)


class NoFaceError(RuntimeError):
    """The query image contains no detectable face."""


def run_search(
    image_bytes: bytes,
    settings: Settings,
    cache: Cache,
    *,
    engines: tuple[str, ...] = ("lens",),
    max_candidates: int = 40,
    face_index: int | None = None,
    on_event: EventHandler | None = None,
) -> SearchOutcome:
    def emit(level: str, message: str) -> None:
        if on_event is not None:
            on_event(level, message)

    engine = get_engine()
    faces = engine.embed_bytes(image_bytes)
    if not faces:
        raise NoFaceError("no face detected in the query image")
    query = pick_query_face(faces, face_index)
    face_id = hashlib.sha256(image_bytes).hexdigest()
    emit(
        "info",
        f"query face: det {query.det_score:.2f}, ipd {query.ipd_px:.0f}px; "
        f"face_id {face_id[:16]}...",
    )

    candidates: list[Candidate] = []
    hints: list[Hint] = []
    meta: list[SearchMeta] = []
    if "lens" in engines:
        fixtures = Cache(FIXTURES_DIR) if FIXTURES_DIR.exists() else None
        result = search_lens(image_bytes, settings, cache, fixtures=fixtures, on_event=on_event)
        candidates.extend(result.candidates)
        hints.extend(result.hints)
        meta.extend(result.meta)
    candidates = dedupe(candidates)
    emit(
        "info", f"{len(candidates)} unique candidates; verifying faces in the top {max_candidates}"
    )

    verified = verify_candidates(
        query.embedding,
        candidates,
        cache=cache,
        engine=engine,
        match_thr=settings.match_threshold,
        review_thr=settings.review_threshold,
        max_n=max_candidates,
    )
    verified = corroborate(verified)
    decision = accept(
        verified, match_thr=settings.match_threshold, corroborate_thr=CORROBORATE_THRESHOLD
    )
    return SearchOutcome(
        face_id=face_id,
        query_face=query,
        faces_in_query=len(faces),
        candidates=verified,
        decision=decision,
        hints=hints,
        meta=meta,
    )
