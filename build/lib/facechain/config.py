"""Settings: `.env` in the working directory, overridden by real environment variables.

The Solana keypair path is deliberately explicit. The Solana CLI config on this machine points at
a stale relative path from another project, so facechain never reads that config.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

DEFAULT_RPC = "https://api.devnet.solana.com"
DEFAULT_KEYPAIR = Path.home() / ".config/solana/id.json"


@dataclass(frozen=True)
class Settings:
    serpapi_key: str | None
    pinata_jwt: str | None
    pinata_gateway: str
    solana_rpc_url: str
    solana_keypair_path: Path
    cache_dir: Path
    evidence_dir: Path
    match_threshold: float
    review_threshold: float
    sas_credential: str | None
    sas_schema: str | None
    offline: bool


def _merged_env(env_file: Path | None) -> dict[str, str]:
    path = env_file or (Path.cwd() / ".env")
    values: dict[str, str] = {}
    if path.exists():
        values.update({k: v for k, v in dotenv_values(path).items() if v is not None})
    values.update(os.environ)  # real environment wins
    return values


def _opt(values: dict[str, str], name: str) -> str | None:
    value = values.get(name, "").strip()
    return value or None


def _path(values: dict[str, str], name: str, default: str | Path) -> Path:
    raw = _opt(values, name)
    path = Path(os.path.expanduser(raw)) if raw else Path(default)
    return path if path.is_absolute() else (Path.cwd() / path)


def _float(values: dict[str, str], name: str, default: float) -> float:
    raw = _opt(values, name)
    return float(raw) if raw else default


def _bool(values: dict[str, str], name: str) -> bool:
    return (_opt(values, name) or "").lower() in {"1", "true", "yes", "on"}


def load(env_file: Path | None = None) -> Settings:
    values = _merged_env(env_file)
    return Settings(
        serpapi_key=_opt(values, "SERPAPI_KEY"),
        pinata_jwt=_opt(values, "PINATA_JWT"),
        pinata_gateway=_opt(values, "PINATA_GATEWAY") or "gateway.pinata.cloud",
        solana_rpc_url=_opt(values, "SOLANA_RPC_URL") or DEFAULT_RPC,
        solana_keypair_path=_path(values, "SOLANA_KEYPAIR_PATH", DEFAULT_KEYPAIR),
        cache_dir=_path(values, "FACECHAIN_CACHE_DIR", Path.home() / ".cache/facechain"),
        evidence_dir=_path(values, "FACECHAIN_EVIDENCE_DIR", "evidence"),
        match_threshold=_float(values, "MATCH_THRESHOLD", 0.45),
        review_threshold=_float(values, "REVIEW_THRESHOLD", 0.35),
        sas_credential=_opt(values, "SAS_CREDENTIAL"),
        sas_schema=_opt(values, "SAS_SCHEMA"),
        offline=_bool(values, "FACECHAIN_OFFLINE"),
    )
