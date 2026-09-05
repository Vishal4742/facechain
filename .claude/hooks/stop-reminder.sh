#!/usr/bin/env bash
# Stop hook: non-blocking reminder when product code changed but was not verified.
# Prints a systemMessage for the user; never blocks Claude.
set -u
cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0
changed="$(git status --porcelain -- facechain tests 2>/dev/null | wc -l | tr -d ' ')"
if [ "${changed:-0}" -gt 0 ]; then
  printf '{"systemMessage":"facechain: %s uncommitted change(s) under facechain/ or tests/. Run /smoke or the verify-app subagent before committing."}\n' "$changed"
fi
exit 0
