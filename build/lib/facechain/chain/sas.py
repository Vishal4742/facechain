"""Solana Attestation Service (SAS) records through the `chain-ts/sas.ts` sidecar.

One-time setup creates a Credential "FACECHAIN" (authority = registry wallet) and a Schema
"FaceMatchV1" v1 `{bundle_hash: String, cid: String, post_url: String, similarity_bps: U64}`.
Every anchored run then gets one attestation whose nonce is the bundle hash itself, so the
attestation PDA `["attestation", credential, schema, nonce]` is derivable from the bundle alone.

The sidecar speaks JSON on stdin/stdout; Python never encodes SAS instructions. The SPL memo is a
separate transaction (see `memo.py`) and is unchanged by any of this.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import Settings
from ..evidence.bundle import LocalResult
from ..evidence.bundle import bundle_hash as hash_bundle
from ..http import redact
from .memo import explorer_url

ROOT = Path(__file__).resolve().parents[2]
SIDECAR = ROOT / "chain-ts" / "sas.ts"  # editable/checkout install


def sidecar_path() -> Path:
    """Where `sas.ts` lives: FACECHAIN_SIDECAR, else next to the package (editable install),
    else `chain-ts/sas.ts` under the current directory (regular install run from a checkout)."""
    override = os.environ.get("FACECHAIN_SIDECAR", "").strip()
    if override:
        return Path(os.path.expanduser(override))
    if SIDECAR.exists():
        return SIDECAR
    local = Path.cwd() / "chain-ts" / "sas.ts"
    return local if local.exists() else SIDECAR


SAS_PROGRAM_ID = "22zoJMtdu4tQc2PzL74ZUT7FrwgB1Udec8DdW4yw4BdG"
CREDENTIAL_NAME = "FACECHAIN"
SCHEMA_NAME = "FaceMatchV1"
SCHEMA_VERSION = 1
SCHEMA_FIELDS = ("bundle_hash", "cid", "post_url", "similarity_bps")
ENV_KEYS = ("SAS_CREDENTIAL", "SAS_SCHEMA")


class SasError(RuntimeError):
    """The sidecar failed, is unavailable, or SAS is not configured."""


# -- sidecar ----------------------------------------------------------------------------
def _parse_json(text: str) -> dict[str, Any]:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return {}
    try:
        data = json.loads(lines[-1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _tail(text: str, n: int = 3) -> str:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    return " | ".join(lines[-n:])


def call_sidecar(cmd: dict[str, Any], timeout: float = 120) -> dict[str, Any]:
    """Run `node chain-ts/sas.ts` with one JSON command; return its JSON result."""
    node = shutil.which("node")
    if node is None:
        raise SasError("node not found on PATH; Node >= 22.6 is required for chain-ts/sas.ts")
    sidecar = sidecar_path()
    if not sidecar.exists():
        raise SasError(
            f"sidecar missing: {sidecar} (run from a checkout with `npm ci` done in chain-ts/, "
            "or set FACECHAIN_SIDECAR)"
        )
    name = str(cmd.get("cmd"))
    try:
        proc = subprocess.run(
            [node, str(sidecar)],
            input=json.dumps(cmd),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=ROOT,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SasError(f"sidecar {name} timed out after {timeout:.0f}s") from exc
    payload = _parse_json(proc.stdout)
    if proc.returncode != 0 or "error" in payload:
        detail = str(payload.get("error") or _tail(proc.stderr) or f"exit code {proc.returncode}")
        if "ERR_MODULE_NOT_FOUND" in detail or "Cannot find package" in detail:
            detail += " (run `npm ci` inside chain-ts/)"
        raise SasError(redact(f"sidecar {name} failed: {detail}"))
    return payload


# -- configuration ----------------------------------------------------------------------
def sas_configured(settings: Settings) -> bool:
    return bool(settings.sas_credential and settings.sas_schema)


def require_sas(settings: Settings) -> tuple[str, str]:
    if not sas_configured(settings):
        raise SasError("SAS_CREDENTIAL / SAS_SCHEMA not set; run `facechain setup-sas` first")
    return str(settings.sas_credential), str(settings.sas_schema)


def write_env_keys(path: Path, values: dict[str, str]) -> list[str]:
    """Fill empty or missing KEY= lines in `.env`; never rewrite other keys or set values.

    A missing `.env` starts as a copy of `.env.example`. Returns the keys that were written.
    """
    if path.exists():
        text = path.read_text(encoding="utf-8")
    else:
        example = next(
            (p for p in (path.with_name(".env.example"), ROOT / ".env.example") if p.exists()),
            None,
        )
        text = example.read_text(encoding="utf-8") if example else ""
    lines = text.splitlines()
    written: list[str] = []
    for key, value in values.items():
        index = next(
            (i for i, line in enumerate(lines) if line.split("=", 1)[0].strip() == key), None
        )
        if index is None:
            lines.append(f"{key}={value}")
        elif lines[index].split("=", 1)[1].strip():
            continue  # already set by hand: keep it
        else:
            lines[index] = f"{key}={value}"
        written.append(key)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return written


def setup_sas(settings: Settings, env_path: Path | None = None) -> dict[str, Any]:
    """Create (or find) the credential and schema; record their addresses in `.env`."""
    result = call_sidecar(
        {
            "cmd": "setup",
            "keypair": str(settings.solana_keypair_path),
            "rpc": settings.solana_rpc_url,
        }
    )
    path = env_path or (Path.cwd() / ".env")
    written = write_env_keys(
        path, {"SAS_CREDENTIAL": str(result["credential"]), "SAS_SCHEMA": str(result["schema"])}
    )
    result["env"] = {"path": str(path), "written": written}
    return result


# -- records ----------------------------------------------------------------------------
def attestation_fields(bundle: dict[str, Any], cid: str | None) -> dict[str, Any]:
    """The four schema fields exactly as they are serialised on chain."""
    return {
        "bundle_hash": hash_bundle(bundle),
        "cid": cid or "",
        "post_url": str(bundle["post"]["url"]),
        "similarity_bps": int(bundle["match"]["similarity_bps"]),
    }


def attest(bundle: dict[str, Any], cid: str | None, settings: Settings) -> dict[str, Any]:
    """Create the attestation for this bundle (no-op if the PDA already exists)."""
    credential, schema = require_sas(settings)
    result = call_sidecar(
        {
            "cmd": "attest",
            "keypair": str(settings.solana_keypair_path),
            "rpc": settings.solana_rpc_url,
            "credential": credential,
            "schema": schema,
            **attestation_fields(bundle, cid),
            "expiry": 0,
        }
    )
    signature = result.get("signature")
    result["credential"] = credential
    result["schema"] = schema
    result["explorer"] = explorer_url(str(signature)) if signature else None
    return result


def fetch_attestation(bundle_hash: str, settings: Settings) -> dict[str, Any]:
    """Derive the PDA for this bundle hash and read the attestation (found: true/false)."""
    credential, schema = require_sas(settings)
    return call_sidecar(
        {
            "cmd": "fetch",
            "rpc": settings.solana_rpc_url,
            "credential": credential,
            "schema": schema,
            "bundle_hash": bundle_hash,
        }
    )


# -- verification -----------------------------------------------------------------------
@dataclass(frozen=True)
class SasCheck:
    found: bool
    hash_used: str
    recomputed: bool = False  # H recomputed from the media on disk (tampered evidence)
    attestation: str | None = None
    nonce: str | None = None
    signer: str | None = None
    signer_ok: bool = False
    fields_ok: bool = False
    mismatches: tuple[str, ...] = ()
    expiry: int = 0
    data: dict[str, Any] | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.found and self.signer_ok and self.fields_ok


def effective_hash(local: LocalResult, bundle: dict[str, Any]) -> tuple[str, bool]:
    """H for the evidence as it is on disk.

    The stored bundle's hash normally; when the media no longer matches the bundle, the hash the
    bundle would have if it described the media actually present. A tampered run therefore
    derives a PDA that nobody ever attested.
    """
    if local.media_ok or local.media_sha256 is None:
        return local.bundle_hash, False
    patched = {**bundle, "post": {**bundle["post"], "media_sha256": local.media_sha256}}
    return hash_bundle(patched), True


def compare_attestation(
    found: dict[str, Any],
    bundle: dict[str, Any],
    registry: str,
    expected_cid: str | None = None,
) -> tuple[bool, tuple[str, ...]]:
    """(signer == registry, field mismatches between the chain record and the bundle).

    The bundle cannot contain its own IPFS CID, so `cid` is only compared when the caller knows
    it (from the memo); `None` skips that field.
    """
    expected = attestation_fields(bundle, expected_cid)
    if expected_cid is None:
        expected.pop("cid")
    data = found.get("data") or {}
    mismatches = tuple(
        f"{key}: chain {data.get(key)!r} != bundle {value!r}"
        for key, value in expected.items()
        if data.get(key) != value
    )
    return found.get("signer") == registry, mismatches


def check_attestation(
    local: LocalResult,
    bundle: dict[str, Any],
    *,
    registry: str,
    settings: Settings,
    expected_cid: str | None = None,
) -> SasCheck:
    """Derive the PDA from the evidence, fetch it and compare it with the bundle (+ memo cid)."""
    h, recomputed = effective_hash(local, bundle)
    try:
        found = fetch_attestation(h, settings)
    except SasError as exc:
        return SasCheck(found=False, hash_used=h, recomputed=recomputed, detail=str(exc))
    attestation = found.get("attestation")
    nonce = found.get("nonce")
    if not found.get("found"):
        detail = (
            "no attestation for the hash recomputed from the media on disk"
            if recomputed
            else "no attestation for this bundle hash"
        )
        return SasCheck(
            found=False,
            hash_used=h,
            recomputed=recomputed,
            attestation=attestation,
            nonce=nonce,
            detail=detail,
        )
    signer_ok, mismatches = compare_attestation(found, bundle, registry, expected_cid)
    return SasCheck(
        found=True,
        hash_used=h,
        recomputed=recomputed,
        attestation=attestation,
        nonce=nonce,
        signer=found.get("signer"),
        signer_ok=signer_ok,
        fields_ok=not mismatches,
        mismatches=mismatches,
        expiry=int(found.get("expiry") or 0),
        data=found.get("data"),
        detail="attestation found"
        + ("" if signer_ok else f"; UNEXPECTED signer {found.get('signer')}"),
    )
