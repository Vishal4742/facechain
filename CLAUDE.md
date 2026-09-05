# CLAUDE.md — facechain

## What this is
HH Goa 2026 shortlisting Task 3. Pipeline: face photo → genuine social search (Google Lens via SerpApi, plus a Wikidata/X identity hop) → face-verified match (InsightFace ArcFace) → canonical evidence bundle → Solana devnet record (SPL Memo; optional Solana Attestation Service attestation) → `verify` with a tamper test.

- Architecture and research log: `docs/ARCHITECTURE.md`
- Build phases and per-phase notes: `notes/` (one file per phase, updated after every phase commit)
- Deadline: Sept 7, 2026 23:59. No resubmission. Reliability beats features.

## Commands
- Activate venv: `source ~/.venvs/facechain/bin/activate` (venv lives on ext4, never under `/mnt/d`)
- Install editable: `pip install -e .`
- CLI: `facechain scan|search|run|anchor|verify|setup-sas` (see README)
- Tests: `pytest -q` · coverage: `pytest --cov=facechain --cov-report=term-missing`
- Lint/format: `ruff check --fix . && ruff format .` · types: `pyright`
- Smoke: `scripts/smoke.sh` (`SMOKE_CHAIN=1` adds anchor + verify + tamper on devnet)
- Devnet wallet: `solana balance -k ~/.config/solana/id.json -u devnet`

## Conventions
- Python 3.12, type hints on every signature, frozen dataclasses, plain modules, no frameworks. `requests` for HTTP, `click` for the CLI, `rich` for output.
- Every network call goes through `facechain/http.py` and `facechain/cache.py` (content-addressed disk cache under `~/.cache/facechain`). `--offline` raises `CacheMiss`; `--live` bypasses cache reads. Never cache non-200 responses or SerpApi `{"error": ...}` bodies. Cache keys never contain secrets or `image_id`.
- solana-py 0.40: `AsyncClient` only (the sync `Client` was removed). Keypair path comes from `SOLANA_KEYPAIR_PATH`, never from the Solana CLI config (its path is stale).
- Canonical bundle JSON: `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)`, no trailing newline. Ints and strings only (`similarity_bps`, never floats). No git commit hash inside the hashed bundle. `verify` hashes stored bytes and never re-downloads media.
- Run ids: `%Y%m%dT%H%M%SZ-<4hex>`. No `:` in generated file names (the repo sits on an NTFS drive).
- Secrets only in `.env` (gitignored). `.env.example` lists every key.
- Commits: `<type>: <description>` with type in feat, fix, refactor, docs, test, chore.

## Workflow (ECC loop + Claude Code team tips)
- Research and reuse before writing new code (`search-first`). The research log is `docs/ARCHITECTURE.md` §12.
- Tests first for pure modules: `evidence/bundle.py`, `search/filters.py`, `chain/memo.py` formatting and parsing, `search/rank.py` acceptance rule, `cache.py`. Model and network modules are covered by fixture-based tests plus `scripts/smoke.sh`. Project override of the ECC coverage rule: the 80 % target applies to those pure modules, not to `face/engine.py` or live clients.
- Close every phase with: `/code-review` from a fresh context, `verification-loop` (ruff, pyright, pytest --cov, secret grep, diff review), the `verify-app` subagent, an update to `notes/phase-N.md` and this file, then `/commit-phase`.
- Before committing a phase: "Grill me on these changes and don't commit until I pass your test." After: "Prove to me this works" with real command output.
- When something goes sideways, re-plan instead of pushing on.
- Phases 5 and 6 run in separate git worktrees under `.claude/worktrees/` after Phase 3 lands on `main`.

## Mistakes and rules
Append one line after every correction ("Update your CLAUDE.md so you don't make that mistake again"). Prune at the end of each day.

- solana-py 0.40: `MemoParams` lives in `spl.memo.models`; only `create_memo` is in `spl.memo.instructions`.
- `get_signatures_for_address` defaults to finalized; pass `commitment=Confirmed` and retry briefly, or a record anchored seconds ago looks missing.
- `EncodedConfirmedTransactionWithStatusMeta.to_json()` is flat: `slot`, `blockTime`, `transaction.message.instructions[].parsed`; there is no nested `transaction.transaction`.
- InsightFace prints model chatter to stdout; construct the engine under `redirect_stdout(sys.stderr)` or `--json` output breaks.
- Never cache an empty Lens result; SerpApi's "no results" can be transient.
- Any error text that can reach the screen goes through `http.redact()` first (API keys ride in query strings).
- The ruff hook only fires for Write/Edit in a fresh session; run `ruff format . && ruff check --fix .` before every commit.
- Exceptions to "network only via http.py": Solana RPC calls (solana-py client) and the stdlib-only `scripts/fetch_samples.py`.
