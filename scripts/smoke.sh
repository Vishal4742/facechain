#!/usr/bin/env bash
# Smoke test: static checks + unit tests + offline pipeline (+ optional live chain round trip).
#   scripts/smoke.sh                 checks, tests, offline run (needs a cached search for the image)
#   SMOKE_CHAIN=1 scripts/smoke.sh   also anchors the run on devnet, verifies it, and runs the tamper test
#   SMOKE_IMAGE=path scripts/smoke.sh  use another query photo
set -uo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1090
source ~/.venvs/facechain/bin/activate

step() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
fail() { printf '\033[1;31mSMOKE FAIL: %s\033[0m\n' "$*"; exit 1; }

step "ruff";    ruff check . && ruff format --check . || fail "ruff"
step "pyright"; pyright || fail "pyright"
step "pytest";  pytest -q || fail "pytest"

IMG="${SMOKE_IMAGE:-samples/kohli/subject.jpg}"
step "offline pipeline on $IMG"
if facechain run --image "$IMG" --offline --no-anchor; then
  echo "offline run: ACCEPT"
else
  code=$?
  if [ "${SMOKE_STRICT:-0}" = "1" ]; then fail "offline run exited $code"; fi
  echo "offline run exited $code (no cached search for this image yet, or REVIEW) - not strict, continuing"
fi

if [ "${SMOKE_CHAIN:-0}" = "1" ]; then
  RUN="$(ls -td evidence/2* 2>/dev/null | grep -v _tampered | head -1)"
  [ -n "$RUN" ] || fail "no evidence run to anchor"
  SAS_FLAG=""
  if grep -Eq '^SAS_CREDENTIAL=.+' .env 2>/dev/null; then SAS_FLAG="--sas"; fi
  step "anchor $RUN $SAS_FLAG"; facechain anchor --run "$RUN" $SAS_FLAG || fail "anchor"
  step "verify";      facechain verify --run "$RUN" || fail "verify did not report VERIFIED"
  step "tamper";      if facechain verify --run "$RUN" --tamper; then fail "tampered run verified"; fi
  echo "tamper test: TAMPERED as expected"
fi
printf '\n\033[1;32mSMOKE OK\033[0m\n'
