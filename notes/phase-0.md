# Phase 0 — Engineering harness + bootstrap

Date: 2026-09-05

## Built
- Repo `/mnt/d/HHGOA/facechain` (git, `core.filemode=false`, `core.autocrlf=false`, LF via `.gitattributes`/`.editorconfig`).
- Harness (Boris Cherny team tips + ECC): `CLAUDE.md`, `notes/`, `.claude/settings.json` (permissions allowlist, ECC marketplace + plugin at project scope, ruff PostToolUse hook, non-blocking Stop reminder), `.claude/commands/{smoke,verify-run,commit-phase,techdebt,demo-dryrun}.md`, `.claude/agents/{verify-app,code-simplifier,plan-reviewer}.md`, `.claude/rules/ecc/{common,python}` copied from ECC v2.2.1.
- Python: venv `~/.venvs/facechain` (ext4), deps pinned in `pyproject.toml` (insightface 1.0.1, onnxruntime, opencv<5, solana 0.40.3, solders 0.29.0, ruff, pyright, pytest-cov). Editable install.
- Model: `buffalo_l` unzipped manually into `~/.insightface/models/buffalo_l/` (5 ONNX files).
- Samples: 19 CC-licensed Commons photos (`samples/{kohli,ronaldo,hamilton}/`, `samples/neg/`), provenance in `samples/SOURCES.md`, fetched by `scripts/fetch_samples.py`.
- `facechain/http.py` (shared session, retries on 429/5xx/network only, media download with browser UA).

## Verified (real output)
- `claude plugin install ecc@ecc --scope project` → "Successfully installed plugin: ecc@ecc (scope: project)".
- Model: `faces in kohli/subject.jpg: 1  bbox [326,338,987,1134] det 0.881 emb (512,)` in ~6 s CPU including load.
- RED run: `pytest tests/test_cache.py tests/test_config.py` → `ModuleNotFoundError: No module named 'facechain.config'` (2 collection errors) before implementation.

## Decisions
- Repo stays on `/mnt/d` (user's folder); everything heavy on ext4.
- Hooks invoked via `bash <path>` so a lost exec bit on a clone cannot break them.
- ECC coverage rule applies to pure modules only (recorded in `CLAUDE.md`).

## Open
- SerpApi key (user signing up), Pinata JWT.
- Two negative-sample searches returned nothing usable (KL Rahul, Bottas); six impostors remain, enough for calibration.

## Next phase needs
- `facechain/cache.py`, `facechain/config.py`, `facechain/cli.py` GREEN (Phase 0 close), then Phase 1 face engine.
