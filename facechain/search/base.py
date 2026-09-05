"""Value objects shared by every search engine and the ranker."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from typing import Any

from ..face.match import band as _band
from .filters import author_of, canonical_url, is_post_url, platform_of

BAND_ORDER = {"match": 0, "review": 1, "reject": 2, "no face": 3, "no media": 4, "pending": 5}


@dataclass(frozen=True)
class Hint:
    """Identity hint from an engine (Google Lens related_content with a Knowledge Graph id)."""

    query: str
    kgmid: str | None = None


@dataclass(frozen=True)
class Candidate:
    url: str  # canonical
    platform: str | None
    is_post: bool
    author: str | None
    title: str | None
    text: str | None
    media_url: str | None
    thumbnail_url: str | None
    engine: str
    engine_rank: int
    similarity_bps: int | None = None
    faces_found: int = 0
    band: str = "pending"
    corroborated_by: tuple[str, ...] = ()
    media_sha256: str | None = None
    media_bytes: bytes | None = field(default=None, repr=False, compare=False)
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        engine: str,
        engine_rank: int,
        title: str | None = None,
        text: str | None = None,
        media_url: str | None = None,
        thumbnail_url: str | None = None,
        raw: dict[str, Any] | None = None,
    ) -> Candidate:
        canonical = canonical_url(url)
        return cls(
            url=canonical,
            platform=platform_of(canonical),
            is_post=is_post_url(canonical),
            author=author_of(canonical),
            title=title,
            text=text,
            media_url=media_url,
            thumbnail_url=thumbnail_url,
            engine=engine,
            engine_rank=engine_rank,
            raw=raw or {},
        )

    def with_similarity(
        self,
        sim: float | None,
        *,
        match_thr: float,
        review_thr: float,
        faces_found: int | None = None,
    ) -> Candidate:
        faces = self.faces_found if faces_found is None else faces_found
        if sim is None:
            return replace(self, similarity_bps=None, band="no face", faces_found=faces)
        return replace(
            self,
            similarity_bps=round(sim * 10_000),
            band=_band(sim, match_thr=match_thr, review_thr=review_thr),
            faces_found=max(faces, 1),
        )

    @property
    def similarity(self) -> float | None:
        return None if self.similarity_bps is None else self.similarity_bps / 10_000

    def sort_key(self) -> tuple[int, int, int, int]:
        return (
            BAND_ORDER.get(self.band, 9),
            -(self.similarity_bps or -10_000),
            0 if self.is_post else 1,
            self.engine_rank,
        )

    def to_dict(self) -> dict[str, Any]:
        """Every field except the repr=False payloads (media_bytes, raw); JSON-ready."""
        return {f.name: getattr(self, f.name) for f in fields(self) if f.repr}
