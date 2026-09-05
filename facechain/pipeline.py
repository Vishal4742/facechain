"""Orchestration shared by the `search` and `run` commands."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .cache import Cache, CacheMiss
from .config import Settings
from .face.engine import get_engine
from .face.match import pick_query_face
from .face.types import Face
from .search.base import Candidate, Hint
from .search.filters import dedupe
from .search.identity import Identity, resolve
from .search.lens import SearchMeta, search_lens
from .search.platforms.x import fetch_timeline, hydrate, tweets_to_candidates
from .search.rank import Decision, accept, corroborate, verify_candidates

CORROBORATE_THRESHOLD = 0.40
HYDRATE_LIMIT = 10
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
    identity: Identity | None = None


class NoFaceError(RuntimeError):
    """The query image contains no detectable face."""


def prioritise(cands: list[Candidate]) -> list[Candidate]:
    """Social posts first, then social profiles, then other pages; engine order within each."""
    posts = [c for c in cands if c.platform and c.is_post]
    profiles = [c for c in cands if c.platform and not c.is_post]
    others = [c for c in cands if not c.platform]
    return posts + profiles + others


NAME_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b")
NAME_STOPWORDS = {
    "The",
    "This",
    "That",
    "Photo",
    "Image",
    "Images",
    "News",
    "Stock",
    "Getty",
    "Alamy",
    "Instagram",
    "Facebook",
    "Twitter",
    "Pinterest",
    "Reddit",
    "YouTube",
    "TikTok",
    "India",
    "Cricket",
    "Sports",
    "Premium",
    "Editorial",
    "Free",
    "Best",
    "Top",
    "New",
    "Latest",
    "Live",
    "Video",
    "Videos",
    "Watch",
    "Wallpaper",
    "Wallpapers",
    "HD",
}


def mine_names(titles: list[str], *, min_count: int = 3) -> list[str]:
    """Most frequent capitalised 2-3 word sequences across candidate titles (likely the person)."""
    counts: dict[str, int] = {}
    for title in titles:
        for match in NAME_RE.findall(title):
            words = match.split()
            if any(w in NAME_STOPWORDS for w in words):
                continue
            counts[match] = counts.get(match, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0])))
    return [name for name, n in ranked if n >= min_count]


def _identity_candidates(
    hints: list[Hint], cache: Cache, emit: EventHandler
) -> tuple[Identity | None, list[Candidate]]:
    try:
        identity = resolve(hints, cache)
    except CacheMiss:
        emit("warn", "identity: not cached, skipped (offline)")
        return None, []
    if identity is None:
        emit("warn", "identity: no Wikidata match for the Lens hints")
        return None, []
    handles = ", ".join(f"{k}={v}" for k, v in identity.author_tags().items()) or "no handles"
    emit("info", f"identity: {identity.label} ({identity.qid}); {handles}")
    if not identity.handles.x:
        return identity, []
    tweets = fetch_timeline(identity.handles.x, cache)
    cands = tweets_to_candidates(tweets, engine="identity:x")
    emit("info", f"identity:x @{identity.handles.x}: {len(cands)} recent posts with media")
    return identity, cands


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
    identity: Identity | None = None
    if "lens" in engines:
        fixtures = Cache(FIXTURES_DIR) if FIXTURES_DIR.exists() else None
        result = search_lens(image_bytes, settings, cache, fixtures=fixtures, on_event=on_event)
        candidates.extend(result.candidates)
        hints.extend(result.hints)
        meta.extend(result.meta)
    if "identity" in engines:
        if not hints:
            mined = mine_names([c.title for c in candidates if c.title])
            if mined:
                emit("info", f"identity: no Lens hint; names mined from titles: {mined[:3]}")
                hints = [Hint(query=name, kgmid=None) for name in mined[:3]]
        identity, extra = _identity_candidates(hints, cache, emit)
        candidates.extend(extra)
    candidates = prioritise(dedupe(candidates))

    hydrated = 0
    for i, cand in enumerate(candidates):
        if cand.platform == "x" and cand.is_post and cand.text is None and hydrated < HYDRATE_LIMIT:
            candidates[i] = hydrate(cand, cache)
            hydrated += 1
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
    identity_tags = set(identity.author_tags().values()) if identity else set()
    verified = corroborate(verified, identity_tags=identity_tags)
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
        identity=identity,
    )
