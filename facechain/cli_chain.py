"""CLI commands that touch evidence and the chain: run, anchor, verify."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import click
from rich.console import Console

from .cache import STATS, Cache
from .chain.memo import explorer_url, format_memo, load_keypair, send_memo
from .chain.sas import SasError, attest, require_sas, setup_sas
from .chain.verify import read_receipt, render_report, verify_run
from .config import Settings, load
from .evidence.bundle import (
    build_bundle,
    bundle_hash,
    load_bundle,
    new_run_id,
    tamper_copy,
    write_evidence,
)

console = Console()


def _event_printer(level: str, message: str) -> None:
    style = {"error": "bold red", "warn": "yellow"}.get(level, "dim")
    console.print(f"[{style}]{message}[/{style}]")


def _registry_pubkey(settings: Settings) -> str:
    return str(load_keypair(settings.solana_keypair_path).pubkey())


def _require_sas_or_exit(settings: Settings) -> None:
    try:
        require_sas(settings)
    except SasError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(2) from exc


def _write_receipt(run_dir: Path, receipt: dict[str, object]) -> None:
    (run_dir / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def attest_run(run_dir: Path, settings: Settings) -> dict[str, object]:
    """Create the SAS attestation for a run's bundle and record it in receipt.json."""
    bundle = load_bundle(run_dir / "bundle.json")
    started = time.perf_counter()
    try:
        record = attest(bundle, bundle["post"].get("media_cid"), settings)
    except SasError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc
    record["seconds"] = round(time.perf_counter() - started, 2)
    receipt = read_receipt(run_dir) or {"bundle_hash": bundle_hash(bundle)}
    previous = receipt.get("sas") or {}
    if record.get("existed") and previous.get("attestation") == record["attestation"]:
        record = {**previous, "existed": True}  # keep the original signature and timing
    receipt["sas"] = record
    _write_receipt(run_dir, receipt)
    if record.get("existed"):
        console.print(f"[dim]attestation already exists: {record['attestation']}[/dim]")
    else:
        console.print(
            f"[bold green]attested[/bold green] in {record['seconds']}s: {record['attestation']}"
            f"\nsas tx: {record['signature']}\nexplorer: {record['explorer']}"
        )
    return record


def anchor_run(run_dir: Path, settings: Settings, *, sas: bool = False) -> dict[str, object]:
    """Send the memo for a run directory's bundle and write receipt.json (+ SAS with --sas)."""
    if sas:
        _require_sas_or_exit(settings)
    bundle = load_bundle(run_dir / "bundle.json")
    h = bundle_hash(bundle)
    post, match = bundle["post"], bundle["match"]
    memo = format_memo(
        h, post["media_sha256"], post.get("media_cid"), match["similarity_bps"], post["url"]
    )
    keypair = load_keypair(settings.solana_keypair_path)
    console.print(f"[dim]memo ({len(memo.encode())} bytes): {memo}[/dim]")
    started = time.perf_counter()
    signature = asyncio.run(send_memo(memo, rpc_url=settings.solana_rpc_url, keypair=keypair))
    receipt = {
        "signature": signature,
        "explorer": explorer_url(signature),
        "memo": memo,
        "bundle_hash": h,
        "registry": str(keypair.pubkey()),
        "rpc_url": settings.solana_rpc_url,
        "anchored_at": int(time.time()),
        "seconds": round(time.perf_counter() - started, 2),
    }
    _write_receipt(run_dir, receipt)
    console.print(f"[bold green]anchored[/bold green] in {receipt['seconds']}s: {signature}")
    console.print(f"explorer: {receipt['explorer']}")
    if sas:
        receipt["sas"] = attest_run(run_dir, settings)
    return receipt


@click.command()
@click.option(
    "--image",
    "image_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--engines", default="lens", show_default=True)
