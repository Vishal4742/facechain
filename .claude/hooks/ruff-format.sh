#!/usr/bin/env bash
# PostToolUse hook: format and lint-fix the Python file Claude just wrote or edited.
# Never blocks: any failure exits 0 so a formatting hiccup cannot stall the session.
set -u
RUFF="${RUFF:-$HOME/.venvs/facechain/bin/ruff}"
if [ ! -x "$RUFF" ]; then
  RUFF="$(command -v ruff 2>/dev/null || true)"
fi
[ -n "$RUFF" ] || exit 0

file="$(python3 -c 'import json,sys
try:
    print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))
except Exception:
    print("")' 2>/dev/null)"

case "$file" in
  *.py)
    [ -f "$file" ] || exit 0
    "$RUFF" format -q "$file" >/dev/null 2>&1
    "$RUFF" check --fix -q "$file" >/dev/null 2>&1
    ;;
esac
exit 0
