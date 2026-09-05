"""Face-verified ranking and the acceptance rule.

Reverse image search only proposes candidates. What decides is the cosine similarity between the
query face and the faces inside each candidate's media, plus corroboration: one high score alone
is not enough, the identity must be supported by a second independent signal.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np
from rich.table import Table

from ..cache import Cache
from ..face.engine import FaceEngine
from ..face.match import best_similarity, quality_ok
from .base import Candidate
from .media import download_all


@dataclass(frozen=True)
class Decision:
    winner: Candidate | None
    accepted: bool
    reason: str


def verify_candidates(
    query_embedding: np.ndarray,
    cands: Sequence[Candidate],
    *,
    cache: Cache,
    engine: FaceEngine,
    match_thr: float,
    review_thr: float,
    max_n: int = 40,
    workers: int = 8,
) -> list[Candidate]:
    """Download media, embed every face, score the best one; returns candidates sorted by rank."""
    subset = list(cands[:max_n])
    media = download_all(subset, cache, workers=workers)
    verified: list[Candidate] = []
    for cand in subset:
        data = media.get(cand.url)
        if not data:
            verified.append(replace(cand, band="no media"))
            continue
        faces = engine.embed_bytes(data)
        good = [f for f in faces if quality_ok(f)[0]]
        pool = good or faces
        sim, _ = best_similarity(query_embedding, pool) if pool else (None, -1)
        scored = cand.with_similarity(
            sim, match_thr=match_thr, review_thr=review_thr, faces_found=len(faces)
        )
        if not good and scored.band == "match":  # only low-quality faces: never a full match
            scored = replace(scored, band="review")
        verified.append(
            replace(scored, media_sha256=hashlib.sha256(data).hexdigest(), media_bytes=data)
        )
    return sorted(verified, key=Candidate.sort_key)


def corroborate(
    cands: Sequence[Candidate], *, identity_tags: set[str] | None = None
) -> list[Candidate]:
    """Mark candidates another engine also reached (same URL/author) or authored by the
    identity resolved through Wikidata (`identity_tags` are "@handle" strings)."""
    out: list[Candidate] = []
    for cand in cands:
        signals = {
            f"engine:{other.engine}"
            for other in cands
            if other is not cand
            and other.engine != cand.engine
            and (other.url == cand.url or (cand.author and other.author == cand.author))
        }
        if (
            identity_tags
            and cand.author
            and cand.author.lower() in {t.lower() for t in identity_tags}
        ):
            signals.add(f"identity:{cand.author}")
        merged = tuple(sorted(set(cand.corroborated_by) | signals))
        out.append(
            replace(cand, corroborated_by=merged) if merged != cand.corroborated_by else cand
        )
    return out


def accept(cands: Sequence[Candidate], *, match_thr: float, corroborate_thr: float) -> Decision:
    match_bps = round(match_thr * 10_000)
    corroborate_bps = round(corroborate_thr * 10_000)
    scored = [c for c in cands if c.similarity_bps is not None]
    posts = [
        c
        for c in scored
        if c.platform and c.is_post and c.band == "match" and (c.similarity_bps or 0) >= match_bps
    ]
    if not posts:
        social_scored = [c for c in scored if c.platform and c.is_post]
        best_social = max(social_scored, key=lambda c: c.similarity_bps or 0, default=None)
        best = max(scored, key=lambda c: c.similarity_bps or 0, default=None)
        if best is None:
            return Decision(None, False, "REVIEW: no candidate with a detectable face")
        if best_social is None:
            n_social = sum(1 for c in cands if c.platform and c.is_post)
            return Decision(
                None,
                False,
                f"REVIEW: {n_social} social posts found but none had usable media/faces "
                f"(best non-social {best.similarity:.2f})",
            )
        return Decision(
            None,
            False,
            f"REVIEW: best social post {best_social.similarity:.2f} < {match_thr:.2f} "
            f"(best overall {best.similarity:.2f})",
        )
    winner = max(posts, key=lambda c: ((c.similarity_bps or 0), -c.engine_rank))
    supporters = {c.url for c in scored if (c.similarity_bps or 0) >= corroborate_bps}
    parts = [f"sim {winner.similarity:.2f} >= {match_thr:.2f}"]
    if len(supporters) >= 2:
        parts.append(f"{len(supporters)} candidates >= {corroborate_thr:.2f}")
        return Decision(winner, True, "ACCEPT: " + "; ".join(parts))
    if winner.corroborated_by:
        parts.append("corroborated by " + ", ".join(winner.corroborated_by))
        return Decision(winner, True, "ACCEPT: " + "; ".join(parts))
    parts.append(
        f"no corroboration (only 1 candidate >= {corroborate_thr:.2f}, "
        "no identity or engine agreement)"
    )
    return Decision(winner, False, "REVIEW: " + "; ".join(parts))


def render_table(cands: Sequence[Candidate], *, title: str = "candidates") -> Table:
    table = Table(title=title)
    for col in ("#", "engine", "platform", "url", "faces", "sim", "band", "corroboration"):
        table.add_column(col, overflow="fold")
    for i, c in enumerate(cands, start=1):
        sim = "-" if c.similarity is None else f"{c.similarity:.3f}"
        colour = {"match": "green", "review": "yellow"}.get(c.band, "dim")
        url = c.url if len(c.url) <= 70 else c.url[:67] + "..."
        table.add_row(
            str(i),
            c.engine,
            (c.platform or "-") + ("" if c.is_post or not c.platform else " (profile)"),
            url,
            str(c.faces_found),
            sim,
            f"[{colour}]{c.band}[/{colour}]",
            ", ".join(c.corroborated_by) or "-",
        )
    return table
