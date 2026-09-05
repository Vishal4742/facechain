"""Specs for facechain.evidence.bundle — canonical JSON, hashing, evidence files, tamper copy."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from facechain.evidence.bundle import (
    assert_hashable,
    build_bundle,
    bundle_hash,
    canonical_bytes,
    load_bundle,
    new_run_id,
    tamper_copy,
    verify_local,
    write_evidence,
)
from facechain.search.base import Candidate


def _winner() -> Candidate:
    cand = Candidate.from_url(
        "https://www.instagram.com/p/Cabc123/",
        engine="lens:visual",
        engine_rank=1,
        title="Virat Kohli on Instagram",
        media_url="https://scontent.cdninstagram.com/full1.jpg",
        raw={"source": "Instagram"},
    )
    media = b"\xff\xd8\xff\xe0fake-jpeg-bytes-for-tests\xff\xd9"
    scored = cand.with_similarity(0.7123, match_thr=0.45, review_thr=0.35, faces_found=1)
    return replace(
        scored,
        media_bytes=media,
        media_sha256=hashlib.sha256(media).hexdigest(),
        corroborated_by=("engine:identity:x",),
    )


def test_run_id_is_sortable_and_ntfs_safe() -> None:
    rid = new_run_id()
    assert re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{4}", rid), rid
    assert ":" not in rid


def test_canonical_bytes_are_sorted_compact_utf8_without_newline() -> None:
    assert (
        canonical_bytes({"b": 1, "a": "é", "c": [True, None]})
        == '{"a":"é","b":1,"c":[true,null]}'.encode()
    )


def test_bundle_hash_equals_sha256_of_canonical_bytes() -> None:
    obj = {"x": {"y": [1, 2, 3]}, "s": "hello"}
    assert bundle_hash(obj) == hashlib.sha256(canonical_bytes(obj)).hexdigest()


def test_assert_hashable_rejects_floats_and_exotic_types() -> None:
    assert_hashable({"a": 1, "b": "s", "c": None, "d": [True, {"e": 2}]})
    with pytest.raises(ValueError, match="float"):
        assert_hashable({"similarity": 0.71})
    with pytest.raises(ValueError):
        assert_hashable({"when": object()})


def test_build_bundle_schema_uses_ints_and_records_provenance() -> None:
    bundle = build_bundle(
        face_id="a" * 64,
        winner=_winner(),
        threshold_bps=4500,
        candidates_considered=37,
        found_at=1_757_000_000,
        engines=("lens",),
    )
    assert_hashable(bundle)  # would raise on a float
    assert bundle["version"] == 1
    assert bundle["query"]["face_id"] == "a" * 64
    assert bundle["query"]["embedder"] == "arcface_r50_buffalo_l"
    assert bundle["post"]["url"] == "https://www.instagram.com/p/Cabc123"
    assert bundle["post"]["platform"] == "instagram"
    assert (
        bundle["post"]["media_sha256"] == hashlib.sha256(_winner().media_bytes or b"").hexdigest()
    )
    assert bundle["post"]["media_cid"] is None
    assert bundle["post"]["text_sha256"] is None  # no text captured for Instagram
    assert bundle["match"] == {
        "engine": "lens:visual",
        "similarity_bps": 7123,
        "threshold_bps": 4500,
        "candidates_considered": 37,
        "corroborated_by": ["engine:identity:x"],
        "engines": ["lens"],
    }
    assert "git_commit" not in json.dumps(bundle)


def test_write_evidence_then_verify_local_and_tamper(tmp_path: Path) -> None:
    winner = _winner()
    bundle = build_bundle(
        face_id="b" * 64,
        winner=winner,
        threshold_bps=4500,
        candidates_considered=3,
        found_at=1_757_000_000,
        engines=("lens",),
    )
    run_dir = tmp_path / "20260905T101500Z-ab12"
    paths = write_evidence(
        run_dir,
        query_bytes=b"query-image-bytes",
        query_suffix=".jpg",
        candidates=[winner],
        winner=winner,
        bundle=bundle,
    )
    assert (run_dir / "bundle.json").read_bytes() == canonical_bytes(bundle)  # sha256sum-compatible
    assert (run_dir / "post_media.jpg").read_bytes() == winner.media_bytes
    assert json.loads((run_dir / "candidates.json").read_text())[0]["url"] == winner.url
    assert json.loads((run_dir / "post.json").read_text())["title"] == "Virat Kohli on Instagram"
    assert paths["bundle"] == run_dir / "bundle.json"
    assert load_bundle(run_dir / "bundle.json") == bundle

    ok = verify_local(run_dir)
    assert ok.media_ok and ok.bundle_hash == bundle_hash(bundle)

    tampered = tamper_copy(run_dir)
    assert tampered.name.endswith("_tampered")
    bad = verify_local(tampered)
    assert bad.media_ok is False
    assert bad.bundle_hash == ok.bundle_hash  # bundle.json untouched, media no longer matches it
    assert "media sha256 mismatch" in bad.detail
