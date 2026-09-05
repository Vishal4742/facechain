"""Shared test setup: no network, isolated cache and evidence dirs."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FACECHAIN_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("FACECHAIN_EVIDENCE_DIR", str(tmp_path / "evidence"))
    monkeypatch.setenv("FACECHAIN_OFFLINE", "1")
    # never let a developer's real keys leak into tests
    for name in ("SERPAPI_KEY", "PINATA_JWT", "SAS_CREDENTIAL", "SAS_SCHEMA"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any real HTTP call inside a unit test is a bug."""
    import requests

    def _blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access is blocked in unit tests")

    monkeypatch.setattr(requests.Session, "request", _blocked)


def model_available() -> bool:
    return (Path.home() / ".insightface/models/buffalo_l/det_10g.onnx").exists()


requires_model = pytest.mark.skipif(
    not model_available() or os.environ.get("FACECHAIN_SKIP_MODEL") == "1",
    reason="InsightFace buffalo_l model pack not present",
)