@click.option("--max-candidates", default=40, show_default=True, type=int)
@click.option("--face-index", type=int, default=None)
@click.option("--live", is_flag=True, help="Bypass cache reads: every search is live (on camera).")
@click.option("--offline", is_flag=True, help="Never touch the network; fail on a cache miss.")
@click.option("--no-anchor", is_flag=True, help="Stop after writing evidence; skip the chain.")
@click.option("--sas", is_flag=True, help="Also create the SAS attestation after the memo.")
def run(
    image_path: Path,
    engines: str,
    max_candidates: int,
    face_index: int | None,
    live: bool,
    offline: bool,
    no_anchor: bool,
    sas: bool,
) -> None:
    """End to end: scan -> search -> face-verify -> evidence bundle -> devnet memo [+ SAS]."""
    from .pipeline import NoFaceError, run_search
    from .search.rank import render_table

    settings = load()
    if sas and not no_anchor:
        _require_sas_or_exit(settings)  # fail before spending a search or a memo
    cache = Cache(settings.cache_dir, offline=offline or settings.offline, live=live)
    STATS.reset()
    engine_list = tuple(e.strip() for e in engines.split(",") if e.strip())
    image_bytes = image_path.read_bytes()
    try:
        outcome = run_search(
            image_bytes,
            settings,
            cache,
            engines=engine_list,
            max_candidates=max_candidates,
            face_index=face_index,
            on_event=_event_printer,
        )
    except NoFaceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(2) from exc

    console.print(render_table(outcome.candidates, title=f"candidates for {image_path.name}"))
    decision = outcome.decision
    style = "bold green" if decision.accepted else "bold yellow"
    console.print(f"[{style}]{decision.reason}[/{style}]")
    console.print(STATS.summary())

    run_id = new_run_id()
    run_dir = settings.evidence_dir / run_id
    winner = decision.winner if decision.accepted else None
    bundle = None
    if winner is not None:
        bundle = build_bundle(
            face_id=outcome.face_id,
            winner=winner,
            threshold_bps=round(settings.match_threshold * 10_000),
            candidates_considered=len(outcome.candidates),
            found_at=int(time.time()),
            engines=engine_list,
        )
    write_evidence(
        run_dir,
        query_bytes=image_bytes,
        query_suffix=image_path.suffix.lower(),
        candidates=outcome.candidates,
        winner=winner,
        bundle=bundle,
    )
    (run_dir / "cache_keys.txt").write_text("\n".join(STATS.keys) + "\n", encoding="utf-8")
    console.print(f"evidence: {run_dir}")
    if bundle is None or winner is None:
        console.print(
            "[yellow]not accepted: evidence written for review, nothing anchored[/yellow]"
        )
        raise SystemExit(2)
    console.print(f"winner: {winner.url}\nbundle sha256 (H): {bundle_hash(bundle)}")
    if no_anchor:
        raise SystemExit(0)
    anchor_run(run_dir, settings, sas=sas)


@click.command()
@click.option(
    "--run", "run_dir", required=True, type=click.Path(exists=True, file_okay=False, path_type=Path)
)
@click.option("--sas", is_flag=True, help="Also create the SAS attestation after the memo.")
def anchor(run_dir: Path, sas: bool) -> None:
    """Anchor an existing run's bundle on devnet (writes receipt.json)."""
    anchor_run(run_dir, load(), sas=sas)


@click.command()
@click.option("--run", "run_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--bundle", "bundle_path", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.option(
    "--tamper", is_flag=True, help="Flip one byte of the stored media first and re-verify."
)
@click.option(
    "--registry", default=None, help="Registry wallet pubkey (default: receipt or keypair)."
)
def verify(
    run_dir: Path | None, bundle_path: Path | None, tamper: bool, registry: str | None
) -> None:
    """Recompute hashes from stored evidence and check them against the on-chain memo."""
    settings = load()
    if run_dir is None and bundle_path is None:
        raise click.UsageError("pass --run DIR or --bundle FILE")
    target = run_dir if run_dir is not None else bundle_path.parent  # type: ignore[union-attr]
    if tamper:
        target = tamper_copy(target)
        console.print(f"[yellow]tampered copy: {target}[/yellow]")
    receipt = read_receipt(run_dir or target)
    registry_key = str(registry or (receipt or {}).get("registry") or _registry_pubkey(settings))
    report = verify_run(
        target, registry=registry_key, rpc_url=settings.solana_rpc_url, settings=settings
    )
    console.print(render_report(report))
    raise SystemExit(0 if report.ok else 1)


@click.command("attest")
@click.option(
    "--run", "run_dir", required=True, type=click.Path(exists=True, file_okay=False, path_type=Path)
)
def attest_cmd(run_dir: Path) -> None:
    """Create the SAS attestation for an already anchored run (no new memo)."""
    settings = load()
    _require_sas_or_exit(settings)
    attest_run(run_dir, settings)


@click.command("setup-sas")
def setup_sas_cmd() -> None:
    """One-time: create the SAS credential + schema on devnet and record them in .env."""
    settings = load()
    try:
        result = setup_sas(settings)
    except SasError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc
    console.print(
        f"credential: {result['credential']}\nschema: {result['schema']}\n"
        f"authority: {result['authority']}\nprogram: {result['program']}"
    )
    for signature in result["txs"]:
        console.print(f"tx: {signature}\n    {explorer_url(signature)}")
    if not result["txs"]:
        console.print("[dim]credential and schema already exist; nothing sent[/dim]")
    env = result["env"]
    written = ", ".join(env["written"]) or "nothing (keys already set)"
    console.print(f"env: {env['path']} <- {written}")
    for key, current in (
        ("SAS_CREDENTIAL", settings.sas_credential),
        ("SAS_SCHEMA", settings.sas_schema),
    ):
        expected = result["credential" if key == "SAS_CREDENTIAL" else "schema"]
        if current and current != expected:
            console.print(f"[yellow]{key} is set to {current}, expected {expected}[/yellow]")
