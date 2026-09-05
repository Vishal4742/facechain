"""Specs for facechain.chain.sas: sidecar glue with the subprocess mocked, plus one live test."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from rich.console import Console

from facechain.chain import sas as sas_mod
from facechain.chain.sas import (
    SasCheck,
    SasError,
    attest,
    attestation_fields,
    call_sidecar,
    check_attestation,
    compare_attestation,
    effective_hash,
    fetch_attestation,
    setup_sas,
    write_env_keys,
)
from facechain.chain.verify import ChainResult, Report, render_report
from facechain.config import Settings
from facechain.evidence.bundle import LocalResult, bundle_hash, canonical_bytes

H = "f91da8318337be538a8f07ecfeb85f5063955d9de0fabe66aa9ba3c49b9cafb0"
MEDIA = "00798ba8ca4fdaa44eb93528381c83d0ebf0ac8fde82fdfe2c2a85e9f45ede03"
REGISTRY = "9ziKFvAU74jNa8RxnDZRxf2AGoDtCafpzvLXYZP5a1MX"
CREDENTIAL = "Awhv5DjjmeeGZPxeMim1hW8yWKgMJtUFD2dX7BrArpzh"
SCHEMA = "DNnsTXgmuPDsb3gKF8rgYsnRYP7h6qLEMC9udtxofpDD"
ATTESTATION = "2PbkcAdrUECskxUMPQsEVYjczqWohPYcsAEU9F54pU5A"
NONCE = "HmSkF2UHkdwFWVusM7qPLULxtLF1RiN8S94TyDg5TuS7"
ROOT = Path(__file__).resolve().parents[1]


def _bundle() -> dict[str, Any]:
    """The synthetic devnet run from Phase 3; its canonical hash is H."""
    return {
        "match": {
            "candidates_considered": 1,
            "corroborated_by": ["engine:identity:x"],
            "engine": "lens:visual",
            "engines": ["lens"],
            "similarity_bps": 7123,
            "threshold_bps": 4500,
        },
        "post": {
            "author": "@imVkohli",
            "fetched_at": 1788576465,
            "media_cid": None,
            "media_sha256": MEDIA,
            "media_url": "https://pbs.twimg.com/media/synthetic.jpg",
            "platform": "x",
            "text": None,
            "text_sha256": None,
            "title": "synthetic devnet smoke",
            "url": "https://x.com/imVkohli/status/1000000000000000001",
        },
        "query": {
            "detector": "scrfd_10g",
            "embedder": "arcface_r50_buffalo_l",
            "face_id": "0" * 64,
        },
        "version": 1,
    }


def _settings(tmp_path: Path, credential: str | None = CREDENTIAL, schema: str | None = SCHEMA):
    return Settings(
        serpapi_key=None,
        pinata_jwt=None,
        pinata_gateway="gateway.pinata.cloud",
        solana_rpc_url="https://rpc.example/devnet",
        solana_keypair_path=tmp_path / "id.json",
        cache_dir=tmp_path / "cache",
        evidence_dir=tmp_path / "evidence",
        match_threshold=0.45,
        review_threshold=0.35,
        sas_credential=credential,
        sas_schema=schema,
        offline=True,
    )


def _found() -> dict[str, Any]:
    return {
        "found": True,
        "attestation": ATTESTATION,
        "nonce": NONCE,
        "signer": REGISTRY,
        "credential": CREDENTIAL,
        "schema": SCHEMA,
        "expiry": 0,
        "data": {
            "bundle_hash": H,
            "cid": "",
            "post_url": "https://x.com/imVkohli/status/1000000000000000001",
            "similarity_bps": 7123,
        },
    }


def _local(run_dir: Path, *, media_ok: bool = True) -> LocalResult:
    return LocalResult(
        run_dir=run_dir,
        bundle_hash=H,
        canonical_ok=True,
        media_ok=media_ok,
        media_sha256=MEDIA if media_ok else "ab" * 32,
        expected_media_sha256=MEDIA,
        detail="",
    )


def _patch_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
    timeout: bool = False,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"argv": argv, **kwargs})
        if timeout:
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 0))
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(sas_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(sas_mod.shutil, "which", lambda name: "/usr/bin/node")
    return calls


def _patch_sidecar(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any]
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_call(cmd: dict[str, Any], timeout: float = 120) -> dict[str, Any]:
        calls.append(cmd)
        return dict(response)

    monkeypatch.setattr(sas_mod, "call_sidecar", fake_call)
    return calls


# -- the bundle used everywhere really hashes to H -----------------------------------------
def test_fixture_bundle_hashes_to_the_synthetic_run_hash() -> None:
    assert bundle_hash(_bundle()) == H


# -- call_sidecar ------------------------------------------------------------------------
def test_call_sidecar_runs_node_with_json_stdin_and_returns_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_subprocess(monkeypatch, stdout='{"found":false,"attestation":"x"}\n')
    out = call_sidecar({"cmd": "fetch", "bundle_hash": H}, timeout=7)
    assert out == {"found": False, "attestation": "x"}
    call = calls[0]
    assert call["argv"][0] == "/usr/bin/node"
    assert call["argv"][1].endswith("chain-ts/sas.ts")
    assert json.loads(call["input"]) == {"cmd": "fetch", "bundle_hash": H}
    assert call["timeout"] == 7 and call["capture_output"] and call["text"]


def test_call_sidecar_raises_on_error_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_subprocess(monkeypatch, stdout='{"error":"schema X does not exist"}', returncode=1)
    with pytest.raises(SasError, match="sidecar attest failed: schema X does not exist"):
        call_sidecar({"cmd": "attest"})


def test_call_sidecar_reports_stderr_tail_and_npm_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    stderr = "node:internal/modules\nError [ERR_MODULE_NOT_FOUND]: Cannot find package 'sas-lib'\n"
    _patch_subprocess(monkeypatch, stderr=stderr, returncode=1)
    with pytest.raises(SasError, match=r"Cannot find package 'sas-lib'.*npm ci"):
        call_sidecar({"cmd": "setup"})


def test_call_sidecar_timeout_and_missing_node(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_subprocess(monkeypatch, timeout=True)
    with pytest.raises(SasError, match="timed out after 5s"):
        call_sidecar({"cmd": "fetch"}, timeout=5)
    monkeypatch.setattr(sas_mod.shutil, "which", lambda name: None)
    with pytest.raises(SasError, match="node not found"):
        call_sidecar({"cmd": "fetch"})


# -- setup_sas / .env ----------------------------------------------------------------------
def test_setup_sas_creates_env_from_example_and_records_addresses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.example").write_text("SERPAPI_KEY=\nSAS_CREDENTIAL=\nSAS_SCHEMA=\n")
    calls = _patch_sidecar(
        monkeypatch, {"credential": CREDENTIAL, "schema": SCHEMA, "txs": ["sig1", "sig2"]}
    )
    result = setup_sas(_settings(tmp_path, None, None))
    assert calls == [
        {"cmd": "setup", "keypair": str(tmp_path / "id.json"), "rpc": "https://rpc.example/devnet"}
    ]
    assert result["env"] == {
        "path": str(tmp_path / ".env"),
        "written": ["SAS_CREDENTIAL", "SAS_SCHEMA"],
    }
    assert (tmp_path / ".env").read_text() == (
        f"SERPAPI_KEY=\nSAS_CREDENTIAL={CREDENTIAL}\nSAS_SCHEMA={SCHEMA}\n"
    )


def test_write_env_keys_fills_empty_appends_missing_and_keeps_set_values(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# comment\nSERPAPI_KEY=abc\nSAS_CREDENTIAL=keep-me\n")
    written = write_env_keys(env, {"SAS_CREDENTIAL": CREDENTIAL, "SAS_SCHEMA": SCHEMA})
    assert written == ["SAS_SCHEMA"]
    assert (
        env.read_text()
        == f"# comment\nSERPAPI_KEY=abc\nSAS_CREDENTIAL=keep-me\nSAS_SCHEMA={SCHEMA}\n"
    )


# -- attest / fetch ------------------------------------------------------------------------
def test_attest_sends_the_four_schema_fields_and_adds_explorer_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _patch_sidecar(
        monkeypatch,
        {"attestation": ATTESTATION, "signature": "5sig", "nonce": NONCE, "existed": False},
    )
    record = attest(_bundle(), None, _settings(tmp_path))
    assert calls == [
        {
            "cmd": "attest",
            "keypair": str(tmp_path / "id.json"),
            "rpc": "https://rpc.example/devnet",
            "credential": CREDENTIAL,
            "schema": SCHEMA,
            "bundle_hash": H,
            "cid": "",
            "post_url": "https://x.com/imVkohli/status/1000000000000000001",
            "similarity_bps": 7123,
            "expiry": 0,
        }
    ]
    assert record["attestation"] == ATTESTATION
    assert record["credential"] == CREDENTIAL and record["schema"] == SCHEMA
    assert record["explorer"] == "https://explorer.solana.com/tx/5sig?cluster=devnet"


def test_attest_existing_record_has_no_signature_or_explorer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_sidecar(
        monkeypatch,
        {"attestation": ATTESTATION, "signature": None, "nonce": NONCE, "existed": True},
    )
    record = attest(_bundle(), "bafy123", _settings(tmp_path))
    assert record["signature"] is None and record["explorer"] is None


def test_attest_and_fetch_require_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _patch_sidecar(monkeypatch, {})
    with pytest.raises(SasError, match="setup-sas"):
        attest(_bundle(), None, _settings(tmp_path, credential=None))
    with pytest.raises(SasError, match="setup-sas"):
        fetch_attestation(H, _settings(tmp_path, schema=None))
    assert calls == []


def test_fetch_attestation_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_sidecar(monkeypatch, _found())
    assert fetch_attestation(H, _settings(tmp_path))["found"] is True
    assert calls == [
        {
            "cmd": "fetch",
            "rpc": "https://rpc.example/devnet",
            "credential": CREDENTIAL,
            "schema": SCHEMA,
            "bundle_hash": H,
        }
    ]


# -- verification helpers ------------------------------------------------------------------
def test_attestation_fields_use_bundle_hash_and_empty_cid() -> None:
    assert attestation_fields(_bundle(), None) == {
        "bundle_hash": H,
        "cid": "",
        "post_url": "https://x.com/imVkohli/status/1000000000000000001",
        "similarity_bps": 7123,
    }
    assert attestation_fields(_bundle(), "bafy1")["cid"] == "bafy1"


def test_compare_attestation_flags_signer_and_field_mismatches() -> None:
    assert compare_attestation(_found(), _bundle(), REGISTRY) == (True, ())
    wrong = _found()
    wrong["signer"] = "1" * 32
    wrong["data"]["similarity_bps"] = 9999
    signer_ok, mismatches = compare_attestation(wrong, _bundle(), REGISTRY)
    assert not signer_ok
    assert mismatches == ("similarity_bps: chain 9999 != bundle 7123",)


def test_effective_hash_recomputes_when_media_was_tampered(tmp_path: Path) -> None:
    assert effective_hash(_local(tmp_path), _bundle()) == (H, False)
    h2, recomputed = effective_hash(_local(tmp_path, media_ok=False), _bundle())
    assert recomputed and h2 != H
    patched = _bundle()
    patched["post"]["media_sha256"] = "ab" * 32
    assert h2 == bundle_hash(patched)


def test_check_attestation_found_and_consistent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_sidecar(monkeypatch, _found())
    check = check_attestation(
        _local(tmp_path), _bundle(), registry=REGISTRY, settings=_settings(tmp_path)
    )
    assert check.ok and check.found and check.signer_ok and check.fields_ok
    assert check.attestation == ATTESTATION and check.hash_used == H and not check.recomputed


def test_check_attestation_absent_for_tampered_media_uses_recomputed_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _patch_sidecar(monkeypatch, {"found": False, "attestation": "Absent111", "nonce": "N"})
    check = check_attestation(
        _local(tmp_path, media_ok=False), _bundle(), registry=REGISTRY, settings=_settings(tmp_path)
    )
    assert not check.found and not check.ok and check.recomputed
    assert calls[0]["bundle_hash"] == check.hash_used != H
    assert check.attestation == "Absent111"
    assert "recomputed from the media" in check.detail


def test_check_attestation_survives_sidecar_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(cmd: dict[str, Any], timeout: float = 120) -> dict[str, Any]:
        raise SasError("sidecar fetch failed: rpc down")

    monkeypatch.setattr(sas_mod, "call_sidecar", boom)
    check = check_attestation(
        _local(tmp_path), _bundle(), registry=REGISTRY, settings=_settings(tmp_path)
    )
    assert not check.found and check.detail == "sidecar fetch failed: rpc down"


def test_render_report_shows_attestation_rows(tmp_path: Path) -> None:
    def render(sas: SasCheck | None) -> str:
        report = Report(
            local=_local(tmp_path),
            chain=ChainResult(found=False, detail="no memo"),
            registry=REGISTRY,
            verdict="UNANCHORED",
            sas=sas,
        )
        console = Console(record=True, width=200)
        console.print(render_report(report))
        return console.export_text()

    text = render(None)
    assert "SAS not configured" in text
    text = render(
        SasCheck(
            found=True,
            hash_used=H,
            attestation=ATTESTATION,
            signer=REGISTRY,
            signer_ok=True,
            fields_ok=True,
        )
    )
    assert ATTESTATION in text and "match bundle" in text
    text = render(
        SasCheck(found=False, hash_used="ab" * 32, recomputed=True, detail="no attestation")
    )
    assert "ABSENT" in text and "recomputed from the media" in text


# -- CLI ----------------------------------------------------------------------------------
def test_anchor_with_sas_records_attestation_in_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from facechain import cli_chain

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "bundle.json").write_bytes(canonical_bytes(_bundle()))
    (run_dir / "post_media.jpg").write_bytes(b"\xff\xd8fake")

    class FakeKeypair:
        def pubkey(self) -> str:
            return REGISTRY

    async def fake_send_memo(text: str, *, rpc_url: str, keypair: Any) -> str:
        return "memoSig"

    attested: list[Any] = []

    def fake_attest(bundle: dict[str, Any], cid: str | None, settings: Settings) -> dict[str, Any]:
        attested.append((bundle_hash(bundle), cid))
        return {"attestation": ATTESTATION, "signature": "sasSig", "nonce": NONCE, "explorer": "x"}

    monkeypatch.setattr(cli_chain, "load", lambda: _settings(tmp_path))
    monkeypatch.setattr(cli_chain, "load_keypair", lambda path: FakeKeypair())
    monkeypatch.setattr(cli_chain, "send_memo", fake_send_memo)
    monkeypatch.setattr(cli_chain, "attest", fake_attest)

    result = CliRunner().invoke(cli_chain.anchor, ["--run", str(run_dir), "--sas"])
    assert result.exit_code == 0, result.output
    receipt = json.loads((run_dir / "receipt.json").read_text())
    assert receipt["signature"] == "memoSig" and receipt["bundle_hash"] == H
    assert receipt["sas"]["attestation"] == ATTESTATION and receipt["sas"]["signature"] == "sasSig"
    assert attested == [(H, None)]
    assert "attested" in result.output and ATTESTATION in result.output


def test_attest_command_keeps_the_original_receipt_entry_when_the_pda_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from facechain import cli_chain

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "bundle.json").write_bytes(canonical_bytes(_bundle()))
    original = {"attestation": ATTESTATION, "signature": "sasSig", "nonce": NONCE, "seconds": 7.4}
    (run_dir / "receipt.json").write_text(json.dumps({"signature": "memoSig", "sas": original}))
    monkeypatch.setattr(cli_chain, "load", lambda: _settings(tmp_path))
    monkeypatch.setattr(
        cli_chain,
        "attest",
        lambda bundle, cid, settings: {
            "attestation": ATTESTATION,
            "signature": None,
            "nonce": NONCE,
            "existed": True,
        },
    )
    result = CliRunner().invoke(cli_chain.attest_cmd, ["--run", str(run_dir)])
    assert result.exit_code == 0, result.output
    assert "already exists" in result.output
    receipt = json.loads((run_dir / "receipt.json").read_text())
    assert receipt["signature"] == "memoSig"
    assert receipt["sas"] == {**original, "existed": True}


def test_anchor_with_sas_fails_before_the_memo_when_unconfigured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from facechain import cli_chain

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "bundle.json").write_bytes(canonical_bytes(_bundle()))
    monkeypatch.setattr(cli_chain, "load", lambda: _settings(tmp_path, credential=None))
    monkeypatch.setattr(cli_chain, "send_memo", None)  # must never be reached
    result = CliRunner().invoke(cli_chain.anchor, ["--run", str(run_dir), "--sas"])
    assert result.exit_code == 2
    assert "setup-sas" in result.output
    assert not (run_dir / "receipt.json").exists()


def test_setup_sas_command_prints_addresses_and_txs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from facechain import cli_chain

    monkeypatch.setattr(cli_chain, "load", lambda: _settings(tmp_path, None, None))
    monkeypatch.setattr(
        cli_chain,
        "setup_sas",
        lambda settings: {
            "credential": CREDENTIAL,
            "schema": SCHEMA,
            "authority": REGISTRY,
            "program": sas_mod.SAS_PROGRAM_ID,
            "txs": ["sig1"],
            "env": {"path": str(tmp_path / ".env"), "written": ["SAS_CREDENTIAL", "SAS_SCHEMA"]},
        },
    )
    result = CliRunner().invoke(cli_chain.setup_sas_cmd, [])
    assert result.exit_code == 0, result.output
    assert CREDENTIAL in result.output and SCHEMA in result.output and "sig1" in result.output


# -- live ---------------------------------------------------------------------------------
@pytest.mark.network
@pytest.mark.skipif(
    os.environ.get("FACECHAIN_LIVE") != "1", reason="set FACECHAIN_LIVE=1 to hit devnet"
)
def test_live_synthetic_attestation_is_on_devnet() -> None:
    from facechain.config import load

    settings = load(ROOT / ".env")
    if not sas_mod.sas_configured(settings):
        pytest.skip("SAS_CREDENTIAL / SAS_SCHEMA not configured in .env")
    found = fetch_attestation(H, settings)
    assert found["found"] is True
    assert found["signer"] == REGISTRY
    assert found["data"]["bundle_hash"] == H
    assert found["data"]["similarity_bps"] == 7123
    assert check_attestation(
        replace(_local(ROOT / "evidence" / "_synthetic"), bundle_hash=H),
        _bundle(),
        registry=REGISTRY,
        settings=settings,
    ).ok
