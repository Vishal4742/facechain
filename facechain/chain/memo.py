"""SPL Memo anchoring on Solana devnet.

The memo carries the bundle hash H, the media hash, the IPFS CID (or "-"), the similarity in
basis points and the post URL. Lookup never needs a receipt: scanning the registry wallet's
signatures finds the memo containing `h=<H>`.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MEMO_PROGRAM_ID = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
MEMO_MAX_BYTES = 500
PREFIX = "FACECHAIN/1"
MEMO_RE = re.compile(
    r"^(?:\[\d+\]\s+)?FACECHAIN/(?P<version>\d+) h=(?P<h>[0-9a-f]{64}) "
    r"media=(?P<media>[0-9a-f]{64}) cid=(?P<cid>\S+) sim=(?P<sim>\d+) url=(?P<url>\S*)$"
)
RETRYABLE = ("Blockhash", "blockhash", "429", "Too Many", "timed out", "timeout")


class MemoError(RuntimeError):
    """Sending or reading the memo transaction failed."""


@dataclass(frozen=True)
class MemoHit:
    signature: str
    slot: int
    block_time: int | None
    memo: str


@dataclass(frozen=True)
class TxInfo:
    signature: str
    memo: str | None
    signer: str | None
    slot: int
    block_time: int | None


# -- pure -------------------------------------------------------------------------------
def format_memo(h: str, media_sha256: str, cid: str | None, sim_bps: int, url: str) -> str:
    head = f"{PREFIX} h={h} media={media_sha256} cid={cid or '-'} sim={int(sim_bps)} url="
    budget = MEMO_MAX_BYTES - len(head.encode("utf-8"))
    tail = url
    while len(tail.encode("utf-8")) > budget:
        tail = tail[:-1]
    return head + tail


def parse_memo(text: str) -> dict[str, Any] | None:
    match = MEMO_RE.match((text or "").strip())
    if match is None:
        return None
    cid = match.group("cid")
    return {
        "version": int(match.group("version")),
        "h": match.group("h"),
        "media": match.group("media"),
        "cid": None if cid == "-" else cid,
        "sim": int(match.group("sim")),
        "url": match.group("url"),
    }


def memo_matches(text: str, h: str) -> bool:
    parsed = parse_memo(text)
    return parsed is not None and parsed["h"] == h


def explorer_url(signature: str) -> str:
    return f"https://explorer.solana.com/tx/{signature}?cluster=devnet"


# -- chain ------------------------------------------------------------------------------
def load_keypair(path: Path) -> Any:
    from solders.keypair import Keypair

    return Keypair.from_json(path.read_text())


def _memo_instruction(signer_pubkey: Any, text: str) -> Any:
    from solders.pubkey import Pubkey
    from spl.memo.constants import MEMO_PROGRAM_ID as SPL_MEMO_ID
    from spl.memo.instructions import create_memo
    from spl.memo.models import MemoParams

    assert str(SPL_MEMO_ID) == MEMO_PROGRAM_ID or Pubkey.from_string(MEMO_PROGRAM_ID)
    return create_memo(
        MemoParams(program_id=SPL_MEMO_ID, signer=signer_pubkey, message=text.encode("utf-8"))
    )


async def send_memo(text: str, *, rpc_url: str, keypair: Any, retries: int = 1) -> str:
    """Build, sign and send in one shot; one retry with a fresh blockhash on expiry/429."""
    from solana.rpc.async_api import AsyncClient
    from solana.rpc.commitment import Confirmed
    from solders.message import MessageV0
    from solders.transaction import VersionedTransaction

    if len(text.encode("utf-8")) > MEMO_MAX_BYTES:
        raise MemoError(f"memo exceeds {MEMO_MAX_BYTES} bytes")
    last: Exception | None = None
    async with AsyncClient(rpc_url, commitment=Confirmed) as client:
        for attempt in range(retries + 1):
            try:
                blockhash = (await client.get_latest_blockhash()).value.blockhash
                message = MessageV0.try_compile(
                    keypair.pubkey(), [_memo_instruction(keypair.pubkey(), text)], [], blockhash
                )
                tx = VersionedTransaction(message, [keypair])
                signature = (await client.send_transaction(tx)).value
                await client.confirm_transaction(signature, Confirmed, sleep_seconds=1.0)
                return str(signature)
            except Exception as exc:  # noqa: BLE001 - classify below
                last = exc
                if attempt >= retries or not any(marker in str(exc) for marker in RETRYABLE):
                    break
                await asyncio.sleep(2.0 * (attempt + 1))
    raise MemoError(f"memo transaction failed: {last}") from last


async def find_memo(
    registry: str, h: str, *, rpc_url: str, limit: int = 1000, attempts: int = 3
) -> MemoHit | None:
    """Scan the registry wallet's recent signatures for a memo carrying this bundle hash.

    A record anchored seconds ago may not be indexed yet, hence the short retry.
    """
    from solana.rpc.async_api import AsyncClient
    from solana.rpc.commitment import Confirmed
    from solders.pubkey import Pubkey

    async with AsyncClient(rpc_url) as client:
        for attempt in range(attempts):
            resp = await client.get_signatures_for_address(
                Pubkey.from_string(registry), limit=limit, commitment=Confirmed
            )
            for entry in resp.value:
                memo = getattr(entry, "memo", None)
                if memo and memo_matches(memo, h):
                    return MemoHit(
                        signature=str(entry.signature),
                        slot=int(entry.slot),
                        block_time=entry.block_time,
                        memo=memo,
                    )
            if attempt < attempts - 1:
                await asyncio.sleep(3.0)
    return None


async def tx_memo(signature: str, *, rpc_url: str) -> TxInfo:
    """Read the memo text, fee-payer and timing of a confirmed transaction (jsonParsed)."""
    from solana.rpc.async_api import AsyncClient
    from solana.rpc.commitment import Confirmed
    from solders.signature import Signature

    async with AsyncClient(rpc_url) as client:
        resp = await client.get_transaction(
            Signature.from_string(signature),
            encoding="jsonParsed",
            commitment=Confirmed,
            max_supported_transaction_version=0,
        )
    if resp.value is None:
        raise MemoError(f"transaction {signature} not found")
    data = json.loads(resp.value.to_json())
    message = data.get("transaction", {}).get("message", {})
    memo_text: str | None = None
    for ix in message.get("instructions", []):
        if ix.get("program") == "spl-memo" and isinstance(ix.get("parsed"), str):
            memo_text = ix["parsed"]
            break
    keys = message.get("accountKeys", [])
    signer = next((k.get("pubkey") for k in keys if k.get("signer")), None)
    return TxInfo(
        signature=signature,
        memo=memo_text,
        signer=signer,
        slot=int(data.get("slot", 0)),
        block_time=data.get("blockTime"),
    )
