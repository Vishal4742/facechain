"""Identity hop: Lens identity hint -> Wikidata entity -> verified social handles.

Google Lens names public figures in `related_content` (sometimes with a Knowledge Graph id).
Wikidata holds their verified handles (P2002 X, P2003 Instagram, P2013 Facebook, P7085 TikTok,
P2397 YouTube). Those handles feed Path B (real posts from the person's own account) and the
corroboration rule (a winner authored by the resolved handle is corroborated).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .. import http
from ..cache import Cache
from .base import Hint

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
SPARQL_URL = "https://query.wikidata.org/sparql"
HANDLE_PROPS = {"x": "P2002", "instagram": "P2003", "facebook": "P2013", "tiktok": "P7085"}
YOUTUBE_PROP = "P2397"
KG_PROP = "P2671"


@dataclass(frozen=True)
class Handles:
    x: str | None = None
    instagram: str | None = None
    facebook: str | None = None
    tiktok: str | None = None
    youtube: str | None = None


@dataclass(frozen=True)
class Identity:
    qid: str
    label: str
    human: bool
    handles: Handles

    def author_tags(self) -> dict[str, str]:
        """Platform -> "@handle" for every platform with a verified handle."""
        return {
            platform: f"@{handle}"
            for platform, handle in (
                ("x", self.handles.x),
                ("instagram", self.handles.instagram),
                ("facebook", self.handles.facebook),
                ("tiktok", self.handles.tiktok),
            )
            if handle
        }


def _sparql(query: str, cache: Cache) -> dict[str, Any]:
    def fetch() -> dict[str, Any]:
        resp = http.get(
            SPARQL_URL,
            params={"query": query, "format": "json"},
            headers={"Accept": "application/sparql-results+json"},
            timeout=40,
        )
        return resp.json() if resp.status_code == 200 else {}

    return cache.cached_json("wikidata.sparql", {"query": query}, fetch) or {}


def handles_query(qids: Sequence[str]) -> str:
    values = " ".join(f"wd:{q}" for q in qids)
    return (
        "SELECT ?item ?itemLabel ?human ?x ?ig ?fb ?tt ?yt WHERE { "
        f"VALUES ?item {{ {values} }} "
        "BIND(EXISTS { ?item wdt:P31 wd:Q5 } AS ?human) "
        f"OPTIONAL {{ ?item wdt:{HANDLE_PROPS['x']} ?x }} "
        f"OPTIONAL {{ ?item wdt:{HANDLE_PROPS['instagram']} ?ig }} "
        f"OPTIONAL {{ ?item wdt:{HANDLE_PROPS['facebook']} ?fb }} "
        f"OPTIONAL {{ ?item wdt:{HANDLE_PROPS['tiktok']} ?tt }} "
        f"OPTIONAL {{ ?item wdt:{YOUTUBE_PROP} ?yt }} "
        'SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } }'
    )


def kgmid_query(kgmid: str) -> str:
    safe = kgmid.replace('"', "")
    return f'SELECT ?item WHERE {{ ?item wdt:{KG_PROP} "{safe}" }} LIMIT 1'


def parse_handles(data: dict[str, Any]) -> dict[str, Identity]:
    """SPARQL bindings -> Identity per QID (first binding per item wins for each field)."""
    out: dict[str, Identity] = {}
    for row in data.get("results", {}).get("bindings", []):
        qid = row.get("item", {}).get("value", "").rsplit("/", 1)[-1]
        if not qid:
            continue

        def val(key: str, row: dict[str, Any] = row) -> str | None:
            value = row.get(key, {}).get("value")
            return str(value) if value not in (None, "") else None

        previous = out.get(qid)
        handles = Handles(
            x=val("x") or (previous.handles.x if previous else None),
            instagram=val("ig") or (previous.handles.instagram if previous else None),
            facebook=val("fb") or (previous.handles.facebook if previous else None),
            tiktok=val("tt") or (previous.handles.tiktok if previous else None),
            youtube=val("yt") or (previous.handles.youtube if previous else None),
        )
        out[qid] = Identity(
            qid=qid,
            label=val("itemLabel") or (previous.label if previous else qid),
            human=(val("human") or "false").lower() == "true",
            handles=handles,
        )
    return out


def pick_human_entity(qids: Sequence[str], humans: dict[str, bool]) -> str | None:
    return next((q for q in qids if humans.get(q)), None)


def _norm(text: str) -> str:
    return " ".join(text.lower().replace(".", " ").split())


def name_matches(query: str, label: str) -> bool:
    """A hint names this entity if the label equals it or contains every word of it."""
    q, lbl = _norm(query), _norm(label)
    if not q or not lbl:
        return False
    return q == lbl or set(q.split()) <= set(lbl.split())


def search_entities(query: str, cache: Cache, *, limit: int = 5) -> list[tuple[str, str]]:
    def fetch() -> dict[str, Any]:
        resp = http.get(
            WIKIDATA_API,
            params={
                "action": "wbsearchentities",
                "search": query,
                "language": "en",
                "format": "json",
                "limit": str(limit),
            },
            timeout=20,
        )
        return resp.json() if resp.status_code == 200 else {}

    data = cache.cached_json("wikidata.search", {"search": query, "limit": limit}, fetch) or {}
    return [
        (str(e["id"]), str(e.get("label") or "")) for e in data.get("search", []) if e.get("id")
    ]


def resolve_by_kgmid(kgmid: str, cache: Cache) -> Identity | None:
    rows = _sparql(kgmid_query(kgmid), cache).get("results", {}).get("bindings", [])
    if not rows:
        return None
    qid = rows[0].get("item", {}).get("value", "").rsplit("/", 1)[-1]
    ident = parse_handles(_sparql(handles_query([qid]), cache)).get(qid)
    return ident if ident and ident.human else None


def resolve_by_name(name: str, cache: Cache) -> Identity | None:
    """Humans whose Wikidata label matches the hint; generic hints ("cricketer") resolve to None."""
    found = [
        (qid, label) for qid, label in search_entities(name, cache) if name_matches(name, label)
    ]
    if not found:
        return None
    qids = [qid for qid, _ in found]
    idents = parse_handles(_sparql(handles_query(qids), cache))
    qid = pick_human_entity(qids, {q: i.human for q, i in idents.items()})
    if not qid:
        return None
    ident = idents[qid]
    label = dict(found)[qid]
    return (
        ident
        if ident.label != qid or not label
        else Identity(qid, label, ident.human, ident.handles)
    )


def resolve(
    hints: Sequence[Hint], cache: Cache, *, fallback_name: str | None = None
) -> Identity | None:
    """Knowledge Graph id first (unambiguous), then the hint text, then a caller-provided name."""
    for hint in hints:
        if hint.kgmid:
            ident = resolve_by_kgmid(hint.kgmid, cache)
            if ident:
                return ident
    for name in [h.query for h in hints if h.query] + ([fallback_name] if fallback_name else []):
        ident = resolve_by_name(name, cache)
        if ident:
            return ident
    return None
