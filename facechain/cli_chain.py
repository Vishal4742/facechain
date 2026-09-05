"""CLI commands that touch evidence and the chain: run, anchor, verify."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import click
from rich.console import Console

from .cache import STATS, Cache, CacheMiss
from .chain import ipfs
from .chain.memo import explorer_url, format_memo, load_keypair, send_memo
from .chain.verify import read_receipt, render_report, verify_run
from .config import Settings, load
from .evidence.bundle import (
    build_bundle,
    bundle_hash,
    load_bundle,
    media_suffix,
    new_run_id,
    tamper_copy,
    write_evidence,
)
from .http import HttpError, redact
from .search.lens import LensError

console = Console()


def _event_printer(level: str, message: str) -> None:
    style = {"error": "bold red", "warn": "yellow"}.get(level, "dim")
    console.print(f"[{style}]{message}[/{style}]")


def _registry_pubkey(settings: Settings) -> str:
    return str(load_keypair(settings.solana_keypair_path).pubkey())


def anchor_run(run_dir: Path, settings: Settings, *, pin: bool = True) -> dict[str, object]:
    """Pin bundle.json (if Pinata is configured), send the memo, write receipt.json."""
    bundle = load_bundle(run_dir / "bundle.json")
    h = bundle_hash(bundle)
    post, match = bundle["post"], bundle["match"]
    bundle_cid: str | None = None
    if pin and settings.pinata_jwt:
        bundle_cid = ipfs.pin_file(
            run_dir / "bundle.json", jwt=settings.pinata_jwt, name=f"{h[:16]}-bundle.json"
        )
        console.print(
            f"[green]pinned bundle.json: {bundle_cid}[/green]"
            if bundle_cid
            else "[yellow]Pinata upload failed; continuing with cid=-[/yellow]"
        )
    memo = format_memo(h, post["media_sha256"], bundle_cid, match["similarity_bps"], post["url"])
    keypair = load_keypair(settings.solana_keypair_path)
    console.print(f"[dim]memo ({len(memo.encode())} bytes): {memo}[/dim]")
    started = time.perf_counter()
    signature = asyncio.run(send_memo(memo, rpc_url=settings.solana_rpc_url, keypair=keypair))
    receipt = {
        "signature": signature,
        "explorer": explorer_url(signature),
        "memo": memo,
        "bundle_hash": h,
        "bundle_cid": bundle_cid,
        "media_cid": post.get("media_cid"),
        "registry": str(keypair.pubkey()),
        "rpc_url": settings.solana_rpc_url,
        "anchored_at": int(time.time()),
        "seconds": round(time.perf_counter() - started, 2),
    }
    (run_dir / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    console.print(f"[bold green]anchored[/bold green] in {receipt['seconds']}s: {signature}")
    console.print(f"explorer: {receipt['explorer']}")
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
@click.option("--no-pin", is_flag=True, help="Skip IPFS pinning even if PINATA_JWT is set.")
def run(
    image_path: Path,
    engines: str,
    max_candidates: int,
    face_index: int | None,
    live: bool,
    offline: bool,
    no_anchor: bool,
    no_pin: bool,
) -> None:
    """End to end: scan -> search -> face-verify -> evidence bundle -> devnet memo."""
    from .pipeline import NoFaceError, run_search
    from .search.rank import render_table

    if live and offline:
        raise click.UsageError("--live and --offline are mutually exclusive")
    settings = load()
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
    except (LensError, HttpError, CacheMiss, ValueError) as exc:
        console.print(f"[bold red]search failed: {redact(str(exc))}[/bold red]")
        raise SystemExit(3) from exc

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
        media_cid: str | None = None
        if settings.pinata_jwt and not no_pin and winner.media_bytes:
            media_cid = ipfs.pin_bytes(
                winner.media_bytes,
                jwt=settings.pinata_jwt,
                name=f"{run_id}-post_media{media_suffix(winner.media_bytes)}",
                content_type="image/jpeg"
                if media_suffix(winner.media_bytes) == ".jpg"
                else "application/octet-stream",
            )
            console.print(
                f"[green]pinned post media: {media_cid}[/green]"
                if media_cid
                else "[yellow]Pinata media upload failed; media_cid stays null[/yellow]"
            )
        bundle = build_bundle(
            face_id=outcome.face_id,
            winner=winner,
            threshold_bps=round(settings.match_threshold * 10_000),
            candidates_considered=len(outcome.candidates),
            found_at=int(time.time()),
            engines=engine_list,
            media_cid=media_cid,
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
    anchor_run(run_dir, settings, pin=not no_pin)


@click.command()
@click.option(
    "--run", "run_dir", required=True, type=click.Path(exists=True, file_okay=False, path_type=Path)
)
@click.option("--no-pin", is_flag=True, help="Skip IPFS pinning even if PINATA_JWT is set.")
def anchor(run_dir: Path, no_pin: bool) -> None:
    """Anchor an existing run's bundle on devnet (writes receipt.json)."""
    anchor_run(run_dir, load(), pin=not no_pin)


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
@click.option("--cid", default=None, help="Fetch bundle.json (and its media) from IPFS by CID.")
def verify(
    run_dir: Path | None,
    bundle_path: Path | None,
    tamper: bool,
    registry: str | None,
    cid: str | None,
) -> None:
    """Recompute hashes from stored evidence and check them against the on-chain memo."""
    settings = load()
    if cid:
        run_dir = fetch_run_from_ipfs(cid, settings)
    if run_dir is None and bundle_path is None:
        raise click.UsageError("pass --run DIR, --bundle FILE or --cid CID")
    target = run_dir if run_dir is not None else bundle_path.parent  # type: ignore[union-attr]
    if tamper:
        target = tamper_copy(target)
        console.print(f"[yellow]tampered copy: {target}[/yellow]")
    receipt = read_receipt(run_dir or target)
    registry_key = str(registry or (receipt or {}).get("registry") or _registry_pubkey(settings))
    report = verify_run(target, registry=registry_key, rpc_url=settings.solana_rpc_url)
    console.print(render_report(report))
    raise SystemExit(0 if report.ok else 1)


def fetch_run_from_ipfs(cid: str, settings: Settings) -> Path:
    """Materialise a run directory from IPFS: bundle.json by CID, media by bundle.post.media_cid."""
    cache = Cache(settings.cache_dir)
    raw = ipfs.fetch(cid, cache=cache, gateway=settings.pinata_gateway)
    if not raw:
        raise click.ClickException(f"could not fetch {cid} from any IPFS gateway")
    run_dir = settings.evidence_dir / f"_cid_{cid[:16]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "bundle.json").write_bytes(raw)
    bundle = json.loads(raw.decode("utf-8"))
    media_cid = bundle.get("post", {}).get("media_cid")
    if media_cid:
        media = ipfs.fetch(media_cid, cache=cache, gateway=settings.pinata_gateway)
        if media:
            (run_dir / f"post_media{media_suffix(media)}").write_bytes(media)
    console.print(f"fetched bundle {cid} -> {run_dir}")
    return run_dir
