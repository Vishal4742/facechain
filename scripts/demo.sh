#!/usr/bin/env bash
# Screen-recording script. Dry run with cache: scripts/demo.sh --dry ; real take: scripts/demo.sh
# Shows: face scan -> live search (SerpApi id + timestamp) -> face-verified ranking -> ACCEPT
#        -> evidence bundle hash -> devnet memo tx -> explorer -> verify -> tamper test.
set -uo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1090
source ~/.venvs/facechain/bin/activate
IMG="${DEMO_IMAGE:-samples/kohli/subject.jpg}"
LIVE="--live"; [ "${1:-}" = "--dry" ] && LIVE=""

pause() { [ "${1:-}" = "--dry" ] || sleep "${DEMO_PAUSE:-2}"; }
banner() { printf '\n\033[1;35m$ %s\033[0m\n' "$*"; }

banner "facechain scan --image $IMG";               facechain scan --image "$IMG"; pause "$@"
banner "facechain run --image $IMG $LIVE --engines lens,identity"
facechain run --image "$IMG" $LIVE --engines lens,identity || { echo "run did not ACCEPT"; exit 1; }
RUN="$(ls -td evidence/2* | grep -v _tampered | head -1)"; pause "$@"
banner "sha256sum $RUN/bundle.json  (must equal h= in the memo)"; sha256sum "$RUN/bundle.json"; pause "$@"
banner "facechain verify --run $RUN";               facechain verify --run "$RUN"; pause "$@"
banner "facechain verify --run $RUN --tamper";      facechain verify --run "$RUN" --tamper || true
printf '\nexplorer: %s\n' "$(python -c "import json;print(json.load(open('$RUN/receipt.json'))['explorer'])")"
