# Helpers sourced by the recorded demo shell (keeps the typed commands short and quote-free).
# shellcheck shell=bash

demo_run_dir() { ls -td evidence/2* 2>/dev/null | grep -v _tampered | head -1; }

# On-chain read of the memo straight from the transaction logs (no facechain code involved).
demo_memo_log() {
  local run="${1:-$(demo_run_dir)}"
  local sig
  sig="$(python -c "import json;print(json.load(open('$run/receipt.json'))['signature'])")"
  solana confirm -v "$sig" -u devnet | grep -E 'Program log: Memo|Status|Block Time' | cut -c1-150
}

demo_links() {
  local run="${1:-$(demo_run_dir)}"
  python - "$run" <<'PY'
import json, sys
r = json.load(open(f"{sys.argv[1]}/receipt.json"))
print("memo tx      :", r["explorer"])
sas = r.get("sas") or {}
if sas:
    print("attestation  :", sas.get("attestation"), "->", sas.get("explorer"))
print("bundle CID   :", r.get("bundle_cid"))
print("post media   :", r.get("media_cid"))
PY
}
