"""X (Twitter) without an API key: the public syndication timeline and tweet-result endpoints.

Rate limits are tight (about 30 timeline calls per 15 minutes per IP), so timeline pages are
always served from the cache when present, even in --live mode; only Lens is forced live.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from ... import http
from ...cache import Cache, CacheMiss
from ..base import Candidate

TIMELINE_URL = "https://syndication.twitter.com/srv/timeline-profile/screen-name/{handle}"
TWEET_URL = "https://cdn.syndication.twimg.com/tweet-result"
NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
STATUS_RE = re.compile(r"/status/(\d+)")


@dataclass(frozen=True)
class Tweet:
    id: str
    url: str
    author: str  # "@handle"
    text: str
    media_urls: tuple[str, ...]
    created_at: str | None


def tweet_id_from_url(url: str) -> str | None:
    match = STATUS_RE.search(url)
    return match.group(1) if match else None


def _find_entries(obj: Any) -> list[Any]:
    if isinstance(obj, dict):
        entries = obj.get("entries")
        if isinstance(entries, list):
            return entries
        for value in obj.values():
            found = _find_entries(value)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_entries(value)
            if found:
                return found
    return []


def _tweet_from_payload(tweet: dict[str, Any], *, handle_hint: str | None) -> Tweet | None:
    tweet_id = tweet.get("id_str") or tweet.get("id")
    if not tweet_id:
        return None
    screen = (tweet.get("user") or {}).get("screen_name") or handle_hint
    if not screen:
        return None
    media_items = (tweet.get("entities") or {}).get("media") or tweet.get("mediaDetails") or []
    media = tuple(str(m["media_url_https"]) for m in media_items if m.get("media_url_https"))
    return Tweet(
        id=str(tweet_id),
        url=f"https://x.com/{screen}/status/{tweet_id}",
        author=f"@{screen}",
        text=str(tweet.get("full_text") or tweet.get("text") or ""),
        media_urls=media,
        created_at=tweet.get("created_at"),
    )


def parse_timeline_html(html: str, *, handle_hint: str | None = None) -> list[Tweet]:
    """Tweets with media from a syndication timeline page; [] when the page is not a timeline."""
    match = NEXT_DATA_RE.search(html or "")
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return []
    tweets: list[Tweet] = []
    for entry in _find_entries(data):
        payload = (entry.get("content") or {}).get("tweet") if isinstance(entry, dict) else None
        if not payload:
            continue
        tweet = _tweet_from_payload(payload, handle_hint=handle_hint)
        if tweet and tweet.media_urls:
            tweets.append(tweet)
    return tweets


def parse_tweet_result(data: dict[str, Any], *, handle_hint: str | None) -> Tweet | None:
    if not isinstance(data, dict) or data.get("error") or not data.get("id_str"):
        return None
    return _tweet_from_payload(data, handle_hint=handle_hint)


def fetch_timeline(handle: str, cache: Cache) -> list[Tweet]:
    """Cached timeline page (never bypassed by --live, see module docstring)."""
    stable = Cache(cache.root, offline=cache.offline, live=False)

    def fetch() -> bytes | None:
        try:
            resp = http.get(
                TIMELINE_URL.format(handle=handle),
                headers={"User-Agent": http.BROWSER_UA},
                timeout=20,
                retries=1,
            )
        except http.HttpError:
            return None  # rate-limited (429 after retries) or blocked: do not cache
        if resp.status_code != 200 or "__NEXT_DATA__" not in resp.text:
            return None
        return resp.content

    try:
        html = stable.cached_bytes("x.timeline", {"handle": handle}, fetch)
    except CacheMiss:
        return []
    return parse_timeline_html(html.decode("utf-8", "replace"), handle_hint=handle) if html else []


def fetch_tweet(tweet_id: str, cache: Cache, *, handle_hint: str | None = None) -> Tweet | None:
    def fetch() -> dict[str, Any] | None:
        try:
            resp = http.get(
                TWEET_URL,
                params={"id": tweet_id, "token": "1"},
                headers={"User-Agent": http.BROWSER_UA},
                timeout=20,
                retries=1,
            )
        except http.HttpError:
            return None
        if resp.status_code != 200:
            return None
        try:
            data = resp.json()
        except ValueError:
            return None
        return data if data.get("id_str") else None

    try:
        data = cache.cached_json("x.tweet", {"id": tweet_id}, fetch)
    except CacheMiss:
        return None
    return parse_tweet_result(data, handle_hint=handle_hint) if data else None


def tweets_to_candidates(
    tweets: Sequence[Tweet], *, engine: str, limit: int = 30
) -> list[Candidate]:
    return [
        Candidate.from_url(
            t.url,
            engine=engine,
            engine_rank=i,
            text=t.text,
            media_url=t.media_urls[0],
            raw={"created_at": t.created_at, "media_urls": list(t.media_urls), "tweet_id": t.id},
        )
        for i, t in enumerate(tweets[:limit], start=1)
        if t.media_urls
    ]


def hydrate(cand: Candidate, cache: Cache) -> Candidate:
    """Fill text and original media for an x.com status candidate found by another engine."""
    if cand.platform != "x" or not cand.is_post:
        return cand
    tweet_id = tweet_id_from_url(cand.url)
    if not tweet_id:
        return cand
    tweet = fetch_tweet(tweet_id, cache, handle_hint=(cand.author or "").lstrip("@") or None)
    if tweet is None:
        return cand
    return replace(
        cand,
        text=tweet.text or cand.text,
        media_url=tweet.media_urls[0] if tweet.media_urls else cand.media_url,
        raw={
            **cand.raw,
            "tweet": {"created_at": tweet.created_at, "media_urls": list(tweet.media_urls)},
        },
    )
