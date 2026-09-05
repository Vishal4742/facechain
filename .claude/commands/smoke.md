---
description: Run the test suite and the offline end-to-end pipeline; report PASS/FAIL with real output
allowed-tools: Bash(pytest:*), Bash(ruff:*), Bash(pyright:*), Bash(scripts/smoke.sh:*), Bash(facechain:*), Read, Grep
---

## Context
- Branch: !`git branch --show-current`
- Uncommitted: !`git status --porcelain | wc -l`
- Venv: !`test -x ~/.venvs/facechain/bin/python && echo ok || echo MISSING`

## Task
Run, in order, using the venv (`source ~/.venvs/facechain/bin/activate`):
1. `ruff check . && ruff format --check .`
2. `pyright` (report errors, do not fix silently)
3. `pytest -q --cov=facechain --cov-report=term-missing`
4. `scripts/smoke.sh` if it exists (offline pipeline; must find a winner with 0 SerpApi calls)

Report a table: step | PASS/FAIL | one-line evidence (test counts, coverage, first failing assertion). Do not claim PASS without the command output. If anything fails, propose the fix but do not apply it unless asked.
