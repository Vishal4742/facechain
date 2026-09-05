---
description: Close a build phase — verify, grill, update notes and CLAUDE.md, then commit with a conventional message
argument-hint: <type>: <description>   e.g. feat: lens search with face-verified ranking
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git add:*), Bash(git commit:*), Bash(pytest:*), Bash(ruff:*), Bash(pyright:*), Read, Edit, Write
---

## Context (pre-computed, no model calls)
- Status: !`git status --porcelain`
- Diff stat vs HEAD: !`git diff --stat HEAD | tail -20`
- Last commits: !`git log --oneline -5`

## Task
1. Verification gate (must pass before anything else): `ruff check . && ruff format --check . && pytest -q`. If it fails, stop and report; do not commit.
2. Grill me: list the three riskiest changes in this diff as questions I must answer (behaviour changes, hashing or canonicalization changes, anything touching money or keys). Wait for my answers before continuing.
3. Update `notes/phase-N.md` for the phase being closed (what was built, what was verified with real output, decisions, open issues, what the next phase needs) and add any new rule learned to the "Mistakes and rules" section of `CLAUDE.md`.
4. Stage only files that belong to this phase (never `.env`, keypairs, `evidence/*` except `evidence/sample_run/`), then commit with message `$ARGUMENTS` and the standard trailer. Show `git log --oneline -1`.
