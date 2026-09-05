"""IPFS pinning through Pinata, so the evidence bundle is retrievable by CID by anyone.

Pinning is best-effort: a failure returns None and the pipeline continues with `cid=-` in the
memo. Verification never depends on the CID; it only adds a third-party retrieval route.
"""

from __future__ import annotations

from pathlib import Path

from .. import http
from ..cache import Cache, CacheMiss

PINATA_UPLOAD = "https://uploads.pinata.cloud/v3/files"
PINATA_AUTH_TEST = "https://api.pinata.cloud/data/testAuthentication"
PUBLIC_GATEWAYS = ("https://ipfs.io/ipfs/{cid}", "https://dweb.link/ipfs/{cid}")


def test_auth(jwt: str) -> bool:
    try:
        resp = http.get(PINATA_AUTH_TEST, headers={"Authorization": f"Bearer {jwt}"}, timeout=15)
    except http.HttpError:
        return False
    return resp.status_code == 200


def pin_bytes(
    data: bytes,
    *,
    jwt: str,
    name: str,
    content_type: str = "application/octet-stream",
    timeout: float = 30,
) -> str | None:
    """Upload one file to Pinata's public IPFS network; returns the CID or None."""
    try:
        resp = http.post(
            PINATA_UPLOAD,
            files={"file": (name, data, content_type)},
            data={"network": "public", "name": name},
            headers={"Authorization": f"Bearer {jwt}"},
            timeout=timeout,
            retries=2,
        )
    except http.HttpError:
        return None
    if resp.status_code not in (200, 201):
        return None
    try:
        cid = resp.json().get("data", {}).get("cid")
    except ValueError:
        return None
    return str(cid) if cid else None


def pin_file(
    path: Path, *, jwt: str, name: str | None = None, content_type: str | None = None
) -> str | None:
    ctype = content_type or (
        "application/json" if path.suffix == ".json" else "application/octet-stream"
    )
    return pin_bytes(path.read_bytes(), jwt=jwt, name=name or path.name, content_type=ctype)


def gateway_urls(cid: str, gateway: str | None) -> list[str]:
    urls = [f"https://{gateway}/ipfs/{cid}"] if gateway else []
    urls.extend(g.format(cid=cid) for g in PUBLIC_GATEWAYS)
    return urls


def fetch(
    cid: str, *, cache: Cache, gateway: str | None, max_bytes: int = 20 * 1024 * 1024
) -> bytes | None:
    """Content by CID via the account gateway first, then public gateways; cached by URL."""
    for url in gateway_urls(cid, gateway):
        try:
            data = cache.cached_bytes(
                "http.get",
                {"url": url},
                lambda url=url: http.download_bytes(
                    url, max_bytes=max_bytes, timeout=20, accept_prefix=""
                ),
            )
        except CacheMiss:
            continue
        if data:
            return data
    return None
