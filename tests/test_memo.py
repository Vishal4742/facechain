"""Specs for the pure parts of facechain.chain.memo — memo text format and parsing."""

from __future__ import annotations

from facechain.chain.memo import MEMO_MAX_BYTES, format_memo, memo_matches, parse_memo

H = "1" * 64
MEDIA = "2" * 64


def test_format_memo_layout() -> None:
    memo = format_memo(H, MEDIA, "bafybeigdyrzt5", 7123, "https://x.com/u/status/1")
    assert (
        memo
        == f"FACECHAIN/1 h={H} media={MEDIA} cid=bafybeigdyrzt5 sim=7123 url=https://x.com/u/status/1"
    )
    assert len(memo.encode()) <= MEMO_MAX_BYTES


def test_format_memo_without_cid_uses_dash_and_truncates_only_the_url() -> None:
    long_url = "https://www.instagram.com/p/" + "x" * 900
    memo = format_memo(H, MEDIA, None, 5000, long_url)
    assert len(memo.encode()) <= MEMO_MAX_BYTES
    assert " cid=- " in memo
    assert f"h={H}" in memo and f"media={MEDIA}" in memo and "sim=5000" in memo
    assert memo.split("url=")[1].startswith("https://www.instagram.com/p/xxx")


def test_parse_memo_roundtrip_and_signature_list_prefix() -> None:
    memo = format_memo(H, MEDIA, "bafy1", 4321, "https://x.com/u/status/1")
    parsed = parse_memo(memo)
    assert parsed == {
        "version": 1,
        "h": H,
        "media": MEDIA,
        "cid": "bafy1",
        "sim": 4321,
        "url": "https://x.com/u/status/1",
    }
    # getSignaturesForAddress reports memos as "[<len>] <text>"
    assert parse_memo(f"[{len(memo)}] {memo}") == parsed


def test_parse_memo_rejects_foreign_memos() -> None:
    assert parse_memo("hello world") is None
    assert parse_memo("FACECHAIN/1 h=short") is None
    assert parse_memo("") is None


def test_memo_matches_bundle_hash() -> None:
    memo = format_memo(H, MEDIA, None, 1, "https://x.com/u/status/1")
    assert memo_matches(f"[100] {memo}", H)
    assert not memo_matches(memo, "9" * 64)
