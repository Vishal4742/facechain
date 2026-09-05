---
description: End-of-session sweep for duplicated code, dead code, and over-engineering in facechain/
allowed-tools: Bash(ruff:*), Bash(git diff:*), Bash(git log:*), Read, Grep, Glob
---

## Context
- Files: !`find facechain -name '*.py' | xargs wc -l | tail -1`
- Today's commits: !`git log --since=midnight --oneline`

## Task
Use subagents to explore in parallel. Find:
1. Duplicated logic across modules (same URL canonicalization, hashing, retry loops, table rendering written twice).
2. Dead code: functions and flags nothing calls (`grep -rn` for each `def` name).
3. Over-engineering for a 3-day hackathon: abstractions with one implementation, config options nobody sets, layers that only forward calls.
4. Any float or git commit hash that leaked into the hashed evidence bundle.

Report a ranked list with file:line and a one-line fix each. Apply only the fixes that are safe and covered by tests, then run `pytest -q`.
