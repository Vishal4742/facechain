"""facechain command-line interface.

Pipeline commands live here (scan, doctor, search, run); the chain-only commands (anchor, verify,
attest, setup-sas) are registered from `cli_chain`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click
from rich.console import Console
from rich.table import Table

from . import __version__
from .cache import STATS, Cache, CacheMiss
from .chain import ipfs
from .cli_chain import anchor, anchor_run, attest_cmd, require_sas_or_exit, setup_sas_cmd, verify
from .config import Settings, load
from .evidence.bundle import build_bundle, bundle_hash, media_suffix, new_run_id, write_evidence
from .http import HttpError, redact
from .search.lens import LensError, account_searches_left

if TYPE_CHECKING:
    from .pipeline import SearchOutcome

ENGINE_ERRORS = (LensError, HttpError, CacheMiss, ValueError)

console = Console()
MODEL_DIR = Path.home() / ".insightface/models/buffalo_l"
MODEL_FILES = ("det_10g.onnx", "w600k_r50.onnx", "1k3d68.onnx", "2d106det.onnx", "genderage.onnx")

image_option = click.option(
    "--image",
    "image_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Photo containing the face to identify.",
)
face_index_option = click.option(
    "--face-index", type=int, default=None, help="Pick this face instead of the largest."
)
SEARCH_OPTIONS = (
    image_option,
    click.option("--engines", default="lens", show_default=True, help="Comma-separated engines."),
    click.option("--max-candidates", default=40, show_default=True, type=int),
    face_index_option,
    click.option(
        "--live", is_flag=True, help="Bypass cache reads: every search is live (on camera)."
    ),
    click.option("--offline", is_flag=True, help="Never touch the network; fail on a cache miss."),
)


def search_options(f: Callable[..., Any]) -> Callable[..., Any]:
    """The options `search` and `run` share, in this order."""
    for option in reversed(SEARCH_OPTIONS):
        f = option(f)
    return f


@click.group()
@click.version_option(__version__, prog_name="facechain")
def main() -> None:
    """Face scan -> genuine social search -> face-verified match -> Solana record -> verify."""


@main.command()
@image_option
@face_index_option
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def scan(image_path: Path, face_index: int | None, as_json: bool) -> None:
    """Detect faces in an image, report quality, and choose the query face."""
    from .face.engine import get_engine
    from .face.match import pick_query_face, quality_ok

    data = image_path.read_bytes()
    face_id = hashlib.sha256(data).hexdigest()
    started = time.perf_counter()
    faces = get_engine().embed_bytes(data)
    elapsed = time.perf_counter() - started
    if not faces:
        console.print(f"[red]no face detected in {image_path}[/red]")
        raise SystemExit(2)
    chosen = pick_query_face(faces, face_index)
    chosen_idx = faces.index(chosen)

    if as_json:
        payload = {
            "image": str(image_path),
            "face_id": face_id,
            "seconds": round(elapsed, 2),
            "query_index": chosen_idx,
            "faces": [
                {**f.to_dict(), "quality": quality_ok(f)[1], "index": i}
                for i, f in enumerate(faces)
            ],
        }
        click.echo(json.dumps(payload, indent=2))
        return

    table = Table(title=f"faces in {image_path.name}")
    for col in ("#", "bbox", "det", "ipd px", "blur", "quality", "query"):
        table.add_column(col)
    for i, f in enumerate(faces):
        ok, reason = quality_ok(f)
        table.add_row(
            str(i),
            " ".join(str(int(v)) for v in f.bbox),
            f"{f.det_score:.2f}",
            f"{f.ipd_px:.0f}",
            f"{f.blur_var:.0f}",
            "[green]ok[/green]" if ok else f"[yellow]{reason}[/yellow]",
            "[bold]*[/bold]" if i == chosen_idx else "",
        )
    console.print(table)
    console.print(
        f"{len(faces)} face(s) in {elapsed:.1f}s; query = face #{chosen_idx}; "
        f"face_id = {face_id[:16]}..."
    )


def _keypair_pubkey(path: Path) -> str | None:
    try:
        from solders.keypair import Keypair

        return str(Keypair.from_json(path.read_text()).pubkey())
    except Exception:  # noqa: BLE001 - doctor reports, never crashes
        return None


async def _balance_sol(rpc_url: str, pubkey: str) -> float:
    from solana.rpc.async_api import AsyncClient
    from solders.pubkey import Pubkey

    async with AsyncClient(rpc_url) as client:
        resp = await client.get_balance(Pubkey.from_string(pubkey))
    return resp.value / 1_000_000_000


def _doctor_rows(settings: Settings, online: bool) -> list[tuple[str, bool, str]]:
    rows: list[tuple[str, bool, str]] = []

    missing = [f for f in MODEL_FILES if not (MODEL_DIR / f).exists()]
    rows.append(
        ("model buffalo_l", not missing, str(MODEL_DIR) if not missing else f"missing {missing}")
    )

    rows.append(
        (
            "SerpApi key",
            settings.serpapi_key is not None,
            "set" if settings.serpapi_key else "SERPAPI_KEY not set",
        )
    )
    rows.append(
        (
            "Pinata JWT",
            settings.pinata_jwt is not None,
            "set" if settings.pinata_jwt else "PINATA_JWT not set (optional)",
        )
    )

    pubkey = _keypair_pubkey(settings.solana_keypair_path)
    rows.append(
        (
            "Solana keypair",
            pubkey is not None,
            pubkey or f"unreadable: {settings.solana_keypair_path}",
        )
    )
    if online and pubkey:
        try:
            bal = asyncio.run(_balance_sol(settings.solana_rpc_url, pubkey))
            rows.append(
                ("devnet balance", bal > 0.05, f"{bal:.4f} SOL @ {settings.solana_rpc_url}")
            )
        except Exception as exc:  # noqa: BLE001
            rows.append(("devnet balance", False, f"rpc error: {exc}"))

    try:
        settings.cache_dir.mkdir(parents=True, exist_ok=True)
        probe = settings.cache_dir / ".write-probe"
        probe.write_text("ok")
        probe.unlink()
        rows.append(("cache dir", True, str(settings.cache_dir)))
    except OSError as exc:
        rows.append(("cache dir", False, f"{settings.cache_dir}: {exc}"))

    rows.append(("evidence dir", True, str(settings.evidence_dir)))
    rows.append(
        (
            "thresholds",
            0 < settings.review_threshold < settings.match_threshold < 1,
            f"match >= {settings.match_threshold}, review >= {settings.review_threshold}",
        )
    )
    rows.append(("offline mode", True, "on" if settings.offline else "off"))
    return rows


@main.command()
@click.option("--online", is_flag=True, help="Also query the devnet balance over RPC.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def doctor(online: bool, as_json: bool) -> None:
    """Check model, keys, wallet and directories."""
    settings = load()
    rows = _doctor_rows(settings, online)
    if as_json:
        click.echo(json.dumps([{"check": c, "ok": ok, "detail": d} for c, ok, d in rows], indent=2))
    else:
        table = Table(title="facechain doctor")
        table.add_column("check")
        table.add_column("status")
        table.add_column("detail", overflow="fold")
        for check, ok, detail in rows:
            table.add_row(check, "[green]OK[/green]" if ok else "[red]FAIL[/red]", detail)
        console.print(table)
    required = {"model buffalo_l", "Solana keypair", "cache dir", "thresholds"}
    if any(not ok for check, ok, _ in rows if check in required):
        raise SystemExit(1)


def _event_printer(level: str, message: str) -> None:
    style = {"error": "bold red", "warn": "yellow"}.get(level, "dim")
    console.print(f"[{style}]{message}[/{style}]")


def _search(
    settings: Settings,
    image_bytes: bytes,
    label: str,
    *,
    engines: str,
    max_candidates: int,
    face_index: int | None,
    live: bool,
    offline: bool,
) -> SearchOutcome:
    """Shared by `search` and `run`: run the pipeline, print the ranked table and the decision."""
    from .pipeline import NoFaceError, run_search
    from .search.rank import render_table

    if live and offline:
        raise click.UsageError("--live and --offline are mutually exclusive")
    cache = Cache(settings.cache_dir, offline=offline or settings.offline, live=live)
    STATS.reset()
    try:
        outcome = run_search(
            image_bytes,
            settings,
            cache,
            engines=tuple(e.strip() for e in engines.split(",") if e.strip()),
            max_candidates=max_candidates,
            face_index=face_index,
            on_event=_event_printer,
        )
    except NoFaceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(2) from exc
    except ENGINE_ERRORS as exc:
        console.print(f"[bold red]search failed: {redact(str(exc))}[/bold red]")
        raise SystemExit(3) from exc
    console.print(render_table(outcome.candidates, title=f"candidates for {label}"))
    style = "bold green" if outcome.decision.accepted else "bold yellow"
    console.print(f"[{style}]{outcome.decision.reason}[/{style}]")
    return outcome


@main.command()
@search_options
@click.option("--json", "json_out", type=click.Path(dir_okay=False, path_type=Path), default=None)
def search(
    image_path: Path,
    engines: str,
    max_candidates: int,
    face_index: int | None,
    live: bool,
    offline: bool,
    json_out: Path | None,
) -> None:
    """Find social posts showing this face: reverse image search + face verification."""
    settings = load()
    started = time.perf_counter()
    outcome = _search(
        settings,
        image_path.read_bytes(),
        image_path.name,
        engines=engines,
        max_candidates=max_candidates,
        face_index=face_index,
        live=live,
        offline=offline,
    )
    decision = outcome.decision
    if decision.winner is not None:
        console.print(f"winner: {decision.winner.url}")
    console.print(f"{STATS.summary()}; {time.perf_counter() - started:.1f}s")
    if any(m.live for m in outcome.meta) and settings.serpapi_key:
        left = account_searches_left(settings.serpapi_key)
        if left is not None:
            console.print(f"SerpApi searches left this month: {left}")

    if json_out is not None:
        payload = {
            "image": str(image_path),
            "face_id": outcome.face_id,
            "decision": {
                "accepted": decision.accepted,
                "reason": decision.reason,
                "winner": decision.winner.url if decision.winner else None,
            },
            "hints": [{"query": h.query, "kgmid": h.kgmid} for h in outcome.hints],
            "search_metadata": [m.__dict__ for m in outcome.meta],
            "candidates": [c.to_dict() for c in outcome.candidates],
        }
        json_out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        console.print(f"wrote {json_out}")
    raise SystemExit(0 if decision.accepted else 2)


@main.command()
@search_options
@click.option("--no-anchor", is_flag=True, help="Stop after writing evidence; skip the chain.")
@click.option("--no-pin", is_flag=True, help="Skip IPFS pinning even if PINATA_JWT is set.")
@click.option("--sas", is_flag=True, help="Also create the SAS attestation after the memo.")
def run(
    image_path: Path,
    engines: str,
    max_candidates: int,
    face_index: int | None,
    live: bool,
    offline: bool,
    no_anchor: bool,
    no_pin: bool,
    sas: bool,
) -> None:
    """End to end: scan -> search -> face-verify -> evidence bundle -> devnet memo [+ SAS]."""
    settings = load()
    if sas and not no_anchor:
        require_sas_or_exit(settings)  # fail before spending a search or a memo
    image_bytes = image_path.read_bytes()
    outcome = _search(
        settings,
        image_bytes,
        image_path.name,
        engines=engines,
        max_candidates=max_candidates,
        face_index=face_index,
        live=live,
        offline=offline,
    )
    decision = outcome.decision
    console.print(STATS.summary())

    run_id = new_run_id()
    run_dir = settings.evidence_dir / run_id
    winner = decision.winner if decision.accepted else None
    bundle = None
    if winner is not None:
        media_cid: str | None = None
        if (
            settings.pinata_jwt
            and not no_pin
            and winner.media_bytes
            and not (offline or settings.offline)
        ):
            suffix = media_suffix(winner.media_bytes)
            media_cid = ipfs.pin_bytes(
                winner.media_bytes,
                jwt=settings.pinata_jwt,
                name=f"{run_id}-post_media{suffix}",
                content_type="image/jpeg" if suffix == ".jpg" else "application/octet-stream",
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
            engines=outcome.engines,
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
    (run_dir / "search.json").write_text(
        json.dumps(
            {
                "engines": list(outcome.engines),
                "search_metadata": [m.__dict__ for m in outcome.meta],
                "hints": [{"query": h.query, "kgmid": h.kgmid} for h in outcome.hints],
                "identity": (
                    {
                        "qid": outcome.identity.qid,
                        "label": outcome.identity.label,
                        "handles": outcome.identity.author_tags(),
                    }
                    if outcome.identity
                    else None
                ),
                "decision": {"accepted": decision.accepted, "reason": decision.reason},
                "faces_in_query": outcome.faces_in_query,
                "cache": STATS.summary(),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    console.print(f"evidence: {run_dir}")
    if bundle is None or winner is None:
        console.print(
            "[yellow]not accepted: evidence written for review, nothing anchored[/yellow]"
        )
        raise SystemExit(2)
    console.print(f"winner: {winner.url}\nbundle sha256 (H): {bundle_hash(bundle)}")
    if no_anchor:
        raise SystemExit(0)
    anchor_run(run_dir, settings, pin=not no_pin, sas=sas)


for command in (anchor, verify, setup_sas_cmd, attest_cmd):
    main.add_command(command)

if __name__ == "__main__":  # `python -m facechain.cli` (worktrees without a console script)
    main()
