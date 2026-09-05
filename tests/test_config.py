"""Specs for facechain.config — written before the implementation (RED first)."""

from __future__ import annotations

from pathlib import Path

import pytest

from facechain.config import Settings, load


def test_defaults_when_nothing_is_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # no .env here
    s = load()
    assert isinstance(s, Settings)
    assert s.serpapi_key is None
    assert s.solana_rpc_url == "https://api.devnet.solana.com"
    assert s.solana_keypair_path == Path.home() / ".config/solana/id.json"
    assert s.match_threshold == 0.45
    assert s.review_threshold == 0.35
    assert s.offline is True  # conftest sets FACECHAIN_OFFLINE=1


def test_env_file_is_read_but_real_env_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("SERPAPI_KEY=from-file\nMATCH_THRESHOLD=0.5\n")
    monkeypatch.setenv("MATCH_THRESHOLD", "0.6")
    s = load()
    assert s.serpapi_key == "from-file"
    assert s.match_threshold == 0.6


def test_tilde_paths_expand_and_dirs_are_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FACECHAIN_CACHE_DIR", "~/somewhere/cache")
    s = load()
    assert s.cache_dir == Path.home() / "somewhere/cache"
    assert s.evidence_dir.is_absolute()


def test_settings_is_frozen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    s = load()
    with pytest.raises(AttributeError):
        s.serpapi_key = "x"  # type: ignore[misc]
