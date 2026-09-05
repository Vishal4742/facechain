"""Content-addressed disk cache for every network response facechain touches.

Why: SerpApi quota is finite, thumbnails are re-downloaded on every dev iteration, and the
recording must be able to prove which calls were live. Keys are sha256(namespace + canonical
params). Params must never contain secrets or volatile values (api keys, upload ids): the key
function refuses them so a leak cannot happen by accident.

Modes:
- normal:  read-through; misses call the fetch function and store the result
- offline: misses raise CacheMiss instead of touching the network (tests, --offline)
- live:    reads are bypassed, results are still written (--live on camera)
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FORBIDDEN_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "token",
    "jwt",
    "secret",
    "password",
    "authorization",
)
FORBIDDEN_KEYS = {"key", "image_id", "cookie", "session"}


class CacheMiss(RuntimeError):
    """Raised in offline mode when a value is not cached."""


@dataclass
class Stats:
    hits: int = 0
    misses: int = 0
    serpapi_searches: int = 0
    keys: list[str] = field(default_factory=list)

    def reset(self) -> None:
        self.hits = 0
        self.misses = 0
        self.serpapi_searches = 0
        self.keys.clear()

    def touch(self, namespace: str, key: str) -> None:
        tag = f"{namespace}/{key}"
        if tag not in self.keys:
            self.keys.append(tag)

    def summary(self) -> str:
        return (
            f"cache: {self.hits} hits, {self.misses} misses, "
            f"SerpApi searches: {self.serpapi_searches}"
        )


STATS = Stats()


def canonical_json(obj: Any) -> str:
    """Sorted keys, no whitespace, UTF-8 preserved, no NaN. Shared with evidence hashing."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _check_params(params: Mapping[str, Any]) -> None:
    for name, value in params.items():
        lowered = str(name).lower()
        if lowered in FORBIDDEN_KEYS or any(frag in lowered for frag in FORBIDDEN_KEY_FRAGMENTS):
            raise ValueError(f"cache params must not contain secret or volatile key {name!r}")
        if isinstance(value, Mapping):
            _check_params(value)


def cache_key(namespace: str, params: Mapping[str, Any]) -> str:
    _check_params(params)
    raw = namespace + "\n" + canonical_json(dict(params))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


class Cache:
    def __init__(self, root: Path | str, *, offline: bool = False, live: bool = False) -> None:
        self.root = Path(os.path.expanduser(str(root)))
        self.offline = offline
        self.live = live

    # -- paths -------------------------------------------------------------------------
    def _base(self, namespace: str, key: str) -> Path:
        return self.root / namespace / key[:2] / key

    def _meta_path(self, namespace: str, key: str) -> Path:
        base = self._base(namespace, key)
        return base.with_name(base.name + ".meta.json")

    def _write_meta(
        self, namespace: str, key: str, params: Mapping[str, Any], meta: Mapping[str, Any] | None
    ) -> None:
        record = {
            **(dict(meta) if meta else {}),
            "namespace": namespace,
            "params": dict(params),
            "fetched_at": int(time.time()),
        }
        _atomic_write(self._meta_path(namespace, key), canonical_json(record).encode("utf-8"))

    def _read(self, namespace: str, params: Mapping[str, Any], suffix: str) -> bytes | None:
        key = cache_key(namespace, params)
        STATS.touch(namespace, key)
        if self.live:
            STATS.misses += 1
            return None
        base = self._base(namespace, key)
        path = base.with_name(base.name + suffix)
        if path.exists():
            STATS.hits += 1
            return path.read_bytes()
        STATS.misses += 1
        return None

    def _write(
        self,
        namespace: str,
        params: Mapping[str, Any],
        suffix: str,
        data: bytes,
        meta: Mapping[str, Any] | None,
    ) -> None:
        key = cache_key(namespace, params)
        STATS.touch(namespace, key)
        base = self._base(namespace, key)
        _atomic_write(base.with_name(base.name + suffix), data)
        self._write_meta(namespace, key, params, meta)

    # -- JSON --------------------------------------------------------------------------
    def get_json(self, namespace: str, params: Mapping[str, Any]) -> Any | None:
        raw = self._read(namespace, params, ".json")
        return None if raw is None else json.loads(raw.decode("utf-8"))

    def put_json(
        self,
        namespace: str,
        params: Mapping[str, Any],
        data: Any,
        meta: Mapping[str, Any] | None = None,
    ) -> None:
        self._write(namespace, params, ".json", canonical_json(data).encode("utf-8"), meta)

    def cached_json(
        self,
        namespace: str,
        params: Mapping[str, Any],
        fetch: Callable[[], Any],
        meta: Mapping[str, Any] | None = None,
    ) -> Any:
        value = self.get_json(namespace, params)
        if value is not None:
            return value
        if self.offline:
            raise CacheMiss(f"{namespace} {canonical_json(dict(params))}")
        value = fetch()
        self.put_json(namespace, params, value, meta)
        return value

    # -- bytes -------------------------------------------------------------------------
    def get_bytes(self, namespace: str, params: Mapping[str, Any]) -> bytes | None:
        return self._read(namespace, params, ".bin")

    def put_bytes(
        self,
        namespace: str,
        params: Mapping[str, Any],
        data: bytes,
        meta: Mapping[str, Any] | None = None,
    ) -> None:
        self._write(namespace, params, ".bin", data, meta)

    def cached_bytes(
        self,
        namespace: str,
        params: Mapping[str, Any],
        fetch: Callable[[], bytes | None],
        meta: Mapping[str, Any] | None = None,
    ) -> bytes | None:
        value = self.get_bytes(namespace, params)
        if value is not None:
            return value
        if self.offline:
            raise CacheMiss(f"{namespace} {canonical_json(dict(params))}")
        value = fetch()
        if value is not None:
            self.put_bytes(namespace, params, value, meta)
        return value
