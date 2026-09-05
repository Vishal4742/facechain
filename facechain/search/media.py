"""Candidate media download: cached, parallel, browser-like, size-capped."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from .. import http
from ..cache import Cache
from .base import Candidate

MAX_MEDIA_BYTES = 10 * 1024 * 1024
X_MEDIA_HOST = "pbs.twimg.com"


def _with_size(url: str) -> str:
    if urlparse(url).netloc == X_MEDIA_HOST and "name=" not in url:
        url += ("&" if "?" in url else "?") + "name=large"
    return url


def media_urls_for(cand: Candidate) -> list[str]:
    """Platform image first (full resolution), Google's thumbnail second (always fetchable)."""
    urls = dict.fromkeys(u for u in (cand.media_url, cand.thumbnail_url) if u)
    return [_with_size(u) for u in urls]


def download_media(cand: Candidate, cache: Cache) -> bytes | None:
    for url in media_urls_for(cand):
        try:
            data = cache.cached_bytes(
                "http.get",
                {"url": url},
                lambda url=url: http.download_bytes(
                    url, max_bytes=MAX_MEDIA_BYTES, referer=cand.url
                ),
                meta={"candidate": cand.url},
            )
        except Exception:  # noqa: BLE001 - offline miss or one bad CDN must not kill the search
            continue
        if data:
            return data
    return None


def download_all(
    cands: list[Candidate], cache: Cache, *, workers: int = 8
) -> dict[str, bytes | None]:
    """Media bytes per canonical candidate URL; failures are None, never exceptions."""
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(cands)))) as pool:
        results = pool.map(lambda c: (c.url, download_media(c, cache)), cands)
    return dict(results)
