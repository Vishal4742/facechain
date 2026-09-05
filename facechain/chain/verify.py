"""Re-verification: recompute hashes from stored evidence and compare with the on-chain memo."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.table import Table

from ..config import Settings
from ..evidence.bundle import LocalResult, load_bundle, verify_local
from .memo import MemoHit, explorer_url, find_memo, parse_memo, tx_memo
from .sas import SasCheck, check_attestation, sas_configured


@dataclass(frozen=True)
class ChainResult:
    found: bool
    signature: str | None = None
    slot: int | None = None
    block_time: int | None = None
    signer: str | None = None
    signer_ok: bool = False
    memo: str | None = None
    memo_fields: dict[str, Any] | None = None
    detail: str = ""


@dataclass(frozen=True)
class Report:
    local: LocalResult
    chain: ChainResult
    registry: str
    verdict: str  # VERIFIED | TAMPERED | UNANCHORED
    sas: SasCheck | None = None  # None when SAS_CREDENTIAL / SAS_SCHEMA are not configured

    @property
    def ok(self) -> bool:
        return self.verdict == "VERIFIED"


def read_receipt(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / "receipt.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


async def verify_chain(
    h: str, *, registry: str, rpc_url: str, signature_hint: str | None = None
) -> ChainResult:
    hit = await find_memo(registry, h, rpc_url=rpc_url)
    route = "wallet scan"
    if hit is None and signature_hint:
        info = await tx_memo(signature_hint, rpc_url=rpc_url)
        hinted = parse_memo(info.memo or "")
        if info.memo and hinted is not None and hinted["h"] == h:
            hit = MemoHit(signature_hint, info.slot, info.block_time, info.memo)
            route = "receipt signature"
    if hit is None:
        return ChainResult(found=False, detail=f"no memo with h={h[:16]}... signed by {registry}")
    info = await tx_memo(hit.signature, rpc_url=rpc_url)
    fields = parse_memo(info.memo or hit.memo)
    signer_ok = info.signer == registry
    return ChainResult(
        found=True,
        signature=hit.signature,
        slot=info.slot or hit.slot,
        block_time=info.block_time or hit.block_time,
        signer=info.signer,
        signer_ok=signer_ok,
        memo=info.memo or hit.memo,
        memo_fields=fields,
        detail=f"memo found via {route}"
        + ("" if signer_ok else f"; UNEXPECTED signer {info.signer}"),
    )


def verify_run(
    run_dir: Path, *, registry: str, rpc_url: str, settings: Settings | None = None
) -> Report:
    local = verify_local(run_dir)
    receipt = read_receipt(run_dir)
    chain = asyncio.run(
        verify_chain(
            local.bundle_hash,
            registry=registry,
            rpc_url=rpc_url,
            signature_hint=(receipt or {}).get("signature"),
        )
    )
    fields = chain.memo_fields or {}
    sas: SasCheck | None = None
    if settings is not None and sas_configured(settings):
        bundle = load_bundle(run_dir / "bundle.json")
        # the memo names the bundle's CID ("-" -> None); the attestation must carry the same one
        expected_cid = (fields.get("cid") or "") if chain.found else None
        sas = check_attestation(
            local, bundle, registry=registry, settings=settings, expected_cid=expected_cid
        )
    media_matches_chain = bool(local.media_sha256) and fields.get("media") == local.media_sha256
    if sas is not None and sas.found and not sas.ok:
        verdict = "TAMPERED"  # an attestation exists but disagrees with the bundle or registry
    elif chain.found and chain.signer_ok and local.ok and media_matches_chain:
        verdict = "VERIFIED"
    elif not chain.found and local.ok:
        verdict = "UNANCHORED"
    else:
        verdict = "TAMPERED"
    return Report(local=local, chain=chain, registry=registry, verdict=verdict, sas=sas)


def _fmt_time(ts: int | None) -> str:
    if ts is None:
        return "-"
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def render_report(report: Report) -> Table:
    colour = {"VERIFIED": "bold green", "TAMPERED": "bold red"}.get(report.verdict, "bold yellow")
    table = Table(title=f"[{colour}]{report.verdict}[/{colour}]", show_header=False)
    table.add_column("field")
    table.add_column("value", overflow="fold")
    local, chain = report.local, report.chain
    table.add_row("run dir", str(local.run_dir))
    table.add_row("bundle sha256 (H)", local.bundle_hash)
    table.add_row("bundle canonical", "yes" if local.canonical_ok else "[red]NO[/red]")
    table.add_row(
        "media sha256",
        f"{local.media_sha256 or '-'}\n"
        + ("matches bundle" if local.media_ok else f"[red]{local.detail}[/red]"),
    )
    table.add_row("registry wallet", report.registry)
    if chain.found:
        table.add_row("memo tx", chain.signature or "-")
        table.add_row("slot / time", f"{chain.slot} / {_fmt_time(chain.block_time)}")
        table.add_row("signer ok", "yes" if chain.signer_ok else f"[red]NO ({chain.signer})[/red]")
        table.add_row("on-chain memo", chain.memo or "-")
        table.add_row("explorer", explorer_url(chain.signature or ""))
    else:
        table.add_row("memo tx", f"[yellow]{chain.detail}[/yellow]")
    _add_sas_rows(table, report.sas)
    return table


def _add_sas_rows(table: Table, sas: SasCheck | None) -> None:
    if sas is None:
        table.add_row(
            "attestation", "[dim]not checked: no credential/schema in receipt or .env[/dim]"
        )
        return
    if not sas.checked:
        table.add_row("attestation", f"[dim]not checked: {sas.detail}[/dim]")
        return
    origin = "recomputed from the media on disk" if sas.recomputed else "stored bundle.json"
    table.add_row("attestation nonce", f"H = {sas.hash_used}\n({origin})")
    table.add_row("attestation PDA", sas.attestation or f"[yellow]{sas.detail}[/yellow]")
    if not sas.found:
        table.add_row("attestation", f"[yellow]ABSENT: {sas.detail}[/yellow]")
        return
    table.add_row("attestation", "found" + (f" (expires {sas.expiry})" if sas.expiry else ""))
    table.add_row(
        "attestation signer",
        "ok" if sas.signer_ok else f"[red]NO ({sas.signer})[/red]",
    )
    table.add_row(
        "attestation fields",
        "match bundle" if sas.fields_ok else "[red]" + "; ".join(sas.mismatches) + "[/red]",
    )
