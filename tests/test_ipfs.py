"""Specs for facechain.chain.ipfs with the HTTP layer faked (no network)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from facechain.cache import Cache
from facechain.chain import ipfs


class _Resp:
    def __init__(self, status: int, payload: Any) -> None:
        self.status_code = status
        self._payload = payload

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def test_pin_bytes_returns_cid_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> _Resp:
        seen.update(url=url, **kwargs)
        return _Resp(200, {"data": {"cid": "bafybeigdyrzt5", "name": "bundle.json"}})

    monkeypatch.setattr(ipfs.http, "post", fake_post)
    cid = ipfs.pin_bytes(b"{}", jwt="secret", name="bundle.json", content_type="application/json")
    assert cid == "bafybeigdyrzt5"
    assert seen["url"] == ipfs.PINATA_UPLOAD
    assert seen["headers"]["Authorization"] == "Bearer secret"
    assert seen["data"]["network"] == "public"
    assert seen["files"]["file"][0] == "bundle.json"


@pytest.mark.parametrize(
    "status,payload", [(401, {"error": "bad jwt"}), (500, ValueError("no json"))]
)
def test_pin_bytes_returns_none_on_failure(
    monkeypatch: pytest.MonkeyPatch, status: int, payload: Any
) -> None:
    monkeypatch.setattr(ipfs.http, "post", lambda url, **kw: _Resp(status, payload))
    assert ipfs.pin_bytes(b"x", jwt="j", name="n") is None


def test_pin_bytes_swallows_transport_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str, **kwargs: Any) -> _Resp:
        raise ipfs.http.HttpError("POST failed")

    monkeypatch.setattr(ipfs.http, "post", boom)
    assert ipfs.pin_bytes(b"x", jwt="j", name="n") is None


def test_fetch_tries_account_gateway_then_public_and_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def fake_download(url: str, **kwargs: Any) -> bytes | None:
        calls.append(url)
        return b"payload" if "ipfs.io" in url else None

    monkeypatch.setattr(ipfs.http, "download_bytes", fake_download)
    cache = Cache(tmp_path)
    assert ipfs.fetch("bafy1", cache=cache, gateway="gateway.pinata.cloud") == b"payload"
    assert calls == ["https://gateway.pinata.cloud/ipfs/bafy1", "https://ipfs.io/ipfs/bafy1"]
    calls.clear()
    assert ipfs.fetch("bafy1", cache=cache, gateway="gateway.pinata.cloud") == b"payload"
    assert calls == ["https://gateway.pinata.cloud/ipfs/bafy1"]  # ipfs.io answer came from cache
