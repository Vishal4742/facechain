"""Candidate media download: cached, parallel, browser-like, size-capped."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from .. import http
from ..cache import Cache, CacheMiss
from .base import Candidate

MAX_MEDIA_BYTES = 10 * 1024 * 1024
X_MEDIA_HOST = "pbs.twimg.com"


def media_url_for(cand: Candidate) -> str | None:
    url = cand.media_url or cand.thumbnail_url
    if not url:
        return None
    if urlparse(url).netloc == X_MEDIA_HOST and "name=" not in url:
        url += ("&" if "?" in url else "?") + "name=large"
    return url


def download_media(cand: Candidate, cache: Cache) -> bytes | None:
    url = media_url_for(cand)
    if url is None:
        return None
    try:
        return cache.cached_bytes(
            "http.get",
            {"url": url},
            lambda: http.download_bytes(url, max_bytes=MAX_MEDIA_BYTES, referer=cand.url),
            meta={"candidate": cand.url},
        )
    except CacheMiss:
        return None


def download_all(
    cands: list[Candidate], cache: Cache, *, workers: int = 8
) -> dict[str, bytes | None]:
    """Media bytes per canonical candidate URL; failures are None, never exceptions."""
    if not cands:
        return {}
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(cands)))) as pool:
        results = pool.map(lambda c: (c.url, download_media(c, cache)), cands)
    return dict(results)
