"""Google Lens via SerpApi: upload the query image, fetch visual and exact matches, parse.

Live-proof: every live call records SerpApi's `search_metadata.id` and `created_at` so the
recording can show the search happened now. Raw responses are cached before parsing, keyed by
the image hash (never by the short-lived upload id), so re-runs cost no quota.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageOps

from .. import http
from ..cache import STATS, Cache, CacheMiss
from ..config import Settings
from .base import Candidate, Hint
from .filters import dedupe

SERPAPI_SEARCH = "https://serpapi.com/search.json"
SERPAPI_UPLOAD = "https://serpapi.com/image"
SERPAPI_ACCOUNT = "https://serpapi.com/account.json"
PREP = {"max_side": 1024, "max_kb": 480}
ENGINE_BY_TYPE = {"visual_matches": "lens:visual", "exact_matches": "lens:exact"}
NO_RESULTS_MARKER = "hasn't returned any results"


class LensError(RuntimeError):
    """SerpApi refused or failed the request (quota, auth, transport)."""


@dataclass(frozen=True)
class SearchMeta:
    type: str
    live: bool
    search_id: str | None
    created_at: str | None
    replayed: bool = False


@dataclass(frozen=True)
class LensResult:
    candidates: list[Candidate]
    hints: list[Hint]
    meta: list[SearchMeta] = field(default_factory=list)


def prepare_upload(data: bytes) -> bytes:
    """RGB JPEG, longest side <= 1024 px, re-encoded until it fits SerpApi's 500 KB cap."""
    with Image.open(io.BytesIO(data)) as im:
        rgb = ImageOps.exif_transpose(im).convert("RGB")
        rgb.thumbnail((PREP["max_side"], PREP["max_side"]), Image.Resampling.LANCZOS)
        quality = 85
        while True:
            buf = io.BytesIO()
            rgb.save(buf, format="JPEG", quality=quality, optimize=True)
            if buf.tell() <= PREP["max_kb"] * 1024 or quality <= 50:
                return buf.getvalue()
            quality -= 10


def upload_image(jpeg: bytes, api_key: str) -> str:
    resp = http.post(
        SERPAPI_UPLOAD,
        files={"image": ("query.jpg", jpeg, "image/jpeg")},
        data={"api_key": api_key},
        timeout=60,
    )
    try:
        payload = resp.json()
    except ValueError as exc:
        raise LensError(f"upload returned non-JSON (HTTP {resp.status_code})") from exc
    image_id = payload.get("image_id")
    if resp.status_code != 200 or not image_id:
        raise LensError(f"upload failed: HTTP {resp.status_code} {payload.get('error', payload)}")
    return str(image_id)


def lens_search_raw(image_id: str, type_: str, api_key: str) -> dict[str, Any]:
    resp = http.get(
        SERPAPI_SEARCH,
        params={
            "engine": "google_lens",
            "image_id": image_id,
            "type": type_,
            "hl": "en",
            "api_key": api_key,
        },
        timeout=90,
    )
    try:
        payload = resp.json()
    except ValueError as exc:
        raise LensError(f"search returned non-JSON (HTTP {resp.status_code})") from exc
    error = payload.get("error")
    if error and NO_RESULTS_MARKER in str(error):
        return {"search_metadata": payload.get("search_metadata", {}), "visual_matches": []}
    if resp.status_code != 200 or error:
        raise LensError(f"search failed: HTTP {resp.status_code} {error or payload}")
    return payload


def account_searches_left(api_key: str) -> int | None:
    """Remaining monthly searches, or None if the account endpoint is unavailable."""
    try:
        resp = http.get(SERPAPI_ACCOUNT, params={"api_key": api_key}, timeout=20)
        data = resp.json()
    except Exception:  # noqa: BLE001 - informational only
        return None
    left = data.get("plan_searches_left")
    return int(left) if isinstance(left, int | float | str) and str(left).isdigit() else None


