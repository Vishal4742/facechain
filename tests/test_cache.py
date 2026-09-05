"""Specs for facechain.cache — written before the implementation (RED first)."""

from __future__ import annotations

from pathlib import Path

import pytest

from facechain.cache import STATS, Cache, CacheMiss, cache_key, canonical_json


def test_canonical_json_is_sorted_compact_and_utf8() -> None:
    assert canonical_json({"b": 1, "a": [1, 2], "c": "é"}) == '{"a":[1,2],"b":1,"c":"é"}'


def test_cache_key_is_stable_and_namespace_scoped() -> None:
    k1 = cache_key("serpapi.lens", {"image_sha256": "ab", "type": "visual_matches"})
    k2 = cache_key("serpapi.lens", {"type": "visual_matches", "image_sha256": "ab"})
    k3 = cache_key("serpapi.google", {"image_sha256": "ab", "type": "visual_matches"})
    assert k1 == k2
    assert k1 != k3
    assert len(k1) == 64


@pytest.mark.parametrize("bad", ["api_key", "token", "jwt", "image_id", "authorization"])
def test_cache_key_refuses_secret_or_volatile_params(bad: str) -> None:
    with pytest.raises(ValueError):
        cache_key("ns", {bad: "x"})


def test_json_roundtrip_and_stats(tmp_path: Path) -> None:
    STATS.reset()
    cache = Cache(tmp_path)
    params = {"q": "hello"}
    assert cache.get_json("ns", params) is None
    cache.put_json("ns", params, {"answer": 42}, meta={"url": "https://example"})
    assert cache.get_json("ns", params) == {"answer": 42}
    assert STATS.hits == 1 and STATS.misses == 1
    # meta sidecar exists and records fetched_at
    metas = list(tmp_path.rglob("*.meta.json"))
    assert len(metas) == 1
    assert '"fetched_at"' in metas[0].read_text()


def test_bytes_roundtrip(tmp_path: Path) -> None:
    cache = Cache(tmp_path)
    cache.put_bytes("http.get", {"url": "https://x/y.jpg"}, b"\xff\xd8data")
    assert cache.get_bytes("http.get", {"url": "https://x/y.jpg"}) == b"\xff\xd8data"


def test_cached_calls_fn_once_then_hits(tmp_path: Path) -> None:
    cache = Cache(tmp_path)
    calls: list[int] = []

    def fetch() -> dict[str, int]:
        calls.append(1)
        return {"n": len(calls)}

    assert cache.cached_json("ns", {"a": 1}, fetch) == {"n": 1}
    assert cache.cached_json("ns", {"a": 1}, fetch) == {"n": 1}
    assert len(calls) == 1


def test_offline_mode_raises_on_miss(tmp_path: Path) -> None:
    cache = Cache(tmp_path, offline=True)
    with pytest.raises(CacheMiss):
        cache.cached_json("ns", {"a": 1}, lambda: {"never": True})


def test_live_mode_bypasses_reads_but_still_writes(tmp_path: Path) -> None:
    cache = Cache(tmp_path)
    cache.put_json("ns", {"a": 1}, {"old": True})
    live = Cache(tmp_path, live=True)
    assert live.cached_json("ns", {"a": 1}, lambda: {"new": True}) == {"new": True}
    # the fresh value replaced the old one on disk
    assert Cache(tmp_path).get_json("ns", {"a": 1}) == {"new": True}


def test_touched_keys_are_recorded(tmp_path: Path) -> None:
    STATS.reset()
    cache = Cache(tmp_path)
    cache.put_json("ns", {"a": 1}, {"x": 1})
    cache.get_json("ns", {"a": 1})
    assert STATS.keys == [f"ns/{cache_key('ns', {'a': 1})}"]
