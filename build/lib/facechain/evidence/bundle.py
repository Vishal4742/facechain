"""Evidence bundle: canonical JSON, hashing rules, on-disk layout, local verification, tamper copy.

Rules (see CLAUDE.md): sorted keys, compact separators, UTF-8, no trailing newline; ints and
strings only (similarity in basis points, never floats); no git commit inside the hashed object.
`bundle.json` on disk is exactly the canonical bytes, so `sha256sum bundle.json` equals H.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..cache import canonical_json
from ..search.base import Candidate

DETECTOR = "scrfd_10g"
EMBEDDER = "arcface_r50_buffalo_l"
MEDIA_SUFFIXES = ((b"\xff\xd8", ".jpg"), (b"\x89PNG", ".png"), (b"RIFF", ".webp"), (b"GIF8", ".gif"))


def new_run_id(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{secrets.token_hex(2)}"


def canonical_bytes(obj: Any) -> bytes:
    return canonical_json(obj).encode("utf-8")


def bundle_hash(obj: Any) -> str:
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def assert_hashable(obj: Any, path: str = "$") -> None:
    """Only None, bool, int, str, list and str-keyed dict may enter the hashed bundle."""
    if obj is None or isinstance(obj, bool | int | str):
        return
    if isinstance(obj, float):
        raise ValueError(f"float at {path}: store integers (e.g. basis points) instead")
    if isinstance(obj, list):
        for i, item in enumerate(obj):
            assert_hashable(item, f"{path}[{i}]")
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            if not isinstance(key, str):
                raise ValueError(f"non-string key at {path}: {key!r}")
            assert_hashable(value, f"{path}.{key}")
        return
    raise ValueError(f"unsupported type {type(obj).__name__} at {path}")


def media_suffix(data: bytes) -> str:
    for magic, suffix in MEDIA_SUFFIXES:
        if data.startswith(magic):
            return suffix
    return ".bin"


def build_bundle(
    *,
    face_id: str,
    winner: Candidate,
    threshold_bps: int,
    candidates_considered: int,
    found_at: int,
    engines: Sequence[str],
    media_cid: str | None = None,
    detector: str = DETECTOR,
    embedder: str = EMBEDDER,
) -> dict[str, Any]:
    media_sha = winner.media_sha256 or (
        hashlib.sha256(winner.media_bytes).hexdigest() if winner.media_bytes else None
    )
    text_sha = hashlib.sha256(winner.text.encode("utf-8")).hexdigest() if winner.text else None
    bundle = {
        "version": 1,
        "query": {"face_id": face_id, "detector": detector, "embedder": embedder},
        "post": {
            "url": winner.url,
            "platform": winner.platform,
            "author": winner.author,
            "title": winner.title,
            "text": winner.text,
            "media_url": winner.media_url,
            "media_sha256": media_sha,
            "media_cid": media_cid,
            "text_sha256": text_sha,
            "fetched_at": int(found_at),
        },
        "match": {
            "engine": winner.engine,
            "similarity_bps": int(winner.similarity_bps or 0),
            "threshold_bps": int(threshold_bps),
            "candidates_considered": int(candidates_considered),
            "corroborated_by": list(winner.corroborated_by),
            "engines": list(engines),
        },
    }
    assert_hashable(bundle)
    return bundle


def write_evidence(
    run_dir: Path,
    *,
    query_bytes: bytes,
    query_suffix: str,
    candidates: Sequence[Candidate],
    winner: Candidate | None,
    bundle: dict[str, Any] | None,
) -> dict[str, Path]:
    """Write the run directory; bundle.json is the exact canonical bytes that were hashed."""
    run_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    paths["query"] = run_dir / f"query{query_suffix or '.bin'}"
    paths["query"].write_bytes(query_bytes)
    paths["candidates"] = run_dir / "candidates.json"
    paths["candidates"].write_text(
        json.dumps([c.to_dict() for c in candidates], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if winner is not None:
        if winner.media_bytes:
            paths["post_media"] = run_dir / f"post_media{media_suffix(winner.media_bytes)}"
            paths["post_media"].write_bytes(winner.media_bytes)
        paths["post"] = run_dir / "post.json"
        paths["post"].write_text(
            json.dumps({**winner.to_dict(), "raw": winner.raw}, indent=2, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
    if bundle is not None:
        paths["bundle"] = run_dir / "bundle.json"
        paths["bundle"].write_bytes(canonical_bytes(bundle))
    return paths


def load_bundle(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def find_media(run_dir: Path) -> Path | None:
    matches = sorted(run_dir.glob("post_media.*"))
    return matches[0] if matches else None


@dataclass(frozen=True)
class LocalResult:
    run_dir: Path
    bundle_hash: str  # sha256 of bundle.json bytes exactly as stored
    canonical_ok: bool  # stored bytes == canonical re-serialisation
    media_ok: bool  # sha256(post_media.*) == bundle.post.media_sha256
    media_sha256: str | None
    expected_media_sha256: str | None
    detail: str

    @property
    def ok(self) -> bool:
        return self.canonical_ok and self.media_ok


def verify_local(run_dir: Path) -> LocalResult:
    """Re-hash what is on disk; never re-download anything."""
    raw = (run_dir / "bundle.json").read_bytes()
    stored_hash = hashlib.sha256(raw).hexdigest()
    bundle = json.loads(raw.decode("utf-8"))
    canonical_ok = raw == canonical_bytes(bundle)
    expected = bundle.get("post", {}).get("media_sha256")
    media_path = find_media(run_dir)
    actual = hashlib.sha256(media_path.read_bytes()).hexdigest() if media_path else None
    media_ok = expected is not None and actual == expected
    notes: list[str] = []
    if not canonical_ok:
        notes.append("bundle.json is not in canonical form")
    if media_path is None:
        notes.append("post_media.* missing")
    elif not media_ok:
        notes.append(f"media sha256 mismatch: file {actual} != bundle {expected}")
    return LocalResult(
        run_dir=run_dir,
        bundle_hash=stored_hash,
        canonical_ok=canonical_ok,
        media_ok=media_ok,
        media_sha256=actual,
        expected_media_sha256=expected,
        detail="; ".join(notes) or "local evidence consistent",
    )


def tamper_copy(run_dir: Path) -> Path:
    """Copy the run and flip one byte in the middle of the post media."""
    target = run_dir.with_name(run_dir.name + "_tampered")
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(run_dir, target)
    media_path = find_media(target)
    if media_path is None:
        raise FileNotFoundError(f"no post_media.* in {run_dir}")
    data = bytearray(media_path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    media_path.write_bytes(bytes(data))
    return target