def parse_lens_response(data: dict[str, Any], *, engine: str) -> tuple[list[Candidate], list[Hint]]:
    key = "exact_matches" if engine == "lens:exact" else "visual_matches"
    candidates: list[Candidate] = []
    for index, item in enumerate(data.get(key) or []):
        link = item.get("link")
        if not isinstance(link, str) or not link:
            continue
        candidates.append(
            Candidate.from_url(
                link,
                engine=engine,
                engine_rank=int(item.get("position") or index + 1),
                title=item.get("title"),
                media_url=item.get("image") or item.get("thumbnail"),
                thumbnail_url=item.get("thumbnail"),
                raw={k: v for k, v in item.items() if k not in {"thumbnail", "image"}}
                | {"source": item.get("source")},
            )
        )
    hints: list[Hint] = []
    for rc in data.get("related_content") or []:
        query = rc.get("query")
        if not query:
            continue
        kgmid = rc.get("kgmid") or _kgmid_from_link(rc.get("link"))
        hint = Hint(query=str(query), kgmid=str(kgmid) if kgmid else None)
        if hint not in hints:
            hints.append(hint)
    return candidates, hints


def _kgmid_from_link(link: Any) -> str | None:
    """Lens puts the Knowledge Graph id in the related_content link (…&kgmid=/m/03qkvyf&…)."""
    if not isinstance(link, str):
        return None
    values = parse_qs(urlparse(link).query).get("kgmid")
    return values[0] if values else None


def search_lens(
    image_bytes: bytes,
    settings: Settings,
    cache: Cache,
    *,
    types: tuple[str, ...] = ("visual_matches", "exact_matches"),
    fixtures: Cache | None = None,
    on_event: Any = None,
) -> LensResult:
    """Run Lens for each requested type; cached responses are reused, misses go live."""
    image_sha = hashlib.sha256(image_bytes).hexdigest()
    jpeg: bytes | None = None
    image_id: str | None = None
    all_cands: list[Candidate] = []
    hints: list[Hint] = []
    meta: list[SearchMeta] = []

    def emit(message: str, level: str = "info") -> None:
        if on_event is not None:
            on_event(level, message)

    for type_ in types:
        params = {"image_sha256": image_sha, "prep": PREP, "type": type_}
        live = False
        replayed = False

        def fetch(type_: str = type_) -> dict[str, Any]:
            nonlocal jpeg, image_id, live
            if settings.serpapi_key is None:
                raise LensError("SERPAPI_KEY is not set (put it in .env)")
            if jpeg is None:
                jpeg = prepare_upload(image_bytes)
            if image_id is None:
                image_id = upload_image(jpeg, settings.serpapi_key)
            data = lens_search_raw(image_id, type_, settings.serpapi_key)
            live = True
            STATS.serpapi_searches += 1
            return data

        try:
            data = cache.get_json("serpapi.lens", params)
            if data is None:
                if cache.offline:
                    raise CacheMiss(f"serpapi.lens {type_} for image {image_sha[:12]}")
                data = fetch()
                if data.get("visual_matches") or data.get("exact_matches"):
                    cache.put_json("serpapi.lens", params, data, meta={"engine": "google_lens"})
                else:
                    emit(f"lens {type_}: Google returned no results this time (not cached)", "warn")
        except CacheMiss:
            raise
        except (http.HttpError, LensError) as exc:
            replay = fixtures.get_json("serpapi.lens", params) if fixtures is not None else None
            if replay is None:
                raise
            data = replay
            replayed = True
            emit(
                f"LIVE CALL FAILED ({exc}); replaying recorded response "
                f"id={data.get('search_metadata', {}).get('id')} "
                f"created_at={data.get('search_metadata', {}).get('created_at')}",
                "error",
            )
        sm = data.get("search_metadata") or {}
        meta.append(SearchMeta(type_, live, sm.get("id"), sm.get("created_at"), replayed))
        cands, new_hints = parse_lens_response(data, engine=ENGINE_BY_TYPE[type_])
        all_cands.extend(cands)
        hints.extend(h for h in new_hints if h not in hints)
        emit(
            f"lens {type_}: {len(cands)} matches "
            f"({'REPLAYED' if replayed else 'live' if live else 'cached'} "
            f"id={sm.get('id')} at {sm.get('created_at')})"
        )

    return LensResult(candidates=dedupe(all_cands), hints=hints, meta=meta)
