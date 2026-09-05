"""URL knowledge: which platform, is it a post, canonical form, author handle."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlparse

if TYPE_CHECKING:
    from .base import Candidate

# platform -> registrable domains (matched as host == d or host endswith "." + d)
PLATFORM_DOMAINS: dict[str, tuple[str, ...]] = {
    "instagram": ("instagram.com",),
    "x": ("x.com", "twitter.com"),
    "facebook": ("facebook.com", "fb.com", "fb.watch"),
    "tiktok": ("tiktok.com",),
    "threads": ("threads.net", "threads.com"),
    "youtube": ("youtube.com", "youtu.be"),
    "linkedin": ("linkedin.com",),
    "pinterest": ("pinterest.com", "pin.it"),
}

# regexes tested against path + ("?" + query) of the canonical URL
POST_PATTERNS: dict[str, re.Pattern[str]] = {
    "instagram": re.compile(r"^/(p|reel|reels|tv)/[^/?]+"),
    "x": re.compile(r"^/[^/]+/status/\d+"),
    "facebook": re.compile(
        r"(/posts/|/photos?/|/videos?/|/reels?/|^/watch|^/photo(\.php)?(\?|$)|^/story\.php|^/share/)"
    ),
    "tiktok": re.compile(r"^/@[^/]+/video/\d+|^/t/"),
    "threads": re.compile(r"^/@[^/]+/post/"),
    "youtube": re.compile(r"^/watch\?v=|^/shorts/|^/live/"),
    "linkedin": re.compile(r"^/posts/|^/feed/update/"),
    "pinterest": re.compile(r"^/pin/"),
}

# query parameters that identify content and therefore survive canonicalisation
KEEP_QUERY: dict[str, frozenset[str]] = {
    "youtube": frozenset({"v"}),
    "facebook": frozenset({"fbid", "story_fbid", "id", "v"}),
}

HOST_ALIASES: dict[str, str] = {
    "twitter.com": "x.com",
    "www.twitter.com": "x.com",
    "mobile.twitter.com": "x.com",
    "m.twitter.com": "x.com",
    "www.x.com": "x.com",
    "mobile.x.com": "x.com",
    "m.youtube.com": "www.youtube.com",
    "youtube.com": "www.youtube.com",
    "m.facebook.com": "www.facebook.com",
    "mobile.facebook.com": "www.facebook.com",
    "facebook.com": "www.facebook.com",
    "instagram.com": "www.instagram.com",
    "threads.com": "www.threads.net",
    "www.threads.com": "www.threads.net",
    "threads.net": "www.threads.net",
}

X_MEDIA_SUFFIX = re.compile(r"/(photo|video)/\d+$")


def _host(url: str) -> str | None:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return parsed.netloc.lower().split("@")[-1].split(":")[0]


def platform_of(url: str) -> str | None:
    host = _host(url)
    if host is None:
        return None
    host = HOST_ALIASES.get(host, host)
    for platform, domains in PLATFORM_DOMAINS.items():
        if any(host == d or host.endswith("." + d) for d in domains):
            return platform
    if "pinterest." in host:  # pinterest.co.uk, in.pinterest.com, ...
        return "pinterest"
    return None


def canonical_url(url: str) -> str:
    """Stable identity for a page: https, aliased host, no tracking query, no fragment/slash."""
    raw = url.strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return raw
    host = parsed.netloc.lower().split("@")[-1]
    host = HOST_ALIASES.get(host, host)
    path = parsed.path or "/"
    query_items = parse_qsl(parsed.query, keep_blank_values=False)

    if host == "youtu.be":
        video_id = path.strip("/").split("/")[0]
        host, path, query_items = "www.youtube.com", "/watch", [("v", video_id)]
    if host == "x.com":
        path = X_MEDIA_SUFFIX.sub("", path)

    platform = platform_of(f"https://{host}{path}")
    keep = KEEP_QUERY.get(platform or "", frozenset())
    query = "&".join(f"{k}={v}" for k, v in query_items if k in keep)

    path = re.sub(r"/{2,}", "/", path)
    if len(path) > 1:
        path = path.rstrip("/")
    return f"https://{host}{path}" + (f"?{query}" if query else "")


def is_post_url(url: str) -> bool:
    canonical = canonical_url(url)
    platform = platform_of(canonical)
    if platform is None:
        return False
    parsed = urlparse(canonical)
    target = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    return POST_PATTERNS[platform].search(target) is not None


def author_of(url: str) -> str | None:
    """Best-effort account handle ("@name") from the URL path; None when the URL has none."""
    canonical = canonical_url(url)
    platform = platform_of(canonical)
    parts = [p for p in urlparse(canonical).path.split("/") if p]
    if not platform or not parts:
        return None
    first = parts[0]
    if platform == "x" and first not in {"i", "search", "hashtag", "explore", "home"}:
        return f"@{first}"
    if platform in {"tiktok", "threads", "youtube"} and first.startswith("@"):
        return first
    if platform == "instagram" and first not in {"p", "reel", "reels", "tv", "explore", "stories"}:
        return f"@{first}"
    if platform == "facebook" and first not in {
        "photo",
        "photo.php",
        "watch",
        "share",
        "story.php",
    }:
        return f"@{first}"
    return None


def filter_social(cands: Iterable[Candidate]) -> list[Candidate]:
    return [c for c in cands if c.platform is not None]


def dedupe(cands: Sequence[Candidate]) -> list[Candidate]:
    """Keep the first occurrence of each canonical URL (input order == engine rank order)."""
    seen: set[str] = set()
    out: list[Candidate] = []
    for cand in cands:
        if cand.url in seen:
            continue
        seen.add(cand.url)
        out.append(cand)
    return out
