"""facechain command-line interface.

Commands are added phase by phase; `doctor` is the bootstrap check.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import Settings, load

console = Console()
MODEL_DIR = Path.home() / ".insightface/models/buffalo_l"
MODEL_FILES = ("det_10g.onnx", "w600k_r50.onnx", "1k3d68.onnx", "2d106det.onnx", "genderage.onnx")


@click.group()
@click.version_option(__version__, prog_name="facechain")
def main() -> None:
    """Face scan -> genuine social search -> face-verified match -> Solana record -> verify."""


@main.command()
@click.option(
    "--image",
    "image_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Photo containing the face to identify.",
)
@click.option("--face-index", type=int, default=None, help="Pick this face instead of the largest.")
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
